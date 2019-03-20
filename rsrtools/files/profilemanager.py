#!/usr/bin/env python3
"""Provides classes for managing a group of Rocksmith save files owned by a steam user.

The primary public class is RSProfileManager, with the other classes being helpers that
support the operation of the profile manager class.

For command line options (database setup, reporting), run:
    'python -m rsrtools.files.profile_manager -h'
"""

import os
import argparse
import time
import copy
import logging
import shutil
from decimal import Decimal
from zipfile import ZipFile
from typing import Dict, Sequence, Union, Tuple, Optional, Any

from rsrtools.files.savefile import RSSaveFile
from rsrtools.files.steamcache import SteamMetadata, SteamMetadataError
from rsrtools import utils

# Rocksmith meta data file. Ties profile name to profile id.
LOCAL_PROFILES = "LocalProfiles.json"
STEAM_REMOTE_DIR = "remote"
RS_WORKING_DIR = "RS_working"
RS_BACKUP_DIR = "RS_backup"
RS_UPDATE_DIR = "RS_update"
PROFILE_DB_STR = "_PRFLDB"
RS_APP_ID = "221680"


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
        Constructor: Checks if the save file exists and prepares for lazy loading.
        file_path: Return path the save file managed by the wrapper instance.
        write_file: Save changed instance data back to the underlying file.
        json_tree: Read/write property. The property read returns a reference to
            instance save data in the form of a json dict. This is a **mutable** -
            changes to the returned object affect the instance data. If the caller
            modifies the instance data, they are also responsible for marking the
            instance as dirty.
            The property write replaces the instance save data completely and marks
            the instance as dirty. Use with care if you know what you are doing.
            See also mark_as_dirty.
        mark_as_dirty: Mark instance data as dirty. Used to inform the instance that
            save data in the json tree has been changed externally.
        get_json_subtree: Returns a subtree in the instance save data. This may or may
            not be mutable (json sub-dicts are mutable, values are normally not
            mutable). In line with json_tree above, the caller is reponsible for
            marking the instance as dirty if it modifies the save data.
        set json_subtree: Overwrites a subtree in the instance save data and marks the
            instance as dirty.

    Note: This class is only intended for use by the profile manager. Use RSSaveFile
    if you want direct access to a save file.

    This class provides a wrapper for reading and writing Rocksmith save files. It is a
    super class for RSProfileDB (wrapper for profiles - *_PRFLDB) and RSLocalProfiles
    (wrapper for LocalProfiles.json), providing routines common to both of these
    classes.

    RSSaveWrapper is implemented as wrapper, rather than a sub class, of RSSaveFile to
    support lazy loading of save files.

    This class and sub-classes use a json path to navigate save data elements in the
    json dict. A json path is a list or tuple of the elements used to locate a specific
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
    one of these mutables, then the caller should also call mark_as_dirty, or should
    use the property setter for json_tree or call set_json_subtree as appropriate.
    """

    _file_path: os.PathLike
    _is_dirty: bool
    __cached_rs_file: Optional[RSSaveFile]

    def __init__(self, file_path: os.PathLike):
        """Check if the save file_path exists, and prepare for lazy loading.
        
        Arguments:
            file_path {os.PathLike} -- Path to the target Rocksmith save file.
        
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

        file_path = os.path.abspath(file_path)
        if os.path.isfile(file_path):
            self._file_path = file_path
        else:
            raise FileNotFoundError("File {0} is missing.".format(file_path))

    @property
    def file_path(self) -> Optional[os.PathLike]:
        """Return the original save file path.
        
        Returns:
            os.Pathlike -- Original file save path used in __init__.

        """
        return self._file_path

    def write_file(self, save_dir: os.PathLike) -> Optional[os.PathLike]:
        """Save **changes** in instance data to the underlying file.
        
        Arguments:
            save_dir {os.PathLike} -- The target directory for saving the file. 
                If save_dir is specified as None, the original file will be overwritten
                and the instance will be marked as clean.
                Otherwise the updated file is written to save dir *AND* instance data
                is not marked as clean, as instance data is not in sync with the
                original source file (this may be useful if the user intent is to
                update the original files later).
        
        Returns:
            None | str -- Returns None if no save occurs (source file and instance
                data are the same). Returns the path to the saved file if the save
                occurs (regardless of value of save_dir).
        
        This method does nothing if the instance data is the same as the original save
        file. To use this method to save an unchanged file to a new location, use 
        self.mark_as_dirty() first and then self.write_file(save_dir).

        """
        save_path = None
        if self._is_dirty:
            if save_dir is None:
                self._rs_file.write_save_file(overwrite_original=True)
                # instance is in sync with file after saving.
                save_path = self._file_path
                self._is_dirty = False

            else:
                save_path = os.path.join(save_dir, os.path.basename(self._file_path))
                # Note that we do not change the is_dirty state, as we are not updating
                # the original source file.
                # This is also relatively safe, as write_save_file will not overwrite
                # an existing file.
                self._rs_file.write_save_file(save_file_name=save_path)

        return save_path

    @property
    def _rs_file(self) -> RSSaveFile:
        """Return a reference to the RSSaveFile instance for the save file.

        Create the instance if this is the first reference to it (lazy loading).
        
        Only meant for use by subclasses.
        
        Returns:
            RSSaveFile -- Rocksmith save file object.

        """
        if self.__cached_rs_file is None:
            self.__cached_rs_file = RSSaveFile(self._file_path)

        return self.__cached_rs_file

    @property
    def json_tree(self) -> Dict:
        """Read/write property for save file data in json tree format (mutable).

        Returns/writes:
            {dict} -- instance simplejson dictionary containing Rocksmith save data.

        The getter returns a reference to the instance json tree. The caller is
        responsible for marking the save file as dirty if it modifies any of the tree
        elements.

        The setter replaces the instance data with new_data. The setter is responsible
        for ensuring the format of the tree is consistent with the Rocksmith save file
        format. Using the setter to replace the tree will automatically mark the save
        file as dirty.        
        """
        return self._rs_file.json_tree

    @json_tree.setter
    def json_tree(self, new_data: Dict) -> None:
        self._rs_file.json_tree = new_data
        self.mark_as_dirty()

    def mark_as_dirty(self) -> None:
        """Mark the instance data as dirty.
        
        This is intended to be used when:
            - The caller has modified the instance save data external to this class.
            - Restoring an old save. By marking the file as dirty, file data, local
              profiles and steam cache data can all be set in sync for the file. The
              save file still needs to be represented in local profiles data and steam
              cache file.
            - Copying a save to a new location without changing it (write_file does
              nothing unless the instance is marked dirty).
        """
        self._is_dirty = True

    def _json_node(
        self, json_path: Sequence[Union[int, str]]
    ) -> Tuple[Dict, Union[str, int]]:
        """Return json sub-dict and key for the last element of json_path.
        
        Arguments:
            json_path {Sequence[Union[int, str]]} -- Path to json sub dictionary or
                data value. See class documentation for a description of json_path.
        
        Raises:
            KeyError -- Raised on invalid key in json_path.
            IndexError -- Raised on invalid index in json_path.
        
        Returns:
            Tuple[Dict, Union[str, int]] -- A (dict, key) tuple, where dict is the
                sub-dict of self.json_tree that contains the last element of json_path,
                and the key is the value of the last element of json path.

        Refer to get/set_json_subtree for usage.
        """
        node = self.json_tree
        prev_node = node

        for key in json_path:
            # traverse full path to check existence of each node.
            prev_node = node
            try:
                node = node[key]
            except KeyError:
                raise KeyError(
                    "Invalid key {0} in json path {1}.".format(key, json_path)
                )
            except IndexError:
                raise IndexError(
                    "Invalid index {0} in json path {1}.".format(key, json_path)
                )

        # actually want to return  final node (prev_node) rather than final value (node)
        return prev_node, json_path[-1]

    def get_json_subtree(
        self, json_path: Sequence[Union[int, str]]
    ) -> Union[Dict, Any]:
        """Returns a subtree/value based on the json_path iterable."""
        parent_dict, key = self._json_node(json_path)

        return parent_dict[key]

    def set_json_subtree(
        self, json_path: Sequence[Union[int, str]], 
        subtree_or_value: Union[Dict, Any]
    ) -> None:
        """Replaces subtree/value of end of json_path.

        Marks instance as dirty, as this is the expected behaviour for a value change.
        """
        parent_dict, key = self._json_node(json_path)

        parent_dict[key] = subtree_or_value

        self.mark_as_dirty()


class RSLocalProfiles(RSSaveWrapper):
    """Wrapper for reading and managing Rocksmith data held in LocalProfiles.json."""

    def __init__(self, profile_dir):
        """Reads Rocksmith data from LocalProfiles.json. """

        file_path = os.path.abspath(os.path.join(profile_dir, LOCAL_PROFILES))
        super().__init__(file_path)

    def _profile_from_unique_id(self, unique_id):
        """Utility function, returns profile data dictionary for unique_id if it exists.
        """
        ret_val = None
        for profile in self.get_json_subtree(("Profiles",)):
            if profile["UniqueID"] == unique_id:
                ret_val = profile
                break
        return ret_val

    def player_name(self, unique_id):
        """Returns the Rocksmith player name for unique id or None if unique_id is not
        found in LocalProfiles.json."""
        profile = self._profile_from_unique_id(unique_id)
        if profile is None:
            return None
        else:
            return profile["PlayerName"]

    def update_local_profiles(self, unique_id, file_path):
        """Updates last modified time for profile unique_id in LocalProfiles.json.

        Uses last modified time from file_path. No update occurs if profile unique_id
        is not found in the local profiles file."""

        profile = self._profile_from_unique_id(unique_id)
        if profile is not None:
            # force decimal precision to match Rocksmith 6 digits (slightly ludicrous,
            # but belt and braces).
            last_modified = Decimal(int(os.path.getmtime(file_path))) + Decimal(
                "0.000000"
            )
            if last_modified != profile["LastModified"]:
                profile["LastModified"] = last_modified
                self.mark_as_dirty()


class RSProfileDB(RSSaveWrapper):
    """Wrapper for reading and managing Rocksmith save files (profile db/PRFLDB files).
    """

    _unique_id: str
    _player_name: str

    def __init__(self, file_path, local_profiles: RSLocalProfiles):
        """Records the profile uniqueID, and and checks local_profiles
        (LocalProfiles.json) for the player name.

        Player name is set to None if not found in local_profiles, or if local_profiles
        is None"""

        super().__init__(file_path)

        self._unique_id = os.path.basename(file_path).upper()
        if not self._unique_id.endswith(PROFILE_DB_STR):
            raise RSProfileError(
                "RSProfileDB objects require a file ending in {0}.".format(
                    PROFILE_DB_STR
                )
            )
        else:
            self._unique_id = self._unique_id[: -len(PROFILE_DB_STR)]

        if local_profiles is None:
            self._player_name = None
        else:
            self._player_name = local_profiles.player_name(self._unique_id)

    @property
    def unique_id(self):
        """Returns the unique_id of the Rocksmith save (file name excluding _PRFLDB
        suffix)."""
        return self._unique_id

    @property
    def player_name(self):
        """Returns the Rocksmith player name associated with the profile."""
        return self._player_name

    def arrangement_ids(self):
        """Iterator for all song arrangement ids that appear in the profile."""

        # can add/remove members as file changes in future. RS appears to fill data as
        # it it is created, so children are likely to be incomplete.
        arrangement_ids = set()

        # noinspection SpellCheckingInspection
        for json_path in (
            ("Playnexts", "Songs"),
            ("Songs",),
            ("Stats", "Songs"),
            ("SongsSA",),
        ):
            try:
                arrangement_dict = self.get_json_subtree(json_path)
            except (KeyError, IndexError):
                pass
            else:
                arrangement_ids = arrangement_ids.union(set(arrangement_dict.keys()))

        for a_id in arrangement_ids:
            yield a_id

    def replace_song_list(self, list_index, new_song_list):
        """Replaces song list[list_index] with the new song list (list_index must be in
        the range 0-5)."""

        node, key = self._json_node(("SongListsRoot", "SongLists", list_index))

        node[key] = new_song_list
        self.mark_as_dirty()

    def set_arrangement_play_count(self, arrangement_id, play_count):
        dec_play_count = Decimal(int(play_count)) + Decimal("0.000000")
        self.set_json_subtree(
            ("Stats", "Songs", arrangement_id, "PlayedCount"), dec_play_count
        )


class RSFileSet:
    """A helper class for gathering and testing Rocksmith save sets.

    A consistent rocksmith save set consists of the following elements:
        - A remotecache.vdf file used for steam cloud syncing.
        - A LocalProfiles.json Rocksmith file used to link profile ids and profile
          names.
        - One or more Rocksmith profiles files (*_PRFLDB)
        - Appropriate cross references/links between the files.

    The class constructor performs basic checks on internal consistency in the file set
    (i.e. save files referenced in local profiles and cache, local profiles referenced
    in cache). Save are lazy loaded, so a corrupt file may cause problems later.
    """

    steam_cache: SteamMetadata
    local_profiles: RSLocalProfiles
    profiles: Dict[str, RSProfileDB]
    consistent: bool
    m_time: str

    def __init__(self, rs_save_dir):
        """Creates an RSFileSet based on rs_save_dir.

        Checks consistency and time of most recent save. If file set is not consistent,
        errors are printed to help user identify issues.

        This routine deliberately excludes crd files."""

        self.steam_cache = None
        try:
            # steam cache should be in parent of Rocksmith save dir
            self.steam_cache = SteamMetadata(
                os.path.dirname(os.path.abspath(rs_save_dir))
            )
        except (FileNotFoundError, SteamMetadataError) as exc:
            logging.warning(exc)

        self.local_profiles = None
        try:
            self.local_profiles = RSLocalProfiles(rs_save_dir)
        except FileNotFoundError as exc:
            logging.warning(
                "Rocksmith local profiles file expected but not found:\n   {0}".format(
                    str(exc)
                )
            )

        self._find_profiles(rs_save_dir)

        self._check_consistency(rs_save_dir)

    def _find_profiles(self, rs_save_dir):
        """Finds all Rocksmith save files in save dir."""
        m_time = 0
        self.profiles = dict()
        for filename in os.scandir(rs_save_dir):
            if os.path.isfile(filename):
                try:
                    profile = RSProfileDB(filename.path, self.local_profiles)
                except RSProfileError:
                    # not a valid save file, so we assume it is not part of the set
                    # and ignore it
                    pass
                else:
                    self.profiles[profile.unique_id] = profile
                    if profile.player_name is not None:
                        # also allow access to profile via player_name if we know it.
                        self.profiles[profile.player_name] = profile

                    profile_time = os.path.getmtime(profile.file_path)
                    if profile_time > m_time:
                        m_time = profile_time

        self.m_time = time.asctime(time.localtime(m_time))

    def _check_consistency(self, rs_save_dir):
        """Checks consistency of Rocksmith file set."""
        consistent = True

        if self.local_profiles is None:
            consistent = False

        if not self.profiles:
            consistent = False
            logging.warning(
                "Warning: No Rocksmith save files ({0}) found in:\n    {1}.".format(
                    PROFILE_DB_STR, rs_save_dir
                )
            )

        for rs_file in self.profiles.values():
            if rs_file.player_name is None:
                consistent = False
                logging.warning(
                    "Rocksmith save file has no player name:\n   {0}".format(
                        rs_file.file_path
                    )
                )

        if self.steam_cache is None:
            consistent = False
        else:
            file_list = list(self.profiles.values())
            if self.local_profiles is not None:
                file_list.append(self.local_profiles)

            for rs_file in file_list:
                if not self.steam_cache.metadata_exists(RS_APP_ID, rs_file.file_path):
                    consistent = False
                    logging.warning(
                        "Steam cache contains no data for file:\n   {0}".format(
                            rs_file.file_path
                        )
                    )

        self.consistent = consistent

    def copy_file_set(self, save_dir):
        """Copies all file in the files set in to the target save directory.

        The copy does not check file set consistency."""

        file_list = list(self.profiles.values())
        if self.local_profiles is not None:
            file_list.append(self.local_profiles)

        for file in file_list:
            shutil.copy2(file.file_path, save_dir)

        if self.steam_cache is not None:
            # steam cache is copied to the parent directory
            shutil.copy2(self.steam_cache.file_path, os.path.dirname(save_dir))

    def delete_files(self):
        """Deletes all files in the file set."""

        file_list = list(self.profiles.values())

        if self.local_profiles is not None:
            file_list.append(self.local_profiles)

        if self.steam_cache is not None:
            file_list.append(self.steam_cache)

        for file in file_list:
            if os.path.exists(file.file_path):
                os.remove(file.file_path)

        # and in case someone tries to use this fileset now
        self.consistent = False


class RSProfileManager:
    """Provides an integrated interface to Rocksmith save files owned by a steam user.

    RSProfileManager(working_dir, steam_user_id=None, auto_setup=False,
                     flush_working_set=False)
    Sets up the working directories, optionally copies a Rocksmith file set from the
    steam user folder, and loads a working file set for use.

        method:: cl_choose_profile(header_text, no_action_text)
            Command line utility for selecting a profile name from the profiles
            available in the profile manager.

        method:: cl_clone_profile()
            Command line utility for cloning the data from one profile into another.

        method:: cl_set_play_counts(self, play_count_file_path)
            Command line utility for setting play counts for a list of arrangements.

        method:: copy_player_json_value(profile_name, json_path)
            Returns a deep copy of a json subtree for the specified profile.

        method:: copy_profile(*, src_name, dst_name, write_files=False)
            Copies all data from the source profile to the destination profile, and
            optionally writes updated files.

        method:: move_updates_to_steam(target_steam_user_id)
            Moves files in the update directory to the steam user folders for the
            specified steam user id.

        method:: player_arrangement_ids(profile_name)
            Provides an iterator for all arrangement ids in the named profile.

        method:: replace_song_list(profile_name, list_index, new_song_list)
            Replaces song list at list_index in profile_name with new_song_list.

        method:: set_arrangement_play_count(profile_name, arrangement_id, play_count)

        method:: write_files()
            Backs up all files in the working set to a zip file in the backup directory,
            and then writes all modified files to the update directory.

        property:: source_steam_uid
            Read only. The steam user id of the file set in the working directory.

    RSProfileManager works on a base directory with the following structure:
        base_dir
            \\-- RS_working   - This directory contains the working copy of the
                                Rocksmith save directory. The object expects to find
                                remotecache.vdf in this directory.
                \\-- remote   - This directory should contain the Rocksmith game files
                                and the LocalProfiles.json file.
            \\-- RS_backup    - Backups of RS_working will be made into this directory
                                before creating the any updates.
            \\-- RS_update    - Changed steam cache files will be saved in this
                                directory.
                \\--remote    - Changed files will be saved in this directory.
    If this structure does not exist, the user will be asked for permission to create
    it, and the class initialisation will fail if refused.
    """

    # type hints
    _local_profiles: RSLocalProfiles
    _steam_cache: SteamMetadata
    _profiles: Dict[str, RSProfileDB]
    _source_steam_uid: Optional[str]

    def __init__(
        self, working_dir, steam_user_id=None, auto_setup=False, flush_working_set=False
    ):
        """Initialises/cleans up working directory structure, optionally copies in
        files from steam, and loads working file set.

        :param working_dir: Working directory. String path or path like object.
        :param int | str steam_user_id: Integer steam user id per steam user folders.
        :param bool auto_setup:
        :param bool flush_working_set:

        Initialisation:
            - Checks the directory structure under working_dir and offers to set up
              missing folders.

            - Checks for Rocksmith files in the update directory, and offers to delete
              any files found.
                - Initialisation raises an error if the user rejects offer of automatic
                  setup (i.e. user must either allow automatic setup to complete or
                  must setup folders manually for successful initialisation).

            - if flush_working_set is True, checks the working directory for any file
              set or partial file set and deletes these files.

            - If no steam user id is specified (default):
                - The working directory and all steam user folders are scanned for
                  Rocksmith file sets.
                - The user is asked to select a working file set from a menu of
                  available, consistent file sets.
                    - An error is raised if the user rejects all available file sets.
                - If a steam user's file set is selected, this file set is copied into
                  the working directory, replacing any file set already in the working
                  directory.

            - If a steam user id is specified and is < 0:
                - The file set in the working directory is selected.
                - If the file set is not valid, an exception is raised
                This function is provided for debugging/testing.

            - If a steam user id is specified:
                  be copied into the working directory (replacing any file set already
                  in the working directory).
                - If the file set is not valid, an exception is raised

            - Finally, the file set in the working directory is loaded for use by the
              profile manager instance.

            If auto_setup is False, the user will be prompted to confirm workspace
            setup.
        """

        if not os.path.isdir(working_dir):
            raise NotADirectoryError(
                "Profile manager constructor called on invalid base directory:\n    "
                '"{0}"'.format(working_dir)
            )

        self._setup_workspace(working_dir, auto_setup=auto_setup)

        # source steam uid is the source uid for this profile manager.
        # string version of integer steam uid. Specifies the source of the file set in
        # the working dir
        #    - negative uid: using the file set found in the working directory at start
        #      of run (no copying from steam).
        #    - positive uid: file set from the steam user data folders corresponding to
        #      this uid will be copied into the working dir for us.
        # I.e. we always work on the files in the working dir, but this is a memo for
        # the source of the files.
        # Also provides a target for copying altered files back into steam folders.
        if steam_user_id is None:
            self._source_steam_uid = None
        else:
            self._source_steam_uid = str(steam_user_id)

        steam_file_sets = self._get_steam_file_sets()

        if flush_working_set:
            logging.disable(logging.CRITICAL)
        working_file_set = RSFileSet(self._working_save_path)
        if flush_working_set:
            working_file_set.delete_files()
            logging.disable(logging.NOTSET)

        if self._source_steam_uid is None:
            # default action: user selects working fileset
            self._source_steam_uid, chosen_file_set = self._choose_file_set(
                steam_file_sets, working_file_set
            )
        elif int(self._source_steam_uid) < 0:
            if working_file_set.consistent:
                chosen_file_set = working_file_set
            else:
                raise RSFileSetError(
                    "Rocksmith file set in working directory is either missing or"
                    "inconsistent."
                )
        else:
            # select specified steam set if available
            if self._source_steam_uid in steam_file_sets:
                chosen_file_set = steam_file_sets[self._source_steam_uid]
            else:
                raise RSFileSetError(
                    "Rocksmith file set for steam user {0} is either missing or"
                    "inconsistent.".format(self._source_steam_uid)
                )

        if chosen_file_set is not working_file_set:
            # remove current working set, copy in new set
            working_file_set.delete_files()
            chosen_file_set.copy_file_set(self._working_save_path)
            # re-read working directory to load updated file set.
            chosen_file_set = RSFileSet(self._working_save_path)

        self._profiles = chosen_file_set.profiles
        self._local_profiles = chosen_file_set.local_profiles
        self._steam_cache = chosen_file_set.steam_cache

    @property
    def source_steam_uid(self):
        """The source steam user id for the profile manager file set.

        This value is negative if the profile manager is handling files originally in
        the working folder rather than copied in from a steam user folder. In this
        instance, the user is responsible for tying the files to a steam user id (if
        relevant).
        """
        return self._source_steam_uid

    @staticmethod
    def _choose_file_set(
        steam_file_sets: Dict[str, RSFileSet], working_file_set: RSFileSet
    ) -> (str, RSFileSet):
        """Provides a command line menu for the user to select a source for the
        Rocksmith file set.

        Returns steam uid and selected fileset. The steam uid is '-1' if the working
        file set is selected.
        """

        header = (
            "Rocksmith profile/file set selection"
            "\n\nSelect a steam user id/Rocksmith file set from the following options. "
        )

        help_text = (
            "HELP: "
            "\n    - A Rocksmith file set is all of the Rocksmith profiles for a single"
            "\n      steam user/login (and some related metadata files)."
            '\n    - You need to choose the steam user id that "owns" the profiles '
            "you want to work on."
            "\n    - When you select a steam user id, I will:"
            "\n          - Clean up the working directory (delete old file sets)"
            "\n          - Find the Rocksmith file set for the selected steam user id."
            "\n          - Copy this file set from steam into the working directory."
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
                "steam user folders (fatal error)."
            )

        options = list()

        active_user = str(utils.steam_active_user())
        for steam_uid, file_set in steam_file_sets.items():
            option_text = "Steam user '{0}'".format(steam_uid)
            if steam_uid == active_user:
                option_text = option_text + ". This is the user logged into steam now."
            option_text = option_text + " ({0}).".format(file_set.m_time)
            options.append((option_text, steam_uid))

        if working_file_set.consistent:
            option_text = (
                "[Debugging/development] Keep and use the file set in the "
                "working directory ({0}).".format(working_file_set.m_time)
            )
            options.append((option_text, "-1"))

        steam_uid = utils.choose(
            options,
            header=header,
            no_action="Do nothing and raise error.",
            help_text=help_text,
        )
        if steam_uid is None:
            raise RSFileSetError(
                "User exit: User did not select a valid Rocksmith file set for use."
            )

        if steam_uid == "-1":
            file_set = working_file_set
        else:
            file_set = steam_file_sets[steam_uid]

        return steam_uid, file_set

    @staticmethod
    def _get_steam_rs_user_dirs(find_steam_user_id):
        """Finds all Rocksmith save directories in steam user folders.

        If find_steam_user_id is specified, the file set is limited to this user.
        Implemented as a static method, as it is specific to Rocksmith.
        """

        user_dirs = utils.steam_user_data_dirs()

        if find_steam_user_id is not None:
            if not isinstance(find_steam_user_id, str):
                raise TypeError(
                    "Unexpected type for find_steam_user_id. This should be string "
                    "version of steam integer uid - str(steam_uid)."
                )
            # retain dir for specified id (if found), delete all other entries.
            save_dir = user_dirs.get(find_steam_user_id, None)
            user_dirs.clear()
            if save_dir is not None:
                user_dirs[find_steam_user_id] = save_dir

        for user_id in list(user_dirs.keys()):
            save_dir = os.path.join(user_dirs[user_id], RS_APP_ID, STEAM_REMOTE_DIR)

            if os.path.isdir(save_dir):
                # update path with Rocksmith save location.
                user_dirs[user_id] = save_dir
            else:
                # user has no Rocksmith save directory, so delete from dictionary
                del user_dirs[user_id]

        return user_dirs

    def _get_steam_file_sets(self):
        """Finds Rocksmith file sets in steam user folders.

        If source steam user id is specified, file set is limited to this user."""
        user_dirs = self._get_steam_rs_user_dirs(
            find_steam_user_id=self._source_steam_uid
        )

        steam_file_sets = dict()
        for user_id, save_path in user_dirs.items():
            file_set = RSFileSet(save_path)
            if file_set.consistent:
                steam_file_sets[user_id] = file_set
            else:
                logging.warning(
                    "Rocksmith save file set for steam user {0} is not consistent and "
                    "will be discarded.\nRefer to previous warnings for "
                    "details .".format(user_id)
                )

        return steam_file_sets

    @staticmethod
    def _user_confirm_setup():
        perform_setup = utils.choose(
            [
                (
                    "Create directories and/or delete file sets from update directory.",
                    True,
                )
            ],
            header="Some required working directories are missing and/or the update "
            "directory contains an old set of Rocksmith saves. \nDo you want to "
            "either: have the directories created and the files deleted; or do nothing "
            "and raise an error?",
            no_action="Do nothing and raise an error.",
        )

        if perform_setup is None:
            raise RSProfileError(
                "User exit: Rocksmith profile manager requires working directories and "
                " a clean"
                "\nupdate directory (no Rocksmith file set from previous runs)."
                "\nEither perform this set up or allow the profile manager to do so."
            )

        return perform_setup

    def _setup_workspace(self, base_dir, auto_setup=False):
        """Check working folder structure and state, optionally create/clean up working folders and files.

        If auto_setup is False, user will be prompted to confirm setup actions.
        Otherwise the routine performs the setup actions without interaction."""

        perform_setup = auto_setup

        working = os.path.abspath(os.path.join(base_dir, RS_WORKING_DIR))
        self._working_save_path = os.path.abspath(
            os.path.join(working, STEAM_REMOTE_DIR)
        )
        self._backup_path = os.path.abspath(os.path.join(base_dir, RS_BACKUP_DIR))
        update_path = os.path.abspath(os.path.join(base_dir, RS_UPDATE_DIR))
        self._update_save_path = os.path.abspath(
            os.path.join(update_path, STEAM_REMOTE_DIR)
        )

        for check_dir in (
            working,
            self._working_save_path,
            self._backup_path,
            update_path,
            self._update_save_path,
        ):
            if os.path.exists(check_dir):
                if not os.path.isdir(check_dir):
                    raise NotADirectoryError(
                        "Profile manager called on invalid working directory\n   "
                        '"{0}"'.format(check_dir)
                    )
            else:
                if not perform_setup:
                    # raises an error if user does not confirm setup.
                    perform_setup = self._user_confirm_setup()

                os.mkdir(check_dir)

        # check and tidy update directory if needed. No need to log on this one as we
        # need to delete any full or partial file set.
        logging.disable(logging.CRITICAL)
        file_set = RSFileSet(self._update_save_path)
        logging.disable(logging.NOTSET)
        if (
            file_set.profiles is not None
            or file_set.local_profiles is not None
            or file_set.steam_cache is not None
        ):

            # at least one file exists, so clean up
            if not perform_setup:
                # raises an error if user does not confirm setup.
                self._user_confirm_setup()

            file_set.delete_files()

    def write_files(self):
        """Writes changed profiles, local profiles and steam cache as required.

        Updated files are written to update_path *AND* data is not marked as clean, as
        data is not in sync with original source files referred to by objects (this is
        only an issue if the user intent is to update original files later).

        Backs up *all* save files (including unchanged files), local profiles and steam
        cache files into a zip file in backup_path before saving changes."""

        # create zip file and back up *all* files before writing any changes.
        # don't apply any compression as most objects are already compressed.
        zipfile_name = "RS" + time.strftime("%Y%m%d%H%M%S", time.localtime()) + ".zip"
        zipfile_name = os.path.join(self._backup_path, zipfile_name)
        with ZipFile(zipfile_name, "x") as my_zip:
            my_zip.write(
                self._local_profiles.file_path,
                "/".join(
                    [STEAM_REMOTE_DIR, os.path.basename(self._local_profiles.file_path)]
                ),
            )
            my_zip.write(
                self._steam_cache.file_path,
                os.path.basename(self._steam_cache.file_path),
            )

            for profile_key, profile in self._profiles.items():
                if profile_key == profile.unique_id:
                    # self._profiles has both unique_id and player_name pointers
                    # to player profiles.
                    # To prevent processing profiles twice, we only process the
                    # unique_id entry and skip the player_name entries.
                    my_zip.write(
                        profile.file_path,
                        "/".join(
                            [STEAM_REMOTE_DIR, os.path.basename(profile.file_path)]
                        ),
                    )

                    saved_file_path = profile.write_file(
                        save_dir=self._update_save_path
                    )
                    if saved_file_path is not None:
                        # save occurred, so update local profiles, steam cache if
                        # applicable
                        self._local_profiles.update_local_profiles(
                            profile.unique_id, saved_file_path
                        )
                        self._steam_cache.update_metadata_set(
                            RS_APP_ID, saved_file_path
                        )

            # Finally, save local profiles, update steam cache, and save steam cache if
            # applicable
            saved_file_path = self._local_profiles.write_file(
                save_dir=self._update_save_path
            )
            if saved_file_path is not None:
                self._steam_cache.update_metadata_set(RS_APP_ID, saved_file_path)
            self._steam_cache.write_metadata_file(
                save_dir=os.path.dirname(self._update_save_path)
            )

    def copy_profile(self, *, src_name, dst_name, write_files=False):
        """Copies all data from src_name profile into dst_name profile, and optionally writes files. One shot for
        creating test profiles.

        This routines replaces *ALL* data in destination file. The routine wil work
        with either player name or unique profile ids."""

        self._profiles[dst_name].json_tree = self._profiles[src_name].json_tree
        self._profiles[dst_name].mark_as_dirty()

        if write_files:
            self.write_files()

    def move_updates_to_steam(self, target_steam_user_id):
        """Moves the file set in the update folder to the save folder for the target steam id.

        The file set must be consistent, and the steam user folder must exist. The
        caller is responsible for ensuring the file set matches up with the steam user
        id."""

        # steam dirs requires string version of steam user id.
        target_steam_user_id = str(target_steam_user_id)

        steam_dirs = self._get_steam_rs_user_dirs(
            find_steam_user_id=target_steam_user_id
        )

        if not steam_dirs:
            raise RSProfileError(
                'Moving updates failed. Steam save folder for user id "{0}" does not '
                "exist".format(target_steam_user_id)
            )

        steam_save_dir = steam_dirs[target_steam_user_id]

        update_set = RSFileSet(rs_save_dir=self._update_save_path)
        if not update_set.consistent:
            raise RSFileSetError(
                "Moving updates failed. Rocksmith update file set is not consistent"
            )

        # copy file set and then delete originals.
        update_set.copy_file_set(steam_save_dir)
        update_set.delete_files()

    def player_arrangement_ids(self, profile_name):
        """Wrapper for arrangement id iterator in named profile."""

        if profile_name in self._profiles:
            return self._profiles[profile_name].arrangement_ids()
        else:
            raise KeyError(
                "Profile name/id {0} does not exist in active Rocksmith file "
                "set".format(profile_name)
            )

    def copy_player_json_value(self, profile_name, json_path):
        """Returns a deep copy of the subtree/value found from the player profile json_path iterable."""
        return copy.deepcopy(self._profiles[profile_name].get_json_subtree(json_path))

    def replace_song_list(self, profile_name, list_index, new_song_list):
        """Replaces song list[list_index (0-5)] in the named profile with the new song list."""

        self._profiles[profile_name].replace_song_list(list_index, new_song_list)

    def set_arrangement_play_count(self, profile_name, arrangement_id, play_count):
        self._profiles[profile_name].set_arrangement_play_count(
            arrangement_id, play_count
        )

    def profile_names(self):
        """Returns a list of the profile names in the file set."""
        ret_val = list()
        for profile in self._profiles.values():
            name = profile.player_name
            if name is not None and name not in ret_val:
                ret_val.append(name)

        return ret_val

    def cl_choose_profile(self, header_text, no_action_text):
        """Provides a command line menu for selection of one of the profiles in the profile manager.

        Returns the name of the selected profile."""
        choice = utils.choose(
            options=self.profile_names(), header=header_text, no_action=no_action_text
        )
        return choice

    def cl_clone_profile(self):
        """Command line interface for profile cloning."""
        while True:
            src = self.cl_choose_profile(
                no_action_text="Exit without cloning.",
                header_text=(
                    "Choose the source profile for cloning (data will be "
                    "copied from this profile).",
                ),
            )

            if src is None:
                return

            dst = self.cl_choose_profile(
                no_action_text="Exit without cloning.",
                header_text=(
                    "Choose the target profile for cloning (all data in "
                    "this profile will be replaced).",
                ),
            )

            if dst is None:
                return

            if src == dst:
                print()
                print(
                    "Source and destination profiles must be different. "
                    "Please try again."
                )
            else:
                break

        if int(self.source_steam_uid) > 0:
            dlg = f",\nand will write the updated profile back to steam user {self.source_steam_uid}."
        else:
            dlg = "."

        dlg = (
            f"Please confirm that you want to copy player data from profile '{src}' into profile '{dst}'."
            f"\nThis will replace all existing data in profile '{dst}'{dlg}"
        )

        if utils.yes_no_dialog(dlg):
            self.copy_profile(src_name=src, dst_name=dst, write_files=True)
            if int(self.source_steam_uid) > 0:
                self.move_updates_to_steam(self.source_steam_uid)

    def cl_set_play_counts(self, play_count_file_path):
        """Primitive routine to set play counts for a profile. Mostly intended for tidying up arrangements that have
        been played once only, and need resetting to zero.

        This function expects the path to a file containing <arrangement id>,
        <play count> on each line. It has no error management, but only writes after
        processing the entire file."""

        target = self.cl_choose_profile(
            no_action_text="Exit.",
            header_text="Which profile do you want to apply play count changes to?.",
        )

        if target is None:
            return

        if int(self.source_steam_uid) > 0:
            dlg = f",\nand write the updated profile back to steam user {self.source_steam_uid}."
        else:
            dlg = "\nand write these changes to the update directory."

        dlg = (
            f"Please confirm that you want to apply arrangement count changes to profile '{target}'"
            f"{dlg}"
        )

        if utils.yes_no_dialog(dlg):
            with open(play_count_file_path, "rt") as fp:
                for arr_line in fp:
                    arr_id, count = arr_line.split(",")
                    arr_id = arr_id.strip()
                    count = count.strip()
                    print(arr_id, count)
                    self.set_arrangement_play_count(target, arr_id, count)

            self.write_files()
            if int(self.source_steam_uid) > 0:
                self.move_updates_to_steam(self.source_steam_uid)


if __name__ == "__main__":
    # TODO Maybe in future add functionality to delete arrangement data. Need more
    #       confidence on what is/isn't useful data (target player arrangement data
    #       where the is no corresponding song arrangement data - but need to eliminate
    #       lesson/practice tracks first - and for this, need a ps arc unpacker!).

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
        "file. Each line in this file should consist of <ArrangementID>, <NewPlayCount>.",
        metavar="play_count_file_path",
    )

    args = parser.parse_args()

    if args.clone_profile:
        pm = RSProfileManager(args.working_dir)
        pm.cl_clone_profile()

    if args.set_play_counts:
        pm = RSProfileManager(args.working_dir)
        pm.cl_set_play_counts(args.set_play_counts)
