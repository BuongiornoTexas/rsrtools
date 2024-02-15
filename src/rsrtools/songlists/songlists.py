#!/usr/bin/env python

"""Provide SongListCreator, which is the main class of the rsrtools package.

For command line options (database setup, reporting), run:
    'python -m rsrtools.songlists.songlists -h'
"""

# cSpell:ignore unsubscriptable, profilemanager

import argparse
import sys

from pathlib import Path
from os import fsdecode
from typing import Dict, List, Optional, TextIO, Union

import rsrtools.utils as utils

from rsrtools.songlists.scanner import newer_songs
from rsrtools.files.config import ProfileKey, MAX_SONG_LIST_COUNT
from rsrtools.songlists.config import ListField, RangeField
from rsrtools.songlists.configclasses import (
    Configuration,
    Settings,
    Filter,
    RSFilterError,
)
from rsrtools.songlists.database import ArrangementDB
from rsrtools.files.profilemanager import RSProfileManager, RSFileSetError

CONFIG_FILE = "config.toml"
SONG_LIST_DEBUG_FILE = "RS_Song_Lists.txt"
ARRANGEMENTS_GRID = "ArrangementsGrid.xml"
# 100ms offset to deal with rounding in saved dlc_mtime
DLC_MTIME_OFFSET = 0.01


class SongListCreator:
    """Provide a command line interface for creating and writing Rocksmith song lists.

    Refer to the rsrtools package README documentation for more detail.

    The public members of this class also provide hooks that could be used to implement
    a GUI for creating song lists. The public members are:

        Constructor -- Sets up the song list creator working directory and files, and
            loads the configuration file.

        create_song_lists -- Creates song lists for the filters in a set and writes the
            resulting song lists back to the currently specified Steam account id/player
            profile.

        load_cfsm_arrangements -- Loads arrangement data from the CFSM file defined in
            self.cfsm_arrangement_file into the arrangements database. Deprecated, due
            for deletion.

        save_config -- Saves the current song list generation configuration file.

        song_list_cli -- Runs the command line driven song list generator.

        cfsm_arrangement_file -- Read/write property. Path to a CFSM arrangement file
            that can be used for setting up the arrangement database. Deprecated, due
            for deletion.

        steam_account_id -- Read/write property. Steam account id (8 digit decimal
            number found under Steam user data folder) to use for Rocksmith saves. Can
            be set as an int or a string representation of the int, always returns str.

        player_profile -- Read/write property. Rocksmith player profile name to use for
            song list generation.

    """

    # instance variables
    _configuration: Configuration

    _arr_db: ArrangementDB
    _working_dir: Path
    # path to configuration file
    _cfg_path: Path
    _profile_manager: Optional[RSProfileManager]

    # variable only used in the CLI implementation.
    # This should be either:
    #   sys.stdout - for reports to console.
    #   A path to a reporting file that will be overwritten
    _cli_report_target: Union[Path, TextIO]

    # A lot of the properties in the following shadow config file parameters.
    # I could have done a lot of this with setattr/getattr, but given
    # the small number of properties, I've stuck with explicit definitions.
    # This also has the benefit of allowing validation along the way.
    @property
    def _settings(self) -> Settings:
        """Get general settings.

        Gets:
            rsrtools.songlists.configclasses.Settings

        Provide default (typically empty) settings if required.

        """
        return self._configuration.settings

    @property
    def _song_list_sets(self) -> Dict[str, List[str]]:
        """Get definitions for song list sets.

        Gets:
            Dict[str, List[str]] -- Each key is the name for a set of song lists, and
                the list values for that key are the filter names for generating the
                song lists in the named set (up to six names per set). Excess values in
                the list will be ignored. That is:

            {'Set name 1': ['Filter 1', 'Filter 2', 'Filter 3'],
             'Set name 2': ['Filter 2', 'Filter 3', 'Filter 4'],}

        """
        return self._configuration.song_list_sets

    @property
    def _filter_dict(self) -> Dict[str, Filter]:
        """Get dictionary of filter definitions.

        Gets:
            Dict[str, Filter] -- Each key is the name of a filter, and Filter is the
                corresponding definition.

        Each filter can be used to generate a song list or as a base filter for building
        other filters.
        """
        return self._configuration.filters

    @property
    def cfsm_arrangement_file(self) -> str:
        """Get/set the string path to a CFSM arrangements file for database setup.

        Gets/sets:
            str -- The string form path the Customs Forge Song Manager arrangements
                file, or the empty string if it has not been set.

        The setter will raise an exception if the path does not point to a file, but
        but does not validate the file.

        Deprecated, due for deletion.

        """
        check_path = self._settings.CFSM_file_path
        if check_path and not Path(check_path).is_file():
            # silently discard invalid path.
            self._settings.CFSM_file_path = ""

        return self._settings.CFSM_file_path

    @cfsm_arrangement_file.setter
    def cfsm_arrangement_file(self, value: str) -> None:
        """Set path to CFSM arrangements file."""
        file_path = Path(value)
        if not file_path.is_file():
            self._settings.CFSM_file_path = ""
            raise FileNotFoundError(f"CFSM arrangement file '{value}' does not exist")

        self._settings.CFSM_file_path = fsdecode(file_path.resolve())

    # ****************************************************
    # Steam account id, _profile_manager, player profile and player data in database are
    # tightly linked.
    # Initialisation uses these properties and exception handlers to manage auto-loading
    # from json.
    @property
    def steam_account_id(self) -> str:
        """Get/set the Steam account id to use for song list creation.

        Gets/sets:
            str -- String representation of Steam account id, or the empty string if it
                has not been set yet.

        The Steam account id is an 8 digit number, which is also the name of Steam user
        data directory.

        Song list changes affect Rocksmith profiles in this Steam user's directories.
        Setting the Steam account id to the empty string triggers an interactive command
        line process to choose a new Steam account id and triggers the side effects
        below.

        Setting Steam account id has the following side effects:
            - The instance flushes and reloads Steam profile data.
            - The instance clears the player profile and flushes player data from the
              arrangement database (reset with self.player_profile)

        """
        # could do extensive validation here, but there is already error checking in the
        # profile manager, and any ui will need to find valid Steam ids to load up.
        # So no error checking here.
        return self._settings.steam_account_id

    @steam_account_id.setter
    def steam_account_id(self, value: str) -> None:
        """Steam account id setter."""
        # reset configuration value to "" in case of errors (correct at end of routine)
        self._settings.steam_account_id = ""

        # Changing Steam account id, so clear profile manager and player profile (and
        # implicitly, flush db as well)
        # Conservative assumption - flush  and everything, even if the assignment
        # doesn't change the original Steam id
        self.player_profile = ""
        self._profile_manager = None

        # Create profile manager.
        # This will trigger an interactive file set selection if value is ""
        # (for command line use). I'm also disabling use of existing working set files
        # for the song list creator.
        # (Working set files are really only intended for debugging).
        self._profile_manager = RSProfileManager(
            self._working_dir,
            steam_account_id=value,
            auto_setup=True,
            flush_working_set=True,
        )

        final_account_id = value
        if not final_account_id:
            # Get the Steam account id resulting from an interactive call to
            # RSProfileManager
            final_account_id = self._profile_manager.steam_account_id

        self._settings.steam_account_id = final_account_id

    @property
    def player_profile(self) -> str:
        """Get/set the Rocksmith player profile name to use for song list generation.

        Gets/sets:
            str -- The player profile name. Gets the empty string if the player profile
                has not been set yet. Setting to the empty string clears the
                current profile data.

        Setting the player name also deletes all profile data from the database and
        loads the profile data for player_profile into the database. Setting to the
        empty string deletes all profile data without loading new data.

        A Steam account id must be specified before setting the player profile.
        """
        # can't do any useful validation without loading profile, so similar to the
        # Steam account id, push it down to the profile manager or up to the ui.
        return self._settings.player_profile

    @player_profile.setter
    def player_profile(self, value: str) -> None:
        """Set player profile name for song list creation."""
        # new player profile, so ditch everything in player database
        self._arr_db.flush_player_profile()
        # reset to default in case of error in setter
        self._settings.player_profile = ""

        if value:
            if self._profile_manager is None:
                # shouldn't happen, but just in case
                raise RSFilterError(
                    f"Attempt to set player profile to {value} before Steam user "
                    f"id/file set has been chosen (profile_manager is None)."
                )

            if value not in self._profile_manager.profile_names():
                description = self._profile_manager.steam_description(
                    self.steam_account_id
                )
                raise RSFilterError(
                    f"Rocksmith player profile '{value}' does not exist in Steam file "
                    f"set for user:"
                    f"\n{description}"
                )

            self._arr_db.load_player_profile(self._profile_manager, value)

            # set this last in case of errors along the way.
            self._settings.player_profile = value

    # End player steam_account_id, player_profile properties block

    def load_cfsm_arrangements(self) -> None:
        """Load arrangement data from the CFSM file into the arrangement database.

        The CFSM file is defined in the property self.cfsm_arrangement_file.

        This method replaces existing data in the database.

        Deprecated, due for deletion.
        """
        if self.cfsm_arrangement_file:
            self._arr_db.load_cfsm_arrangements(Path(self.cfsm_arrangement_file))

    # start initialisation block
    def __init__(self, working_dir: Path) -> None:
        """Initialise the song list creator.

        Arguments:
            working_dir {pathlib.Path} -- Working directory path.

        Create working files and sub-folders in the working directory, and load the
        configuration file (if any) from the working folder.
        """
        self._profile_manager = None

        # Default to console for reporting.
        self._cli_report_target = sys.stdout

        if not working_dir.is_dir():
            raise NotADirectoryError(
                f"SongListCreator requires a valid working directory. Invalid argument "
                f"supplied:\n   {fsdecode(working_dir)}"
            )
        self._working_dir = working_dir.resolve()

        self._cfg_path = self._working_dir.joinpath(CONFIG_FILE)
        self._configuration = self._load_config()

        # Save the default config if we don't have one.
        if not self._cfg_path.exists():
            self.save_config()

        self._arr_db = ArrangementDB(self._working_dir)

        # The next block is a slightly clumsy way of avoiding separate auto load code
        # for setting up profile manager and player database from json parameters for
        # Steam id and player profile name
        if not self.steam_account_id:
            # reset player profile and database (invalid with no Steam id anyway).
            tmp_profile = ""
        else:
            # resetting Steam id will trash player profile, so grab a temp copy
            tmp_profile = self.player_profile
            try:
                # this looks like a non-op, but triggers the side effect of loading the
                # profile manager for the Steam account id.
                self.steam_account_id = self.steam_account_id
            except RSFileSetError:
                # invalid Steam id, Steam id will have been reset to "".
                # discard player profile as well (meaningless without Steam id)
                tmp_profile = ""

        try:
            # this will load the database for the original self.player_profile if it
            # exists.
            self.player_profile = tmp_profile
        except RSFilterError:
            # player profile not found, player profile set to none, nothing more needed.
            pass
        # end auto load from json.

    def _load_config(self) -> Configuration:
        """Load the TOML configuration file from the working directory.

        Create a default configuration if no file is found.
        """
        return Configuration.load_toml(self._cfg_path)

    # end initialisation block

    def save_config(self) -> None:
        """Save configuration file to working directory.

        This method dumps the self._configuration object to a TOML file.
        """
        self._configuration.save_toml(self._cfg_path)

    # # *******************************************************************

    def _cli_menu_header(self) -> str:
        """Create the command line interface header string."""
        if not self._profile_manager:
            steam_str = "'not set'"
        else:
            steam_str = self._profile_manager.steam_description(self.steam_account_id)

        if not self.player_profile:
            player_str = "'not set'"
        else:
            player_str = f"'{self.player_profile}'"

        if isinstance(self._cli_report_target, Path):
            report_to = f"File '{fsdecode(self._cli_report_target)}'."
        else:
            report_to = "Standard output/console"

        header = (
            f"Rocksmith song list generator main menu."
            f"\n"
            f"\n    Steam account id:    {steam_str}"
            f"\n    Rocksmith profile:   {player_str}"
            f"\n    Reporting to:        {report_to}"
            f"\n    Working directory:   {fsdecode(self._working_dir)}"
            f"\n"
            f"\nPlease choose from the following options:"
        )

        return header

    def _cli_select_steam_account(self) -> None:
        """Select a Steam account id from a command line menu."""
        # daft as it looks, this will trigger an interactive selection process
        self.steam_account_id = ""

    def _cli_select_profile(self) -> None:
        """Select a Rocksmith profile from a command line menu."""
        # ask the user to select a profile to load.
        if self._profile_manager is None:
            # can't select a player profile until the Steam user/profile manager have
            # been selected
            return

        # a valid player profile will automatically refresh player database as well.
        choice = utils.choose(
            options=self._profile_manager.profile_names(),
            header="Select player profile for song list creation.",
            no_action=(
                "No selection (warning - you can't create song lists without "
                "choosing a profile)."
            ),
        )

        if choice is None:
            self.player_profile = ""
        else:
            profile = choice[0]
            if not isinstance(profile, str):
                raise TypeError(
                    f"Unexpected type from profile choice. Should be string, "
                    f"got f{type(profile)}."
                )
            self.player_profile = profile

    def _cli_toggle_reporting(self) -> None:
        """Toggles reports between stdout and the working directory report file."""
        if isinstance(self._cli_report_target, Path):
            self._cli_report_target = sys.stdout
        else:
            self._cli_report_target = self._working_dir.joinpath(SONG_LIST_DEBUG_FILE)

    def _cli_single_filter_report(self) -> None:
        """Select and run a report on a single filter from a command line interface."""
        self._cli_song_list_action(ProfileKey.FAVORITES_LIST, self._cli_report_target)

    def _cli_song_list_report(self) -> None:
        """Select and run a song list report  from a command line interface."""
        self._cli_song_list_action(ProfileKey.SONG_LISTS, self._cli_report_target)

    def _cli_write_song_lists(self) -> None:
        """Select a song list set and write the resulting song lists to the profile.

        Song list selection is by command line interface, and the method will write the
        song lists to the currently selected Rocksmith profile.
        """
        self._cli_song_list_action(ProfileKey.SONG_LISTS, None)

    def _cli_write_favorites(self) -> None:
        """Select a filter and write the resulting favorites list to the profile.

        Song list selection is by command line interface, and the method will write the
        favorites lists to the currently selected Rocksmith profile.
        """
        self._cli_song_list_action(ProfileKey.FAVORITES_LIST, None)

    def _cli_song_list_action(
        self, list_target: ProfileKey, report_target: Optional[Union[Path, TextIO]]
    ) -> None:
        """Execute song list generation, report writing and save to profiles.

        Arguments:
            list_target {ProfileKey} -- must be either ProfileKey.SONG_LISTS or
                ProfileKey.FAVORITES_LIST (import from rsrtools.files.config).
                The target for the action.
            report_target {Optional[Union[Path, TextIO]]} -- The reporting target for
                the method, which can be None, a file path or a text stream.

        Raises:
            RSFilterError -- Raised if list_target is an invalid type.

        The behaviour of this routine depends on the argument values:
            - If list_target is SONG_LISTS, the the user is asked to choose a filter
              set to use for song list generation/reporting (up to six song lists).
            - If list_target is FAVORITES_LIST, the user is asked choose a single
              filter for favorites generation or filter testing/reporting.
            - If report_target is None, the song lists will be created and written
              to the instance Rocksmith profile.
            - If report_target is not None, the song lists will be created and written
              to the report target, and will not be written to the Rocksmith profile.

        """
        if not self.player_profile:
            # can't do anything with song lists without a player profile.
            return

        if list_target is ProfileKey.FAVORITES_LIST:
            # Running favorites or testing a filter, so need to select a single filter
            # from the dictionary of filters
            option_list = tuple(self._filter_dict.keys())
        elif list_target is ProfileKey.SONG_LISTS:
            # Running song lists, so need to select from available song list sets
            option_list = tuple(
                self._song_list_sets.keys()
            )
        else:
            raise RSFilterError(
                f"_cli_song_list_action called with invalid list target {list_target}."
            )

        # a valid player profile will automatically refresh player database as well.
        choice = utils.choose(
            options=option_list,
            header="Select filter or song list set.",
            no_action=(
                "No selection (warning - you can't create song lists without choosing "
                "a filter/song list set)."
            ),
        )

        if choice is None:
            return

        key = choice[0]
        if not isinstance(key, str):
            raise TypeError(
                f"Unexpected type from filter/song list set choice. Should be string, "
                f"got f{type(key)}."
            )

        if list_target is ProfileKey.FAVORITES_LIST:
            # Creating a favorites list or testing a single filter here.
            # Create a synthetic song list set for this case.
            # choice is the name of the filter we should use.
            song_list_set = [key]
        else:
            # Get the selected song list set from the song_list_sets dict. No need for
            # extended else clause, as we have checked previously for invalid
            # list_target
            song_list_set = self._song_list_sets[
                key
            ]

        confirmed = True
        if report_target is None:
            # File write only happens if report target is None.
            # However, because we want to be really sure about users intentions,
            # reconfirm write to file here.
            confirmed = utils.yes_no_dialog(
                f"Please confirm that you want to create song lists and write them "
                f"to profile '{self.player_profile}'"
            )

        if confirmed:
            self.create_song_lists(list_target, song_list_set, report_target)

    def _cli_full_scan(self) -> None:
        """Do a full scan of song data and rebuild the arrangements table."""
        mtime = self._arr_db.scan_arrangements(last_modified=None, show_progress=True)
        self._configuration.settings.dlc_mtime = mtime + DLC_MTIME_OFFSET

    def _cli_partial_scan(self) -> None:
        """Do a partial scan of song data and update the arrangements table."""
        mtime = self._configuration.settings.dlc_mtime
        mtime = self._arr_db.scan_arrangements(last_modified=mtime, show_progress=True)
        self._configuration.settings.dlc_mtime = mtime + DLC_MTIME_OFFSET

    def song_list_cli(self) -> None:
        """Provide a command line menu for the song list generator routines."""
        if not self._arr_db.has_arrangement_data:
            print("No arrangement data in database. Running full scan to load data.")
            self._cli_full_scan()
        elif newer_songs(self._configuration.settings.dlc_mtime):
            choice = utils.choose(
                options=[
                    ("Recommended: Run a full database refresh", self._cli_full_scan),
                    (
                        "Scan for new songs only (faster, may not find all changes).",
                        self._cli_partial_scan,
                    ),
                ],
                header="It looks as though you have some new DLC.",
            )
            if choice is not None:
                choice[0]()

        options = list()
        options.append(
            (
                "Change/select Steam account id. This also clears the profile "
                "selection.",
                self._cli_select_steam_account,
            )
        )
        options.append(
            ("Change/select Rocksmith player profile.", self._cli_select_profile)
        )
        options.append(("Toggle the report destination.", self._cli_toggle_reporting))
        options.append(
            (
                "Choose a single filter and create a song list report.",
                self._cli_single_filter_report,
            )
        )
        options.append(
            (
                "Choose a song list set and create a song list report.",
                self._cli_song_list_report,
            )
        )
        options.append(
            (
                "Choose a song list set and write the list(s) to Song Lists in the "
                "Rocksmith profile.",
                self._cli_write_song_lists,
            )
        )
        options.append(
            (
                "Choose a filter and write the resulting song list to Favorites in the "
                "Rocksmith profile.",
                self._cli_write_favorites,
            )
        )
        options.append(
            ("Utilities (database reports, profile management.)", self._cli_utilities)
        )

        help_text = (
            "Help:  "
            "\n    - The Steam account id owns the Rocksmith profile."
            "\n    - A Steam account id must be selected before a Rocksmith profile "
            "can be selected."
            "\n    - Song lists are saved to a Rocksmith profile. Player data is "
            "extracted from this"
            "\n      profile."
            "\n    - You can view/test/debug song lists by printing to the console or "
            "saving to a file."
            "\n      These reports contain more data about the tracks than the song "
            "lists actually saved"
            "\n      into the Rocksmith profile."
            "\n    - You can view/test song lists for a single filter or a complete "
            "song list set (the latter"
            "\n      can be very long - consider saving song list set reports to file)."
        )

        while True:
            header = self._cli_menu_header()
            choice = utils.choose(
                options=options,
                header=header,
                no_action="Exit program.",
                help_text=help_text,
            )

            if choice is None:
                break

            # otherwise execute the action
            action = choice[0]
            if not callable(action):
                raise TypeError(
                    f"Unexpected type from song list action choice. Should be "
                    f"callable, got f{type(action)}."
                )

            action()

        if utils.yes_no_dialog(
            "Save config file (overwrites current config even if nothing has changed)?"
        ):
            self.save_config()

    def create_song_lists(
        self,
        list_target: ProfileKey,
        song_list_set: List[str],
        debug_target: Optional[Union[Path, TextIO]] = None,
    ) -> None:
        """Create song lists and write them to a Steam Rocksmith profile.

        Arguments:
            list_target {ProfileKey} -- must be either ProfileKey.SONG_LISTS or
                ProfileKey.FAVORITES_LIST (import from rsrtools.files.config).
                The song list target for creating/writing.
            song_list_set {List[str]} -- The list of filter names that will be used to
                create the song lists. The list should contain up to six elements for
                Song Lists (an empty string entry will skip a song list), or one element
                for Favorites. Any excess elements will be ignored.

        Keyword Arguments:
            debug_target {Optional[Union[Path, TextIO]]} -- If set to None, the song
                lists will be written to the currently selected Steam account id and
                Rocksmith profile. Otherwise, a diagnostic report will be written to the
                file or stream specified by debug target.  (default: {None})

        Raises:
            RSFilterError -- Raised for an incomplete database or if the profile manager
                is undefined.

        Creates song lists for the filters in the set and writes the resulting song
        lists back to player profile.

        The song list creator will only create up to 6 song lists, and song lists for
        list entries with an empty string value will not be changed. Further,
        steam_account_id and player_profile must be set to valid values before
        executing.

        If debug target is not None, song lists are not saved to the instance profile.
        Instead:
            - If debug_target is a stream, extended song lists are written to the
              stream.
            - If debug_target is a file path, the file is opened and the extended
              song lists are written to this file.

        """
        # error condition really shouldn't happen if properties are working properly.
        if not self._arr_db.has_arrangement_data or not self._arr_db.has_player_data:
            raise RSFilterError(
                "Database requires both song arrangement data and player data to "
                "generate song lists."
                "\nOne or both data sets are missing"
            )

        if list_target is ProfileKey.SONG_LISTS:
            if len(song_list_set) > MAX_SONG_LIST_COUNT:
                use_set = song_list_set[0:MAX_SONG_LIST_COUNT]
            else:
                use_set = song_list_set[:]
        elif list_target is ProfileKey.FAVORITES_LIST:
            use_set = song_list_set[0:1]
        else:
            raise RSFilterError(
                f"Create song lists called with an invalid list target {list_target}."
            )

        if isinstance(debug_target, Path):
            # Using open rather than path.open() gives a TextIO type
            # (Path.open() has type IO[Any], which is not what we want).
            with open(debug_target, "wt", encoding='locale') as file_handle:
                song_lists = self._arr_db.generate_song_lists(
                    use_set, self._filter_dict, file_handle
                )

        else:
            song_lists = self._arr_db.generate_song_lists(
                use_set, self._filter_dict, debug_target
            )

        if debug_target is None and song_lists:
            # not debugging/reporting, so write song lists to profile, and move
            # updates to Steam.
            # Fail silently if song_lists is empty (nothing to do).
            if self._profile_manager is None:
                # shouldn't happen, but just in case
                raise RSFilterError(
                    "Attempt to write song lists to a player profile before Steam "
                    "user id/file set has been chosen (profile_manager is None)."
                )

            # Song list update
            # Note that an empty list will flush the existing song list!
            # If this is a problem for people, we can add a check for an empty list
            # at the same place we do a None check and skip.
            for idx, song_list in enumerate(song_lists):
                if song_list is not None:
                    # Index 0 for favorites will be cheerfully ignored.
                    self._profile_manager.replace_song_list(
                        self.player_profile, list_target, song_list, idx
                    )

            # Steam update
            self._profile_manager.write_files()
            self._profile_manager.move_updates_to_steam(self.steam_account_id)

    def _cli_utilities(self) -> None:
        """Provide command line utilities menu."""
        while True:
            choice = utils.choose(
                header="Utility menu",
                no_action="Return to main menu.",
                options=[
                    ("Database reports.", self._arr_db.run_cl_reports),
                    (
                        "Database string field names (for list type sub-filters).",
                        ListField.report_field_values,
                    ),
                    (
                        "Database numeric field names (for range type sub-filters).",
                        RangeField.report_field_values,
                    ),
                    (
                        "Clone profile. Copies source profile data into target "
                        "profile. Replaces all target profile data."
                        "\n      - Reloads Steam user/profile after cloning.",
                        self._cli_clone_profile,
                    ),
                    (
                        "Rescan all song data. The best way to add new songs to the "
                        "database.",
                        self._cli_full_scan,
                    ),
                    (
                        "Update database with new song data. Mostly robust, but may "
                        "sometimes miss songs"
                        "\n      - Do a full scan if this happens.",
                        self._cli_partial_scan,
                    ),
                    (
                        "Export profile to JSON (readable text format).",
                        self._export_json,
                    ),
                ],
            )

            if choice is None:
                break

            # otherwise execute the action
            action = choice[0]
            if not callable(action):
                raise TypeError(
                    f"Unexpected type from utilities choice. Should be "
                    f"callable, got f{type(action)}."
                )

            action()

    def _export_json(self) -> None:
        """Dump the active profile to JSON text file."""
        if self._profile_manager is not None:
            self._profile_manager.export_json_profile(
                self.player_profile,
                self._working_dir.joinpath(self.player_profile + ".json"),
            )

    def _cli_clone_profile(self) -> None:
        """Provide command line interface for cloning profiles."""
        # grab temp copy of profile so we can reload after cloning and write back.
        profile = self.player_profile

        # do the clone thing.
        if self._profile_manager is None:
            # shouldn't happen, but just in case
            raise RSFilterError(
                "Attempt to clone player profile before Steam user "
                "id/file set has been chosen (profile_manager is None)."
            )
        self._profile_manager.cl_clone_profile()

        # force a reload regardless of outcome.
        self.steam_account_id = self.steam_account_id
        # profile has been nuked, so reset with temp copy.
        self.player_profile = profile


def main() -> None:
    """Provide basic command line interface to song list creator."""
    parser = argparse.ArgumentParser(
        description="Command line interface for generating song list from config "
        "files. Provides minimal command line menus to support this activity."
    )
    parser.add_argument(
        "working_dir",
        help="Working directory for database, config files, working "
        "sub-directories amd working files.",
    )

    parser.add_argument(
        "--CFSMxml",
        help="Loads database with song arrangement data from CFSM xml file (replaces "
        "all existing data). Expects CFSM ArrangementsGrid.xml file structure. "
        "This is a deprecated function and will be removed in future.",
        metavar="CFSM_file_name",
    )

    args = parser.parse_args()

    creator = SongListCreator(Path(args.working_dir).resolve(True))

    if args.CFSMxml is not None:
        # String path by definition here.
        creator.cfsm_arrangement_file = args.CFSMxml
        creator.load_cfsm_arrangements()

    # run the command line interface.
    creator.song_list_cli()


if __name__ == "__main__":
    main()
