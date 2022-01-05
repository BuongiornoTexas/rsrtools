#!/usr/bin/env python

"""Welder Provides classes for managing Rocksmith psarc files.

TODO: It does not yet provide psarc file write routines.
"""

# cSpell:ignore struct, rsrpad, PSAR, Rijndael, mkdir, macos, pycryptodome, pyrocksmith
# cSpell:ignore odlc, cdlc, xbdq, situ

import argparse
import hashlib
import struct
import sys
import zlib
from io import BytesIO
from os import fsdecode
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO, Iterator, List, Optional, TextIO, Tuple, Type, cast
from typing import TYPE_CHECKING
from dataclasses import field
from typing_extensions import Literal

from Crypto.Cipher import AES
from Crypto.Util import Counter

from rsrtools.files.exceptions import RSFileFormatError
from rsrtools.utils import rsrpad

# workaround for mypy checking. See https://github.com/python/mypy/issues/6239
if TYPE_CHECKING:
    from dataclasses import dataclass
else:
    from pydantic.dataclasses import dataclass

# Header (and presumably  the rest of the file) is big endian
SUFFIX = ".psarc"
HEADER_STRUCT = ">4s4s4sLLLL4s"
HEADER_BYTES = 32
EXPECT_MAGIC = b"PSAR"
# Major version 1, minor version 4
EXPECT_VERSION = b"\x00\x01\x00\x04"
EXPECT_COMP_TYPE = b"zlib"
# Default 30 bytes, which is currently hardcoded in implementation
TOC_ENTRY_BYTES = 30
DEFAULT_BLOCK_LEN = 65536
# Block Length entry bytes
BLOCK_LEN_BYTES = 2
# I think this means Rijndael encrypted
ARCHIVE_FLAGS = b"\x00\x00\x00\x04"

# SNG file stuff
SNG_HEADER = b"\x4A\x00\x00\x00\x03\x00\x00\x00"
SNG_IV_OFFSET = 8
SNG_ENC_PAYLOAD_OFFSET = 24
SNG_SIG_OFFSET = -56
SNG_DEC_PAYLOAD_OFFSET = 4

# WEM handling
WEM_SUFFIX = ".wem".casefold()
WEM_ALIGN_LEN = 8192

CDLC_STD_MD5 = b"\xd5\x0f\x05d\xad\x0c\x0e\xb5\x9f\xe9\x0e\xc9\xb8\xbdq)"

ARC_KEY = bytes.fromhex(
    "C53DB23870A1A2F71CAE64061FDD0E1157309DC85204D4C5BFDF25090DF2572C"
)
ARC_IV = bytes.fromhex("E915AA018FEF71FC508132E4BB4CEB42")
MAC_PATH = "songs/bin/macos/"
MAC_KEY = bytes.fromhex(
    "9821330E34B91F70D0A48CBD625993126970CEA09192C0E6CDA676CC9838289D"
)
WIN_PATH = "songs/bin/generic/"
WIN_KEY = bytes.fromhex(
    "CB648DF3D12A16BF71701414E69619EC171CCA5D2A142E3E59DE7ADDA18A3A30"
)


@dataclass  # pylint: disable=used-before-assignment
class TocEntry:
    """Table of contents dataclass entry."""

    # 16 byte md5
    md5: bytes = b""
    # Offset into _block_lengths (i.e. first block size value for file)
    first_block_index: int = -1
    # Size of uncompressed file in bytes created from 40 bit value.
    length: int = 0
    # Offset to the first compressed file byte in the archive (including header, toc).
    # Again, a 40 bit value.
    offset: int = -1
    # path to the file in the archive
    path: str = ""
    # data for packing - not used in unpack operations.
    pack_data: bytes = b""
    pack_lengths: List[int] = field(default_factory=list)
    # Only used when packing and aligning wem files on block boundaries.
    align_bytes: int = 0

    def is_wem_file(self) -> bool:
        """Return True if the toc entry is for a wem file."""
        return self.path.casefold().endswith(WEM_SUFFIX)


class Welder:
    """Provide class for managing Rocksmith PSARC files.

    Welder objects are designed to be used with a context manager.

        with Welder(psarc_path) as psarc:
            # Do things with psarc object.

    If you only want to view the contents of one or more files, use the iterator and
    contents grabber. If you want to modify the psarc file, use a welder to extract the
    contents of the archive to a temporary directory (and discard the welder), modify
    the files in the temporary directory, and use a new welder to create the modified
    psarc file.

    Public Members:
        Constructor -- Creates the instance. If called in read mode, the caller can
            then use read methods below. If called in write mode, the constructor
            is  a one shot that will create the archive from the contents of a target
            directory (no public write methods). The constructor includes a flag
            to allow encryption/decryption of SNG files. If you want to pack a subset
            of files in the directory, refer to use_manifest in the __init__ method.

        close -- Closes the archive. Provided in case the caller does not use a
            context manager.

        arc_name -- Returns the name and relative path of a indexed file in the archive.
            e.g. manifests/songs_dlc_bong/bong_lead.json

        arc_data -- returns the contents of an indexed file in the archive.

        decrypt_sng -- Static method for decrypting SNG files.

        unpack -- Extract all files in the archive to disk.

        verify -- Verify that Welder can rebuild a file that matches the original
            .psarc (or report where and why it fails).

    A Welder instance is iterable, returning integer indices for the elements in th
    archive. The iterable can be used as index for arc_name and arc_data.
    An iterator for the files in the archive. Each call to names yield

    """

    # Path to the PSARC file. Does not need to exist if we are packing, needs to exist
    # for unpacking
    _path: Path
    # File descriptor
    _fd: BinaryIO
    # Length of the combined header and toc
    _preamble_len: int
    # The size of each toc entry
    _toc_entry_len: int
    # The number of files in the archive, and hence the number of toc entries
    _n_toc_entries: int
    # The default block size for data chunks
    _default_block_len: int
    _sng_crypto: bool

    # metadata for each file in the archive including the manifest
    _toc_entries: List[TocEntry]
    # List of all block lengths in the data section of the archive.
    # This contains the sequential block lengths for all files in the archive.
    # i.e. sum of block lengths should equal the size of the data block
    # (after any correction for default blocks).
    _block_lengths: List[int]
    # iterator index
    _arc_index: int
    # True if we are doing a verify rather than an actual pack
    _verify: bool
    # Text stream for verify output.
    _verify_io: TextIO
    # Verify warning/error count
    _verify_warnings: int
    # verify log indent level
    _verify_indent: str = ""
    # Apply odlc wem handling in pack operations
    _odlc_wem: bool
    # Use CDLC md5 in packing.
    _use_cdlc_m5: bool

    def __init__(
        self,
        file_or_dir_path: Path,
        mode: str,
        sng_crypto: bool = False,
        use_manifest: Optional[List[str]] = None,
        odlc_wem: bool = True,
        cdlc_md5: bool = False,
    ) -> None:
        r"""Write a PSARC file, or open a PSARC file for reading.

        Arguments:
            file_or_dir_path {Path} -- For read mode, the path to a PSARC file to read.
                For write mode, the path to directory to pack into a PSARC file. For a
                target directory of the form '<parent path>/<target_dir>', the PSARC
                file will be '<parent path>/<target_dir>.PSARC'.
            mode {str} -- One of 'r', 'w', or 'x', per file open mode.
            sng_crypto {bool} -- True if '.sng' files should be decrypted/encrypted
                during unpack/pack operations, False otherwise. Only relevant to users
                who want to modify these files.
            use_manifest: Optional[List[str]] -- If specified the pack operation will
                pack only the files provided in the manifest (and in the order
                specified in the manifest). Each row of the manifest should be of the
                form:

                    a/b/c/d.txt

                where a/b/c is a relative path from the root directory for the archive,
                and d.txt is the file name to pack. For the above example when packing a
                directory ding, the following paths should exist:

                    ding/a/b/c/d.txt (Mac OS X)
                    ding\a\b\c\d.txt (Windows)

                Absolute paths are not supported (the path must not begin with '/'). If
                verify is True, use_manifest is ignored.

                use_manifest is primarily provided for verification and debugging
                purposes. It may also be useful to create an archive based on a limited
                set of files in a folder.
            odlc_wem {bool} -- Pack operation only. If True, wem files will be aligned
                to 8192 byte blocks (0 padding) and will not be compressed. If False,
                wem files will be compressed and will not be aligned. This parameter is
                ignored for read and verify operations. (default: True)
            cdlc_md5 {bool} -- If True, pack operation will use what appears to be a
                semi-standard md5 signature for the manifest. If False (default), use
                the ODLC method of 16 bytes of zeros for this hash.

        Raises:
            ValueError: On invalid path.

        """
        self._sng_crypto = sng_crypto

        self._path = file_or_dir_path.resolve(False)

        self._verify = False

        # At a bare minimum, open the file
        if mode == "r":
            # The next two parameters shouldn't be used during read ops, but in case ...
            self._use_cdlc_m5 = False
            self._odlc_wem = True
            if self._path.suffix.casefold() != SUFFIX.casefold():
                raise ValueError(
                    f"File should end in case insensitive suffix of '{SUFFIX}'."
                )

            # read mode
            self._fd = open(self._path, "rb")
            # Read the header, toc and manifest, then back to the caller to decide what
            # else to do.
            self._read_header()
            self._read_toc()
            self._read_manifest()

        elif mode in ("w", "x"):
            if not self._path.is_dir():
                raise ValueError(
                    "PSARC expects a directory to pack. "
                    "Directory is missing or argument is not a directory."
                )

            self._use_cdlc_m5 = cdlc_md5
            # Table of contents and block entry list initialisation for writing.
            self._toc_entries = list()
            self._block_lengths = list()

            # Create PSARC in the parent of the target dir
            pack_dir = self._path
            self._path = self._path.parent.joinpath(self._path.name + SUFFIX)
            # mypy doesn't have enough information to work out this is a binary mode
            # file.
            self._fd = cast(
                BinaryIO,
                open(self._path, mode + "b"),  # pylint: disable=unspecified-encoding
            )
            # Packing is the only place an alternate manifest will be used.
            self._pack(pack_dir, odlc_wem=odlc_wem, use_manifest=use_manifest)

        else:
            raise ValueError("Invalid Welder mode. Must be 'r', 'w', or 'x'.")

    def __enter__(self) -> "Welder":
        """Return Welder instance for context manager."""
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Literal[False]:
        """Clean up for context manager."""
        self.close()
        # Don't suppress exceptions
        return False

    def close(self) -> None:
        """Provide close in case the user doesn't wish to use a context manager."""
        self._fd.close()

    def _read_header(self) -> None:
        """Read the header section up to the start of the table of contents."""
        header = self._fd.read(HEADER_BYTES)
        (
            magic,
            version,
            compression_type,
            self._preamble_len,
            self._toc_entry_len,
            self._n_toc_entries,
            self._default_block_len,
            archive_flags,
        ) = struct.unpack(HEADER_STRUCT, header)

        # Quick checks that formats are as expected. I'm sure I could figure a cleaner
        # way to do this, but head cold and lack of interest rule the day.
        if magic != EXPECT_MAGIC:
            raise RSFileFormatError(
                f"Bad magic value in file '{self._path.name}'. Expected "
                f"'{EXPECT_MAGIC.decode()}', got '{magic.decode()}'."
            )

        if version != EXPECT_VERSION:
            raise RSFileFormatError(
                f"Bad version value in file '{self._path.name}'. Expected "
                f"'{EXPECT_VERSION.decode()}', got '{version.decode()}'."
            )

        if compression_type != EXPECT_COMP_TYPE:
            raise RSFileFormatError(
                f"Bad compression type in file '{self._path.name}'. Expected "
                f"'{EXPECT_COMP_TYPE.decode()}', got '{compression_type.decode()}'."
            )

        if self._toc_entry_len != TOC_ENTRY_BYTES:
            raise RSFileFormatError(
                f"Bad TOC entry size in file '{self._path.name}'. Expected "
                f"'{TOC_ENTRY_BYTES}', got '{self._toc_entry_len}'."
            )

        if self._default_block_len != DEFAULT_BLOCK_LEN:
            raise RSFileFormatError(
                f"Bad block size in file '{self._path.name}'. Expected "
                f"'{DEFAULT_BLOCK_LEN}', got '{self._default_block_len}'."
            )

        if archive_flags != ARCHIVE_FLAGS:
            raise RSFileFormatError(
                f"Bad archive flags in file '{self._path.name}'. Expected "
                f"'{ARCHIVE_FLAGS.decode()}', got '{archive_flags.decode()}'."
            )

    def _read_toc(self) -> None:
        """Load the table of contents."""
        # The preamble_len parameter is the size of the  header and table of contents
        # (i.e. everything up to the first data byte). So toc_len is easy.
        toc_len = self._preamble_len - HEADER_BYTES

        # First step, decrypt the toc
        self._fd.seek(HEADER_BYTES)
        encrypted_toc = rsrpad(self._fd.read(toc_len), 16)
        cipher = AES.new(ARC_KEY, AES.MODE_CFB, IV=ARC_IV, segment_size=128)
        toc = cipher.decrypt(encrypted_toc)[: len(encrypted_toc)]

        self._toc_entries = list()
        index = 0
        position = 0
        while index < self._n_toc_entries:
            data = toc[position : position + self._toc_entry_len]
            # this code is straight from 0x0l. Ungodly weird stuff here.
            self._toc_entries.append(
                TocEntry(
                    # 16 byte md5
                    md5=data[:16],
                    # Offset into _block_lengths (i.e. first block size value for file)
                    first_block_index=struct.unpack(">L", data[16:20])[0],
                    # Size of uncompressed file in bytes created from 40 bit value.
                    length=struct.unpack(">Q", b"\x00" * 3 + data[20:25])[0],
                    # Offset to the first compressed file byte in the file!
                    # Again, a 40 bit value.
                    offset=struct.unpack(">Q", b"\x00" * 3 + data[25:])[0],
                )
            )

            position = position + self._toc_entry_len
            index = index + 1

        # it looks as though _block_lengths is a list of all blocks/chunks making up the
        # payload. A _block_lengths element is zero if the block is the default size and
        # non-zero for the last/residual block in the file. 0x0L gets clever and
        # creates sublists for each entry. Will skip this and maintain _block_lengths as
        # a full blown member
        self._block_lengths = list()

        while position < toc_len:
            data = toc[position : position + BLOCK_LEN_BYTES]
            self._block_lengths.append(struct.unpack(">H", data)[0])
            position += BLOCK_LEN_BYTES

    def _write_preamble(self) -> None:
        """Prepare and write the preamble to file (first write step in packing)."""
        # Header
        header = struct.pack(
            HEADER_STRUCT,
            EXPECT_MAGIC,
            EXPECT_VERSION,
            EXPECT_COMP_TYPE,
            self._preamble_len,
            TOC_ENTRY_BYTES,
            len(self._toc_entries),
            DEFAULT_BLOCK_LEN,
            ARCHIVE_FLAGS,
        )

        # Toc entries
        data_stream = BytesIO()
        for toc_entry in self._toc_entries:
            data_stream.write(toc_entry.md5)
            data_stream.write(struct.pack(">L", toc_entry.first_block_index))
            # two by 40 bit int please
            data_stream.write(struct.pack(">Q", toc_entry.length)[-5:])
            data_stream.write(struct.pack(">Q", toc_entry.offset)[-5:])

        for block_len in self._block_lengths:
            data_stream.write(struct.pack(">H", block_len))

        data = data_stream.getvalue()
        data_stream.close()

        data = rsrpad(data, 16)
        cipher = AES.new(ARC_KEY, AES.MODE_CFB, IV=ARC_IV, segment_size=128)
        data = header + cipher.encrypt(data)
        # Chop padding off.
        data = data[: self._preamble_len]

        if self._verify:
            self._fd.seek(0)
            check_data = self._fd.read(self._toc_entries[0].offset)
            if check_data != data:
                self._verify_log(
                    "Rebuilt preamble does not match original. "
                    "This really shouldn't happen.",
                    "ERROR",
                )
        else:
            self._fd.write(data)

    def _read_manifest(self) -> None:
        """Read the manifest, which is the first entry in the TOC."""
        manifest = self.arc_data(0).decode().split()
        for i, arc_path in enumerate(manifest):
            # The manifest itself has no name, so start adding manifest info to the
            # second entry
            self._toc_entries[i + 1].path = arc_path

    def arc_data(self, index: int, get_raw: bool = False) -> bytes:
        """Return the archive file contents for the item index.

        Arguments:
            index {int} -- Item index, should be from the Welder iterator.
            get_raw {bool} -- If True, returns the raw (uncompressed) data.
                (default: False)

        Returns:
            bytes -- File data. May be text as bytes.

        """
        # Nifty. Always nice to pick up something new from null pointer.
        data_stream = BytesIO()
        if get_raw:
            raw_stream = BytesIO()

        entry = self._toc_entries[index]
        # Find the start of the data based on offset from start of archive
        self._fd.seek(entry.offset)

        length = 0
        for block_len in self._block_lengths[entry.first_block_index :]:
            if block_len == 0:
                block_len = self._default_block_len

            chunk = self._fd.read(block_len)
            if get_raw:
                raw_stream.write(chunk)

            try:
                chunk = zlib.decompress(chunk)
            except zlib.error:
                pass

            length = length + len(chunk)
            data_stream.write(chunk)

            if length == entry.length:
                # At least some of the ubi files include data blocks of zero values.
                # These blocks appear in the block length array, but do not appear in
                # in the manifest/toc. Possibly files deliberately removed by Ubisoft?
                # For now, break out of when we get to the correct size, but this
                # is going to make building the manifest harder!
                # It also means we have to decompress even when we only want the raw
                # data for validation.
                break

        data = data_stream.getvalue()
        data_stream.close()

        if len(data) != entry.length:
            raise RSFileFormatError(
                "Archive file larger than expected. Extract failed."
            )

        if get_raw:
            # Discard the uncompressed data and replace with the raw data.
            data = raw_stream.getvalue()
            raw_stream.close()

        elif self._sng_crypto:
            # decrypt .sng files
            if self._toc_entries[index].path.startswith(WIN_PATH):
                data = self.decrypt_sng(data, WIN_KEY)
            elif self._toc_entries[index].path.startswith(MAC_PATH):
                data = self.decrypt_sng(data, MAC_KEY)

        return data

    def unpack(self) -> None:
        """Unpacks the archive into the current working directory."""
        # Clunky way of getting an absolute path (not really needed anyway)
        arc_dir = Path(".").resolve().joinpath(self._path.stem)
        try:
            arc_dir.mkdir(parents=False, exist_ok=False)
        except FileExistsError as f_e:
            raise FileExistsError(
                f"Cannot unpack archive into a directory that already exists:"
                f"\n  {fsdecode(arc_dir)}."
            ) from f_e

        for index in self:
            file = self._toc_entries[index]
            if file.path[0] == "/" or file.path[0] == "\\":
                raise RSFileFormatError("Cannot unpack a file using absolute paths.")

            else:
                file_path = arc_dir.joinpath(file.path)
                # Create the parent folders.
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_bytes(self.arc_data(index))

    def arc_name(self, index: int) -> str:
        """Return the archive file path for the item index.

        Arguments:
            index {int} -- Item index, should be from the Welder iterator.

        Returns:
            str -- The path and file name in the archive.

        """
        return self._toc_entries[index].path

    def verify(self, verify_io: TextIO) -> None:
        """Verify re-constructability of an archive opened in read mode.

        Arguments:
            verify_io {TextIO} -- Text stream for the verification reporting.

        """
        # Apply crypto is not relevant for verify
        # Set to false for duration
        sng_crypto = self._sng_crypto
        self._sng_crypto = False

        # Flag verification active.
        self._verify = True

        # We are going to try to rebuild the archive based on the uncompressed data
        # from archive and the file paths from toc_entries object. As this is pretty
        # well the pack process, we do the verification as a variant pack call.

        self._verify_warnings = 0
        self._verify_io = verify_io
        self._verify_log(f"Verifying '{fsdecode(self._path.name)}'.")
        self._verify_indent = "    "
        self._pack(None)
        if self._verify_warnings > 0:
            self._verify_log(
                f"{self._verify_warnings} warning(s) or error(s) occurred during "
                f"verification of '{self._path.name}'."
            )

        # Reset flags post-verification
        self._sng_crypto = sng_crypto
        self._verify = False

    def _verify_log(self, message: str, warn_text: str = "") -> None:
        """Write log for verification.

        Arguments:
            message {str} -- The log message.

        Keyword Arguments:
            warn_text {str} -- Warning or error text, prepended to the message (e.g.
                "WARNING", "ERROR" or "FATAL"). A colon and space will be added to the
                warning text. If specified, increments the warning/error counter.
                (default: {""})

        """
        if warn_text:
            self._verify_warnings = self._verify_warnings + 1
            msg = f"{warn_text}: "
        else:
            msg = ""

        print(f"{self._verify_indent}{msg}{message}", file=self._verify_io)

    def _md5(self, index: int, manifest: List[str]) -> bytes:
        """Return md5 for toc entry.

        Arguments:
            index {int} -- Manifest index.
            manifest {List[str]} -- Manifest archive paths.

        """
        if index == 0:
            if not self._verify and self._use_cdlc_m5:
                md5 = CDLC_STD_MD5
            else:
                md5 = bytes(16)

            if self._verify and md5 != self._toc_entries[index].md5:
                md5 = self._toc_entries[index].md5
                if md5 == CDLC_STD_MD5:
                    self._verify_log("Found CDLC manifest md5 entry.")
                    self._verify_log("    For perfect rebuild, use CDLC md5.")
                else:
                    self._verify_log(
                        f"Unexpected manifest md5 entry "
                        f"0x{self._toc_entries[index].md5.hex()}",
                        "WARNING",
                    )

        else:
            md5 = hashlib.md5(manifest[index].encode()).digest()

        return md5

    def _verify_toc(self, toc_entry: TocEntry, index: int, arc_data: bytes) -> int:
        """Verify toc and check wem alignment block if needed.

        Arguments:
            toc_entry {TocEntry} -- The rebuilt toc entry to verify.
            index {int} -- The index of the original toc entry.
            arc_data {bytes} -- The rebuilt archive data for the entry.

        Returns:
            int -- The size of the alignment block in bytes.

        """
        align_len = 0
        if toc_entry.is_wem_file():
            if arc_data.startswith(b"RIFF"):
                if (
                    toc_entry.first_block_index
                    == self._toc_entries[index].first_block_index
                ):
                    self._verify_log(
                        f"Uncompressed wem without alignment. Likely CDLC? "
                        f"{toc_entry.path}"
                    )
                else:
                    # Looks like we have an alignment block.
                    align_len = WEM_ALIGN_LEN - (toc_entry.offset % WEM_ALIGN_LEN)

                    self._fd.seek(toc_entry.offset)
                    align_data = self._fd.read(align_len)

                    if not all([v == 0 for v in align_data]):
                        self._verify_log(
                            "Invalid alignment block for wem file.", "ERROR"
                        )

            else:
                self._verify_log(
                    f"Compressed wem file, probably CDLC: {toc_entry.path}"
                )
                self._verify_log("   For byte perfect rebuild, disable odlc wem.")

        if align_len != 0:
            # Correct toc for the alignment block
            toc_entry.offset = toc_entry.offset + align_len
            toc_entry.first_block_index = toc_entry.first_block_index + 1
            self._verify_log(
                f"Wem alignment block found, probably ODLC: {toc_entry.path}"
            )

        # And now we can check the toc entry.
        if toc_entry != self._toc_entries[index]:
            self._verify_log(
                f"Mismatch between rebuilt and original toc entries:"
                f"\n Original: {self._toc_entries[index]}."
                f"\n Rebuilt: {toc_entry}.",
                "ERROR",
            )

        return align_len

    def _build_manifest(
        self, pack_dir: Optional[Path], use_manifest: Optional[List[str]] = None
    ) -> List[str]:
        """Build a list of manifest entries.

        Arguments are per _pack.

        The first value in the manifest is always an empty string, representing the
        un-named manifest itself.

        """
        if self._verify:
            # Exclude the entry for the manifest
            manifest = [x.path for x in self._toc_entries[1:]]

            # Expect ubisoft dlc to be in reverse alpha order.
            temp_list = sorted(manifest, reverse=True)
            if manifest != temp_list:
                self._verify_log(
                    "Manifest is not in reverse alphabetical order. Possibly custom "
                    "dlc?",
                    "WARNING",
                )
                self._verify_log("  Byte perfect rebuild requires custom manifest.")

        elif use_manifest is not None:
            manifest = use_manifest

        elif pack_dir is not None:
            # Generate the manifest from pack dir
            # Annoyingly, because pathlib does the right thing, we need to undo
            # backslash for windows
            manifest = [
                fsdecode(x.relative_to(pack_dir)).replace("\\", "/")
                for x in pack_dir.glob("**/*")
                if x.is_file()
            ]
            manifest.sort(reverse=True)

        else:
            # shouldn't happen, but ...
            raise ValueError("Invalid argument combination (pack_dir is None?).")

        # insert the empty string entry for the manifest.
        manifest = [""] + manifest

        return manifest

    def _arc_entry(
        self, file_data: bytes, compress: bool = True
    ) -> Tuple[bytes, List[int]]:
        """Create the data for an archive entry from the supplied file contents.

        Arguments:
            file_data {bytes} -- The file data to be packed.
            compress {bool} -- True if default compression logic should be applied,
                False if compression should be disabled for the file.

        Returns:
            Tuple[bytes, List[int]] -- The packed data and the list of packed block
                sizes.

        """
        file_stream = BytesIO(file_data)
        arc_stream = BytesIO()
        block_lengths = list()

        raw = file_stream.read(DEFAULT_BLOCK_LEN)
        while raw:
            if compress:
                chunk = zlib.compress(raw, zlib.Z_BEST_COMPRESSION)

                if len(raw) <= len(chunk):
                    # use raw unless we are getting benefit from compression.
                    chunk = raw
            else:
                chunk = raw

            arc_stream.write(chunk)
            block_lengths.append(len(chunk) % DEFAULT_BLOCK_LEN)

            raw = file_stream.read(DEFAULT_BLOCK_LEN)

        file_stream.close()

        arc_data = arc_stream.getvalue()
        # This is throwing a pylint error, but not sure why. Leaving for now.
        arc_stream.close

        return arc_data, block_lengths

    def _get_data(
        self, pack_dir: Optional[Path], toc_entry: TocEntry, manifest: List[str]
    ) -> Tuple[bytes, List[int], int]:
        """Get file data, pack it, and return packed data and packing parameters.

        Arguments:
            pack_dir {Path} -- Root directory for packing.
            toc_entry {TocEntry} -- Partial toc entry for the file. At a minimum,
                the path must be defined.
            manifest  {List[str]} -- The manifest list for the file.

        Returns:
            Tuple[bytes, List[int], int] -- File data for pack operation, list of
                block lengths, size of raw data.

        """
        if not toc_entry.path:
            # Manifest entry. Data is the same regardless of pack/verify mode.
            # Ignore empty string first entry.
            data = ("\n").join(manifest[1:]).encode()

        compress = True
        if self._verify:
            # Find the index for the file we are checking.
            check_index = -1
            arc_path = ""
            for idx, arc_path in enumerate(manifest):
                if arc_path.casefold() == toc_entry.path.casefold():
                    check_index = idx
                    break
            if check_index < 0:
                raise IndexError(
                    f"Manifest is missing an arc_path entry for {arc_path}."
                )

            if toc_entry.path:
                # Not the manifest, so find and unpack data for repacking ...
                data = self.arc_data(check_index)

            # Get the check data as well. If this looks like an uncompressed .wem,
            # disable compression for verification (as this is the ubi way).
            check_data = self.arc_data(check_index, get_raw=True)
            if check_data[0:4] == b"RIFF":
                compress = False
                if toc_entry.is_wem_file():
                    self._verify_log(
                        f"Uncompressed wem, possibly ODLC? {toc_entry.path}"
                    )
                else:
                    self._verify_log(f"Unexpected uncompressed file: {toc_entry.path}")

        elif pack_dir is not None:
            if toc_entry.path:
                data = pack_dir.joinpath(toc_entry.path).read_bytes()
                if toc_entry.is_wem_file() and self._odlc_wem:
                    # No compression for wem in ODLC, handle alignment later
                    compress = False

        else:
            # shouldn't happen, but ...
            raise ValueError("Invalid argument combination (pack_dir is None?).")

        # Encrypt data if needed, pack data, get block lengths
        if self._sng_crypto:
            if toc_entry.path.startswith(WIN_PATH):
                data = self.encrypt_sng(data, WIN_KEY)
            elif toc_entry.path.startswith(MAC_PATH):
                data = self.encrypt_sng(data, MAC_KEY)

        arc_data, block_lengths = self._arc_entry(data, compress)

        if self._verify:
            # Verify packed data
            if check_data != arc_data:
                self._verify_log(
                    f"Rebuilt archive entry/file doesn't match the original entry: "
                    f"{toc_entry.path}",
                    "WARNING",
                )
                self._verify_log(
                    "  This is probably an older CDLC that uses a non-standard "
                    "compression level/method."
                )
                self._verify_log(
                    "  Continuing tests using original TOC and contents for this file."
                )
                self._verify_log("  Byte perfect rebuild not possible.")
                # Replace verify return values with original data, otherwise
                # everything in the file will become broken because offsets are
                # shagged from here. Ugly, ugly, ugly hack.
                arc_data = check_data
                block_lengths = list()
                arc_len = 0
                for this_len in self._block_lengths[
                    self._toc_entries[check_index].first_block_index :
                ]:
                    block_lengths.append(this_len)
                    if this_len == 0:
                        this_len = DEFAULT_BLOCK_LEN
                    arc_len = arc_len + this_len
                    if arc_len >= len(arc_data):
                        break

        return arc_data, block_lengths, len(data)

    def _build_entries(self, pack_dir: Optional[Path], manifest: List[str]) -> None:
        """Build toc, block length vector and data blocks from manifest and pack_dir.

        Arguments:
            pack_dir {Optional[Path]} -- Per _pack.

        Keyword Arguments:
            verify {bool} -- Per _pack (default: {False})
            manifest {List[str]} -- As generated by _build_manifest (including the
                empty string first member!). (default: {None})

        If self._verify is True, this method does not modify the instance data.

        If this method is run in pack mode, both the toc entries and the block lengths
        are incomplete. Block lengths need to be corrected for any wem alignment blocks
        and toc entries need to be corrected for preamble, wem alignment offsets and
        wem alignment effects of first block index.

        """
        if self._verify:
            # Supply data block offset. We will check preamble later.
            offset = self._preamble_len
            first_block_index = 0
            check_lengths = list()

        for index, arc_path in enumerate(manifest):
            # Build up the toc entry as we go.
            # Offset and first block index both left at default (-1) for packing. Need
            # to correct later after calculating preamble length and wem alignment
            # blocks. Verification values are tidied up later in this routine.
            toc_entry = TocEntry(path=arc_path, md5=self._md5(index, manifest))

            # Grab the data and toc parameters.
            arc_data, block_lengths, raw_length = self._get_data(
                pack_dir, toc_entry, manifest
            )
            toc_entry.length = raw_length

            if self._verify:
                # Pack_data, pack_lengths are not set for verify (checked elsewhere).
                # Fix up toc entries and update accumulators
                toc_entry.offset = offset
                offset = offset + len(arc_data)

                toc_entry.first_block_index = first_block_index
                first_block_index = first_block_index + len(block_lengths)

                # Verify toc and check alignment as a a side effect
                align_len = self._verify_toc(toc_entry, index, arc_data)

                if align_len != 0:
                    # Correct block lengths for the alignment block
                    check_lengths.append(align_len)
                    # must also correct offset, first block index for future blocks
                    offset = offset + align_len
                    first_block_index = first_block_index + 1

                # As we now have made any correction needed for alignment blocks,
                # we can now append the toc entry lengths
                check_lengths.extend(block_lengths)

            else:
                toc_entry.pack_data = arc_data
                toc_entry.pack_lengths = block_lengths
                # Append toc entry to instance list. Still need to correct
                # various elements in toc, build block lengths vector.
                self._toc_entries.append(toc_entry)

        if self._verify:
            if check_lengths != self._block_lengths:
                self._verify_log(
                    f"Rebuilt block lengths do not match archive."
                    f"\nOriginal {self._block_lengths}"
                    f"\nRebuilt {check_lengths}"
                )

    def _finalise_toc(self) -> None:
        """Clean up toc entries and block_lengths array preparatory for pack."""
        if self._verify:
            raise RSFileFormatError(
                "_finalise_toc should never be called in verify mode."
            )

        # Correct offsets, and along the way insert any wem alignment blocks needed
        # Note that we can't do this any earlier, because the size of the alignment
        # block depends on the size of the header and the toc. Wem alignment block
        # inserts element into block lengths, changes offset and first block index
        # values, also need to add the block of zeros to the file data.
        align_blocks = 0
        block_len_count = 0
        for toc_entry in self._toc_entries:
            block_len_count = block_len_count + len(toc_entry.pack_lengths)
            if self._odlc_wem:
                # Count wem files, which is also the most likely number of aligns needed
                if toc_entry.is_wem_file():
                    align_blocks = align_blocks + 1

        aligns_used = -1
        while aligns_used != align_blocks:
            # may need more than one pass if doing wem align
            aligns_used = 0
            first_block_index = 0
            self._block_lengths = list()

            self._preamble_len = (
                HEADER_BYTES
                + len(self._toc_entries) * TOC_ENTRY_BYTES
                + (block_len_count + align_blocks) * BLOCK_LEN_BYTES
            )
            offset = self._preamble_len

            for toc_entry in self._toc_entries:
                if self._odlc_wem and toc_entry.is_wem_file():
                    # do the alignment thing, correct offsets, block lengths
                    align_bytes = WEM_ALIGN_LEN - (offset % WEM_ALIGN_LEN)
                    if align_bytes != 0:
                        offset = offset + align_bytes
                        toc_entry.align_bytes = align_bytes
                        aligns_used = aligns_used + 1
                        self._block_lengths.append(align_bytes)
                        first_block_index = first_block_index + 1

                # Finalise toc entry.
                toc_entry.offset = offset
                toc_entry.first_block_index = first_block_index
                self._block_lengths.extend(toc_entry.pack_lengths)

                # update offsets.
                offset = offset + len(toc_entry.pack_data)
                first_block_index = first_block_index + len(toc_entry.pack_lengths)

            if aligns_used != align_blocks:
                # Try again with 1 less align block.
                align_blocks = align_blocks - 1
                aligns_used = -1

            if align_blocks < 0:
                raise RSFileFormatError(
                    "Edge case: Cannot create block aligned wem files in archive."
                )

    def _pack(
        self,
        pack_dir: Optional[Path],
        odlc_wem: bool = True,
        use_manifest: Optional[List[str]] = None,
    ) -> None:
        r"""Create PSARC file from contents of directory.

        Arguments:
            pack_dir {Path} -- The target directory.
            odlc_wem {bool} -- If True, wem files will be aligned to 8192 byte
                blocks (0 padding) and will not be compressed. If False, wem files
                will be compressed and will not be aligned. This parameter is ignored
                for verify operations. (default: True)
            use_manifest {Optional[List[str]]} -- As described in init and class
                description.

        """
        self._odlc_wem = odlc_wem
        # Create a manifest list - all files in the archive excluding
        # the manifest itself.
        manifest = self._build_manifest(pack_dir, use_manifest)

        # now build the toc entries and data for each entry.
        self._build_entries(pack_dir, manifest)

        if not self._verify:
            # set up the toc for a single pass pack operation. Not needed for verify,
            # as this was done in situ.
            self._finalise_toc()

        self._write_preamble()

        if not self._verify:
            # Finally, the data block to file.
            for toc_entry in self._toc_entries:
                if toc_entry.align_bytes > 0:
                    self._fd.write(bytes(toc_entry.align_bytes))

                self._fd.write(toc_entry.pack_data)

    def __iter__(self) -> Iterator[int]:
        """Provide iterator for files in the archive excluding the manifest."""
        # start at 1, as we are not providing the manifest directly
        self._arc_index = 1
        return self

    def __next__(self) -> int:
        """Provide iterator index for files in the archive excluding the manifest."""
        if self._arc_index < len(self._toc_entries):
            ret_val = self._arc_index
            self._arc_index += 1
            return ret_val

        raise StopIteration

    # .sng encryption/decryption. Pretty well small variations on code in
    # 0x0L's rs-utils and rocksmith packages on github.
    # Still haven't figure out how to handle typing on pycryptodome yet.
    @staticmethod
    def _sng_cipher(key: bytes, b_init_vector: bytes) -> Any:
        """Return cipher object for decrypting SNG data.

        Arguments:
            key {bytes} -- Decryption key.
            b_init_vector {bytes} -- Initialisation vector.

        Returns:
            Any -- AES CTR mode cipher.

        """
        int_init_vector = int.from_bytes(b_init_vector, "big")
        # I'm taking 0x0Ls word here. From the docs, this is a 16 byte counter
        # that starts at whatever iv is (which I suspect to be 0 from 0x0Ls encrypt?)
        ctr = Counter.new(128, initial_value=int_init_vector, allow_wraparound=False)
        return AES.new(key, mode=AES.MODE_CTR, counter=ctr)

    @staticmethod
    def decrypt_sng(data: bytes, key: bytes) -> bytes:
        """Decrypt SNG file following recipe from 0x0L.

        Arguments:
            data {bytes} -- Encrypted SNG file data.
            key {bytes} -- Decryption key.

        Returns:
            bytes -- Decrypted song file.

        I've tested this method and confirmed it delivers the same output as 0x0L's
        pyrocksmith tool. However, as I don't use this functionality, this should be
        treated as a limited beta - I'd recommend using either 0x0L's toolset or the
        Rocksmith Custom Song Toolkit.

        """
        header = data[0:SNG_IV_OFFSET]
        if header != SNG_HEADER:
            raise RSFileFormatError(
                f"Unexpected header in '.SNG' file. Expected "
                f"'0x{SNG_HEADER.hex()}', got '0x{header.hex()}'."
            )

        b_init_vector = data[SNG_IV_OFFSET:SNG_ENC_PAYLOAD_OFFSET]
        # Remember to add 56 bytes of zeros to payload as signature when writing!
        # This is padding to replace the digital signature attached to the file.
        # The Customs Forge dll bypasses the DSA check, so the value doesn't matter.
        # Follow CFSM convention of 56 bytes of zeros.
        payload = data[SNG_ENC_PAYLOAD_OFFSET:SNG_SIG_OFFSET]

        cipher = Welder._sng_cipher(key, b_init_vector)
        payload = cipher.decrypt(rsrpad(payload, 16))
        length = struct.unpack("<L", payload[0:SNG_DEC_PAYLOAD_OFFSET])[0]
        payload = zlib.decompress(payload[SNG_DEC_PAYLOAD_OFFSET:])

        if length != len(payload):
            raise RSFileFormatError("Unexpected payload size in SNG file.")

        return payload

    @staticmethod
    def encrypt_sng(data: bytes, key: bytes) -> bytes:
        """Encrypt SNG file following recipe from 0x0L.

        Arguments:
            data {bytes} -- Raw SNG file data.
            key {bytes} -- Decryption key.

        Returns:
            bytes -- Encrypted song file.

        I've tested this method and confirmed it delivers the same output as 0x0L's
        pyrocksmith tool. However, as I don't use this functionality, this should be
        treated as a limited beta - I'd recommend using either 0x0L's toolset or the
        Rocksmith Custom Song Toolkit.

        """
        length = struct.pack("<L", len(data))

        payload = length + zlib.compress(data, zlib.Z_BEST_COMPRESSION)

        # Using 16 zero bytes as IV, in line with other rs decrypt/encrypt utilities
        b_init_vector = bytes(16)
        cipher = Welder._sng_cipher(key, b_init_vector)

        # encrypt and chop off padding
        e_payload = cipher.encrypt(rsrpad(payload, 16))[: len(payload)]
        # Add 56 bytes of zeros to payload as signature when writing!
        # This is padding to replace the digital signature attached to the file.
        # The Customs Forge dll bypasses the DSA check, so the value doesn't matter.
        # Follow CFSM convention of 56 bytes of zeros.
        e_payload = SNG_HEADER + b_init_vector + e_payload + bytes(56)

        return e_payload


def main() -> None:
    """Provide basic command line interface for Welder."""
    parser = argparse.ArgumentParser(
        description="Command line interface for managing rocksmith psarc files."
    )

    parser.add_argument(
        "file_or_dir_path",
        help="Path to the target psarc file for read actions, or path to the target "
        "folder for packing.",
    )
    parser.add_argument(
        "--use-manifest",
        help="Only applicable for pack operations. Reads the manifest from the named "
        "psarc file and uses it as the manifest for building the archive. Provided "
        "for debugging only. This argument ensures the new archive will be packed in "
        "the same order as the psarc_file specified, and is only really useful for "
        "checking a rebuild of the named file from disk (i.e. after unpack ding.psarc "
        "to disk, you can force the same manifest for a rebuild check by specifying "
        "the original ding.psarc as the argument to --use-manifest). Ignored for "
        "read and verify actions.",
        metavar="manifest_psarc_file",
    )

    parser.add_argument(
        "--sng-crypto",
        help="If specified, '.sng' files will be decrypted during "
        "unpack operations and encrypted during pack operations. Otherwise the files "
        "are packed/unpacked as is. This flag is only relevant for users that "
        "modify data in the '.sng' files. This is beta functionality - you'd be better "
        "off using 0x0L's tool set or the Rocksmith Custom Song Toolkit. Disabled by "
        "--verify.",
        action="store_true",
    )

    parser.add_argument(
        "--no-odlc-wem",
        help="Only affects pack operation. If specified, disables ODLC wem handling "
        "(no compression, aligned to block boundaries). Instead, wem files are "
        "compressed and block boundary alignment is ignored. This is primarily "
        "intended for debug reconstruction of byte perfect CDLC.",
        action="store_true",
    )

    parser.add_argument(
        "--cdlc-md5",
        help="Only affects pack operation. If specified, uses a 'standard' CDLC md5 "
        "(I have no idea how this is derived), rather than 16 zero bytes. Again, this "
        "is primarily intended for debug reconstruction of byte perfect CDLC.",
        action="store_true",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--extract",
        help="Finds all matching files in the manifest and saves them to the"
        "working directory. File matching is done by comparing the end of the manifest "
        "file path with the supplied extract_name. For example, an extract string of "
        "'songs_dlc_bong/bong_lead.json' will extract the file 'bong_lead.json' from "
        "the archive path: 'manifests/songs_dlc_bong/bong_lead.json'. If you want to "
        "extract all JSON files, use an extract_name of '.json'. If you want to find "
        "a specific file, use --list find out what the archive contains, and then "
        "extract to obtain the file (although it may often be easier just "
        "to unpack the entire archive). The match doesn't support wildcards, but is "
        "case insensitive.",
        metavar="extract_name",
    )
    group.add_argument(
        "--list", help="Prints a list of the files in the archive.", action="store_true"
    )
    group.add_argument(
        "--pack",
        help="TODO: Packs the named folder into a Rocksmith psarc file in the working"
        "directory, does not overwrite existing files.",
        action="store_true",
    )
    group.add_argument(
        "--unpack",
        help="Extracts all files from the archive into the current working"
        "directory. Creates a new folder from the archive name excluding .psarc.",
        action="store_true",
    )
    group.add_argument(
        "--verify",
        help="Read mode only. Checks the archive against expectations and tests "
        "ability to reconstruct archive. Primarily intended for development testing. "
        "Disables sng_crypto for verification phase.",
        action="store_true",
    )

    args = parser.parse_args()

    manifest: Optional[List[str]]
    manifest = None
    odlc_wem = True
    cdlc_md5 = False
    if args.pack:
        mode = "x"
        odlc_wem = not args.no_odlc_wem
        cdlc_md5 = args.cdlc_md5
        if args.use_manifest is not None:
            manifest = list()
            with Welder(Path(args.use_manifest), "r") as psarc:
                for index in psarc:
                    manifest.append(psarc.arc_name(index))
    else:
        mode = "r"

    with Welder(
        Path(args.file_or_dir_path),
        mode,
        sng_crypto=args.sng_crypto,
        use_manifest=manifest,
        odlc_wem=odlc_wem,
        cdlc_md5=cdlc_md5,
    ) as psarc:
        if args.list:
            for index in psarc:
                print(f"{index}: {psarc.arc_name(index)}")

        if args.unpack:
            psarc.unpack()

        if args.extract is not None:
            name = args.extract.casefold()
            for index in psarc:
                if psarc.arc_name(index).casefold().endswith(name):
                    file = Path(".").joinpath(Path(psarc.arc_name(index)).name)
                    file.write_bytes(psarc.arc_data(index))

        if args.verify:
            psarc.verify(sys.stdout)


if __name__ == "__main__":
    main()
