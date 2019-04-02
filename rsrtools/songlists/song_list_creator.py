#!/usr/bin/env python3

"""Provide SongListCreator, which is the main class of the rsrtools package."""

import argparse
import simplejson
import jsonschema  # type:ignore
import sys

from pathlib import Path
from os import fsdecode
from typing import Callable, cast, Optional, TextIO, Union

import rsrtools.songlists.sldefs as SLDEF
from rsrtools.songlists.arrangement_db import ArrangementDB, RSFilterError
from rsrtools.files.profilemanager import RSProfileManager, RSFileSetError
import rsrtools.utils as utils

SONG_LIST_CONFIG = "song_list_config.json"
SONG_LIST_DEBUG_FILE = "RS_Song_Lists.txt"
ARRANGEMENTS_GRID = "ArrangementsGrid.xml"


class SongListCreator:
    """Provide a command line interface for creating and writing Rocksmith song lists.

    Refer to the rsrtools package README documentation for more detail.

    The public members of this class also provide hooks that could be used to implement
    a GUI for creating song lists. The public members are:

        Contructor -- Sets up the song list creator working directory and files, and
            loads the configuration file.

        create_song_lists -- Creates song lists for the filters in a set and writes the
            resulting song lists back to the currently specified steam user id/player
            profile.

        load_cfsm_arrangements -- Loads arrangement data from the CFSM file defined in
            self.cfsm_arrangement_file into the arrangements database.

        save_config -- Saves the current song list generation configuration file.

        song_list_cli -- Runs the command line driven song list generator.

        cfsm_arrangement_file -- Read/write property. Path to a CFSM arrangement file
            that can be used for setting up the arrangement database.

        steam_user_id -- Read/write property. Steam user id (8 digit decimal number
            found under steam user data folder) to use for Rocksmith saves. Can be set
            as an int or a string representation of the int, always returns str.

        player_profile -- Read/write property. Rocksmith player profile name to use for
            song list generation.

    """

    # member annotations.
    # TODO: conversion to toml may allow replacement of _cfg_dict with sub-dicts?
    #   - Could still use json schema for validation of sub-dicts and a cleaner
    #     implementation than one massive validation.
    _cfg_dict: SLDEF.JSONConfig

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

    # A lot of the properties in the following shadowing config file parameters
    # Could have done a lot of this with setattr/getattr, but given
    # the small number of properties, I've stuck with explicit definitions.
    # This also has the benefit of allowing validation along the way.
    @property
    def _db_config(self) -> SLDEF.DBConfig:
        """Get dictionary of database configuration parameters.

        Gets:
            rsrtools.songlists.sltypes.DBConfig

        Creates empty dictionary if required.

        """
        return cast(
            SLDEF.DBConfig,
            self._cfg_dict.setdefault(SLDEF.DB_CONFIG, cast(SLDEF.DBConfig, dict())),
        )

    @property
    def _filter_set_dict(self) -> SLDEF.FilterSetDict:
        """Get dictionary of filter sets.

        Gets:
            rsrtools.songlists.sltypes.FilterSetDict

        Each filter set contains a list of filter names for generating song lists.

        Creates empty dictionary if required.
        """
        return cast(
            SLDEF.FilterSetDict,
            self._cfg_dict.setdefault(
                SLDEF.FILTER_SET_DICT, cast(SLDEF.FilterSetDict, dict())
            ),
        )

    @property
    def _filter_dict(self) -> SLDEF.FilterDict:
        """Get dictionary of filters.

        Gets:
            rsrtools.songlists.sltypes.FilterDict

        Each filter can be used to generate a song list or as a base filter for building
        other filters.

        Creates empty dictionary if required.
        """
        return cast(
            SLDEF.FilterDict,
            self._cfg_dict.setdefault(
                SLDEF.FILTER_DICT, cast(SLDEF.FilterDict, dict())
            ),
        )

    @property
    def cfsm_arrangement_file(self) -> str:
        """Get/set the string path to a CFSM arrangements file for database setup.

        Gets/sets:
            str -- The string form path the Customs Forge Song Manager arrangements
                file, or the empty string if it has not been set.

        The setter will raise an exception if the path does not point to a file, but
        but does not validate the file.

        """
        ret_val = self._db_config.setdefault(SLDEF.CFSM_FILE, "")

        if ret_val and not Path(ret_val).is_file():
            # silently discard invalid path.
            ret_val = ""
            self._db_config[SLDEF.CFSM_FILE] = ""

        return ret_val

    @cfsm_arrangement_file.setter
    def cfsm_arrangement_file(self, value: str) -> None:
        """Set path to CFSM arrangements file."""
        file_path = Path(value)
        if not file_path.is_file():
            self._db_config[SLDEF.CFSM_FILE] = ""
            raise FileNotFoundError(
                f"CFSM arrangement file '{value}' does not exist"
            )

        self._db_config[SLDEF.CFSM_FILE] = fsdecode(file_path.resolve())

    # ****************************************************
    # Steam user id, _profile_manager, player profile and player data in database are
    # tightly linked.
    # Initialisation uses these properties and exception handlers to manage auto-loading
    # from json.
    @property
    def steam_user_id(self) -> str:
        """Get/set the Steam user id to use for song list creation.

        Gets/sets:
            str -- String representation of Steam user id, or the empty string if it has
                not been set yet.

        The steam user id is an 8 digit number, which is the name of steam user data
        directory.

        Song list changes affect Rocksmith profiles in this Steam user's directories.
        Setting the steam user id to the empty string triggers an interactive command
        line process to choose a new steam user id and triggers the side effects below.

        Setting steam user id has the following side effects:
            - The instance flushes and reloads steam profile data.
            - The instance clears the player profile and flushes player data from the
              arrangement database (reset with self.player_profile)

        """
        # could do extensive validation here, but there is already error checking in the
        # profile manager, and any ui will need to find valid steam ids to load up.
        # So no error checking here.
        return self._db_config.setdefault(SLDEF.STEAM_USER_ID, "")

    @steam_user_id.setter
    def steam_user_id(self, value: str) -> None:
        """Steam user id setter."""
        # reset shadow value to None in case of errors (correct at end of routine)
        self._db_config[SLDEF.STEAM_USER_ID] = ""

        # Changing steam user id, so clear profile manager and player profile (and
        # implicitly, flush db as well)
        # Conservative assumption - flush  and everything, even if the assignment
        # doesn't change the original steam id
        self.player_profile = ""
        self._profile_manager = None

        # Create profile manager.
        # This will trigger an interactive file set selection if steam user id is None
        # (for command line use). I'm also disabling use of existing working set files
        # for the song list creator.
        # (Working set files are really only intended for debugging).
        self._profile_manager = RSProfileManager(
            self._working_dir,
            steam_user_id=value,
            auto_setup=True,
            flush_working_set=True,
        )

        str_value = value
        if not str_value:
            # Get the steam user id resulting from an interactive call to
            # RSProfileManager
            str_value = self._profile_manager.source_steam_uid

        self._db_config[SLDEF.STEAM_USER_ID] = str_value

    @property
    def player_profile(self) -> str:
        """Get/set the Rocksmith player profile name to use for song list generation.

        Gets/sets:
            str -- The player profile name. Get returns the empty string if the player
                profile it has not been set yet. Setting to the empty string clears the
                current profile data.

        Setting the player name also deletes all profile data from the database and
        loads the profile data for player_profile into the database. Setting to the
        empty string deletes all profile data without loading new data.

        A steam user id must be specified before setting the player profile.
        """
        # can't do any useful validation without loading profile, so similar to the
        # steam user id, push it down to the profile manager or up to the ui.
        return self._db_config.setdefault(SLDEF.PLAYER_PROFILE, "")

    @player_profile.setter
    def player_profile(self, value: str) -> None:
        """Set player profile name for song list creation."""
        # new player profile, so ditch everything in player database
        self._arr_db.flush_player_profile()
        # reset to default in case of error in setter
        self._db_config[SLDEF.PLAYER_PROFILE] = ""

        if value:
            if self._profile_manager is None:
                # shouldn't happen, but just in case
                raise RSFilterError(
                    f"Attempt to set player profile to {value} before steam user "
                    f"id/file set has been chosen (profile_manager is None)."
                )

            if value not in self._profile_manager.profile_names():
                raise RSFilterError(
                    f"Rocksmith player profile '{value}' does not exist in steam file "
                    f"set for user '{self.steam_user_id}'"
                )

            self._arr_db.load_player_profile(self._profile_manager, value)

            # set this last in case of errors along the way.
            self._db_config[SLDEF.PLAYER_PROFILE] = value

    # End player steam_user_id, player_profile properties block

    def load_cfsm_arrangements(self) -> None:
        """Load arrangement data from the CFSM file into the arrangement database.

        The CFSM file is defined in the property self.cfsm_arrangement_file.

        This method replaces existing data in the database.
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
        # Empty config dict, should be replaced in _load_config()
        self._cfg_dict = dict()
        self._profile_manager = None

        # Default to console for reporting.
        self._cli_report_target = sys.stdout

        if not working_dir.is_dir():
            raise NotADirectoryError(
                f"SongListCreator requires a valid working directory. Invalid argument "
                f"supplied:\n   {fsdecode(working_dir)}"
            )
        self._working_dir = working_dir.resolve()

        self._load_config()

        self._arr_db = ArrangementDB(self._working_dir)
        # The next block is a slightly clumsy way of avoiding separate auto load code
        # for setting up profile manager and player database from json parameters for
        # steam id and player profile name
        if not self.steam_user_id:
            # reset player profile and database (invalid with no steam id anyway).
            tmp_profile = ""
        else:
            # resetting steam id will trash player profile, so grab a temp copy
            tmp_profile = self.player_profile
            try:
                # this looks like a non-op, but triggers the side effect of loading the
                # profile manager for the steam user id.
                self.steam_user_id = self.steam_user_id
            except RSFileSetError:
                # invalid steam id, steam id will have been reset to None.
                # discard player profile as well (meaningless without steam id)
                tmp_profile = ""

        try:
            # this will load the database for the original self.player_profile if it
            # exists.
            self.player_profile = tmp_profile
        except RSFilterError:
            # player profile not found, player profile set to none, nothing more needed.
            pass
        # end auto load from json.

    def _load_config(self) -> None:
        """Load the configuration file from the working directory.

        Create a default configuration if no file is found.
        """
        self._cfg_path = self._working_dir.joinpath(SONG_LIST_CONFIG)
        try:
            with self._cfg_path.open("rt") as fp:
                self._cfg_dict = simplejson.load(fp)
        except FileNotFoundError:
            # no config found, load default
            from rsrtools.songlists.default_sl_config import DEFAULT_SL_CONFIG

            self._cfg_dict = simplejson.loads(DEFAULT_SL_CONFIG)

        # and finally try validating against the schema.
        jsonschema.validate(self._cfg_dict, SLDEF.CONFIG_SCHEMA)

    # end initialisation block

    def save_config(self) -> None:
        """Save configuration file to working directory.

        This method dumps the self._cf_dict JSON object to file.
        """
        with self._cfg_path.open("wt") as fp:
            simplejson.dump(self._cfg_dict, fp, indent=2 * " ")

    # # *******************************************************************

    def _cli_menu_header(self) -> str:
        """Create the command line interface header string."""
        if not self.steam_user_id:
            steam_str = "'not set'"
        else:
            steam_str = ""
            if self.steam_user_id == str(utils.steam_active_user()):
                steam_str = ", logged into steam now"

            steam_str = "".join(("'", self.steam_user_id, "'", steam_str))

        if not self.player_profile:
            player_str = "'not set'"
        else:
            player_str = "".join(("'", self.player_profile, "'"))

        if isinstance(self._cli_report_target, Path):
            report_to = f"File '{fsdecode(self._cli_report_target)}'."
        else:
            report_to = "Standard output/console"

        header = (
            f"Rocksmith song list generator main menu."
            f"\n"
            f"\n    Steam user id:       {steam_str}"
            f"\n    Rocksmith profile:   {player_str}"
            f"\n    Reporting to:        {report_to}"
            f"\n    Working directory:   {fsdecode(self._working_dir)}"
            f"\n"
            f"\nPlease choose from the following options:"
        )

        return header

    def _cli_select_steam_user(self) -> None:
        """Select a steam user id from a command line menu."""
        # daft as it looks, this will trigger an interactive selection process
        self.steam_user_id = ""

    def _cli_select_profile(self) -> None:
        """Select a Rocksmith profile from a command line menu."""
        # ask the user to select a profile to load.
        if self._profile_manager is None:
            # can't select a player profile until the steam user/profile manager have
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
            self.player_profile = cast(str, choice)

    def _cli_toggle_reporting(self) -> None:
        """Toggles reports between stdout and the working directory report file."""
        if isinstance(self._cli_report_target, Path):
            self._cli_report_target = sys.stdout
        else:
            self._cli_report_target = self._working_dir.joinpath(SONG_LIST_DEBUG_FILE)

    def _cli_single_filter_report(self) -> None:
        """Select and run a report on a single filter from a command line interface."""
        self._cli_song_list_action(self._filter_dict, self._cli_report_target)

    def _cli_filter_set_report(self) -> None:
        """Select and run a filter set report  from a command line interface."""
        self._cli_song_list_action(self._filter_set_dict, self._cli_report_target)

    def _cli_write_song_lists(self) -> None:
        """Select a filter set and write the resulting song lists to the profile.

        Song list selection is by command line interface, and the method will write the
        song lists to the currently selected Rocksmith profile.
        """
        self._cli_song_list_action(self._filter_set_dict, None)

    def _cli_song_list_action(
        self,
        source_dict: Union[SLDEF.FilterSetDict, SLDEF.FilterDict],
        report_target: Optional[Union[Path, TextIO]],
    ) -> None:
        """Execute song list generation, report writing and save to profiles.

        Arguments:
            source_dict {Union[SLDEF.FilterSetDict, SLDEF.FilterDict]} -- Either a list
                of filter names, or a dictionary of filter definitions.
            report_target {Optional[Union[Path, TextIO]]} -- The reporting target for
                the method, which can be None, a file path or a text stream.

        Raises:
            RSFilterError -- Raised if source_dict is an invalid type.

        The behaviour of this routine depends on the types of the calling arguments:
            - If source_dict is a dictionary of filter definitions (FilterDict):
                - If report_target is not None, raise an error.
                - If report target is stream of Path, ask the user to select a filter,
                  create the filter output and write to the stream/Path.
            - If source dict is dictionary of FilterSets (where each filter set is a
              list of up to six filter names):
                - Ask the user to select a filter set from the dictionary.
                - Create a song list for each filter in the filter set.
                - If report target is None, write the song lists to the currently
                  selected steam user id/profile.
                - If report target is a stream/file, write the song lists to this
                  destination.

        """
        if not self.player_profile:
            # can't do anything with song lists without a player profile.
            return

        # a valid player profile will automatically refresh player database as well.
        choice = utils.choose(
            options=tuple(source_dict.keys()),
            header="Select filter or filter set.",
            no_action=(
                "No selection (warning - you can't create song lists without choosing "
                "a filter/filter set)."
            ),
        )

        if choice is None:
            return

        choice = cast(str, choice)
        if isinstance(source_dict, SLDEF.FilterDict) and report_target is not None:
            # testing a single filter here. Create a synthetic filter set for this case.
            # could check report_target as well, but this should be handled within the
            # caller.
            filter_set: SLDEF.FilterSet = [choice]
        elif isinstance(source_dict, SLDEF.FilterSetDict):
            # working on filter sets
            filter_set = source_dict[choice]
        else:
            raise RSFilterError(
                f"cli_song_list_action called on unknown source "
                f"dictionary {source_dict}."
            )

        confirmed = False
        if report_target is None:
            # reconfirm write.
            confirmed = utils.yes_no_dialog(
                f"Please confirm that you want to create song lists and write them "
                f"to profile '{self.player_profile}'"
            )

        if confirmed:
            self.create_song_lists(filter_set, report_target)

    def song_list_cli(self) -> None:
        """Provide a command line menu for the song list generator routines."""
        if not self._arr_db.has_arrangement_data:
            # check for CFSM file for now.
            # In future, offer to scan song database.
            check_xml = self._working_dir.joinpath(ARRANGEMENTS_GRID)
            if check_xml.is_file():
                self.cfsm_arrangement_file = fsdecode(check_xml)
                self.load_cfsm_arrangements()
            else:
                raise RSFilterError(
                    "Database has no song arrangement data. Re-run with --CFSMxml or "
                    " song scan (if available) to load this data."
                )

        options = list()
        options.append(
            (
                "Change/select steam user id. This also clears the profile selection.",
                self._cli_select_steam_user,
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
                "Choose a filter set and create a song list report.",
                self._cli_filter_set_report,
            )
        )
        options.append(
            (
                "Choose a filter set and write the song list(s) to the Rocksmith "
                "profile.",
                self._cli_write_song_lists,
            )
        )
        options.append(
            ("Utilities (database reports, profile management.)", self._cli_utilities)
        )

        help_text = (
            "Help:  "
            "\n    - The steam user id owns the Rocksmith profile."
            "\n    - A steam user id must be selected before a Rocksmith profile can "
            "be selected."
            "\n    - Song lists are saved to Rocksmith profile. Player data is "
            "extracted from this"
            "\n      profile."
            "\n    - You can view/test/debug song lists by printing to the console or "
            "saving to a file."
            "\n      These reports contain more data about the tracks than the song "
            "lists actually saved"
            "\n      into the Rocksmith profile."
            "\n    - You can view/test song lists for a single filter or a complete "
            "filter set (the latter"
            "\n      can be very long - consider saving filter set reports to file)."
            "\n    - You can only save filter set song lists to Rocksmith."
        )

        while True:
            header = self._cli_menu_header()
            action = utils.choose(
                options=options,
                header=header,
                no_action="Exit program.",
                help_text=help_text,
            )

            if action is None:
                break

            # otherwise execute the action
            action = cast(Callable, action)
            action()

        if utils.yes_no_dialog(
            "Save config file (overwrites current config even if nothing has changed)?"
        ):
            self.save_config()

    def create_song_lists(
        self,
        filter_set: SLDEF.FilterSet,
        debug_target: Optional[Union[Path, TextIO]] = None,
    ) -> None:
        """Create song lists and write them to a Rocksmith profile.

        Arguments:
            filter_set {SLDEF.FilterSet} -- The set of of song lists to create and
                write.

        Keyword Arguments:
            debug_target {Optional[Union[Path, TextIO]]} -- If set to None, the song
                lists will be written to the current selected steam user id and
                Rocksmith profile. Otherwise, a diagnostic report will be written to the
                file or stream specified by debug target.  (default: {None})

        Raises:
            RSFilterError -- Raised for an incomplete database or if the profile manager
                is undefined.

        Creates song lists for the filters in the set and writes the resulting song
        lists back to player profile.

        The song list creator will only create up to 6 song lists, and song lists for
        list entries with an empty string value will not be changed. Further,
        steam_user_id and player_profile must be set to valid values before executing.

        If debug target is not None, filters are not saved to the instance profile.
        Instead:
            - If debug_target is a stream, extended song lists are writtend to the
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

        if isinstance(debug_target, Path):
            with debug_target.open("wt") as fp:
                song_lists = self._arr_db.generate_song_lists(
                    filter_set, self._filter_dict, cast(TextIO, fp)
                )

        else:
            song_lists = self._arr_db.generate_song_lists(
                filter_set, self._filter_dict, debug_target
            )

        if debug_target is None:
            if self._profile_manager is None:
                # shouldn't happen, but just in case
                raise RSFilterError(
                    "Attempt to write song lists to a player profile before steam "
                    "user id/file set has been chosen (profile_manager is None)."
                )

            for idx, song_list in enumerate(song_lists):
                if song_list is not None:
                    self._profile_manager.replace_song_list(
                        self.player_profile, idx, song_list
                    )

            self._profile_manager.write_files()
            self._profile_manager.move_updates_to_steam(self.steam_user_id)

    def _cli_utilities(self) -> None:
        """Provide command line utilities menu."""
        while True:
            action = utils.choose(
                header="Utility menu",
                no_action="Return to main menu.",
                options=[
                    ("Database reports.", self._arr_db.run_cl_reports),
                    (
                        "Clone profile. Copies source profile data into target "
                        "profile. Replaces all target profile data."
                        "\n      - Reloads steam user/profile after cloning.",
                        self._cli_clone_profile,
                    ),
                ],
            )

            if action is None:
                break

            action = cast(Callable, action)
            action()

    def _cli_clone_profile(self) -> None:
        """Provide command line interface for cloning profiles."""
        # grab temp copy of profile so we can reload after cloning and write back.
        profile = self.player_profile

        # do the clone thing.
        if self._profile_manager is None:
            # shouldn't happen, but just in case
            raise RSFilterError(
                "Attempt to clone player profile before steam user "
                "id/file set has been chosen (profile_manager is None)."
            )
        self._profile_manager.cl_clone_profile()

        # force a reload regardless of outcome.
        self.steam_user_id = self.steam_user_id
        # profile has been nuked, so reset with temp copy.
        self.player_profile = profile


if __name__ == "__main__":
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
        "all existing data). Expects CFSM ArrangementsGrid.xml file structure.",
        metavar="CFSM_file_name",
    )

    args = parser.parse_args()

    main = SongListCreator(Path(args.working_dir))

    if args.CFSMxml:
        # String path by definition here.
        main.cfsm_arrangement_file = args.CFSMxml
        main.load_cfsm_arrangements()

    # run the command line interface.
    main.song_list_cli()
