#!/usr/bin/env python3
"""Provides classes for managing Steam cloud metadata files (remotecache.vdf).

Refer to class SteamMetadata for further detail/definitions.
"""

from os import fsdecode
from pathlib import Path
from hashlib import sha1
from collections import abc
from enum import Enum
from typing import Dict, Any, Iterator, Tuple, Mapping, Optional

from rsrtools.utils import double_quote

REMOTE_CACHE_NAME = "remotecache.vdf"
SECTION_START = "{"
SECTION_END = "}"
SEPARATOR = "\t\t"
BLOCK_SIZE = 65536


class SteamMetadataKey(Enum):
    """Provides a list of writeable metadata keys for Steam cloud files."""

    SIZE = '"size"'
    LOCALTIME = '"localtime"'
    TIME = '"time"'
    SHA = '"sha"'


class SteamMetadataError(Exception):
    """Base class for Steam metadata handling errors."""

    def __init__(self, message: str = None) -> None:
        """Minimal constructor.

        Keyword Arguments:
            message {str} -- Custom error text. If no message is supplied (default),
                the exception will supply a not very informative message.
                (default: {None})
        """
        if message is None:
            message = "An unspecified Steam cloud metadata handling error had occurred."

        super().__init__(message)


class SteamMetadata:
    r"""Finds and loads Steam cloud metadata file and manages updates to this file.

    Public methods:
        Constructor: Finds and loads a Steam cloud metadata file from a specified
            directory.
        metadata_exists: Returns True if a metadata set exists for a Steam cloud file
            (app_id/file_path pair).
        update_metadata_set: Updates writeable metadata values for a Steam cloud file.
        write_metadata_file: Saves the instance metadata to file.
        file_path: Returns the path to the underlying Steam metadata file.

    Key Terms:
        Steam cloud file: A file automatically backed up by Steam to a remote server.
            A Steam cloud file has both a path and an associated app_id. The path is
            typically of the form:
                <Steam path>\<user_id>\<app_id>\remote\<cloud file name>.
        app_id: A Steam game or application identifier.
        Steam cloud file metadata set or cloud file metadata set: Metadata describing a
            single Steam cloud file, such as modification time, hashes, etc.
        Steam metadata file: A file containing metadata about Steam cloud files for a
            game or Steam application. Typically named remotecache.vdf and found in the
            same directory as the remote directory. This file contains a set of metadata
            for each Steam cloud file in the remote directory.

        The following extract from a Steam remotecache.vdf for a Rocksmith
        LocalProfiles.json file shows the typical metadata for a Steam cloud file.

            {
                "root"		"0"
                "size"		"244"
                "localtime"		"1551482347"
                "time"		"1551482345"
                "remotetime"		"1551482345"
                "sha"		"685..."
                "syncstate"		"1"
                "persiststate"		"0"
                "platformstosync2"		"-1"
            }

    Warning: The class does not validate the steam cloud files and does not validate
    the file locations. These are caller responsibilities.

    Implementation notes for the Steam metadata dictionary (self._steam_metadata):
        - This is a dictionary with one entry:
            key = Steam app_id
            value = file dictionary
        - The file dictionary has one entry per Steam cloud file, where each entry:
          consists of:
            key = Steam cloud file name
            value = A dictionary containing the metadata for the Steam cloud file.

    """

    # lazy annotation here.
    # Path to Steam metadata file.
    _metadata_path: Path
    # Instance version of the steam metadata
    _steam_metadata: Dict[str, Dict[str, Dict[str, str]]]
    _is_dirty: bool

    def _read_steam_metadata(self) -> None:
        """Read Steam metadata file and load metadata dictionary."""
        self._steam_metadata = dict()

        # ugly custom parser, cos Steam doesn't do standard file formats
        # node needs a type to stop mypy collapsing during the walk
        node: dict = self._steam_metadata
        section_label = ""
        branches = list()
        with self._metadata_path.open("rt") as fh:
            for line in fh:
                key = line.strip()
                try:
                    (key, value) = key.split()
                except ValueError:
                    if key == SECTION_START:
                        node[section_label] = dict()
                        branches.append(node)
                        node = node[section_label]
                        section_label = ""
                    elif key == SECTION_END:
                        node = branches.pop()
                    else:
                        section_label = key
                else:
                    node[key] = value

        # sense check
        if branches:
            raise SteamMetadataError(
                "Incomplete Steam metadata file: at least one section is not "
                'terminated.\n  (Missing "}".)'
            )

    @staticmethod
    def _update_metadata_key_value(
        metadata_set: Dict, key: SteamMetadataKey, value: str
    ) -> None:
        """Update value for the specified key in the Steam cloud file metadata set.

        Arguments:
            metadata_set {dict} -- Metadata set for a Steam cloud (remote) file
                (see _cloud_file_metadata_set).
            key {SteamMetadataKey} -- Key to update in the metadata set. Must be a
                member of SteamMetadataKey enum. The key must already exist in the
                metatdata dict (no creating new keys).
            value {str} -- New value to be assigned to the key. The caller is
                responsible for value formatting per Steam standards.

        Raises:
            ValueError -- Raised for an invalid key.
            KeyError -- Raised for a valid key that is not in the dictionary.

        Implementation detail: This a static method as it operates on the metadata
        dictionary for a specific file, rather than on self._steam_metadata, which
        which contains metadata for a *set* of Steam cloud files, and the method does
        not reference any other instance data.

        """
        # pylint - may cause problems with enum?
        # if type(key) is not SteamMetadataKey:
        if not isinstance(key, SteamMetadataKey):
            raise ValueError("Invalid Steam metadata key {0} specified".format(key))

        # watch out for the need to use the key value twice, otherwise create a
        # new entry in dict.
        if key.value in metadata_set:
            metadata_set[key.value] = double_quote(value)
        else:
            # this really, really shouldn't happen implies a corrupt Steam cache
            # file/file with missing keys.
            raise KeyError(
                "Steam metadata entry does not exist for key {0}.".format(key.name)
            )

    def _cloud_file_metadata_set(self, app_id: str, file_path: Path) -> Dict:
        """Return the Steam cloud file metadata set for the app_id/file_path pair.

        Arguments:
            app_id {str} -- Steam app id for the Steam cloud file.
            file_path {pathlib.Path} -- Path to the Steam cloud file. Warning: this
                method extracts the filename from the path and ignores all other path
                information. It is the caller responsibility to ensure the path points
                to the correct steam cloud file.

        Raises:
            KeyError -- Raised if the Steam metadata does not contain an entry for the
                app_id/file_path parameters.

        Returns:
            dict -- Steam cloud file metadata set for the app_id/file_path pair.

        Note: This method returns the metadata dictionary for a single Steam cloud
        file. It does **not** return self._steam_metadata (see Class help for
        definition).

        """
        file_metadata = None
        # This will throw a key error if the metadata dictionary doesn't contain
        # entries for app_id. Otherwiser returns a dictionary of dicts containing
        # metadata for *ALL* of the steam cloud files associated with the app_id. Need
        # to search this dict to find the sub-dictionary for the target file.
        file_dict = self._steam_metadata[double_quote(app_id)]

        # As I've seen weird case stuff for file names in remotecache.vdf, assume we
        # need to do a case insensitive check for the filename. Should be OK for
        # windows, may break on OSX/Linux
        find_name = double_quote(file_path.name.upper())
        for check_name in file_dict.keys():
            if check_name.upper() == find_name:
                file_metadata = file_dict[check_name]
                break

        if file_metadata is None:
            raise KeyError(
                "No Steam metadata entry  for file {0} in "
                "app {1}".format(find_name, app_id)
            )

        return file_metadata

    def metadata_exists(self, app_id: str, file_path: Path) -> bool:
        """Return True if a metadata set exists for a Steam cloud file.

        Arguments:
            app_id {str} --  Steam app id for the Steam cloud file.
            file_path {pathlib.Path} -- Path to the Steam cloud file. Warning: this
                method extracts the filename from the path and ignores all other path
                information. It is the caller responsibility to ensure the path points
                to the correct steam cloud file.

        """
        ret_val = True

        try:
            self._cloud_file_metadata_set(app_id, file_path)
        except KeyError:
            ret_val = False

        return ret_val

    def update_metadata_set(
        self, app_id: str, file_path: Path, data: bytes = None
    ) -> None:
        """Update all writeable metadata for a Steam cloud file.

        Arguments:
            app_id {str} --  Steam app id for the Steam cloud file.
            file_path {pathlib.Path} -- Path to the Steam cloud file. Warning: this
                method extracts the filename from the path to identify the metadata set
                and updates metadata based on the file properties. It is the caller
                responsibility to ensure the path points to the correct steam cloud
                file (i.e. this method does not validate that the file is valid
                steam cloud file in a valid location).

        Keyword Arguments:
            data {bytes} -- Binary Steam cloud file held in memory
                (default: {None})

        By default, this method will determine the writeable Steam cloud metadata
        values (hash, size and modification times) directly from the file on  disk.
        However, if the otional data argument is supplied, the hash and size values
        will be calculated from the contents of data.

        This method does nothing if the metadata set for the Steam cloud file does not
        exist.

        """
        try:
            cache_dict = self._cloud_file_metadata_set(app_id, file_path)
        except KeyError:
            # file metadata set dict not found, so do nothing.
            return

        hasher = sha1()
        if data is None:
            with file_path.open("rb") as fh:
                buffer = fh.read(BLOCK_SIZE)
                while buffer:
                    hasher.update(buffer)
                    buffer = fh.read(BLOCK_SIZE)

            # st_size works on windows
            file_size = file_path.stat().st_size
        else:
            hasher.update(data)
            file_size = len(data)

        self._update_metadata_key_value(
            cache_dict, SteamMetadataKey.SIZE, str(file_size)
        )

        self._update_metadata_key_value(
            cache_dict, SteamMetadataKey.SHA, hasher.hexdigest().lower()
        )

        # st_mtime appears gives the right (UTC since jan 1 1970) values on Windows,
        # probably also OK on OSX, Linux?
        self._update_metadata_key_value(
            cache_dict, SteamMetadataKey.LOCALTIME, str(int(file_path.stat().st_mtime))
        )
        self._update_metadata_key_value(
            cache_dict, SteamMetadataKey.TIME, str(int(file_path.stat().st_mtime))
        )

        # instance contents out of sync with metadata file.
        self._is_dirty = True

    def _iter_tree(self, tree: Mapping[Any, Any]) -> Iterator[Tuple[Any, Any]]:
        """Iterate (walk) the Steam metadata tree.

        Arguments:
            tree {dict} -- A node in the self._steam_metadata dictionary.

        Helper method for write_metadata_file.

        """
        for key, value in tree.items():
            if isinstance(value, abc.Mapping):
                yield key, SECTION_START
                for inner_key, inner_value in self._iter_tree(value):
                    yield inner_key, inner_value
                yield key, SECTION_END
            else:
                yield key, value

    def write_metadata_file(self, save_dir: Optional[Path]) -> None:
        """Write Steam metadata file if instance data differs from the original file.

        Arguments:
            save_dir {Optional[pathlib.Path]} -- Save directory for the steam metadata
                file or None.

        If save_dir is specified as None, the original steam metadata file will be
        overwritten.

        Otherwise the updated file is written to save_dir with the original file name.
        Further, the object instance remains marked as dirty, as the object data is out
        of sync with the original source files loaded by the object. (this is only an
        issue if the caller intent is to update original files later).

        Note: The Steam metadata file will likely contain metadata for more than one
        Steam cloud file. This is typically the desired state.
        """
        if self._is_dirty:
            indent = ""
            file_lines = list()
            for key, value in self._iter_tree(self._steam_metadata):
                if value == SECTION_START:
                    file_lines.append("".join([indent, key, "\n"]))
                    file_lines.append("".join([indent, SECTION_START, "\n"]))
                    indent = indent + "\t"
                elif value == SECTION_END:
                    indent = indent[:-1]
                    file_lines.append("".join([indent, SECTION_END, "\n"]))
                else:
                    file_lines.append("".join([indent, key, SEPARATOR, value, "\n"]))

            if save_dir is None:
                with self._metadata_path.open("wt") as fh:
                    fh.writelines(file_lines)
                # original source file and instance now in sync
                self._is_dirty = False

            else:
                save_path = save_dir.joinpath(self._metadata_path.name)

                with save_path.open("xt") as fh:
                    fh.writelines(file_lines)

    def __init__(self, search_dir: Path) -> None:
        """Locate Steam metadata file in search_dir and load it.

        Arguments:
            search_dir {pathlib.Path} -- Search directory for metadata file.

        Raises:
            FileNotFoundError -- Metadata file not found.

        """
        # see if we can find a path to remotecache.vdf.
        self._is_dirty = False

        target_path = search_dir.joinpath(REMOTE_CACHE_NAME)

        if target_path.is_file():
            self._metadata_path = target_path
        else:
            raise FileNotFoundError(
                "Steam metadata file {0} expected but not found in:\n   {1}".format(
                    REMOTE_CACHE_NAME, fsdecode(search_dir)
                )
            )

        self._read_steam_metadata()

    @property
    def file_path(self) -> Path:
        """Return the path to the underlying Steam metadata file.

        Returns:
            pathlib.Path -- Path to metadata file.

        """
        return self._metadata_path
