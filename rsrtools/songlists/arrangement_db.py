#!/usr/bin/env python3
"""Provide methods and classes for creating and querying a Rocksmith song arrangement
database. The primary function of the module is to provide the song list generator used
by the SongListCreator class.

The core public class provided by this module is ArrangementDB, which uses
SongListSQLGenerator as a helper class.

TODO: fix/check this. For command line options (database setup, reporting), run 
    'python arrangement_db.py -h'.
"""

import sqlite3
import argparse

import xml.etree.ElementTree as eTree

from enum import Enum
from pathlib import Path
from typing import Optional, TextIO

import rsrtools.songlists.song_list_config as config
from rsrtools.utils import choose
from rsrtools.files.fileconfig import MAX_SONG_LIST_COUNT
from rsrtools.files.profilemanager import RSProfileManager

DB_NAME = "RS_Arrangements.sqlite"
# CFSM_MAP translates Customs Forge column arrangement titles to database fields.
# CFSM map is ugly, but allows for easy remapping in the future if needed
# See cfsm function for use and for manual processing of album, year
CFSM_MAP = {
    "RSSongId": "colDLCKey",
    "ArrangementId": "colPersistentID",
    "ArrangementName": "colArrangementName",
    "Artist": "colArtist",
    "Title": "colTitle",
    "Tempo": "colSongAverageTempo",
    "Tuning": "colTuning",
    "Pitch": "colTuningPitch",
    "NoteCount": "colNoteCount",
}

# Useful block on Rocksmith player profile json structure.
# Key data in profiles for setting up song lists:
# json_tree['Stats']['Songs'][SongArrangementId]
#     ['PlayedCount'] - on the box Decimal 6
#     ['MasteryPeak'] - Fractional Mastery (0-1) Decimal 6
#     ['SAWinCount'] - I can't work out what this is. Not captured.
#     ['SAPlayCount'] - As of mid-18, these appear to sum to the displayed SA count for
#           the track
#         [0]['V'] - Easy play count
#         [1]['V'] - Medium play count
#         [2]['V'] - Hard play count
#         [3]['V'] - Master play count
#     ['SAPlatinumPointAwarded'] - Flag for platinum badges
#     ['SAGeneralPointAwarded'] - Flag for songs passed
#         - PointAwarded are hex char '0' to 'F' used for gathering stats
#             1 = easy song pass/easy plat
#             2 = medium/medium
#             3 = hard/hard
#             4 = master/master
#         Way better to use actual badge data for this one. More info, less bit shifting.
#
#     json_tree['SongsSA'][SongArrangementId]
#         ['Badges']['Easy'] to ['Master'] - more useful than stat point awarded flags
#             Decimal 6
#             0 no badge
#             1 strike out
#             2 bronze
#             3 silver
#             4 Gold
#             5 Platinum
#         ['PlayCount'] - I can't work out what this is. Not captured.
# End player profile json structure.
# PLAYER_PROFILE_MAP is a dict for translating profile data to database fields.
# Each entry has the database field as a key, and item which is a tuple containing:
#   - A sub-tuple which provides the json path to the data value
#       - a value of ':a_id' will be dynamically substituted with an arrangement id.
#   - A default value if the json key/item does not exist.
#   - a type conversion function.
PLAYER_PROFILE_MAP = {
    "PlayedCount": (("Stats", "Songs", ":a_id", "PlayedCount"), 0, int),
    "MasteryPeak": (("Stats", "Songs", ":a_id", "MasteryPeak"), 0.0, float),
    "SAEasyCount": (("Stats", "Songs", ":a_id", "SAPlayCount", 0, "V"), 0, int),
    "SAMediumCount": (("Stats", "Songs", ":a_id", "SAPlayCount", 1, "V"), 0, int),
    "SAHardCount": (("Stats", "Songs", ":a_id", "SAPlayCount", 2, "V"), 0, int),
    "SAMasterCount": (("Stats", "Songs", ":a_id", "SAPlayCount", 3, "V"), 0, int),
    "SAEasyBadges": (("SongsSA", ":a_id", "Badges", "Easy"), 0, int),
    "SAMediumBadges": (("SongsSA", ":a_id", "Badges", "Medium"), 0, int),
    "SAHardBadges": (("SongsSA", ":a_id", "Badges", "Hard"), 0, int),
    "SAMasterBadges": (("SongsSA", ":a_id", "Badges", "Master"), 0, int),
}

# base table name for all filter queries.
FILTER_TABLE_BASE = "__TempTable"


class FieldTypes(Enum):
    """Provide list of database field names that can be used as filters."""

    # list types. Automatically validated before use.
    TUNING = "Tuning"
    ARRANGEMENT_NAME = "ArrangementName"
    ARRANGEMENT_ID = "ArrangementId"
    ARTIST = "Artist"
    TITLE = "Title"
    ALBUM = "Album"

    # numerical types. Range filters can be applied to these.
    PITCH = "Pitch"
    TEMPO = "Tempo"
    NOTE_COUNT = "NoteCount"
    YEAR = "Year"
    PLAYED_COUNT = "PlayedCount"
    MASTERY_PEAK = "MasteryPeak"
    SA_EASY_COUNT = "SAEasyCount"
    SA_MEDIUM_COUNT = "SAMediumCount"
    SA_HARD_COUNT = "SAHardCount"
    SA_MASTER_COUNT = "SAMasterCount"
    SA_PLAYED_COUNT = "SAPlayedCount"
    SA_EASY_BADGES = "SAEasyBadges"
    SA_MEDIUM_BADGES = "SAMediumBadges"
    SA_HARD_BADGES = "SAHardBadges"
    SA_MASTER_BADGES = "SAMasterBadges"


# bucket of field types that will be processed as string list filters.
LIST_FILTERS = (
    FieldTypes.TUNING,
    FieldTypes.ARRANGEMENT_NAME,
    FieldTypes.ARRANGEMENT_ID,
    FieldTypes.TITLE,
    FieldTypes.ARTIST,
    FieldTypes.ALBUM,
)

# bucket of field types that will be processed as positive range filters.
POSITIVE_RANGE_FILTERS = (
    FieldTypes.PITCH,
    FieldTypes.TEMPO,
    FieldTypes.NOTE_COUNT,
    FieldTypes.YEAR,
    FieldTypes.PLAYED_COUNT,
    FieldTypes.MASTERY_PEAK,
    FieldTypes.SA_EASY_COUNT,
    FieldTypes.SA_MEDIUM_COUNT,
    FieldTypes.SA_HARD_COUNT,
    FieldTypes.SA_MASTER_COUNT,
    FieldTypes.SA_PLAYED_COUNT,
    FieldTypes.SA_EASY_BADGES,
    FieldTypes.SA_MEDIUM_BADGES,
    FieldTypes.SA_HARD_BADGES,
    FieldTypes.SA_MASTER_BADGES,
)


class RSFilterError(Exception):
    def __init__(self, message: str = None) -> None:
        """Base exception for song list filtering/SQL classes."""
        if message is None:
            message = "An unspecified Rocksmith Filter Error has occurred."
        super().__init__(message)


class SongListSQLGenerator:
    """Single use class for generating song list sql. This is a helper class for ArrangementDB.

    The class creates two sets of sql queries for song list generation, both of which are public attributes:
        attribute:: tmp_table_sql
            Provides the sql for the temporary tables.
        attribute:: song_list_sql
            Provides the sql for the song lists.

    Both of these fields are lists, where each element is a tuple consisting of:
        - The SQL query text.
        - The where values to be substituted into the SQL query ((?) form).
    """

    _next_table_index: int
    _filter_names: config.FilterSet

    def _next_table_name(self) -> str:
        """Return the next temporary table name.
        
        Returns:
            str -- SQL temporary table name
        """
        table_name = "".join((FILTER_TABLE_BASE, str(self._next_table_index)))
        self._next_table_index = self._next_table_index + 1
        return table_name

    def _table_setup(self, filter_name: str, where_clause, where_values):
        """Construct an SQL query for creating a song list filter temporary table.
        
        Arguments:
            filter_name {str} -- [description]
            where_clause {str} -- [description]
            where_values {[type]} -- [description]
        
        based on where_clause, where_values and the base filter for
        filter_name.
        """

        new_table = self._next_table_name()
        self._table_map[filter_name] = new_table
        base_table = self._table_map[self._base_filter(filter_name)]

        # set up the start of the SQL query for the table
        self.tmp_table_sql.append((f"DROP TABLE IF EXISTS {new_table};", ()))
        query = f"CREATE TEMP TABLE {new_table} AS SELECT * FROM {base_table}"
        query = "".join((query, "\n", where_clause, ";"))
        self.tmp_table_sql.append((query, where_values))

    def __init__(self, filter_set: config.FilterSet, filter_definition, list_validators):
        """Generates song list sql queries for the filter set based on the filter definitions and list list_validators.

        :param filter_set: List of filter names for sql query generation.
        :param filter_definitions: Dictionary of filter definitions. Refer song_list_creator for structure of items.
        :param list_validators: Dictionary of list_validators for list based fields. Refer ArrangementDB for structure.

        After initialisation, the sql queries are provided in fields tmp_table_sql and song_list_sql. Refer to the
        class documentation for more details.
        """
        self.filter_definitions = filter_definitions
        self.list_validators = list_validators
        if len(filter_set) > MAX_SONG_LIST_COUNT:
            # Rocksmith supports up to 6 song lists. Discard any beyond this.
            self._filter_names = filter_set[0: MAX_SONG_LIST_COUNT - 1]
        else:
            self._filter_names = filter_set[:]

        self.tmp_table_sql = list()
        self.song_list_sql = list()
        self._table_map = dict()
        self._next_table_index = 1

        # set up for the root table for all filters
        self._root_table = self._next_table_name()
        # map name to itself. Might be a problem if someone cleverly names their base table to match the root table.
        self._table_map[self._root_table] = self._root_table
        # note that we exclude vocals here
        self.tmp_table_sql.append((f"DROP TABLE IF EXISTS {self._root_table};", ()))

        query = (
            f"CREATE TEMP TABLE {self._root_table} AS SELECT * "
            f"\n    FROM Arrangements LEFT JOIN PlayerProfile ON "
            f"\n    Arrangements.ArrangementId == PlayerProfile.ArrangementId"
            f'\n    WHERE ArrangementName != "Vocals";'
        )

        self.tmp_table_sql.append((query, ()))

        # create the rest of the tables
        self._generate_table_sql()
        self._generate_song_list_sql()

    def _base_filter(self, filter_name):
        """Returns the name of the base filter for filter_name, or if it is not defined, the root table for song list
        queries.
        """
        return self.filter_definitions[filter_name].get("BaseFilter", self._root_table)

    def _generate_table_sql(self):
        """Creates the sql queries for all temporary tables required by the filter set."""
        pending_tables = list()

        for filter_name in self._filter_names:
            if not filter_name:
                # nothing needed for empty filter set.
                continue

            if filter_name not in self.filter_definitions:
                raise KeyError(f"No definition for filter {filter_name}.")

            # only generating sql for temp tables, not for target song lists.
            this_filter = self._base_filter(filter_name)
            while True:
                if this_filter not in self._table_map:
                    if this_filter not in self.filter_definitions:
                        raise KeyError(f"No definition for filter {this_filter}.")

                    # table needs to be defined for this filter.
                    # but, before we can do this, need to the same check on the base filter
                    base_filter = self._base_filter(this_filter)
                    if base_filter not in self._table_map:
                        # need to create table for base filter before we can create table for this filter.
                        # do a quick check on circular filters and then push this filter onto the queue for later
                        if this_filter in pending_tables:
                            raise RSFilterError(
                                f"Filter {this_filter} is recursive - it appears in as a parent filter to itself."
                                f" Recursive filter list follows.\n   {pending_tables}"
                            )
                        pending_tables.append(this_filter)
                        # go down the base_filter rabbit hole
                        this_filter = base_filter
                        continue

                    # base table for filter is defined, so create where clause
                    where_clause, where_values = self._where_clause(this_filter)
                    # and then create the the table.
                    self._table_setup(this_filter, where_clause, where_values)

                if pending_tables:
                    # pop out the next table in the sequence.
                    this_filter = pending_tables.pop()
                else:
                    # nothing pending, break out.
                    break

    def _generate_song_list_sql(self):
        """Creates the sql for the song lists in the filter set."""
        # temporary tables have already been created and consistency tests run previously,
        # so the code for the song list sql is a lot cleaner than that for table generation.
        for filter_name in self._filter_names:
            if not filter_name:
                # empty song list
                self.song_list_sql.append((None, None))
            else:
                base_table = self._table_map[self._base_filter(filter_name)]
                where_clause, where_values = self._where_clause(filter_name)

                query = (
                    f"SELECT "
                    f"\n    RSSongId, ArrangementId, ArrangementName, Artist,"
                    f"\n    Title, Album, Year, Tuning, Pitch, PlayedCount"
                    f"\n    FROM {base_table}"
                )

                query = "".join((query, "\n", where_clause, ";"))
                self.song_list_sql.append((query, where_values))

    def _where_clause(self, filter_name):
        """Returns the sql WHERE clause for filter_name."""
        where_text = list()
        where_values = list()

        if "QueryFields" not in self.filter_definitions[filter_name]:
            raise KeyError(f"Missing QueryFields in filter {filter_name}")

        for idx, field_dict in enumerate(
            self.filter_definitions[filter_name]["QueryFields"]
        ):
            # do a whack of validation here to provide help debugging json. Would have been better
            # to learn how to use the json schema validator, but I found it a bit late.
            field_type = field_dict.get("Field", None)
            if field_type is None:
                raise KeyError(
                    f"Missing Field type definition in QueryFields[{idx}] for "
                    f"filter {filter_name}."
                )
            try:
                field_type = FieldTypes[field_type]
            except KeyError:
                raise AttributeError(
                    f"Invalid field type {field_type} in QueryFields[{idx}] of "
                    f"filter {filter_name}."
                )

            include = field_dict.get("Include", None)
            if include is None:
                raise KeyError(
                    f"Missing Include field definition in QueryFields[{idx}] for "
                    f"filter {filter_name}."
                )
            if not isinstance(include, bool):
                raise KeyError(
                    f"Include field definition in QueryFields[{idx}] of filter "
                    f"{filter_name} is not a valid boolean."
                )

            if field_type in self.list_validators:
                values = field_dict.get("Values", None)
                if values is None or not values:
                    raise KeyError(
                        f"Missing or empty Values field definition in "
                        f"QueryFields[{idx}] for filter {filter_name}."
                    )
                sql_text = self._list_clause(field_type, include, values)
                sql_values = values

            elif field_type in POSITIVE_RANGE_FILTERS:
                values = field_dict.get("Ranges", None)
                if values is None or not values:
                    raise KeyError(
                        f"Missing or empty Ranges field definition in "
                        f"QueryFields[{idx}] for filter {filter_name}."
                    )
                sql_text, sql_values = self._positive_range_clause(
                    field_type, include, values
                )

            else:
                raise RSFilterError(
                    f"Clause generator not implemented for field type {field_type.name}"
                )

            where_text.append(sql_text)
            where_values.extend(sql_values)

        # this is clumsy, but allows dumping of SQL for debugging.
        joiner = "".join(("\n", " " * 8, "AND "))
        where_text = joiner.join(where_text)
        where_text = "".join((" " * 4, "WHERE", "\n", " " * 8, where_text))

        return where_text, tuple(where_values)

    def _list_clause(self, field_type, include, values):
        """Creates list clause and validates data against the validator list."""
        val_list = self.list_validators[field_type]
        for value in values:
            if value not in val_list:
                raise RSFilterError(
                    f"Invalid value ({value}) for field type {field_type.value}"
                )

        if include:
            not_text = ""
        else:
            not_text = "NOT "

        if len(values) > 1:
            q_marks = "?, " * (len(values) - 1)
        else:
            q_marks = ""

        sql_text = f"{field_type.value} {not_text}IN ({q_marks}?)"

        return sql_text

    @staticmethod
    def _positive_range_clause(field_type, include, values):
        """Creates positive range clause and performs very limited validation of values."""
        ret_values = list()
        text_list = list()

        if include:
            not_text = ""
        else:
            not_text = "NOT "

        for value_pair in values:
            if len(value_pair) != 2:
                raise IndexError(
                    f"Range field type {field_type} expected high/low pair, got "
                    f"{value_pair}."
                )

            if not isinstance(value_pair[0], (int, float)) or not isinstance(
                value_pair[1], (int, float)
            ):
                raise RSFilterError(
                    f"Range field type {field_type} expects numeric pairs of values to "
                    f"define range. Got {value_pair}."
                )

            # silent tidy.
            if value_pair[1] > value_pair[0]:
                high_val = value_pair[1]
                low_val = value_pair[0]
            else:
                high_val = value_pair[0]
                low_val = value_pair[1]
            if low_val < 0:
                low_val = 0

            # and finally the SQL
            text_list.append(
                f"{field_type.value} {not_text}BETWEEN ? AND ?"
            )
            ret_values.append(low_val)
            ret_values.append(high_val)

        if include:
            joiner = "".join(("\n", " " * 12, "OR "))
        else:
            joiner = "".join(("\n", " " * 12, "AND "))

        sql_text = joiner.join(text_list)
        sql_text = "".join(("(", sql_text, ")"))

        return sql_text, tuple(ret_values)


class ArrangementDB:
    """Class for creating, updating and querying SQLite database of Rocksmith song arrangements.

    The public members of ArrangementDB are:

    class:: ArrangementDB(db_path)
        db_path: String path to directory that contains the database. The database will be created if it doesn't exist.

        method:: generate_song_lists(filter_set, filter_definitions, debug_target=None)
            Generates up to 6 song lists based on the first six filters named in filter_set (list of strings).
            The song lists are returned as a list of (list of strings). The filter definitions are as described
            in module song_list_creator.

        method:: cl_update_player_data(working_dir)
            Runs a command line menu for the user to update player profile data in the database from a steam user
            profile. working_dir is the path to the folder that will be used for working copies of steam files (and
            can be the same as db_path).

        method:: run_cl_reports()
            Provides command line menu to a set of utility reports on the database.

        method:: load_cfsm_arrangements(cfsm_xml_file)
            Replaces all song specific arrangement data with data read from the cfsm_xml_file (string path to file).

        method:: load_player_profile(profile_manager, profile_name)
            Replaces all player specific arrangement data with data read from the named profile in the profile_manager
            (an RSProfileManager instance).

        method:: open_db()
            Utility method for opening the database.

        property:: has_arrangement_data
            Read only bool, True if the database contains song specific arrangement data (title, tuning, artist, etc).

        property:: has_player_data
            Read only bool, True if the database contains player profile data (play count, badge performance, etc.)

        method:: flush_player_profile()
            Deletes the player profile table and re-creates an empty player profile table.

        method:: list_validators()
            Returns a dictionary of all of the unique list field values in the database (e.g. unique tunings, artists,
            album names).
    """

    # Type declarations
    _db_file_path: Path

    def __init__(self, db_path: Path = None) -> None:
        """Initialise instance path to database.
        
        Keyword Arguments:
            db_path {Path} -- Path to directory containing SQLite3 database file.
                (default: {None})
        """
        if db_path is None:
            self._db_file_path = Path(DB_NAME)
        else:
            self._db_file_path = db_path.joinpath(DB_NAME)

        self._db_file_path = self._db_file_path.resolve()

    def open_db(self):
        """Utility for opening/connecting to database."""
        return sqlite3.connect(self._db_file_path)

    def _refresh_arrangements(self):
        """Deletes song specific arrangements table and creates a new one."""
        conn = self.open_db()
        conn.executescript(
            "DROP TABLE IF EXISTS Arrangements;"
            "\nCREATE TABLE Arrangements"
            "\n    (ArrangementId text PRIMARY KEY, RSSongId text, "
            "\n    ArrangementName text, Artist text, Title text, "
            "\n    Album text, Year integer, Tempo integer, Tuning text, Pitch real, "
            "\n    NoteCount integer);"
        )
        conn.commit()
        conn.close()

    def _table_has_data(self, name):
        """Returns boolean indicating if the named table is empty, or has one or more records."""
        if name not in ("Arrangements", "PlayerProfile"):
            raise ValueError(f"Invalid table name {name}")

        conn = self.open_db()
        ret_val = True
        try:
            count = conn.execute(f"select count(*) from {name}").fetchone()
        except sqlite3.OperationalError:
            ret_val = False
        else:
            if count[0] == 0:
                ret_val = False

        conn.close()
        return ret_val

    @property
    def has_arrangement_data(self):
        """True if the Arrangements table has one or more records."""
        return self._table_has_data("Arrangements")

    @property
    def has_player_data(self):
        """True if the player profile table has one or more records."""
        return self._table_has_data("PlayerProfile")

    @staticmethod
    def _fill_arrangements(conn, value_dict):
        """Writes song data from value dictionary into a row in song arrangements.

        Will skip the row if ArrangementId is None."""
        if value_dict["ArrangementId"] is not None:
            # may need to modify this test in the future? Let calling routine decide if row should be recorded or not?
            conn.execute(
                "INSERT INTO Arrangements"
                "\n    (ArrangementId, RSSongId, ArrangementName, Artist, Title, "
                "\n    Album, Year, Tempo, Tuning, Pitch, NoteCount)"
                "\n    VALUES"
                "\n    (:ArrangementId,:RSSongId,:ArrangementName,:Artist,:Title, "
                "\n    :Album, :Year, :Tempo, :Tuning, :Pitch, :NoteCount);",
                value_dict,
            )

    def load_cfsm_arrangements(self, cfsm_xml_file: Path) -> None:
        """Reads CFSM arrangement file into arrangements table. 
        
        Arguments:
            cfsm_xml_file {pathlib.Path} -- Path to the CFSM ArrangmentsGrid.xml file.
        
        Replaces any existing table.
        """
        self._refresh_arrangements()
        # create file object from path to keep mypy happy
        # (etree seems to grok pathlikes, but annotations don't reflect this)
        with cfsm_xml_file.open("rt") as fp:
            tree = eTree.parse(fp)

        root = tree.getroot()

        conn = self.open_db()
        sql_values = dict()
        for data_row in root:
            for sql_key, cfsm_tag in CFSM_MAP.items():
                try:
                    sql_values[sql_key] = data_row.find(cfsm_tag).text
                except AttributeError:
                    # some fields don't exist for e.g. Vocal arrangements.
                    # set as empty
                    sql_values[sql_key] = None

            # and the ugly manual handles
            try:
                _, _, sql_values["Album"], year = data_row.find(
                    "colArtistTitleAlbumDate"
                ).text.split(";")
                sql_values["Year"] = year[:4]
            except AttributeError:
                sql_values["Album"] = None
                sql_values["Year"] = None

            self._fill_arrangements(conn, sql_values)

        conn.commit()
        conn.close()

    def flush_player_profile(self):
        """Deletes Player Profile table and creates a new one."""
        conn = self.open_db()
        conn.executescript(
            "DROP TABLE IF EXISTS PlayerProfile;"
            "\nCREATE TABLE PlayerProfile"
            "\n    (ArrangementId text PRIMARY KEY, PlayedCount integer, "
            "\n    MasteryPeak real, SAPlayedCount integer, SAEasyCount integer, "
            "\n    SAMediumCount integer, SAHardCount integer, SAMasterCount integer, "
            "\n    SAEasyBadges integer, SAMediumBadges integer, SAHardBadges integer, "
            "\n    SAMasterBadges integer);"
        )
        conn.commit()
        conn.close()

    def load_player_profile(self, profile_manager, profile_name: str):
        """Loads data from profile name into player profile table.  Replaces any existing table."""

        self.flush_player_profile()

        conn = self.open_db()

        for a_id in profile_manager.player_arrangement_ids(profile_name):
            value_dict = dict()
            value_dict["ArrangementId"] = a_id

            for key, item in PLAYER_PROFILE_MAP.items():
                json_path = list(item[0])

                for i in range(
                    len(json_path)
                ):  # pylint: disable=consider-using-enumerate
                    if json_path[i] == ":a_id":
                        json_path[i] = a_id

                try:
                    value = profile_manager.copy_player_json_value(
                        profile_name, json_path
                    )
                    # type conversion
                    value = item[2](value)
                except (KeyError, IndexError):
                    # not found, return default
                    value = item[1]

                value_dict[key] = value

            # manual fixes
            sa_played = 0
            for sa_key in (
                "SAEasyCount",
                "SAMediumCount",
                "SAHardCount",
                "SAMasterCount",
            ):
                sa_played = sa_played + value_dict[sa_key]

            value_dict["SAPlayedCount"] = sa_played

            value_dict["MasteryPeak"] = 100 * value_dict["MasteryPeak"]

            # Database update
            conn.execute(
                "INSERT INTO PlayerProfile"
                "\n    (ArrangementId, PlayedCount, MasteryPeak, SAPlayedCount,"
                "\n    SAEasyCount, SAMediumCount, SAHardCount, SAMasterCount,"
                "\n    SAEasyBadges, SAMediumBadges, SAHardBadges, SAMasterBadges)"
                "\n    VALUES"
                "\n    (:ArrangementId, :PlayedCount, :MasteryPeak, :SAPlayedCount,"
                "\n    :SAEasyCount, :SAMediumCount, :SAHardCount, :SAMasterCount,"
                "\n    :SAEasyBadges, :SAMediumBadges, :SAHardBadges,"
                "\n    :SAMasterBadges);",
                value_dict,
            )

        conn.commit()
        conn.close()

    def _no_player_data_report(self):
        """Quick and dirty report on song data that doesn't appear in the player profile. Most likely to occur if an
        arrangement hasn't been played yet."""

        conn = self.open_db()

        # Automatically exclude vocal data. There should never be any player data for vocals anyway.
        query = (
            "SELECT ArrangementId, ArrangementName, Artist, Title, Album "
            "\n    FROM Arrangements"
            "\n    WHERE NOT EXISTS"
            "\n    (SELECT ArrangementId FROM PlayerProfile"
            "\n        WHERE Arrangements.ArrangementId == PlayerProfile.ArrangementId)"
            '\n     AND (Arrangements.ArrangementName != "Vocals")'
        )

        for row in conn.execute(query):
            print(row)

        conn.close()

    def _missing_song_data_report(self):
        """Quick and dirty report on song arrangement ids that appear in player profile but don't exist in song list."""

        print(
            "WARNING. This is report is NOT useful in its current form (still under "
            "development)."
            "\n"
            "\nThis report summarises arrangements that appear in the player profile, "
            "but do not have any corresponding song"
            "\narrangement data (title, artist, album, tuning, etc.). Possible causes "
            "for this are:"
            "\n    - The arrangements are lesson/practice tracks without song "
            "names/details."
            "\n    - DLC/Custom DLC has been removed from the library (and hence the "
            "song data is no longer present, while the player"
            "\n      history for the song arrangement is retained)."
            "\nAs noted, this report is still under development. I do not recommend "
            "using output of this report."
        )

        input("Enter anything to run report ->")

        conn = self.open_db()

        query = (
            "SELECT * FROM PlayerProfile"
            "\n    WHERE NOT EXISTS"
            "\n    (SELECT ArrangementId FROM Arrangements"
            "\n     WHERE Arrangements.ArrangementId == PlayerProfile.ArrangementId);"
        )

        for row in conn.execute(query):
            print(row)

        conn.close()

    def list_validators(self, validator_report: FieldTypes = None):
        """Creates dictionary of list list_validators for use in creating song lists/UI drop down lists.

        If validator report is specified, prints a summary report on that validator to stdout."""
        if validator_report is None:
            validators = LIST_FILTERS
        else:
            validators = (validator_report,)

        ret_dict = dict()

        conn = self.open_db()

        for f_type in validators:
            # Note that I assume we will never be interested in records relating to Vocals.
            query = (
                f"SELECT {f_type.value}, COUNT(*)"
                f"\n    FROM Arrangements"
                f'\n    WHERE ArrangementName != "Vocals"'
                f"\n    GROUP BY {f_type.value}"
            )

            result = conn.execute(query).fetchall()
            v_list = [i[0] for i in result]
            ret_dict[f_type] = v_list

            if validator_report is not None:
                print()
                print("  " + str(len(result)) + " unique records for " + f_type.value)
                print("    Unique item: Count")
                for i in result:
                    print(f"    {i[0]}: {i[1]}")

        conn.close()

        return ret_dict

    def generate_song_lists(
        self,
        filter_set: config.FilterSet,
        filter_definitions,
        debug_target: Optional[TextIO] = None,
    ):
        """Creates a list of up to six song lists from the filters named in filter set and the filter definitions.

        :param list filter_set: List of filter names that will be used to generate song lists.
        :param dict filter_definitions: Definitions of filters. Filters may be constructed hierarchically.
        :param io.IO[str] debug_target: Stream target for debug output.
        :rtype: list of (list of str): Up to six lists of the song keys required by Rocksmith."""

        song_lists = list()

        list_validators = self.list_validators()
        sql_queries = SongListSQLGenerator(
            filter_set, filter_definitions, list_validators
        )

        conn = self.open_db()
        for query, values in sql_queries.tmp_table_sql:
            # create the temporary tables needed for the queries.
            conn.execute(query, values)

        for idx, (query, values) in enumerate(sql_queries.song_list_sql):
            if query is None:
                # empty song list
                song_lists.append(None)
            else:
                # Run the queries for each song list, report out as needed.
                results = conn.execute(query, values).fetchall()

                # use a set comprehension to eliminate duplicate song ids thrown up by
                # the query.
                songs = {record[0] for record in results}
                song_lists.append(list(songs))

                if debug_target is not None:
                    print("-" * 80, file=debug_target)
                    print(file=debug_target)
                    print(
                        f"{len(results)} records for {filter_set[idx]}",
                        file=debug_target,
                    )
                    print(file=debug_target)
                    for line in results:
                        print(line, file=debug_target)
                    print("-" * 80, file=debug_target)
        conn.close()

        return song_lists

    def run_cl_reports(self):
        """Command line utility for interactively selecting and running reports on data in arr_db."""
        if not self.has_player_data or not self.has_arrangement_data:
            raise RSFilterError(
                "Cannot run reports, as database is missing player data and/or song arrangement data."
            )

        options = [
            ("Tunings.           Report unique tuning names.", FieldTypes.TUNING),
            (
                "Arrangement Types. Report unique arrangement types.",
                FieldTypes.ARRANGEMENT_NAME,
            ),
            ("Artists.           Report unique artist names.", FieldTypes.ARTIST),
            ("Albums.            Report unique album names.", FieldTypes.ALBUM),
            ("Titles.            Report unique song titles.", FieldTypes.TITLE),
            (
                "No player data. Diagnostic. Reports on song arrangements that have no data in the player profile.",
                1,
            ),
            ("Missing song data. Do not use. Under development.", 2),
        ]

        while True:
            choice = choose(
                options=options,
                header="Choose report to run",
                no_action="Exit reports.",
            )

            if choice is None:
                return

            if choice == 1:
                self._no_player_data_report()
            elif choice == 2:
                self._missing_song_data_report()
            elif choice in FieldTypes:
                self.list_validators(choice)

    def cl_update_player_data(self, working_dir):
        """Command line/interactive update of player data."""
        # calling profile manager without arguments will result in CLI calls to select steam user id
        # copying of file set in working directory, and loading of working set.
        p_manager = RSProfileManager(working_dir)
        profile_name = p_manager.cl_choose_profile(
            header_text="Choose profile to load into database.",
            no_action_text="Do not change database.",
        )

        if profile_name:
            self.load_player_profile(p_manager, profile_name)


def main() -> None:
    """Provide a basic command line interface to arrangements database."""
    parser = argparse.ArgumentParser(
        description="Command line interface to the arrangements database."
    )

    parser.add_argument(
        "db_directory", help="Working directory containing the database."
    )

    parser.add_argument(
        "--CFSMxml",
        help="Loads arrangements from CFSM xml file (replaces all existing data).",
        metavar="Filename",
    )
    parser.add_argument(
        "--update-player-data",
        help="Provides a command line menu interface for updating the "
        "player profile data in the arrangements database (creates working directories/files if "
        "needed).",
        action="store_true",
    )
    parser.add_argument(
        "--reports",
        help="Runs the interactive diagnostic report generator. Updates to database "
        "are performed before running reports.",
        action="store_true",
    )

    args = parser.parse_args()

    db = ArrangementDB(args.db_directory)

    if args.CFSMxml:
        db.load_cfsm_arrangements(Path(args.CFSMxml))

    if args.update_player_data:
        db.cl_update_player_data(args.db_directory)

    if args.reports:
        db.run_cl_reports()

if __name__ == "__main__":
    main()
