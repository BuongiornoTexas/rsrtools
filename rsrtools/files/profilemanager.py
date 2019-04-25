#!/usr/bin/env python3
"""Provides classes for managing a group of Rocksmith save files owned by a Steam user.

The primary public class is RSProfileManager. The other classes are helpers that support
the operation of the profile manager class.

For command line options (database setup, reporting), run:
    'python -m rsrtools.files.profilemanager -h'
"""

# cSpell:ignore shutil, PRFLDB, mkdir, strftime

import argparse
import time
import copy
import logging
import shutil
from decimal import Decimal
from zipfile import ZipFile
from typing import (
    cast,
    Dict,
    Sequence,
    Union,
    Tuple,
    Optional,
    Any,
    Iterator,
    Set,
    List,
)
from pathlib import Path
from os import fsdecode

from rsrtools import utils
from rsrtools.steam import SteamAccounts, SteamMetadataError
from rsrtools.files.config import ProfileKey, MAX_SONG_LIST_COUNT
from rsrtools.files.savefile import RSSaveFile, RSJsonRoot
from rsrtools.files.steamcache import SteamMetadata

# Rocksmith meta data file. Ties profile name to profile id.
LOCAL_PROFILES = "LocalProfiles.json"
STEAM_REMOTE_DIR = "remote"
RS_WORKING_DIR = "RS_working"
RS_BACKUP_DIR = "RS_backup"
RS_UPDATE_DIR = "RS_update"
PROFILE_DB_STR = "_PRFLDB"
RS_APP_ID = "221680"
MINUS_ONE = "-1"

# Local profiles keys
LP_PLAYER_NAME = "PlayerName"
LP_PROFILES = "Profiles"
LP_UNIQUE_ID = "UniqueID"
LP_LAST_MODIFIED = "LastModified"

# type alias
JSON_path_type = Sequence[Union[int, str, ProfileKey]]


class RSFileSetError(Exception):
    """Exception for errors in Rocksmith file sets."""

    def __init__(self, message: str = None) -> None:
        """Minimal constructor for RSFileSetError.

        Keyword Arguments:
            message {str} -- Custom error text. If no message is supplied (default),
                the exception will supply a not very informative message.
                (default: {None})

        """
        if message is None:
            message = "An unspecified Rocksmith file set error has occurred."
        super().__init__(message)


class RSProfileError(Exception):
    """Exception for errors in the Rocksmith profile manager and associated classes."""

    def __init__(self, message: str = None) -> None:
        """Minimal constructor for RSProfileError.

        Keyword Arguments:
            message {str} -- Custom error text. If no message is supplied (default),
                the exception will supply a not very informative message.
                (default: {None})

        """
        if message is None:
            message = "An unspecified Rocksmith profile error has occurred."
        super().__init__(message)


class RSSaveWrapper:
    """A helper class for RSProfileManager.

    Public members:
        Constructor -- Checks if the save file exists and prepares for lazy loading.
        file_path -- Return path the save file managed by the wrapper instance.
        write_file -- Save changed instance data back to the underlying file.
        json_tree -- Read/write property. The property read returns a reference to
            instance save data in the form of a json dict. This is a **mutable** -
            changes to the returned object affect the instance data. If the caller
            modifies the instance data, they are also responsible for marking the
            instance as dirty.
            The property write replaces the instance save data completely and marks
            the instance as dirty. Use with care if you know what you are doing.
            See also mark_as_dirty.
        mark_as_dirty -- Mark instance data as dirty. Used to inform the instance that
            save data in the json tree has been changed externally.
        get_json_subtree -- Returns a subtree in the instance save data. This may or
            may not be mutable (json sub-dicts are mutable, values are normally not
            mutable). In line with json_tree above, the caller is responsible for
            marking the instance as dirty if it modifies the save data.
        set json_subtree -- Overwrites a subtree in the instance save data and marks
            the instance as dirty.

    Note: This class is only intended for use by the profile manager. Use RSSaveFile
    if you want direct access to a save file.

    This class provides a wrapper for reading and writing Rocksmith save files. It is a
    super class for RSProfileDB (wrapper for profiles - *_PRFLDB) and RSLocalProfiles
    (wrapper for LocalProfiles.json), providing routines common to both of these
    classes.

    RSSaveWrapper is implemented as wrapper, rather than a sub class, of RSSaveFile to
    support lazy loading of save files.

    This class and sub-classes use a JSON path to navigate save data elements in the
    json dict. A JSON path is a list or tuple of the elements used to locate a specific
    value or subtree in the save data. E.g. the json_path to song list 2 is:

        ('SongListsRoot', 'SongLists', 1)

    Implementation note: I believe all Rocksmith Json objects have either names [str],
    such as 'Songlists' or integer indices into arrays [int], such as the second
    Songlist (2). Type annotations in this class reflect this assumption.

    Save wrapper instances should be marked as dirty when instance data is changed
    (i.e. the caller should mark the instance as dirty when the instance data no longer
    matches the source file data). Some, but not all, member functions will handle this
    automatically.

    Note in particular, that the json_tree property returns a mutable, and the
    get_json_subtree method **may** return a mutable. If the caller modifies data in
    one of these mutable objects, then the caller should also call mark_as_dirty, or
    should use the property setter for json_tree or call set_json_subtree as
    appropriate.
    """

    # instance variables
    _file_path: Path
    _is_dirty: bool
    __cached_rs_file: Optional[RSSaveFile]

    def __init__(self, file_path: Path) -> None:
        """Check if the save file_path exists, and prepare for lazy loading.

        Arguments:
            file_path {pathlib.Path} -- Path to the target Rocksmith save file.

        The instance will not check if the file is a valid Rocksmith save file until it
        is actually loaded.
        """
        # flags object contains changes that haven't been written to file.
        self._is_dirty = False
        # __cached_rs_file is used for lazy loading of Rocksmith save in this class
        # only, hence marked as private. Subclasses should access save file via the
        # _rs_file property.
        # This variable should only ever be used here (initialised) and in _rs_file
        # (lazy load)
        self.__cached_rs_file = None

        if file_path.is_file():
            self._file_path = file_path.resolve()
        else:
            raise FileNotFoundError(f"File {file_path} is missing.")

    @property
    def file_path(self) -> Path:
        """Get the original save file path.

        Gets:
            pathlib.Path -- Original file save path used in __init__.

        """
        return self._file_path

    def write_file(self, save_path: Optional[Path]) -> Optional[Path]:
        """Save **changes** in instance data to the underlying file.

        Arguments:
            save_path {Optional[pathlib.Path]} -- The target directory path for saving
                the file. If save_path is specified as None, the original file will be
                overwritten and the instance will be marked as clean.
                Otherwise the instance data is written to the directory save_path using
                the **original** file name *AND* the instance data is not marked as
                clean (as instance data is not in sync with the original source file).
                This may be useful if the caller intent is to update the original files
                later.

        Returns:
            Optional[pathlib.Path] -- Returns None if no save occurs (source file and
                instance data are the same). Returns the path to the saved file if the
                save occurs (regardless of value of save_path).

        This method does nothing if the instance data is the same as the original save
        file. To use this method to save an unchanged file to a new location, use
        self.mark_as_dirty() first and then self.write_file(save_path).

        """
        target_path = None
        if self._is_dirty:
            if save_path is not None:
                target_path = save_path.joinpath(self._file_path.name)
                # Note that we do not change the is_dirty state, as we are not updating
                # the original source file.
                # This is also relatively safe, as save_to_new_file will not overwrite
                # an existing file.
                self._rs_file.save_to_new_file(target_path)

            else:
                self._rs_file.overwrite_original()
                # instance is in sync with file after saving.
                target_path = self._file_path
                self._is_dirty = False

        return target_path

    @property
    def _rs_file(self) -> RSSaveFile:
        """Get a reference to the RSSaveFile instance for the save file.

        Create the instance if this is the first reference to it (lazy loading).

        Only meant for use by subclasses.

        Gets:
            RSSaveFile -- Rocksmith save file object.

        """
        if self.__cached_rs_file is None:
            self.__cached_rs_file = RSSaveFile(self._file_path)

        return self.__cached_rs_file

    @property
    def json_tree(self) -> RSJsonRoot:
        """Read/write property for instance save file data in mutable json tree format.

        Gets/sets:
            {RSJsonRoot} -- Simplejson dictionary containing instance Rocksmith save
                data.

        The getter returns a reference to the instance json tree. The caller is
        responsible for marking the save file as dirty if it modifies any of the tree
        elements.

        The setter replaces the instance data with new_data.  Using the setter to
        replace the tree will automatically mark the save file as dirty.

        The caller is responsible for ensuring that any changes to the tree are
        consistent with the Rocksmith save file structure and format. That is, the class
        does not validate data changes. (It should be possible to implement a json
        schema to address this, but it's not worth the effort for now.)
        """
        return self._rs_file.json_tree

    @json_tree.setter
    def json_tree(self, new_data: RSJsonRoot) -> None:
        self._rs_file.json_tree = new_data
        self.mark_as_dirty()

    def mark_as_dirty(self) -> None:
        """Mark the instance data as dirty.

        This is intended to be used when:
            - The caller has modified the instance save data external to this class.
            - Restoring an old save. By marking the file as dirty, file data, local
              profiles and Steam cache data can all be set in sync for the file. The
              save file still needs to be represented in local profiles data and steam
              cache file.
            - Copying a save to a new location without changing it (write_file does
              nothing unless the instance is marked dirty).
        """
        self._is_dirty = True

    def _json_node(self, json_path: JSON_path_type) -> Tuple[Any, Union[str, int]]:
        """Return container and key/index pair for JSON path.

        Arguments:
            json_path {Sequence[Union[int, str, ProfileKey]]} -- Path to json sub
                container or data value. See class documentation for a description of
                json_path.

        Raises:
            KeyError -- Raised on invalid key in json_path.
            IndexError -- Raised on invalid index in json_path.

        Returns:
            Tuple[Any, Union[str, int]] -- Returns a tuple consisting of:
                - A container for the last element in the JSON path (a dict or
                  list - not that this is NOT the last element in the JSON path); and
                - The container key (str) or index (int) that can be used to get or
                  the set the value or container referenced by JSON path (i.e. this is
                  the last element of the JSON path).

        Refer to get/set_json_subtree for usage.

        """
        node = self.json_tree
        prev_node = node

        for iter_value in json_path:
            # traverse full path to check existence of each node.
            prev_node = node
            if isinstance(iter_value, ProfileKey):
                path_item = iter_value.value
            else:
                path_item = iter_value

            if isinstance(path_item, str):
                if isinstance(node, dict):
                    try:
                        node = node[path_item]
                    except KeyError:
                        raise KeyError(
                            f"Invalid key {path_item} in JSON path {json_path}."
                        )
                else:
                    raise KeyError(
                        f"Key {path_item} supplied in JSON path {json_path}, but JSON "
                        f"dict not found."
                    )
            elif isinstance(path_item, int):
                if isinstance(node, list):
                    try:
                        node = node[path_item]
                    except IndexError:
                        raise IndexError(
                            f"Invalid index {path_item} in JSON path {json_path}."
                        )
                else:
                    raise IndexError(
                        f"Index {path_item} supplied in JSON path {json_path}, but "
                        f"JSON list not found."
                    )
            else:
                raise TypeError(
                    f"Invalid value {path_item} in JSON path {json_path}.\nJson path "
                    f"should be a tuple of string and integer values."
                )

        # actually want to return  final node (prev_node) rather than final value (node)
        # path_item should be the final key in json_path and have either int or str type
        return prev_node, path_item

    def get_json_subtree(self, json_path: JSON_path_type) -> Any:
        """Return a json subtree or value based on the json_path sequence.

        Arguments:
            json_path {Sequence[Union[int, str, ProfileKey]]} -- Path to json sub
                container or data value. See class documentation for a description of
                json_path. If json_path is empty, returns self.json_tree.

        Returns:
            Any -- A json subtree (list, dict), or a json value (str, bool, Decimal)
                found at the end of the json_path. Keep in mind that editing a mutable
                is editing the save file. If you do this, you should also mark the file
                as dirty.

        """
        if not json_path:
            # Nothing in json_path, return entire json_tree.
            return self.json_tree
        else:
            parent_dict, key = self._json_node(json_path)
            return parent_dict[key]

    def set_json_subtree(
        self, json_path: JSON_path_type, subtree_or_value: Any
    ) -> None:
        """Replace subtree or value at the end of json_path.

        Arguments:
            json_path {Sequence[Union[int, str, ProfileKey]]} -- Path to json sub
                container or data value. See class documentation for a description of
                json_path. If json_path is empty, the method will replace the entire
                json tree for the instance (self.json_tree) with subtree_or_value.
            subtree_or_value {Any} -- A json subtree (list, dict), or a json value
                (str, bool, Decimal) that replaces the subtree/value found at the end
                of the json_path. The caller is responsible for ensuring the
                format of this argument is consistent with Rocksmith json.

        Marks instance as dirty, as this is the expected behaviour for a value change.
        """
        if not json_path:
            self.json_tree = subtree_or_value
        else:
            parent_dict, key = self._json_node(json_path)

            parent_dict[key] = subtree_or_value

        self.mark_as_dirty()


class RSLocalProfiles(RSSaveWrapper):
    """Wrapper for reading and managing Rocksmith data held in LocalProfiles.json.

    This is a subclass of RSSaveWrapper.

    Subclass public members:
        Constructor -- Load a LocalProfiles.json file.
        player_name -- Return the player name associated with a Rocksmith profile
            unique id.
        update_local_profiles -- Updates instance data last modified time for a profile
            save file/unique id pair.
    """

    def __init__(self, remote_dir: Path) -> None:
        """Read Rocksmith data from LocalProfiles.json.

        Arguments:
            remote_dir {pathlib.Path} -- Path to directory containing target
                LocalProfiles.json file. Typically a Rocksmith save directory.
        """
        file_path = remote_dir.joinpath(LOCAL_PROFILES).resolve()
        super().__init__(file_path)

    def _profile_from_unique_id(
        self, unique_id: str
    ) -> Optional[Dict[str, Union[str, Decimal]]]:
        """Return profile data dictionary for unique_id if it exists.

        Arguments:
            unique_id {str} -- Rocksmith profile unique identifier.

        Returns:
            Optional[Dict[str, Any]] -- Returns the data dictionary for
                Rocksmith profile unique_id if it exists, returns None if there is
                no data dictionary for the unique id.

        Note: This method returns Rocksmith metadata from LocalProfiles.json about a
        a specific Rocksmith profile with the specified unique_id. It is not steam
        cloud metadata.

        """
        ret_val = None
        for profile in self.get_json_subtree((LP_PROFILES,)):
            if profile[LP_UNIQUE_ID] == unique_id:
                ret_val = profile
                break
        return ret_val

    def player_name(self, unique_id: str) -> str:
        """Return the Rocksmith player name for unique id.

        Arguments:
            unique_id {str} -- Rocksmith profile unique identifier.

        Returns:
            str -- Returns the player name for Rocksmith profile unique_id if
                it exists, returns empty string '' otherwise.

        """
        profile = self._profile_from_unique_id(unique_id)
        if profile is None:
            return ""

        ret_val = profile[LP_PLAYER_NAME]
        if isinstance(ret_val, str):
            return ret_val

        raise TypeError(f"Expected string type for player name, got {type(ret_val)}.")

    def update_local_profiles(self, unique_id: str, file_path: Path) -> None:
        """Update last modified time for profile unique_id in LocalProfiles.json.

        Arguments:
            unique_id {str} -- Rocksmith profile unique identifier.
            file_path {Path} -- Path to file that will be used for the last modified
                time value.

        The caller is responsible for ensuring the file path and the unique_id are
        consistent (file_path is the save file for unique_id).

        If the profile is updated, the instance is marked as dirty, but not saved.

        No update occurs if profile unique_id is not found in the local profiles file.
        """
        profile = self._profile_from_unique_id(unique_id)
        if profile is not None:
            # force decimal precision to match Rocksmith 6 digits (slightly ludicrous,
            # but belt and braces).
            last_modified = Decimal(
                int(file_path.stat().st_mtime)  # cSpell: disable-line
            ) + Decimal("0.000000")
            if last_modified != profile[LP_LAST_MODIFIED]:
                profile[LP_LAST_MODIFIED] = last_modified
                self.mark_as_dirty()


class RSProfileDB(RSSaveWrapper):
    """Wrapper for managing Rocksmith save profiles (profile db/*PRFLDB files).

    This is a subclass of RSSaveWrapper.

    Subclass public members:
        Constructor -- Load a Rocksmith profile save file, link a unique id and
            (optionally) a player name with the profile file.
        player_name -- Return the player name associated with the Rocksmith profile
            save file.
        unique_id -- Return the unique id associated with the Rocksmith profile save
            file.
        arrangement_ids -- An iterator that yields the unique arrangement ids in the
            Rocksmith profile.
        replace_song_list -- Replace one of the songlists in the profile with a new
            songlist.
        set_arrangement_play_count -- Set the "Learn a Song" play count of an
            arrangement to a new value.
    """

    # instance variables
    _unique_id: str
    _player_name: str

    def __init__(
        self, file_path: Path, local_profiles: Optional[RSLocalProfiles]
    ) -> None:
        """Initialise superclass, associate profile unique_id and find player name.

        Arguments:
            file_path {pathlib.Path} -- Path to the Rocksmith profile save file.
            local_profiles {RSLocalProfiles} -- If supplied, this should be an
                RSLocalProfiles that contains metadata about the profile save.
                Can be specified as None (see notes).

        Raises:
            RSProfileError -- Raised if the profile file name does not match the
                pattern for Rocksmith profiles (<unique_id>_PRFLDB).

        This method prepares the instance for lazy loading of the profile file,
        extracts the profile unique id from the file name, and checks local_profiles
        (LocalProfiles.json) for the player name.

        Player name is set to empty string ('') if:
            - local_profiles is None; or
            - the profile unique id is not found in local_profiles.

        """
        super().__init__(file_path.resolve())

        self._unique_id = file_path.name.upper()
        if not self._unique_id.endswith(PROFILE_DB_STR):
            raise RSProfileError(
                f"RSProfileDB objects require a file ending in {PROFILE_DB_STR}."
            )
        else:
            self._unique_id = self._unique_id[: -len(PROFILE_DB_STR)]

        if local_profiles is None:
            self._player_name = ""
        else:
            self._player_name = local_profiles.player_name(self._unique_id)

    @property
    def unique_id(self) -> str:
        """Get the unique_id {str} for the Rocksmith profile.

        This is/should be the save file name excluding _PRFLDB suffix.
        """
        return self._unique_id

    @property
    def player_name(self) -> str:
        """Get the Rocksmith player name {str} associated with the profile.

        Return empty string ('') if there is no player name associated with the profile.
        """
        return self._player_name

    def arrangement_ids(self) -> Iterator[str]:
        """Return iterator for all song arrangement ids that appear in the profile.

        Yields:
            str -- song arrangement id.

        """
        # can add/remove members as file changes in future. RS appears to fill data as
        # it it is created, so children are likely to be incomplete.
        arrangement_ids: Set[str] = set()

        # make json_path dynamic as a workaround for mypy issue #4975
        json_path: Any
        # noinspection SpellCheckingInspection
        for json_path in (
            (ProfileKey.PLAY_NEXTS, ProfileKey.SONGS),  # cSpell: disable-line
            (ProfileKey.SONGS,),
            (ProfileKey.STATS, ProfileKey.SONGS),  # cSpell: disable-line
            (ProfileKey.SONG_SA,),
        ):
            try:
                arrangement_dict = self.get_json_subtree(json_path)
            except (KeyError, IndexError):
                pass
            else:
                arrangement_ids = arrangement_ids.union(set(arrangement_dict.keys()))

        for a_id in arrangement_ids:
            yield a_id

    def replace_song_list(
        self, target: ProfileKey, new_song_list: List[str], list_index: int = -1
    ) -> None:
        """Replace Favorites or indexed Song List with a new song list.

        Arguments:
            target {ProfileKey} -- must be either ProfileKey.SONG_LISTS or
                ProfileKey.FAVORITES_LIST (import from rsrtools.files.config).
            new_song_list {List[str]} -- The list of new songs to be inserted into the
                song list. Refer rsrtools.songlists.database for details on song
                list generation and structure. In summary, this is a list of the short
                form song names: e.g. ["BlitzkriegBop", "CallMe"].
            list_index {int} -- If target is SONG_LISTS, the index of the song list to
                replace in the range 0-5. Ignored if target is FAVORITES.

        Raises:
            RSProfileError -- If the target is invalid, if the new_song_list is not a
                List[str], or if list_index is invalid for SONG_LISTS.

        Note: Rocksmith has 6 user specifiable song lists. Following python convention,
        we index these from 0 to 5.

        """
        if not isinstance(new_song_list, List):
            raise RSProfileError(
                f"Invalid song list argument. Song lists must be a list of strings."
                f"\nArgument is of type {type(new_song_list)}."
            )

        if not all(isinstance(songkey, str) for songkey in new_song_list):
            raise RSProfileError(
                "Invalid song list argument. Song lists must be a list of strings."
                "\nSome non-string types found in list."
            )

        if target is not ProfileKey.FAVORITES_LIST:
            if target is not ProfileKey.SONG_LISTS:
                raise RSProfileError(
                    "Invalid song list argument. The target for replacement must be "
                    "either ProfileKey.FAVORITES_LIST or ProfileKey.SONG_LISTS"
                )

            if not (0 <= list_index <= MAX_SONG_LIST_COUNT - 1):
                raise RSProfileError(
                    f"List index must be in the range 0 to 5 for SONG_LISTS. "
                    f"Got {list_index}."
                )

            json_path: JSON_path_type = (
                ProfileKey.SONG_LISTS_ROOT,
                ProfileKey.SONG_LISTS,
                list_index,
            )

        else:
            json_path = (ProfileKey.FAVORITES_LIST_ROOT, ProfileKey.FAVORITES_LIST)

        node, key = self._json_node(json_path)

        node[key] = new_song_list
        self.mark_as_dirty()

    def set_arrangement_play_count(self, arrangement_id: str, play_count: int) -> None:
        """Set the "Learn a Song" play count of an arrangement to a new value.

        Arguments:
            arrangement_id {str} -- The unique id for a Rocksmith arrangement.
            play_count {int} -- The new play count value.

        Note: This is a utility function that I find useful to reset some arrangement
        play counts to zero (e.g. rhythm arrangements I may have played once that I
        don't want to appear in count based song lists).
        """
        dec_play_count = Decimal(int(play_count)) + Decimal("0.000000")
        self.set_json_subtree(
            (
                ProfileKey.STATS,  # cSpell: disable-line
                ProfileKey.SONGS,
                arrangement_id,
                ProfileKey.PLAYED_COUNT,
            ),
            dec_play_count,
        )


class RSFileSet:
    """A helper class for gathering and testing Rocksmith save sets.

    Public methods:
        Constructor -- Creates and check the consistency of a Rocksmith file set based
            on the files and and sub-directories in a target directory.
        copy_file_set -- Copy a Rocksmith fileset to a new directory.
        delete_files -- Delete all files in the file set.
        consistent -- Read only property. True if the file set has passed basic tests on
            folder structure, existences of Steam and Rocksmith files, and metadata
            consistency. False otherwise.
        steam_metadata -- Read only property, returns the Steam metadata for the file
            set.
        local_profiles -- Read only property, returns the local_profiles instance for
            the file set (RSLocalProfiles object).
        profiles -- Read only property, returns a dictionary of the Rocksmith profiles
            in the the file set (RSProfileDB objects).
        m_time -- Read only property, returns the most recent modification date/time for
            all of the profiles in the fileset (i.e. checks all profiles and returns the
            date from the most recently modified of these).

    A consistent rocksmith save set consists of the following elements:
        - A remotecache.vdf file used for Steam cloud syncing.
        - A directory named 'remote' in the same directory as remotecache.vdf.
        - The following files in the 'remote' sub-directory:
            - A LocalProfiles.json Rocksmith file used to link profile ids and profile
              names.
            - One or more Rocksmith profiles files (*_PRFLDB)
        - Appropriate metadata cross references/links between the files.

    The class constructor performs basic checks on internal consistency in the file set
    (i.e. save files referenced in local profiles and cache, local profiles referenced
    in cache). Save are lazy loaded, so a corrupt file may cause problems later.
    """

    # instance variables
    _fs_steam_metadata: Optional[SteamMetadata]
    _fs_local_profiles: Optional[RSLocalProfiles]
    _fs_profiles: Dict[str, RSProfileDB]
    _valid_structure: bool
    _consistent: bool
    _m_time: str

    def __init__(self, remote_path: Path) -> None:
        """Create an RSFileSet instance based on remote_path.

        Arguments:
            remote_path {pathlib.Path} -- The path to a directory named 'remote'
                containing Rocksmith profiles and a LocalFiles.json file.

        The Constructor will check that the files are in a directory named 'remote',
        and expects to find the Steam 'remotecache.vdf' file in the parent directory
        that contains the 'remote' directory. See the RSProfileManager class description
        for more details on the expected file and directory structure.

        The Constructor also checks consistency of the file set and finds time of the
        most recent profile save.

        If there are errors in structure or the fileset is not consistent, errors are
        printed to help user resolve issues.

        This method deliberately excludes crd files.
        """
        self._valid_structure = True
        resolved_path = remote_path.resolve()
        dir_name = resolved_path.name
        if dir_name != STEAM_REMOTE_DIR:
            logging.warning(
                f"Rocksmith profiles should be in a directory named:"
                f"\n    {STEAM_REMOTE_DIR}\nRocksmith file set constructor (__init__) "
                f"called on directory named:\n    {dir_name}"
            )
            self._valid_structure = False

        self._fs_steam_metadata = None
        try:
            # Steam cache should be in parent of Rocksmith save dir
            self._fs_steam_metadata = SteamMetadata(resolved_path.parent)
        except (FileNotFoundError, SteamMetadataError) as exc:
            logging.warning(exc)

        self._fs_local_profiles = None
        try:
            self._fs_local_profiles = RSLocalProfiles(resolved_path)
        except FileNotFoundError as exc:
            logging.warning(
                f"Rocksmith local profiles file expected but not found:"
                f"\n   {str(exc)}"
            )

        self._find_profiles(resolved_path)

        self._check_consistency(resolved_path)

    def _find_profiles(self, remote_path: Path) -> None:
        """Find all Rocksmith profile save files in directory remote_path.

        Arguments:
            remote_path {pathlib.Path} -- The path to a directory named 'remote'
                containing Rocksmith profiles and a LocalFiles.json file.
        """
        m_time = 0.0
        self._fs_profiles = dict()
        for file_path in remote_path.iterdir():
            if file_path.is_file():
                try:
                    profile = RSProfileDB(file_path, self._fs_local_profiles)
                except RSProfileError:
                    # not a valid save file, so we assume it is not part of the set
                    # and ignore it
                    pass
                else:
                    self._fs_profiles[profile.unique_id] = profile
                    if profile.player_name:
                        # also allow access to profile via player_name if we know it.
                        self._fs_profiles[profile.player_name] = profile

                    profile_time = (
                        profile.file_path.stat().st_mtime  # cSpell: disable-line
                    )
                    if profile_time > m_time:
                        m_time = profile_time

        self._m_time = time.asctime(time.localtime(m_time))

    def _check_consistency(self, remote_path: Path) -> None:
        """Check consistency of Rocksmith file set.

        Arguments:
            remote_path {pathlib.Path} -- The path to a directory named 'remote'
                containing Rocksmith profiles and a LocalFiles.json file. Only used
                for error reporting.
        """
        # Starting point: only as valid as the directory structure.
        consistent = self._valid_structure

        if self._fs_local_profiles is None:
            consistent = False

        if not self._fs_profiles:
            consistent = False
            logging.warning(
                f"Warning: No Rocksmith save files ({PROFILE_DB_STR}) found in:"
                f"\n    {fsdecode(remote_path)}."
            )

        for rs_profile in self._fs_profiles.values():
            if not rs_profile.player_name:
                consistent = False
                logging.warning(
                    f"Rocksmith save file has no player name:"
                    f"\n   {fsdecode(rs_profile.file_path)}"
                )

        if self._fs_steam_metadata is None:
            consistent = False
        else:
            file_list: List[RSSaveWrapper] = list(self._fs_profiles.values())
            if self._fs_local_profiles is not None:
                file_list.append(self._fs_local_profiles)

            for rs_save in file_list:
                if not self._fs_steam_metadata.metadata_exists(
                    RS_APP_ID, rs_save.file_path
                ):
                    consistent = False
                    logging.warning(
                        f"Steam cache contains no data for file:"
                        f"\n   {fsdecode(rs_save.file_path)}"
                    )

        self._consistent = consistent

    def copy_file_set(
        self, new_remote_path: Path, require_consistent: bool = True
    ) -> None:
        """Copy all files in the files set to the target save directory.

        Arguments:
            new_remote_path {pathlib.Path} -- The destination directory for the
                Rocksmith save files.
            require_consistent {bool} -- If true, the copy will raise an exception if
                the fileset is not not consistent. See notes below. A False value for
                this parameter may be useful when working with incomplete file sets.
                (default: True)

        The copy performs the following actions:
            - Raise an exception if require_consistent is true and the source file set
              is inconsistent and the base name of the new_remote_path directory is not
              'remote'.
            - If it exists, it will copy the Steam remotecache.vdf file into the parent
              directory of new_remote_path.
            - It will copy all Rocksmith profiles and LocalProfiles.json in the file
              set into new_remote_path.
        """
        if not new_remote_path.is_dir():
            raise NotADirectoryError(
                f"RSFileSet.copy_file_set requires a directory as a target.\n"
                f"'{fsdecode(new_remote_path)}' is not a directory."
            )

        if require_consistent:
            if not self._consistent:
                raise RSFileSetError(
                    "RSFileSet.copy_file_set called on an inconsistent file set."
                )
            elif new_remote_path.name != STEAM_REMOTE_DIR:
                raise RSFileSetError(
                    f"RSFileSet.copy_file_set called with a target directory named "
                    f"'{new_remote_path.name}'.\nThis directory should have the name "
                    f"'{STEAM_REMOTE_DIR}'."
                )

        # only need the unique save instances - _fs_profiles carries
        # index by name and unique_id
        file_set: Set[RSSaveWrapper] = set(self._fs_profiles.values())
        if self._fs_local_profiles is not None:
            file_set.add(self._fs_local_profiles)

        for file in file_set:
            shutil.copy2(fsdecode(file.file_path), fsdecode(new_remote_path))

        if self._fs_steam_metadata is not None:
            # Steam cache is copied to the parent directory
            shutil.copy2(
                fsdecode(self._fs_steam_metadata.file_path),
                fsdecode(new_remote_path.parent),
            )

    def delete_files(self) -> None:
        """Delete all files in the file set."""
        file_set: Set[Union[RSSaveWrapper, SteamMetadata]] = set(
            self._fs_profiles.values()
        )

        if self._fs_local_profiles is not None:
            file_set.add(self._fs_local_profiles)

        if self._fs_steam_metadata is not None:
            file_set.add(self._fs_steam_metadata)

        for file in file_set:
            if file.file_path.exists():
                file.file_path.unlink()

        # and in case someone tries to use this fileset now
        self._consistent = False
        self._fs_profiles = dict()
        self._fs_local_profiles = None
        self._fs_steam_metadata = None

    @property
    def consistent(self) -> bool:
        """Read only property. True if the file set has passed basic consistency tests.

        Gets:
            bool -- True if the file set is consistent, false otherwise.

        The tests address folder structure, existence of Steam and Rocksmith files,
        and metadata.

        """
        return self._consistent

    @property
    def steam_metadata(self) -> Optional[SteamMetadata]:
        """Get the Steam metadata for the file set if it exists. Read only property.

        Gets:
            Optional[SteamMetadata] -- The file set Steam metadata.

        """
        return self._fs_steam_metadata

    @property
    def local_profiles(self) -> Optional[RSLocalProfiles]:
        """Get the RSLocalProfiles for the file set if it exists. Read only property.

        Gets:
            Optional[RSLocalProfiles] -- The local profiles instance for the file set.

        """
        return self._fs_local_profiles

    @property
    def profiles(self) -> Dict[str, RSProfileDB]:
        """Get a dictionary of the RSProfileDB objects for the file set. Read only.

        Gets:
            Dict[str, RSProfileDB] -- The keys are the Rocksmith unique ids and profile
                names associated with the Rocksmith profiles (i.e. each profile has up
                two keys associated with it).

        """
        return self._fs_profiles

    @property
    def m_time(self) -> str:
        """Get data/time of most recently modified Rocksmith profile. Read only.

        Gets:
            str -- Returns the most recent modification date/time for all of the
            profiles in the fileset (i.e. checks all profiles and returns the date from
            the most recently modified of these).

        """
        return self._m_time


class RSProfileManager:
    r"""Provides an integrated interface to Rocksmith save files owned by a Steam user.

    Public members:
        Constructor -- Sets up the working directories, optionally copies a Rocksmith
            file set from the Steam user directory, and loads a working file set.

        cl_choose_profile -- Command line utility for selecting a profile name from the
            profiles available in the profile manager.

        cl_clone_profile -- Command line utility for cloning the data from one profile
            into another.

        cl_set_play_counts -- Command line utility for setting play counts for a list
            of arrangements.

        copy_player_json_value -- Returns a deep copy of a json subtree for the
            specified profile.

        copy_profile -- Copies all data from the source profile to the destination
            profile, and optionally writes updated files.

        move_updates_to_steam -- Moves files in the update directory to the Steam user
            directories for the specified Steam account id.

        player_arrangement_ids -- Provides an iterator for all arrangement ids in the
            named profile.

        replace_song_list -- Replaces a song list in a profile with a new_song_list.

        set_arrangement_play_count -- Set play count for a specific arrangement in a
            profile.

        write_files -- Backs up all files in the working set to a zip file in a backup
            directory, and then writes all modified files to the update directory.

        steam_account_id -- Read only property. The Steam account id of the file set in
            the working directory.

        mark_as_dirty -- Mark profile data as dirty. Used to inform the instance that
            profile save data in the json tree has been changed externally.

        get_json_subtree -- Returns a save data json subtree from a profile. This may or
            may not be mutable (json sub-dicts/lists are mutable, values are normally
            not mutable). The caller is responsible for marking the profile as dirty if
            it modifies the save data.

        set json_subtree -- Overwrites a save data json subtree in a profile and marks
            the profile as dirty.

    RSProfileManager works on a base directory with the following structure:
        base_dir
            \-- RS_working   - This directory contains the working copy of the
                               Rocksmith save directory. The object expects to find
                               remotecache.vdf in this directory.
                \-- remote   - This directory should contain the Rocksmith game files
                               and the LocalProfiles.json file.
            \-- RS_backup    - Backups of RS_working will be made into this directory
                               before creating any updates.
            \-- RS_update    - Changed Steam cache files will be saved in this
                               directory.
                \--remote    - Changed Rocksmith files will be saved in this
                               directory.

    If this structure does not exist, the user will be asked for permission to create
    it, and the class initialisation will fail if refused.
    """

    # instance variables
    # As we should be working on consistent fileset, none of these three
    # should ever be None.
    _steam_metadata: SteamMetadata
    _local_profiles: RSLocalProfiles
    _profiles: Dict[str, RSProfileDB]

    _steam_account_id: str
    _working_save_path: Path
    _backup_path: Path
    _update_save_path: Path

    # None of the information in Steam accounts should change while we are running
    # rsrtools, so we can make this a class object.
    _steam_accounts: SteamAccounts = SteamAccounts()

    def __init__(
        self,
        base_dir: Path,
        steam_account_id: Union[str, int] = None,
        auto_setup: bool = False,
        flush_working_set: bool = False,
    ) -> None:
        """Initialise the directory structure, copy Steam files and load working set.

        Arguments:
            base_dir {pathlib.Path} -- The base directory for the profile manager. This
                directory will house all working files and directories used or created
                by the profile manager. This directory must exist.

        Keyword Arguments:
            steam_account_id {Union[str, int]} -- Optional. Specifies the Rocksmith
                files that will be managed by the profile manager. If specified, this
                must be an integer or a string representation of an integer.
                (default: {None})
                - If the value is a positive integer, it should correspond to a steam
                  account id. In this case, the instance will manage this users
                  Rocksmith saves.
                - If the value is negative, the instance will manage the Rocksmith
                  saves in the working directory.
                - If no value is specified (default), the constructor will provide a
                  command line interface for the user to select a Steam account id or
                  the saves in the working directory.
            auto_setup {bool} -- If False, the user will be prompted to confirm
                workspace setup actions. Otherwise the method performs the setup actions
                without interaction. (default: {False})
            flush_working_set {bool} -- If True, delete any Rocksmith file set or
                partial file set in the working directory. If False, does nothing.
                (default: {False})

        Raises:
            NotADirectoryError -- If base_dir is not a directory.
            RSFileSetError -- If the selected/specified fileset is not valid.

        The constructor performs the following actions:
            - Checks the directory structure under base_dir and offers to set up any
              missing directories.

            - Checks for Rocksmith files in the update directory, and offers to delete
              any files found.
                - If the user rejects automatic setup, the constructor will raise an
                  exception (i.e. user must either allow automatic setup to complete,
                  or must setup directories manually for successful initialisation).

            - If no Steam account id is specified (default):
                - The working directory and all Steam user directories are scanned for
                  valid Rocksmith file sets.
                - The user is asked to select a working file set from a menu of
                  available, consistent file sets.
                    - If the user rejects all available file sets, the constructor will
                      raise an exception.

            - If steam_account_id < 0 or the user interactively selected the file set in
              the working directory, the instance will manage the file set in the
              working directory. This functionality provides for debugging/testing.

            - If a Steam account id is specified or selected interactively by the user,
              this user's file set is copied into the working directory, replacing any
              file set already in the working directory.

            - If the specified/selected file set is not valid and consistent, an
              exception is raised.

            - Finally, the file set in the working directory is loaded for use by the
              profile manager instance.

        """
        if not base_dir.is_dir():
            raise NotADirectoryError(
                f"Profile manager constructor called on invalid base directory:\n    "
                f"'{fsdecode(base_dir)}'"
            )

        self._setup_workspace(base_dir.resolve(), auto_setup=auto_setup)

        # Steam account id is the source account id for this profile manager.
        # string version of integer Steam id. Specifies the source of the file set in
        # the working dir
        #    - negative id: using the file set found in the working directory at start
        #      of run (no copying from Steam).
        #    - positive id: file set from the Steam user data directories corresponding
        #      to this id will be copied into the working dir for us.
        # I.e. we always work on the files in the working dir, but this is a memo for
        # the source of the files.
        # Also provides a target for copying altered files back into Steam directories.
        if steam_account_id is None:
            self._steam_account_id = ""
        else:
            self._steam_account_id = str(steam_account_id)

        # If Steam account id has been specified, returns the file set for this id.
        # Otherwise returns file sets for all account ids.
        steam_file_sets = self._get_steam_file_sets()

        # tidy up working set.
        if flush_working_set:
            logging.disable(logging.CRITICAL)
        working_file_set = RSFileSet(self._working_save_path)
        if flush_working_set:
            working_file_set.delete_files()
            logging.disable(logging.NOTSET)

        if not self._steam_account_id:
            # default action: user selects working fileset from command line
            self._steam_account_id, chosen_file_set = self._choose_file_set(
                steam_file_sets, working_file_set
            )
        elif int(self._steam_account_id) < 0:
            if working_file_set.consistent:
                chosen_file_set = working_file_set
            else:
                raise RSFileSetError(
                    "Rocksmith file set in working directory is either missing or"
                    "inconsistent."
                )
        else:
            # select specified Steam set if available
            if self._steam_account_id in steam_file_sets:
                chosen_file_set = steam_file_sets[self._steam_account_id]
            else:
                raise RSFileSetError(
                    f"Missing or inconsistent Rocksmith file set for Steam user:"
                    f"\n    {self.steam_description(self._steam_account_id)}"
                )

        if chosen_file_set is not working_file_set:
            # remove current working set, copy in new set
            working_file_set.delete_files()
            chosen_file_set.copy_file_set(self._working_save_path, True)
            # re-read working directory to load updated file set.
            chosen_file_set = RSFileSet(self._working_save_path)

        self._profiles = chosen_file_set.profiles

        if chosen_file_set.local_profiles is None:
            # Really shouldn't be possible.
            raise RSFileSetError(
                f"Very unexpected: undefined {LOCAL_PROFILES} for chosen fileset."
            )
        self._local_profiles = chosen_file_set.local_profiles

        if chosen_file_set.steam_metadata is None:
            # Really shouldn't be possible.
            raise RSFileSetError(
                f"Very unexpected: undefined Steam metadata for chosen fileset."
            )
        self._steam_metadata = chosen_file_set.steam_metadata

    @property
    def steam_account_id(self) -> str:
        """Get the source Steam account id for the profile manager file set.

        Gets:
            str -- The string representation of an integer Steam account id.

        This value is negative if the profile manager constructor loaded the file set
        in the working directory. Otherwise, the Steam account id corresponds to a steam
        user with a valid Rocksmith file set, and this file set has been copied
        into the working directory.

        """
        return self._steam_account_id

    def steam_description(self, account_id: str) -> str:
        """Return a description string for a Steam account id.

        Arguments:
            account_id {str} -- The target account id.

        Returns:
            str -- The description string for the account, ideally from Steam accounts,
                otherwise the profile manager will supply something.

        """
        description = ""
        if account_id == MINUS_ONE:
            description = f"{account_id} (working directory files, no Steam account)."

        else:
            try:
                description = self._steam_accounts.account_info(account_id).description
            except KeyError:
                # no data for account_id.
                pass

        if not description:
            description = f"{account_id} (no information available on Steam account)."

        return description

    def _choose_file_set(
        self, steam_file_sets: Dict[str, RSFileSet], working_file_set: RSFileSet
    ) -> Tuple[str, RSFileSet]:
        """Provide a command line menu for choosing a Rocksmith file set.

        Arguments:
            steam_file_sets {Dict[str, RSFileSet]} -- A dictionary of all consistent
                Steam account id/Rocksmith file set pairs.
            working_file_set {RSFileSet} -- The file set found in the working directory
                by the profile manager constructor.

        Raises:
            RSFileSetError -- If there are no valid, consistent file sets to manage, or
                if the user did not select a file set.

        Returns:
            Tuple[str, RSFileSet] -- A string representation of the Steam account id
                selected, and the corresponding file set object.  An account id of '-1'
                is returned if the user selects the working file set.

        """
        header = (
            "Rocksmith profile/file set selection"
            "\n\nSelect a Steam account id/Rocksmith file set from the following "
            "options. "
        )

        help_text = (
            "HELP: "
            "\n    - A Rocksmith file set is all of the Rocksmith profiles for a single"
            "\n      Steam user/login (and some related metadata files)."
            '\n    - You need to choose the Steam account id that "owns" the profiles '
            "you want to work on."
            "\n    - When you select a Steam account id, I will:"
            "\n          - Clean up the working directory (delete old file sets)"
            "\n          - Find the Rocksmith file set for the selected "
            "Steam account id."
            "\n          - Copy this file set from Steam into the working directory."
            "\n      For most use cases, this is exactly what you want to happen."
            "\n    - (date-time) is the date stamp of the most recent profile save in "
            "the file set."
            "\n    - You may be offered the option of using a file set in the working "
            "directory. This is mainly"
            "\n      used for development/debugging. Only use this if you know what "
            "you are doing."
        )

        if not steam_file_sets and not working_file_set.consistent:
            raise RSFileSetError(
                "No valid Rocksmith file sets found in working directory or "
                "Steam user directories (fatal error)."
            )

        options = list()

        for steam_account_id, file_set in steam_file_sets.items():
            option_text = f"Steam user {self.steam_description(steam_account_id)}"
            option_text = f"{option_text} ({file_set.m_time})"
            options.append((option_text, steam_account_id))

        if working_file_set.consistent:
            option_text = (
                f"[Debugging/development] Keep and use the file set in the "
                f"working directory. ({working_file_set.m_time})"
            )
            options.append((option_text, MINUS_ONE))

        choice = utils.choose(
            options,
            header=header,
            no_action="Do nothing and raise error.",
            help_text=help_text,
        )
        if choice is None:
            raise RSFileSetError(
                "User exit: User did not select a valid Rocksmith file set for use."
            )

        steam_account_id = choice[0]
        if not isinstance(steam_account_id, str):
            raise TypeError(
                f"Unexpected type from file set choice. Should be string, "
                f"got f{type(steam_account_id)}."
            )

        if steam_account_id == MINUS_ONE:
            file_set = working_file_set
        else:
            file_set = steam_file_sets[steam_account_id]

        return steam_account_id, file_set

    def _get_steam_rs_user_dirs(self, find_account_id: str) -> Dict[str, Path]:
        """Return Rocksmith save directories for those Steam users that have them.

        Arguments:
            find_account_id {str} -- String representation of a Steam account id or the
                empty string.

        Raises:
            TypeError -- On find_account_id type error.

        Returns:
            Dict[str, Path] -- String Steam account id/Path object for the Steam user's
                Rocksmith save directory.

        If find_account_id is empty, returns Rocksmith save directories for all users
        that have one, otherwise returns only the Rocksmith save directory of the
        account id specified in find_account_id. Returns an empty dictionary if no save
        directories are found.

        """
        user_dirs: Dict[str, Path] = dict()
        # List of valid steam accounts
        account_list = self._steam_accounts.account_ids(only_valid=True)

        if find_account_id:
            if not isinstance(find_account_id, str):
                raise TypeError(
                    "Unexpected type for find_account_id. This should be a string "
                    "version of the Steam integer account id."
                )
            # Get path info if we have valid account data.
            # If caller has asked for an invalid account, leave user_dirs empty.
            if find_account_id in account_list:
                info = self._steam_accounts.account_info(find_account_id)
                # Should be safe to cast here, because we have asked for valid accounts
                user_dirs[find_account_id] = cast(Path, info.path)

        else:
            for account_id in account_list:
                info = self._steam_accounts.account_info(account_id)
                user_dirs[account_id] = cast(Path, info.path)

        for account_id in list(user_dirs.keys()):
            # extend path to Steam rocksmith remote folder.
            save_dir = user_dirs[account_id].joinpath(RS_APP_ID, STEAM_REMOTE_DIR)

            if save_dir.is_dir():
                # update user_dirs path with Rocksmith remote save location.
                user_dirs[account_id] = save_dir
            else:
                # user has no Rocksmith save directory, so delete from dictionary
                del user_dirs[account_id]

        return user_dirs

    def _get_steam_file_sets(self) -> Dict[str, RSFileSet]:
        """Return a dictionary of the valid Rocksmith file sets for Steam users.

        Returns:
            Dict[str, RSFileSet] -- Dictionary of valid Rocksmith file sets, where the
                keys are Steam account ids as strings, and the values are the Rocksmith
                file sets for each Steam user.

        If a target Steam account id was set in the constructor, the dictionary will
        contain only the file set for this user (if it exists).

        """
        user_dirs = self._get_steam_rs_user_dirs(find_account_id=self.steam_account_id)

        steam_file_sets = dict()
        for account_id, save_path in user_dirs.items():
            file_set = RSFileSet(save_path)
            if file_set.consistent:
                steam_file_sets[account_id] = file_set
            else:
                logging.warning(
                    f"Discarding inconsistent Rocksmith save file set for Steam user:"
                    f"\n    {self.steam_description(account_id)}"
                    f"\nRefer to previous warnings for details ."
                )

        return steam_file_sets

    @staticmethod
    def _user_confirm_setup() -> bool:
        """Prompt user to confirm setup of workspace for profile manager.

        Raises:
            RSProfileError: If the users rejects setup of the workspace.

        """
        perform_setup = utils.yes_no_dialog(
            "Some required working directories are missing and/or the update directory "
            "contains"
            "\nan old set of Rocksmith saves."
            "\nYou can either: have the directories created and the files deleted; or "
            "do nothing "
            "\nand raise an error."
            "\n"
            "\nWould you like to create the directories and/or delete the file sets "
            "from the"
            "\nupdate directory?"
        )

        if perform_setup is False:
            raise RSProfileError(
                "User exit: Rocksmith profile manager requires working directories and "
                " a clean"
                "\nupdate directory (no Rocksmith file set from previous runs)."
                "\nEither perform this set up or allow the profile manager to do so."
            )

        return perform_setup

    def _setup_workspace(self, base_dir: Path, auto_setup: bool = False) -> None:
        """Check and create working directory structure and state.

        Arguments:
            base_dir {pathlib.Path} -- The base directory for the profile manager
                instance.

        Keyword Arguments:
            auto_setup {bool} -- If False, the user will be prompted to confirm setup
                actions. Otherwise the method performs the setup actions without
                interaction. (default: {False})

        Raises:
            NotADirectoryError -- If any of the workspace directory paths exist, but are
                not directories.

        Workspace set up consists of checking that workspace directories exist, creating
        them if they don't, and deleting any old files from the update directory.

        """
        perform_setup = auto_setup

        working = base_dir.joinpath(RS_WORKING_DIR)
        self._working_save_path = working.joinpath(STEAM_REMOTE_DIR)
        self._backup_path = base_dir.joinpath(RS_BACKUP_DIR)
        update_path = base_dir.joinpath(RS_UPDATE_DIR)
        self._update_save_path = update_path.joinpath(STEAM_REMOTE_DIR)

        for check_dir in (
            working,
            self._working_save_path,
            self._backup_path,
            update_path,
            self._update_save_path,
        ):
            if check_dir.exists():
                if not check_dir.is_dir():
                    raise NotADirectoryError(
                        f"Profile manager called on invalid working directory\n   "
                        f"'{fsdecode(check_dir)}'"
                    )
            else:
                if not perform_setup:
                    # raises an error if user does not confirm setup.
                    perform_setup = self._user_confirm_setup()

                check_dir.mkdir()

        # check and tidy update directory if needed. No need to log on this one as we
        # need to delete any full or partial file set.
        logging.disable(logging.CRITICAL)
        file_set = RSFileSet(self._update_save_path)
        logging.disable(logging.NOTSET)
        # Note fileset.profiles is a dict - Returns True if it contains members
        if (
            file_set.profiles
            or file_set.local_profiles is not None
            or file_set.steam_metadata is not None
        ):

            # at least one file exists, so clean up
            if not perform_setup:
                # raises an error if user does not confirm setup.
                perform_setup = self._user_confirm_setup()

            file_set.delete_files()

    def write_files(self) -> None:
        """Write changed profiles, local profiles and Steam metadata as required.

        Updated files are written to self._update_path *AND* data is not marked as
        clean, as the instance data is not in sync with original source files (this is
        only an issue if the caller intent is to update original files later).

        Backs up *all* save files (including unchanged files), local profiles and steam
        cache files into a zip file in self._backup_path before saving changes.
        """
        # create zip file and back up *all* files before writing any changes.
        # don't apply any compression as most objects are already compressed.
        zip_path = self._backup_path.joinpath(
            "RS" + time.strftime("%Y%m%d%H%M%S", time.localtime()) + ".zip"
        )

        with ZipFile(zip_path, "x") as my_zip:
            my_zip.write(
                self._local_profiles.file_path,
                "/".join([STEAM_REMOTE_DIR, self._local_profiles.file_path.name]),
            )
            my_zip.write(
                self._steam_metadata.file_path, self._steam_metadata.file_path.name
            )

            for profile_key, profile in self._profiles.items():
                if profile_key == profile.unique_id:
                    # self._profiles has both unique_id and player_name pointers
                    # to player profiles.
                    # To prevent processing profiles twice, we only process the
                    # unique_id entry and skip the player_name entries.
                    my_zip.write(
                        profile.file_path,
                        "/".join([STEAM_REMOTE_DIR, profile.file_path.name]),
                    )

                    # as we have the profile, try writing it to the update save path
                    # Save will only occur if the instance is dirty.
                    saved_file_path = profile.write_file(
                        save_path=self._update_save_path
                    )
                    if saved_file_path is not None:
                        # save occurred, so update local profiles, Steam metadata if
                        # applicable
                        self._local_profiles.update_local_profiles(
                            profile.unique_id, saved_file_path
                        )
                        self._steam_metadata.update_metadata_set(
                            RS_APP_ID, saved_file_path
                        )

            # Finally, save local profiles, update Steam metadata, and save steam
            # metadata if applicable.
            # Again, this only happens if the instance is dirty.
            saved_file_path = self._local_profiles.write_file(
                save_path=self._update_save_path
            )
            if saved_file_path is not None:
                # update Steam metadata for local profiles.
                self._steam_metadata.update_metadata_set(RS_APP_ID, saved_file_path)

            # and save the Steam metadata in to the parent directory!
            self._steam_metadata.write_metadata_file(
                save_dir=self._update_save_path.parent
            )

    def copy_profile(
        self, *, src_name: str, dst_name: str, write_files: bool = False
    ) -> None:
        """Copy all data from one profile into another (destroys destination data).

        Arguments:
            src_name {str} -- The source profile name or unique id.
            dst_name {str} -- The destination profile name or unique id.

        Keyword Arguments:
            write_files {bool} -- If True, the method will call self.write_files() after
                copy the profile data. (default: {False})

        This is a one shot utility for filling test profiles with data.

        This method replaces *ALL* data in the destination profile (destructive copy).
        The method wil work with either player name or unique profile ids.

        """
        self._profiles[dst_name].json_tree = self._profiles[src_name].json_tree
        self._profiles[dst_name].mark_as_dirty()

        if write_files:
            self.write_files()

    def move_updates_to_steam(self, target_steam_account_id: str) -> None:
        """Move any updated files to a Steam user directory.

        Arguments:
            target_steam_account_id {str} -- String representation of an integer steam
                account id.

        Raises:
            RSProfileError -- If there is no Rocksmith save directory for the steam
                user.
            RSFileSetError -- If the file set in the update folder is not consistent.

        The method moves all Rocksmith save and metadata files in the update directory
        of the workspace to the target Steam user's Rocksmith save directory.

        The file set must be consistent, and the Steam user Rocksmith save directory
        must exist. The caller is responsible for ensuring the file set matches up with
        the Steam account id.

        """
        # Steam dirs requires string version of Steam account id.
        target_steam_account_id = str(target_steam_account_id)

        steam_dirs = self._get_steam_rs_user_dirs(
            find_account_id=target_steam_account_id
        )

        if not steam_dirs:
            raise RSProfileError(
                f"Moving updates failed. Steam Rocksmith save directory does not exist "
                f"for account:"
                f"\n    {self.steam_description(target_steam_account_id)}"
            )

        steam_save_dir = steam_dirs[target_steam_account_id]

        # Note: update set only contains files that have been changed.
        # Metadata for unchanged files should still exist in the local profiles and
        # Steam metadata files, and should be unchanged as well!
        update_set = RSFileSet(remote_path=self._update_save_path)
        if not update_set.consistent:
            raise RSFileSetError(
                "Moving updates failed. Rocksmith update file set is not consistent"
            )

        # copy file set and then delete originals.
        update_set.copy_file_set(steam_save_dir, True)
        update_set.delete_files()

    def player_arrangement_ids(self, profile_name: str) -> Iterator[str]:
        """Return iterator for all song arrangement ids that appear in a profile.

        Arguments:
            profile_name {str} --  The target profile name or unique id.

        Raises:
            KeyError -- If the profile name does not exist.

        Yields:
            str -- song arrangement id.

        """
        if profile_name in self._profiles:
            return self._profiles[profile_name].arrangement_ids()
        else:
            raise KeyError(
                f"Profile name/id {profile_name} does not exist in active Rocksmith "
                f"file set"
            )

    def copy_player_json_value(
        self, profile_name: str, json_path: JSON_path_type
    ) -> Any:
        """Return a deep copy of part of the player profile data tree.

        Arguments:
            profile_name {str} -- The target profile name or unique id.
            json_path {Sequence[Union[int, str, ProfileKey]]} -- Path to json sub
                container or data value. See class documentation for a description of
                json_path.

        Returns:
            Any -- A json subtree (list, dict), or a json value (str, bool, Decimal)
                found at the end of the json_path.

        """
        return copy.deepcopy(self._profiles[profile_name].get_json_subtree(json_path))

    def replace_song_list(
        self,
        profile_name: str,
        target: ProfileKey,
        new_song_list: List[str],
        list_index: int = -1,
    ) -> None:
        """Replace Favorites or indexed Song List with a new song list.

        Arguments:
            profile_name {str} -- The target profile name or unique id.
            target {ProfileKey} -- must be either ProfileKey.SONG_LISTS or
                ProfileKey.FAVORITES_LIST (import from rsrtools.files.config).
            new_song_list {List[str]} -- The list of new songs to be inserted into the
                song list. Refer rsrtools.songlists.database for details on song
                list generation and structure. In summary, this is a list of the short
                form song names: e.g. ["BlitzkriegBop", "CallMe"].
            list_index {int} -- If target is SONG_LISTS, the index of the song list to
                replace in the range 0-5. Ignored if target is FAVORITES.

        Note: Rocksmith has 6 user specifiable song lists. Following python convention,
        we index these from 0 to 5.
        """
        self._profiles[profile_name].replace_song_list(
            target, new_song_list, list_index
        )

    def set_arrangement_play_count(
        self, profile_name: str, arrangement_id: str, play_count: int
    ) -> None:
        """Set a profile's "Learn a Song" play count for an arrangement.

        Arguments:
            profile_name {str} -- The target profile name or unique id.
            arrangement_id {str} -- The unique id for a Rocksmith arrangement.
            play_count {int} -- The new play count value.

        Note: This is a utility function that I find useful to reset some arrangement
        play counts to zero (e.g. rhythm arrangements I may have played once that I
        don't want to appear in count based song lists).
        """
        self._profiles[profile_name].set_arrangement_play_count(
            arrangement_id, play_count
        )

    def mark_as_dirty(self, profile_name: str) -> None:
        """Mark the profile data as dirty.

        WARNING! This method has not been tested yet.

        Arguments:
            profile_name {str} -- The target profile name or unique id.

        This is intended to be used when:
            - The caller has modified the profile save data external to this class.
            - Restoring an old save. By marking the file as dirty, file data, local
              profiles and Steam cache data can all be set in sync for the file. The
              save file still needs to be represented in local profiles data and steam
              cache file.
            - Copying a save to a new location without changing it (write_file does
              nothing unless the instance is marked dirty).
        """
        self._profiles[profile_name].mark_as_dirty()

    def get_json_subtree(self, profile_name: str, json_path: JSON_path_type) -> Any:
        """Return profile json subtree or value based on the json_path sequence.

        WARNING! This method has not been tested yet.

        Arguments:
            profile_name {str} -- The target profile name or unique id.
            json_path {Sequence[Union[int, str, ProfileKey]]} -- Path to json sub
                container or data value. See RSWrapper documentation for a description
                of json_path. If json_path is empty, returns full profile json_tree.

        Returns:
            Any -- A json subtree (list, dict), or a json value (str, bool, Decimal)
                found at the end of the json_path. Keep in mind that editing a mutable
                is editing the save file. If you do this, you should also mark the file
                as dirty.

        """
        return self._profiles[profile_name].get_json_subtree(json_path)

    def set_json_subtree(
        self, profile_name: str, json_path: JSON_path_type, subtree_or_value: Any
    ) -> None:
        """Replace profile subtree or value at the end of json_path.

        WARNING! This method has not been tested yet.

        Arguments:
            profile_name {str} -- The target profile name or unique id.
            json_path {Sequence[Union[int, str, ProfileKey]]} -- Path to json sub
                container or data value. See RSWrapper documentation for a description
                of json_path. If json_path is empty, the method will replace the entire
                json tree for the profile with subtree_or_value.
            subtree_or_value {Any} -- A json subtree (list, dict), or a json value
                (str, bool, Decimal) that replaces the subtree/value found at the end
                of the json_path. The caller is responsible for ensuring the
                format of this argument is consistent with Rocksmith json.

        Marks instance as dirty, as this is the expected behaviour for a value change.
        """
        self._profiles[profile_name].set_json_subtree(json_path, subtree_or_value)

    def profile_names(self) -> List[str]:
        """Return a list of the profile names in the file set.

        Returns:
            List[str] -- The list of profile names in the working Rocksmith file set.

        """
        ret_val: List[str] = list()
        for profile in self._profiles.values():
            name = profile.player_name
            if name and name not in ret_val:
                ret_val.append(name)

        return ret_val

    def cl_choose_profile(self, header_text: str, no_action_text: str) -> str:
        """Provide a command line menu for selecting a Rocksmith profile name.

        Arguments:
            header_text {str} -- Menu description text.
            no_action_text {str} -- Description of no action selection.

        Returns:
            str -- The name of the selected profile, or empty string if none selected.

        The menu will list all profile names in the working Rocksmith file set.

        """
        choice = utils.choose(
            options=self.profile_names(), header=header_text, no_action=no_action_text
        )

        if choice is None:
            ret_val = ""

        else:
            ret_val = choice[0]
            if not isinstance(ret_val, str):
                raise TypeError(
                    f"Unexpected type from profile choice. Should be string, "
                    f"got f{type(ret_val)}."
                )

        return ret_val

    def cl_clone_profile(self) -> None:
        """Provide a command line interface for profile cloning."""
        while True:
            src = self.cl_choose_profile(
                no_action_text="Exit without cloning.",
                header_text=(
                    "Choose the source profile for cloning (data will be "
                    "copied from this profile)."
                ),
            )

            if not src:
                return

            dst = self.cl_choose_profile(
                no_action_text="Exit without cloning.",
                header_text=(
                    "Choose the target profile for cloning (all data in "
                    "this profile will be replaced)."
                ),
            )

            if not dst:
                return

            if src == dst:
                print()
                print(
                    "Source and destination profiles must be different. "
                    "Please try again."
                )
            else:
                break

        if int(self.steam_account_id) > 0:
            dlg = (
                f",\nand will write the updated profile back to Steam "
                f"account:"
                f"\n    {self.steam_description(self.steam_account_id)}"
            )
        else:
            dlg = "."

        dlg = (
            f"Please confirm that you want to copy player data from profile"
            f"\n'{src}' into profile '{dst}'.\n"
            f"\nThis will replace all existing data in profile '{dst}'{dlg}"
        )

        if utils.yes_no_dialog(dlg):
            self.copy_profile(src_name=src, dst_name=dst, write_files=True)
            if int(self.steam_account_id) > 0:
                self.move_updates_to_steam(self.steam_account_id)

    def cl_set_play_counts(self, play_count_file_path: Path) -> None:
        """Set some arrangement play counts for a profile (very primitive).

        Arguments:
            play_count_file_path {Path} -- Path to test file containing arrangement ids
                and play counts.

        Mostly intended for tidying up arrangements that have been played once only,
        and need resetting to zero. The method will use a command line menu to get
        the user to select a target profile.

        This method expects the path to a file containing:
            <arrangement id>, <play count>
        on each line. It has no error management, but only writes after processing the
        entire file.
        """
        target = self.cl_choose_profile(
            no_action_text="Exit.",
            header_text="Which profile do you want to apply play count changes to?.",
        )

        if not target:
            return

        if int(self.steam_account_id) > 0:
            dlg = (
                f",\nand write the updated profile back to Steam user:"
                f"\n\n    {self.steam_description(self.steam_account_id)}"
            )
        else:
            dlg = "\nand write these changes to the update directory."

        dlg = (
            f"Please confirm that you want to apply arrangement count changes to "
            f"profile '{target}'{dlg}"
        )

        if utils.yes_no_dialog(dlg):
            with play_count_file_path.open("rt") as fp:
                for arr_line in fp:
                    arr_id, count = arr_line.split(",")
                    arr_id = arr_id.strip()
                    count = count.strip()
                    print(arr_id, count)
                    self.set_arrangement_play_count(target, arr_id, int(count))

            self.write_files()
            if int(self.steam_account_id) > 0:
                self.move_updates_to_steam(self.steam_account_id)


def main() -> None:
    """Provide basic command line main."""
    # TODO Maybe in future add functionality to delete arrangement data. Need more
    #       confidence on what is/isn't useful data (target player arrangement data
    #       where the is no corresponding song arrangement data - but need to eliminate
    #       lesson/practice tracks first - and for this, need a ps arc extractor!).

    parser = argparse.ArgumentParser(
        description="Command line interface for Rocksmith profile manager utilities."
    )

    parser.add_argument(
        "working_dir",
        help="Working directory for config files, working sub-dirs, files, etc.",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--clone-profile",
        help="Interactive process to copy the contents of a source profile into "
        "a target profile. This replaces the target profile contents.",
        action="store_true",
    )
    group.add_argument(
        "--set-play-counts",
        help="Sets play counts for arrangements as specified in the play count "
        "file. Each line in this file should consist of: "
        "<ArrangementID>, <NewPlayCount>.",
        metavar="play_count_file_path",
    )

    args = parser.parse_args()

    pm = RSProfileManager(Path(args.working_dir))

    if args.clone_profile:
        pm.cl_clone_profile()

    if args.set_play_counts:
        pm.cl_set_play_counts(Path(args.set_play_counts))


if __name__ == "__main__":
    main()
