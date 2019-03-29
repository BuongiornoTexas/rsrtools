#!/usr/bin/env python3

"""Provide SongListCreator, which is the main class of the rsrtools package."""

import argparse
import simplejson
import jsonschema # type:ignore
import os
import sys

from arrangement_db import ArrangementDB, RSFilterError
from profile_manager import RSProfileManager, RSFileSetError
import utils

SONG_LIST_CONFIG = 'song_list_config.json'
SONG_LIST_DEBUG_FILE = 'RS_Song_Lists.txt'

# json schema for config file.
CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "db_config": {
            "type": "object",
            "description": "Dictionary of configuration parameters",
            "properties": {
                "CFSM_Arrangement_File": {"type": ["string", "null"]},
                "steam_user_id": {"type": ["string", "null"]},
                "player_profile": {"type": ["string", "null"]}
            }
        },
        "FilterSets": {
            "type": "object",
            "description": "Dictionary of filter sets.",
            "additionalProperties": {
                "type": "array",
                "description": "List of filters in set or null to skip song list.",
                "items": {"type": ["string", "null"]},
                "minItems": 1,
                "maxItems": 6
            }
        },
        "Filters": {
            "type": "object",
            "description": "Dictionary of filters.",
            "additionalProperties": {
                "type": "object",
                "description": "Dictionary for definition of a single filter",
                "properties": {
                    "BaseFilter": {"type": "string"},
                    "QueryFields": {
                        "type": "array",
                        "description": "List of query field dictionaries.",
                        "items": {
                            "type": "object",
                            "description": "Single query field dictionary.",
                            "minItems": 1,
                            "properties": {
                                "Field": {"type": "string"},
                                "Include": {"type": "boolean"},
                                "Values": {
                                    "type": "array",
                                    "description": "List of string values.",
                                    "items": {"type": "string"},
                                    "minItems": 1
                                },
                                "Ranges": {
                                    "type": "array",
                                    "description": "Array of pairs of low/high values.",
                                    "minItems": 1,
                                    "items": {
                                        "description": "Array of low high/values.",
                                        "type": "array",
                                        "items": {"type": "number", "minimum": 0},
                                        "minItems": 2,
                                        "maxItems": 2
                                    }
                                }
                            },
                            "required": ["Field", "Include"],
                            "oneOf": [
                                {"required": ["Values"]},
                                {"required": ["Ranges"]}
                            ]
                        }
                    }
                },
                "required": ["QueryFields"]
            }
        }
    },
    "required": ["Filters", "FilterSets"]
}


class SongListCreator:
    """The primary function of this class is to provide a command line menu interface for creating song lists and
    writing them back to Rocksmith profiles. Refer to the module documentation for more detail.

    The public members of this class also provide hooks that could be used to implement a GUI for creating song lists.
    The public members are:

    class:: SongListCreator(working_dir)
        Sets up the song list creator working directory and files, and loads the configuration file.

        property:: cfsm_arrangement_file
            Path to a CFSM arrangement file that can be used for setting up the arrangement database.

        property:: steam_user_id
            Steam user id (8 digit decimal number found under steam user data folder) to use for Rocksmith saves.

        property:: player_profile
            Rocksmith player profile name to use for song list generation.

        method:: create_song_lists(filter_set, debug_target=None)
            Creates song lists for the filters in the set and writes the resulting song lists back to the currently
            specified steam user id/player profile.

        method:: load_cfsm_arrangements()
            Loads arrangement data from the CFSM file defined in self.cfsm_arrangement_file into the arrangements
            database.

        method:: save_config()
            Saves the current song list generation configuration file.

        method:: song_list_cli()
            Runs the command line driven song list generator.

    """
    # A lot of the properties in the following shadowing config file parameters
    # Could have done a lot of this with setattr/getattr, but given
    # the small number of properties, I've stuck with explicit definitions.
    # This also has the benefit of allowing validation along the way.
    @property
    def _db_config(self) -> dict:
        """Dictionary of database configuration parameters."""
        return self._config.setdefault('db_config', dict())

    @property
    def _filter_sets(self) -> dict:
        """Dictionary of filter sets. Each filter set contains a list of filter names for generating song lists."""
        return self._config.setdefault('FilterSets', dict())

    @property
    def _filters(self) -> dict:
        """Dictionary of filters, where each filter can be used to generate a song list or as a based filter for other
        filters."""
        return self._config.setdefault('Filters', dict())

    @property
    def cfsm_arrangement_file(self):
        """Path to a CFSM arrangement file that can be used for setting up the arrangement database."""
        ret_val = self._db_config.setdefault('CFSM_Arrangement_File', None)

        if ret_val is not None and not os.path.isfile(ret_val):
            # silently discard invalid path.
            ret_val = None
            self._db_config['CFSM_Arrangement_File'] = None

        return ret_val

    @cfsm_arrangement_file.setter
    def cfsm_arrangement_file(self, value):
        if not os.path.isfile(value):
            raise FileNotFoundError('CFSM arrangement file "{0}" does not exist'.format(value))

        self._db_config['CFSM_Arrangement_File'] = os.path.abspath(value)

    # ****************************************************
    # Steam user id, _profile_manager, player profile and player data in database are tightly linked
    # Initialisation uses these properties and exception handlers to manage auto-loading from json.
    @property
    def steam_user_id(self):
        """Steam user id (8 digit decimal number found under steam user data folder) to use for Rocksmith saves.

        Setting steam user id has the following side effects:
            - Flushes and reloads steam profile data.
            - Clears the player profile and flushes player data from the database (reset with self.player_profile)

        Setting steam user id to None triggers an interactive command line process to choose a new steam user
        id and triggers the side effects above.
        """
        # could do extensive validation here, but there is already error checking in the profile manager,
        # and any ui will need to find valid steam ids to load up. So no error checking here.
        return self._db_config.setdefault('steam_user_id', None)

    @steam_user_id.setter
    def steam_user_id(self, value):
        # reset shadow value to None in case of errors (correct at end of routine)
        self._db_config['steam_user_id'] = None

        # Changing steam user id, so clear profile manager and player profile (and implicitly, flush db as well)
        # Conservative assumption - flush  and everything, even if the assignment doesn't change the original
        # steam id
        self.player_profile = None
        self._profile_manager = None

        if value is not None:
            value = str(value)

        # Create profile manager.
        # This will trigger an interactive file set selection if steam user id is None (for command line use).
        # I'm also disabling use of existing working set files for the song list creator
        # (Working set files are really only intended for debugging).
        self._profile_manager = RSProfileManager(self._working_dir,
                                                 steam_user_id=value,
                                                 auto_setup=True,
                                                 flush_working_set=True)

        if value is None:
            # Get the steam user id resulting from an interactive call to RSProfileManager
            value = self._profile_manager.source_steam_uid

        self._db_config['steam_user_id'] = value

    @property
    def player_profile(self):
        """Rocksmith player profile name to use for song list generation. Setting the player name also updates the
        player data in the database.

        A steam user id must be specified before setting the player profile.
        """
        # can't do any useful validation without loading profile, so similar to the steam user id, push it down to the
        # profile manager or up to the ui.
        return self._db_config.setdefault('player_profile', None)

    @player_profile.setter
    def player_profile(self, value):
        # new player profile, so ditch everything in player database
        self._arr_db.flush_player_profile()
        # reset to default in case of error in setter
        self._db_config['player_profile'] = None

        if value is not None:
            value = str(value)
            if value not in self._profile_manager.profile_names():
                raise RSFilterError('Rocksmith player profile \'{0}\'does not exist in steam file set for '
                                    'user \'{1}\''.format(value, self.steam_user_id))

            self._arr_db.load_player_profile(self._profile_manager, value)

            # set this last in case of errors along the way.
            self._db_config['player_profile'] = value
    # End player steam_user_id, player_profile properties block

    def load_cfsm_arrangements(self):
        """Loads arrangement data from the CFSM file defined in self.cfsm_arrangement_file into the arrangements
        database (this replaces existing data in the database)."""
        if self.cfsm_arrangement_file is not None:
            self._arr_db.load_cfsm_arrangements(self.cfsm_arrangement_file)

    # start initialisation block
    def __init__(self, working_dir):
        """Initialises the filter manager, creates working files and sub-folders in the working directory, and loads
        the configuration file (if any) from the working folder."""

        self._config_file = None
        self._config: dict = None
        self._profile_manager: RSProfileManager = None

        # variable only used in the CLI implementation.
        self._cli_report_target = None

        if not os.path.isdir(working_dir):
            raise NotADirectoryError('SongListCreator requires a valid working directory. Invalid argument supplied:'
                                     '\n   {0}'.format(working_dir))
        self._working_dir = os.path.abspath(working_dir)

        self._load_config()

        self._arr_db = ArrangementDB(self._working_dir)
        # next block is a slightly clumsy way of avoiding separate auto load code for setting up profile manager
        # and player database from json parameters for steam id and player profile name
        if self.steam_user_id is None:
            # reset player profile and database (invalid with no steam id anyway).
            tmp_profile = None
        else:
            # resetting steam id will trash player profile, so grab a temp copy
            tmp_profile = self.player_profile
            try:
                # this looks like a non-op, but triggers the side effect of loading the profile
                # manager for the steam user id.
                self.steam_user_id = self.steam_user_id
            except RSFileSetError:
                # invalid steam id, steam id will have been reset to None.
                # discard player profile as well (meaningless without steam id)
                tmp_profile = None

        try:
            # this will load the database for the original self.player_profile if it exists.
            self.player_profile = tmp_profile
        except RSFilterError:
            # player profile not found, player profile set to none, nothing more needed.
            pass
        # end auto load from json.

    def _load_config(self):
        """Loads the configuration file from the working directory, or creates a default configuration if no file
        found."""
        self._config_file = os.path.join(self._working_dir, SONG_LIST_CONFIG)
        try:
            with open(self._config_file, 'rt') as fp:
                self._config = simplejson.load(fp)
        except FileNotFoundError:
            # no config found, load default
            from default_sl_config import DEFAULT_SL_CONFIG
            self._config = simplejson.loads(DEFAULT_SL_CONFIG)

        # and finally try validating against the schema.
        jsonschema.validate(self._config, CONFIG_SCHEMA)
    # end initialisation block

    def save_config(self):
        """Dumps filter configuration and database setup parameters to  the json configuration file."""
        with open(self._config_file, 'wt') as fp:
            simplejson.dump(self._config, fp, indent=2 * ' ')

    # # *******************************************************************

    def _cli_menu_header(self):
        """Creates the command line interface header string."""
        if self.steam_user_id is None:
            steam_str = '\'not set\''
        else:
            steam_str = ''
            if self.steam_user_id == str(utils.steam_active_user()):
                steam_str = ', logged into steam now'

            steam_str = ''.join(('\'', self.steam_user_id, '\'', steam_str))

        if self.player_profile is None:
            player_str = '\'not set\''
        else:
            player_str = ''.join(('\'', self.player_profile, '\''))

        if self._cli_report_target is sys.stdout:
            report_to = 'Standard output/console'
        else:
            report_to = f'File \'{self._cli_report_target}\' in working directory'

        header = f'''Rocksmith song list generator main menu.
 
    Steam user id:       {steam_str} 
    Rocksmith profile:   {player_str}
    Reporting to:        {report_to}
    Working directory:   {self._working_dir}
        
Please choose from the following options:'''
        return header

    def _cli_select_steam_user(self):
        # daft as it looks, this will trigger an interactive selection process
        self.steam_user_id = None

    def _cli_select_profile(self):
        # ask the user to select a profile to load.
        if self._profile_manager is None:
            # can't select a player profile until the steam user/profile manager have been selected
            return

        # a valid player profile will automatically refresh player database as well.
        self.player_profile = utils.choose(
            options=self._profile_manager.profile_names(),
            header='Select player profile for song list creation.',
            no_action='No selection (warning - you can\'t create song lists without choosing a profile).')

    def _cli_toggle_reporting(self):
        if self._cli_report_target is sys.stdout:
            self._cli_report_target = SONG_LIST_DEBUG_FILE
        else:
            self._cli_report_target = sys.stdout

    def _cli_single_filter_report(self):
        self._cli_song_list_action(self._filters, self._cli_report_target)

    def _cli_filter_set_report(self):
        self._cli_song_list_action(self._filter_sets, self._cli_report_target)

    def _cli_write_song_lists(self):
        self._cli_song_list_action(self._filter_sets, None)

    def _cli_song_list_action(self, source_dict, report_target):
        """Runs the song list generator and writes reports if requested."""
        if self.player_profile is None:
            # can't do anything with song lists without a player profile.
            return

        # a valid player profile will automatically refresh player database as well.
        choice = utils.choose(
            options=source_dict.keys(),
            header='Select filter or filter set.',
            no_action='No selection (warning - you can\'t create song lists without choosing a filter/filter set).')

        if choice is None:
            return

        if source_dict is self._filters and report_target is not None:
            # testing a single filter here. Create a synthetic filter set for this case.
            # could check report_target as well, but this should be handled within the caller.
            filter_set = [choice]
        elif source_dict is self._filter_sets:
            # working on filter sets
            filter_set = source_dict[choice]
        else:
            raise RSFilterError(f'cli_song_list_action called on unknown source dictionary {source_dict}.')

        confirmed = True
        if report_target is None:
            # reconfirm write.
            if not utils.yes_no_dialog('Please confirm that you want to create song lists and write them '
                                       f'to profile \'{self.player_profile}\''):
                confirmed = False

        if confirmed:
            self.create_song_lists(filter_set, report_target)

    def song_list_cli(self):
        """Provides a simple menu driven command line interface to the song list generator routines."""
        if not self._arr_db.has_arrangement_data:
            # check for CFSM file for now.
            # In future, offer to scan song database.
            check_xml = os.path.join(self._working_dir, 'ArrangementsGrid.xml')
            if os.path.isfile(check_xml):
                self.cfsm_arrangement_file = check_xml
                self.load_cfsm_arrangements()
            else:
                raise RSFilterError('Database has no song arrangement data. Re-run with --CFSMxml or '
                                    ' song scan (if available) to load this data.')

        self._cli_report_target = sys.stdout

        options = list()
        options.append(('Change/select steam user id. This also clears the profile selection.',
                        self._cli_select_steam_user))
        options.append(('Change/select Rocksmith player profile.',
                        self._cli_select_profile))
        options.append(('Toggle the report destination.', self._cli_toggle_reporting))
        options.append(('Choose a single filter and create a song list report.', self._cli_single_filter_report))
        options.append(('Choose a filter set and create a song list report.', self._cli_filter_set_report))
        options.append(('Choose a filter set and write the song list(s) to the Rocksmith profile.',
                        self._cli_write_song_lists))
        options.append(('Utilities (database reports, profile management.)', self._cli_utilities))

        help_text = '''    Help:  
        - The steam user id owns the Rocksmith profile.
        - A steam user id must be selected before a Rocksmith profile can be selected. 
        - Song lists are saved to Rocksmith profile. Player data is extracted from this profile.
        - You can view/test/debug song lists by printing to the console or saving to a file. These reports contain
          more data about the tracks than the song lists actually saved into the Rocksmith profile.
        - You can view/test song lists for a single filter or a complete filter set (the latter can be very long - 
          consider saving filter set reports to file).
        - You can only save filter set song lists to Rocksmith.'''

        while True:
            header = self._cli_menu_header()
            action = utils.choose(options=options, header=header, no_action='Exit program.', help_text=help_text)

            if action is None:
                break
            # execute the action
            action()

        if utils.yes_no_dialog('Save config file (overwrites current config even if nothing has changed)?'):
            self.save_config()

    def create_song_lists(self, filter_set, debug_target=None):
        """Creates song lists for the filters in the set and writes the resulting song lists back to player profile.

        The song list creator will only create up to 6 song lists, and song lists for list entries with a value of None
        will not be changed. Further, steam_user_id and player_profile must be set to valid values before executing.

        If debug target is not None, filters are not saved.
            - If debug_target is sys.stdout, they are printed to sys.stdout.
            - If debug_target is a file path, they are saved to the file path.
        """

        # error condition really shouldn't happen if properties are working properly.
        if not self._arr_db.has_arrangement_data or not self._arr_db.has_player_data:
            raise RSFilterError('Database requires both song arrangement data and player data to generate song lists.'
                                '\nOne or both data sets are missing')

        if debug_target is SONG_LIST_DEBUG_FILE:
            fp = None
            try:
                fp = open(os.path.join(self._working_dir, SONG_LIST_DEBUG_FILE), 'wt')
                song_lists = self._arr_db.generate_song_lists(filter_set, self._filters, fp)
            finally:
                fp.close()
        else:
            song_lists = self._arr_db.generate_song_lists(filter_set, self._filters, debug_target)

        if debug_target is None:
            for idx, song_list in enumerate(song_lists):
                if song_list is not None:
                    self._profile_manager.replace_song_list(self.player_profile, idx, song_list)

            self._profile_manager.write_files()
            self._profile_manager.move_updates_to_steam(self.steam_user_id)

    def _cli_utilities(self):
        """Command line utilities menu."""
        while True:
            action = utils.choose(header='Utility menu', no_action='Return to main menu.',
                                  options=[
                                      ('Database reports.', self._arr_db.run_cl_reports),
                                      ('Clone profile. Copies source profile data into target profile. Replaces '
                                       'all target profile data.\n      - Reloads steam user/profile after cloning.',
                                       self._cli_clone_profile)
                                  ])

            if action is None:
                break

            action()

    def _cli_clone_profile(self):
        """Command line interface for cloning profile and reloading player profile data."""

        # grab temp copy of profile so we can reload after cloning and write back.
        profile = self.player_profile

        # do the clone thing.
        self._profile_manager.cl_clone_profile()

        # force a reload regardless of outcome.
        self.steam_user_id = self.steam_user_id
        # profile has been nuked, so reset with temp copy.
        self.player_profile = profile


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Command line interface for generating song list from config files. '
                                     'Provides minimal command line menus to support this activity.')
    parser.add_argument('working_dir', help='Working directory for database, config files, working '
                        'sub-directories amd working files.')

    parser.add_argument('--CFSMxml', help='Loads database with song arrangement data from CFSM xml file (replaces all '
                                          'existing data). Expects CFSM ArrangementsGrid.xml file structure.',
                        metavar='CFSM_file_name')

    args = parser.parse_args()

    main = SongListCreator(args.working_dir)

    if args.CFSMxml:
        main.cfsm_arrangement_file = args.CFSMxml
        main.load_cfsm_arrangements()

    # run the command line interface.
    main.song_list_cli()
