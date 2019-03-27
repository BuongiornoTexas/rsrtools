#!/usr/bin/env python3
"""Provides a class (RSSaveFile) for loading and saving Rocksmith save files.

I do not recommend using this class on its own, as it does not provide any protection
from overwriting save files (no backups) and doesn't manage interactions between the
Rocksmith files and steam.

Instead, use the profile manager class, RSProfileManager, which handles these issues
automatically. RSSaveFile is a service provider for RSProfileManager.

Usage:
    See RSSaveFile class help.

Implements:
    RSSaveFile: A class for reading & writing Rocksmith user save files, credential
        files, and LocalProfiles.json files (*_PRFLDB, *.crd, LocalFiles.json).
    self_test(): A limited self test method.

Calling this module as a script runs the self test (__name__=="__main__"). This can be
run from the command line by:

    py -m rsrtools.files.savefile <test_dir>

Where test_dir is the name of a directory containing one or more files that can be used
for testing (I wouldn't run this on any files in the steam directory though ...)
"""

import struct
import zlib
import argparse
from os import fsdecode
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, Union, List
from decimal import Decimal

import simplejson

# pycryptodome provides Crypto replacement
# noinspection PyPackageRequirements
from Crypto.Cipher import AES

from rsrtools.files.exceptions import RSFileFormatError
from rsrtools.utils import rsrpad

# aliases for first level of Rocksmith json tree types.
# mypy doesn't do recursion at the moment, and may never,
# casting to any makes life a whole lot easier in handling the json structure.
RSJsonRoot = Dict[str, Any]

# Encryption key for Rocksmith save files
SAVE_FILE_KEY: bytes = bytes.fromhex(
    "728B369E24ED0134768511021812AFC0A3C25D02065F166B4BCC58CD2644F29E"
)

HEADER_BYTES = 16
PAYLOAD_SIZE_BYTES = 4
FIRST_PAYLOAD_BYTE: int = HEADER_BYTES + PAYLOAD_SIZE_BYTES
ECB_BLOCK_SIZE = 16


class RSSaveFile:
    """File manager for Rocksmith save files. Loads, writes and exposes file data.

    Rocksmith save files (*_PRFLDB, *.crd, and LocalProfiles.json) should be managed
    with RSProfileManager, which automatically handles interactions between Rocksmith
    files and steam (not managed by this class).

    Based on routines from 0x0L.

    The key class methods are:
        Constructor: loads a file and exposes the data as a simplejson member
            self.json_tree.
        write_save_file: Saves file based on data in simplejson object self.json_tree.
            Does not make backups, **use at your own risk**. Can either overwrite
            original file or save to new file.
        save_json_file: Save json file to text. Includes any Ubisoft formatting.
        generate_save_file: Returns a byte object containing the save file
            corresponding the current json tree.

    The object exposes json_tree, which is the JSON data dictionary loaded from the
    Rocksmith profile.

    The Constructor performs limited self checks when loading a file. These checks try
    to reconstruct the original source file from the simplejson tree. If the self check
    fails, it implies that the class implementation is not consistent with the source
    file. This could be because of Ubisoft changing file structure or because of a
    corrupt file. In either instance, this tool should not be used for changing save
    file data, as it is almost certain to result in file that is unreadable by
    Rocksmith and may corrupt the installation.
    """

    _debug: bool
    _json_debug_path: Optional[Path]
    _file_path: Path
    _check_padding: bytes
    _original_file_data: bytes
    _header: bytes
    # too hard to figure out how factory annotation works today.
    # for now make _cipher explictly dynamic with an Any type
    # TODO: more reading another time.
    _cipher: Any
    _debug_z_payload: bytes  # compressed payload
    _debug_payload: bytes  # null terminated payload
    json_tree: RSJsonRoot

    def __init__(
        self, rs_file_path: Path, json_debug_file: str = None, debug: bool = False
    ) -> None:
        """Read a file, perform reconstructability test, and expose file data as self.json_tree.

        Arguments:
            rs_file_path {pathlib.Path} -- The name/path of the Rocksmith file to load.

        Keyword Arguments:
            json_debug_file {str} -- If supplied, the constructor will write the
                decoded json payload as text to the file/path specified by
                json_debug_file. This occurs before dumping to simplejson and
                reconstruction tests. (default: {None})
            debug {bool} -- if specified as True, generates and keeps more data in the
                raw file/decrypted payload/decompressed payload. Primarily intended for
                use if/when Ubisoft change file format. It may also be useful in
                repairing corrupted files. (default: {False})

        Developer functionality: If both _debug and json_debug_file are specified and
        reconstruction of the json file fails, the reconstructed json will be saved as
        json_debug_file + '.reconstruct'. Comparing this and the raw json may help
        identify format updates to be applied in _generate_json_string.

        Subclasses should *always* call super().__init__() for reading the file if
        overriding. See also docs for _apply_UBI_formats if it exists.
        """
        self._debug = debug
        if json_debug_file is None:
            self._json_debug_path = None
        else:
            self._json_debug_path = Path(json_debug_file)

        self._file_path = rs_file_path

        self._read_save_file()

        # run self check on file reconstructability, discard return
        self._generate_file_data(self_check=True)

    def _generate_json_string(self) -> str:
        """Generate json string and and apply Ubisoft specific formatting.

        Returns:
            str -- formatted payload string.

        This method allows overriding to implement specific formatting for each
        different file. For example, if the _PRFLDB file format is changed to something
        that breaks other files, we can create <subclass>._generate_json_string to
        handle specific formatting.

        As of March 2019, there is no variation between the file types (no subclassing
        needed).

        Note: any override must either generate the json dump or call this routine with
        super() to do so.

        """
        # as of 14/6/18, Ubisoft separators are: (',',' : '), indent is 0
        payload = simplejson.dumps(self.json_tree, separators=(",", " : "), indent=0)

        # this pattern is needed by LocalFiles.json, *_PRFLDB, not by crd
        payload = payload.replace('" : [', '" : \n[')

        # these patterns are needed for PRFLDB, not used in others
        payload = payload.replace(" : {}", " : {\n}")
        payload = payload.replace("\n[]", "\n[\n]")
        payload = payload.replace("\n{}", "\n{\n}")
        payload = payload.replace("\n[\n[", "\n[\n\n[")
        payload = payload.replace("\n],\n[", "\n],\n\n[")
        payload = payload.replace("\n[]", "\n[\n]")
        # the next two deal with an annoyance where simplejson converts two unicode
        # chars to lower case. There no internal difference for python, but just in
        # case Rocksmith goes it's own way,let's make it internally consistent
        payload = payload.replace(r"\u00ae", r"\u00AE")
        payload = payload.replace(r"\u00c2", r"\u00C2")

        return payload

    def _compress_payload(self) -> Tuple[bytes, int]:
        """Generate and return compressed payload and uncompressed payload size.

        Returns:
            (bytes, int) -- Compressed payload, size of of uncompressed payload in
                bytes.

        Includes self checking on reconstructability if required.

        """
        payload_str = self._generate_json_string()

        # convert str payload to terminated bytes
        # RS expects null terminated payload
        payload = b"".join([payload_str.encode(), b"\x00"])

        z_payload = zlib.compress(payload, zlib.Z_BEST_COMPRESSION)

        if self._debug:
            if payload != self._debug_payload:
                if self._json_debug_path is not None:
                    self.save_json_file(
                        self._json_debug_path.with_suffix(
                            self._json_debug_path.suffix + ".reconstruct"
                        )
                    )

                raise RSFileFormatError(
                    "Mismatch between original payload and self check reconstructed "
                    "payload in: \n\n    {0}\n\nRun with _debug=True and "
                    "json_debug_file specified to gather "
                    "diagnostics.".format(fsdecode(self._file_path))
                )

            if z_payload != self._debug_z_payload[: len(z_payload)]:
                # debug_z_payload may include padding, which appears to be:
                #   \x00 + random bytes to end of 16 byte padding block.
                # (I'm really hoping it isn't Rocksmith data - if it is, none of this
                # editing will work!). So we compare without padding.
                raise RSFileFormatError(
                    "Mismatch between original compressed payload and self check "
                    "reconstruction in:\n\n    {0}\n".format(fsdecode(self._file_path))
                )

        return z_payload, len(payload)

    def _generate_file_data(self, self_check: bool) -> bytes:
        """Convert simplejson data into save file as bytes object.

        Arguments:
            self_check {bool} -- If True, the call will run a self check on file
                reconstructabilty. Only meaningful in constructor. Use True in
                __init__, False elsewhere.

        Returns:
            bytes -- Binary file data.

        Includes self checking on reconstructability.

        """
        # compress payload is a one stop shop, converting simplejson
        # data to bytes and compressing it.
        (z_payload, payload_size) = self._compress_payload()

        if self_check:
            # only for the self check, add original padding before encrypting
            z_payload = b"".join([z_payload, self._check_padding])
        else:
            # create an appropriate pad which will hopefully not break Rocksmith!
            z_payload = rsrpad(z_payload, ECB_BLOCK_SIZE)

        file_data = self._cipher.encrypt(z_payload)

        size_array = struct.pack("<L", payload_size)

        file_data = b"".join([self._header, size_array, file_data])

        if self_check:
            if file_data != self._original_file_data:
                raise RSFileFormatError(
                    "Mismatch between original file and self check reconstruction in: "
                    "\n\n    {0}\n".format(fsdecode(self._file_path))
                )
            elif not self._debug:
                # discard self check vars. If we didn't have the problem of random
                # padding in the encryption, it would have been good to retain the
                # original file data to check if the file had changed before writing.
                # But we do, so we don't. Could keep the z_payload if this was a really
                # useful check?
                self._original_file_data = b""
                self._check_padding = b""

        return file_data

    def generate_save_file(self) -> bytes:
        """Return a bytes object containing the save file corresponding the current json tree.

        Returns:
            bytes -- Binary file data.

        This is intended for use in managing multiple save files at once. It does not
        provide belt and braces backups. Use at your own risk.

        """
        return self._generate_file_data(self_check=False)

    def _write_save_file(self, save_path: Path, mode: str) -> None:
        """Save instance data to file.

        Keyword Arguments:
            save_path {pathlib.Path} -- Save file name/path.
            mode {str} -- File open mode. Must be a valid binary write mode. Should be
                either "wb" or "xb".

        """
        file_data = self._generate_file_data(self_check=False)

        with save_path.open(mode) as fh:
            fh.write(file_data)

    def overwrite_original(self) -> None:
        """Overwrite original save file with instance data."""
        self._write_save_file(self._file_path, "wb")

    def save_to_new_file(self, save_path: Path) -> None:
        """Save instance data to a new save file.

        Keyword Arguments:
            save_path {pathlib.Path} -- Save file name/path.

        The method will not overwrite existing files.
        """
        self._write_save_file(save_path, "xb")

    def _load_file(self) -> None:
        """Load save file into memory and perform preliminary integrity checks."""
        with self._file_path.open("rb") as f:
            # discard self._original_file_data after validation at end of __init__
            self._original_file_data = f.read()

        self._header = self._original_file_data[0:HEADER_BYTES]

        found_magic = self._header[0:4]
        expect_magic = b"EVAS"
        if found_magic != expect_magic:
            raise RSFileFormatError(
                "Unexpected value in in file: \n\n    {0}"
                "\n\nExpected '{1}' as first four bytes (magic number), "
                "found '{2}'.".format(
                    fsdecode(self._file_path),
                    expect_magic.decode(),
                    found_magic.decode(),
                )
            )

    def _decompress_payload(self, z_payload: bytes) -> bytes:
        """Decompress compressed payload, and return decompressed payload.

        Arguments:
            z_payload {bytes} -- Compressed payload.

        Raises:
            RSFileFormatError -- On unexpected data/file format.

        Returns:
            bytes -- Decompressed payload with no padding.

        """
        # decompress binary
        #  - returns only decompressed data bytes.
        # That is decompress discards any garbage padding bytes at the end of stream.
        payload = zlib.decompress(z_payload)

        # We need to recover the encryption padding for self test. To do this:
        #  - reconstruct the compressed data stream
        #  - padding must be all data in the original compressed data past the length
        # of the reconstructed stream.
        # This is really clumsy, but is needed for reconstruction of the original file
        actual_z_payload_len = len(zlib.compress(payload, zlib.Z_BEST_COMPRESSION))
        self._check_padding = z_payload[actual_z_payload_len:]

        # get size of C null (\0) terminated decrypted json string from the header
        # if I'm reading this correctly, 4 byte little endian value
        # starting from byte 16 (Thanks 0x0L)
        size_array = self._original_file_data[HEADER_BYTES:FIRST_PAYLOAD_BYTE]
        expect_payload_size = struct.unpack("<L", size_array)[0]

        if len(payload) != expect_payload_size:
            raise RSFileFormatError(
                "Unexpected decompressed payload size in file: \n\n    {0}"
                "\n\nExpected {1} bytes, found "
                "{2} bytes.".format(
                    fsdecode(self._file_path),
                    str(expect_payload_size),
                    str(len(payload)),
                )
            )

        return payload

    def _read_save_file(self) -> None:
        """Read save file into memory.

        Reading file takes the following steps:
            - Read binary file.
            - Extract header and decompressed payload size.
            - Decrypt payload.
            - Decompress payload to bytes.
            - Read the payload into a simplejson object.
        """
        self._load_file()

        # create cipher for decrypting/encrypting
        self._cipher = AES.new(SAVE_FILE_KEY, AES.MODE_ECB)

        # 0x0L padded the encrypted data to 16 bytes.
        # However, from my quick checks, this looks unnecessary - the file data already
        # appears to be aligned on 16 byte blocks. I've removed this pad call, but
        # included a check and raise an exception if needed.
        z_payload = self._original_file_data[FIRST_PAYLOAD_BYTE:]

        if (len(z_payload) % ECB_BLOCK_SIZE) != 0:
            raise RSFileFormatError(
                "Unexpected encrypted payload in file: \n\n    {0}"
                "\n\nPayload should be multiple of {1} bytes, found {2} unexpected "
                "bytes.".format(
                    fsdecode(self._file_path),
                    ECB_BLOCK_SIZE,
                    len(z_payload) % ECB_BLOCK_SIZE,
                )
            )

        z_payload = self._cipher.decrypt(z_payload)

        payload = self._decompress_payload(z_payload)

        # gather _debug data for future use
        if self._debug:
            self._debug_z_payload = z_payload
            self._debug_payload = payload

        # remove trailing null from payload
        payload = payload[:-1]

        if self._json_debug_path is not None:
            # Note: this is the raw json as loaded, not reconstructed.
            # See save_json_file for reconstructed json file
            with self._json_debug_path.open("xt") as fh:
                fh.write(payload.decode())

        # we use simplejson because it understands decimals and will preserve number
        # formats in the file (required for reconstructability checks).
        self.json_tree = simplejson.loads(payload.decode(), use_decimal=True)

    def save_json_file(self, file_path: Path) -> None:
        """Generate json string including Ubisoft formatting and save to a file.

        Arguments:
            file_path {pathlib.Path} -- File/path for saving json data.

        Useful for debugging and working out changes in file formats.
        """
        payload = self._generate_json_string()
        with file_path.open("xt") as fh:
            fh.write(payload)


def self_test() -> None:
    """Limited self test for RSSaveFile.

    Run with:
        py -m rsrtools.files.savefile test_directory

    test_directory must contain one or more Rocksmith files for testing (*.crd,
    LocalProfiles.json, *_PRFLDB).

    I'd strongly recommend you **do not** run this script on any of your steam
    directories.
    """
    parser = argparse.ArgumentParser(
        description="Runs a self test of RSSaveFile on a specified directory."
    )
    parser.add_argument(
        "test_directory",
        help="A directory containing RS save files that will be used for the "
        "self test.",
    )
    test_dir = parser.parse_args().test_directory

    keep_save_file = None
    for child in Path(test_dir).iterdir():
        if child.is_file():
            try:
                keep_save_file = RSSaveFile(child)
                print(
                    'Successfully loaded and validated save file "{0}".'.format(
                        fsdecode(child)
                    )
                )
            except Exception as exc:
                # probably not a save file. Provide a message and move on.
                print(
                    'Failed to load and validate file "{0}".\nIf this file is a '
                    "Rocksmith save file, there may be a problem with with the "
                    "RSSaveFile class. Error details follow.".format(fsdecode(child))
                )
                print(exc)

    if keep_save_file is not None:
        test_path = keep_save_file._file_path
        test_path = test_path.with_suffix(test_path.suffix + "test.tmp")

        if test_path.exists():
            print(
                'File "{0}" exists. Save and reload test not run (rename/delete '
                "existing file for test).".format(fsdecode(test_path))
            )
        else:
            try:
                keep_save_file.save_to_new_file(test_path)
                print('Saved test file "{0}".'.format(fsdecode(test_path)))

                try:
                    keep_save_file = RSSaveFile(test_path)
                    print("  Reloaded and validated test file.")
                except Exception as exc:
                    print(
                        "  Failed to reload and validate test file. Error details "
                        "follow."
                    )
                    print(exc)

                # clean up
                test_path.unlink()

            except Exception as exc:
                print(
                    'Failed to save test file "{0}".\nThere '
                    "may be a problem with with the RSSaveFile class. Error details "
                    "follow.".format(fsdecode(test_path))
                )
                print(exc)


if __name__ == "__main__":
    self_test()
