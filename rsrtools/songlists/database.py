#!/usr/bin/env python3

"""Provide methods and classes for creating and querying a song arrangement database.

The primary function of the module is to provide the song list generator used
by the SongListCreator class.

The core public class provided by this module is ArrangementDB, which uses
SongListSQLGenerator as a helper class.

For command line options (database setup, reporting), run
    'python rsrtools.songlists.database.py -h'.
"""

import sqlite3
import argparse

import xml.etree.ElementTree as eTree

from pathlib import Path

# I'd prefer to import OrderedDict from typing, but this isn't quite working as at 3.7.3
from collections import OrderedDict
from typing import (
    cast,
    Callable,
    Dict,
    List,
    MutableMapping,
    Optional,
    TextIO,
    Tuple,
    Union,
)

from rsrtools.songlists.config import ListField, RangeField, SQLField
from rsrtools.songlists.configclasses import Filter, RSFilterError, SQLClause
from rsrtools.utils import choose
from rsrtools.files.config import MAX_SONG_LIST_COUNT
from rsrtools.files.profilemanager import RSProfileManager, JSON_path_type

# type aliases
ListValidator = Dict[ListField, List[str]]
# This gets around problem with declaring OrderedDicts in 3.7.3. This will hopefully be
# sorted in the next release.
SQLTableDict = MutableMapping[SQLField, str]

# database file name
DB_NAME = "RS_Arrangements.sqlite"
# base table name for all filter queries.
TEMP_TABLE_BASE = "RSRTempTable"

# We use these two field constants an awful lot, so define module level shortener here.
ARRANGEMENT_NAME = ListField.ARRANGEMENT_NAME
ARRANGEMENT_ID = ListField.ARRANGEMENT_ID

# Arrangements and player profile table names, field definitions
ARRANGEMENTS_TABLE = "Arrangements"
ARRANGEMENT_FIELDS: SQLTableDict = OrderedDict(
    [
        (ListField.ARRANGEMENT_ID, "text"),
        (ListField.SONG_KEY, "text"),
        (ListField.ARRANGEMENT_NAME, "text"),
        (ListField.ARTIST, "text"),
        (ListField.TITLE, "text"),
        (ListField.ALBUM, "text"),
        (RangeField.YEAR, "integer"),
        (RangeField.TEMPO, "integer"),
        (ListField.TUNING, "text"),
        (RangeField.PITCH, "real"),
        (RangeField.NOTE_COUNT, "integer"),
    ]
)

PROFILE_TABLE = "PlayerProfile"
PROFILE_FIELDS: SQLTableDict = OrderedDict(
    [
        (ListField.ARRANGEMENT_ID, "text"),
        (RangeField.PLAYED_COUNT, "integer"),
        (RangeField.MASTERY_PEAK, "real"),
        (RangeField.SA_PLAYED_COUNT, "integer"),
        (RangeField.SA_EASY_COUNT, "integer"),
        (RangeField.SA_MEDIUM_COUNT, "integer"),
        (RangeField.SA_HARD_COUNT, "integer"),
        (RangeField.SA_MASTER_COUNT, "integer"),
        (RangeField.SA_EASY_BADGES, "integer"),
        (RangeField.SA_MEDIUM_BADGES, "integer"),
        (RangeField.SA_HARD_BADGES, "integer"),
        (RangeField.SA_MASTER_BADGES, "integer"),
    ]
)

SONG_LIST_FIELDS: SQLTableDict = OrderedDict(
    [
        (ListField.SONG_KEY, ""),
        (ListField.ARRANGEMENT_ID, ""),
        (ListField.ARRANGEMENT_NAME, ""),
        (ListField.ARTIST, ""),
        (ListField.TITLE, ""),
        (ListField.ALBUM, ""),
        (RangeField.YEAR, ""),
        (ListField.TUNING, ""),
        (RangeField.PITCH, ""),
        (RangeField.PLAYED_COUNT, ""),
    ]
)

NO_PLAYER_FIELDS: SQLTableDict = OrderedDict(
    [
        (ListField.ARRANGEMENT_ID, ""),
        (ListField.ARRANGEMENT_NAME, ""),
        (ListField.ARTIST, ""),
        (ListField.TITLE, ""),
        (ListField.ALBUM, ""),
    ]
)

# CFSM_MAP translates Customs Forge column arrangement titles to database fields.
# CFSM map is ugly, but allows for easy remapping in the future if needed
# See cfsm function for use and for manual processing of album, year
CFSM_MAP = {
    ListField.SONG_KEY: "colDLCKey",
    ListField.ARRANGEMENT_ID: "colPersistentID",
    ListField.ARRANGEMENT_NAME: "colArrangementName",
    ListField.ARTIST: "colArtist",
    ListField.TITLE: "colTitle",
    RangeField.TEMPO: "colSongAverageTempo",
    ListField.TUNING: "colTuning",
    RangeField.PITCH: "colTuningPitch",
    RangeField.NOTE_COUNT: "colNoteCount",
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
#         Way better to use actual badge data for this one. More info, less bit
#         shifting.
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
#        - Note that this must be a tuple, as we want to reuse with multiple
#          substitutions
#   - A default value if the json key/item does not exist.
#   - a type conversion function.
PLAYER_PROFILE_MAP: Dict[
    SQLField, Tuple[JSON_path_type, Union[int, float], Callable]
] = {
    RangeField.PLAYED_COUNT: (("Stats", "Songs", ":a_id", "PlayedCount"), 0, int),
    RangeField.MASTERY_PEAK: (("Stats", "Songs", ":a_id", "MasteryPeak"), 0.0, float),
    RangeField.SA_EASY_COUNT: (
        ("Stats", "Songs", ":a_id", "SAPlayCount", 0, "V"),
        0,
        int,
    ),
    RangeField.SA_MEDIUM_COUNT: (
        ("Stats", "Songs", ":a_id", "SAPlayCount", 1, "V"),
        0,
        int,
    ),
    RangeField.SA_HARD_COUNT: (
        ("Stats", "Songs", ":a_id", "SAPlayCount", 2, "V"),
        0,
        int,
    ),
    RangeField.SA_MASTER_COUNT: (
        ("Stats", "Songs", ":a_id", "SAPlayCount", 3, "V"),
        0,
        int,
    ),
    RangeField.SA_EASY_BADGES: (("SongsSA", ":a_id", "Badges", "Easy"), 0, int),
    RangeField.SA_MEDIUM_BADGES: (("SongsSA", ":a_id", "Badges", "Medium"), 0, int),
    RangeField.SA_HARD_BADGES: (("SongsSA", ":a_id", "Badges", "Hard"), 0, int),
    RangeField.SA_MASTER_BADGES: (("SongsSA", ":a_id", "Badges", "Master"), 0, int),
}


class SQLTable:
    """Provide a limited SQL table creator/filler and field list generator.

    Public members:
        Constructor.
        field_list -- Return a partial SQL expression containing a list of all fields
            in the table.
        rebuild_table -- Runs an SQL script to drop the current table and recreate a new
            empty version of the table.
        write_row -- Write a row of data to the table.
        table_name -- Read only, the table name.

    """

    # dictionary of field types and SQL types for those fields.
    _fields_dict: SQLTableDict
    # table name  and primary key only needed for table functionality
    _table_name: str
    _primary: Optional[SQLField]
    _new_table_script: str
    _write_row_script: str

    def __init__(
        self,
        fields_dict: SQLTableDict,
        table_name: str = "",
        primary: Optional[SQLField] = None,
    ) -> None:
        """Provide SQL table constructor.

        Arguments:
            fields {OrderedDict[SQLField, str]} -- An ordered dictionary of SQL fields
                and the SQL types of these fields. The dictionary values (SQL types) can
                be empty strings if the instance is only being used for field list
                generation. While the specific order of the keys is not important,
                repeatability of iteration is important for row writing, so we
                explicitly require an ordered dictionary.
            table_name {str} -- The SQL table name. Not required for field
                list generation. (default: {""})
            primary {Optional[SQLField]} -- The SQL primary key field. Not required for
                field list generation. (default: {None})

        """
        self._fields_dict = fields_dict
        self._table_name = table_name
        self._primary = primary
        self._new_table_script = ""
        self._write_row_script = ""

    @property
    def table_name(self) -> str:
        """Return the string table name, or an exception if not defined."""
        if not (self._table_name):
            raise RSFilterError("Table name is not defined (maybe only a field list?).")

        return self._table_name

    def field_list(self, prefix: str = "", new_table: bool = False) -> str:
        """Generate a SQL string list of the field names, with one field per line.

        Keyword Arguments:
            prefix {str} -- Optional prefix on each line, which can be used for
                indenting/pretty printing. (default: {""})
            new_table {bool}: If true will generate the field list with type information
                and primary key (primarily a utility for rebuild_table).
        """
        if new_table and self._primary is None:
            raise RSFilterError(
                f"Can't generate a new table field list without a primary key."
                f"\nTable named '{self._table_name}'' has no primary key."
            )

        sql_text = ""
        for field, type_str in self._fields_dict.items():
            primary = ""
            type_text = ""
            if new_table:
                type_text = f" {type_str}"
                if field is self._primary:
                    primary = " PRIMARY KEY"

            if sql_text:
                # appending a field
                separator = ",\n"
            else:
                # first field
                separator = ""

            sql_text = f"{sql_text}{separator}{prefix}{field.value}{type_text}{primary}"

        return f"{sql_text}\n"

    def rebuild_table(self, conn: sqlite3.Connection) -> None:
        """Flush and rebuild table. Drops the table and creates a new, empty table.

        Arguments:
            conn {sqlite3.Connection} -- Connection to database for table.
        """
        if not self._new_table_script:
            # generate the script
            script = self.field_list(prefix="  ", new_table=True)

            # Raise an error if table name doesn't exist.
            script = (
                f"DROP TABLE IF EXISTS {self.table_name};"
                f"\nCREATE TABLE {self.table_name} ("
                f"\n{script}"
                f");"
            )
            # cache in case of re-use.
            self._new_table_script = script

        conn.executescript(self._new_table_script)
        conn.commit()
        conn.close()

    def write_row(
        self,
        conn: sqlite3.Connection,
        values: Dict[str, Optional[Union[float, int, str]]],
    ) -> None:
        """Write a dictionary of values into a a row in the database.

        Arguments:
            conn {sqlite3.Connection} -- Connection to database for table.
            values {Dict[str, Optional[Union[float, int, str]]]} -- The dictionary
                of values to be written.

                The keys of the dictionary *must* be the string values of the SQLField
                Enum used to define the SQLTable (i.e. the SQLFields defined in the
                fields_dict argument to __init__), and there must be a key/value pair
                for *every* field the SQLTable. For example, if a table was defined with
                the fields ListField.ARTIST, RangeField.PITCH and Listfield.TUNING, then
                the values dictionary should be of the form:

                    {ListField.ARTIST.value: "David Bowie",
                     RangeField.PITCH.value: 440,
                     ListField.TUNING.value: "E Standard"}

                The method will raise an exception if the primary key does not exist or
                if the values dictionary does not contain value for the primary key.

        As this routine should be called repeatedly, the caller is responsible for
        commit and close.
        """
        if not self._write_row_script:
            if self._primary is None:
                raise RSFilterError(
                    f"\nTable named '{self._table_name}'' has no primary key."
                )

            try:
                values[self._primary.value]
            except KeyError:
                raise RSFilterError(
                    f"There is no key/value for primary key {self._primary} in "
                    f"table named '{self._table_name}'."
                )

            # create and cache the script.
            field_list = self.field_list(prefix="  ")
            target_list = self.field_list(prefix="    :")

            # Property will raise exception if table name doesn't exist.
            self._write_row_script = (
                f"INSERT INTO {self.table_name} ("
                f"\n{field_list}"
                f")"
                f"\n  VALUES ("
                f"\n{target_list}"
                f"  );"
            )

        conn.execute(self._write_row_script, values)


class SongListSQLGenerator:
    """Single use class for generating sql for a song list set.

    This is a helper class for ArrangementDB, and effectively implements the methods for
    a song_list_set returned from:
        rsrtools.songlists.configclasses.song_list_set[value]

    The class creates two sets of sql queries for song list generation, both of which
    are public attributes:
        tmp_table_sql -- Provides the sql for the temporary tables.
        song_list_sql -- Provides the sql for the song lists in the song list set.

    Both of these attributes are lists, where each element is a tuple consisting of:
        - The SQL query text {Optional[str]}.
        - A sub-tuple of where values to be substituted into the SQL query ((?) form)
          {Optional[Tuple[Union[str, int, float]]]}.
        - An empty song list is represented by the tuple (None, None).

    Both attributes are mutable, but are only intended for use in a read-only mode by
    ArrangementDB.

    """

    song_list_sql: List[SQLClause]
    tmp_table_sql: List[SQLClause]
    _list_validator: ListValidator
    _next_table_index: int
    _song_list_set: List[str]
    _filter_definitions: Dict[str, Filter]
    # table_map maps filter names to table names
    _table_map: Dict[str, str]
    _root_table: str

    def __init__(
        self,
        song_list_set: List[str],
        filter_definitions: Dict[str, Filter],
        list_validator: ListValidator,
        arrangements_name: str,
        profile_name: str,
    ) -> None:
        """Generate song list sql queries for a song list set and filter definitions.

        Arguments:
            song_list_set {List[str]} -- A list of filter names that will be used
                for song list definition. That is, each song list corresponds to a
                filter name in this list, and SQL will be generated for each of these
                names.
            filter_definitions {Dict[str, Filter]} -- A dictionary of filter definitions
                that will be used for SQL generation. Refer to the package
                documentation, songlists.config and songlists.configclasses for more
                details.
            list_validator {Dict[ListField, List[str]]} -- For each list field in the
                dictionary, a list of valid values for this field.
            arrangements_name {str} -- Rocksmith arrangements table name.
            profile_name {str} -- Player profile table name.

        After initialisation, the sql queries are provided in fields tmp_table_sql and
        song_list_sql. Refer to the class documentation for more details.
        """
        self._filter_definitions = filter_definitions
        self._list_validator = list_validator
        if len(song_list_set) > MAX_SONG_LIST_COUNT:
            # Rocksmith supports up to 6 song lists. Discard any beyond this.
            self._song_list_set = song_list_set[0:MAX_SONG_LIST_COUNT]
        else:
            self._song_list_set = song_list_set[:]

        self.tmp_table_sql = list()
        self.song_list_sql = list()
        self._table_map = dict()
        self._next_table_index = 1

        # set up for the root table for all filters
        self._root_table = self._next_table_name()

        self.tmp_table_sql.append((f"DROP TABLE IF EXISTS {self._root_table};", ()))

        # note that we exclude vocals here
        sql_text = (
            f"CREATE TEMP TABLE {self._root_table} AS SELECT *"
            f"\n  FROM {arrangements_name} LEFT JOIN {profile_name} ON"
            f"\n    {arrangements_name}.{ARRANGEMENT_ID.value}"
            f"\n      == {profile_name}.{ARRANGEMENT_ID.value}"
            f'\n  WHERE {ARRANGEMENT_NAME.value} != "Vocals";'
        )

        self.tmp_table_sql.append((sql_text, ()))

        # create the rest of the tables
        self._generate_table_sql()
        self._generate_song_list_sql()

    def _next_table_name(self) -> str:
        """Return the next temporary table name.

        Returns:
            str -- SQL temporary table name

        """
        table_name = f"{TEMP_TABLE_BASE}{self._next_table_index}"
        self._next_table_index = self._next_table_index + 1
        return table_name

    def _table_setup(self, filter_name: str) -> None:
        """Construct the SQL query for a temporary table that represents a filter.

        Arguments:
            filter_name {str} -- The filter that the temporary table will represent.

        The temporary table will be used as a foundation for either further temporary
        tables or as a foundation for one or more song list queries.
        """
        # grab the name for the table we are creating.
        new_table = self._table_map[filter_name]

        where_clause, where_values = self._where_clause(filter_name)

        # set up the SQL query for the table
        self.tmp_table_sql.append((f"DROP TABLE IF EXISTS {new_table};", ()))

        query = (
            f"CREATE TEMP TABLE {new_table} AS SELECT * "
            f"FROM {self._base_table(filter_name)}"
            f"\n{where_clause};"
        )
        self.tmp_table_sql.append((query, where_values))

    def _base_table(self, filter_name: str) -> str:
        """Return the name of the base SQL table {str} for the named filter."""
        base_filter = self._filter_definitions[filter_name].base
        if base_filter:
            base_table = self._table_map[base_filter]
        else:
            # Undefined base filter, so use the root table name.
            base_table = self._root_table

        return base_table

    def _generate_table_sql(self) -> None:
        """Create the SQL for all temporary tables needed for the song list set."""
        pending_tables: List[str] = list()

        for filter_name in self._song_list_set:
            if not filter_name:
                # Skipping this song list, no table needed.
                continue

            if filter_name not in self._filter_definitions:
                raise KeyError(f"No definition for filter {filter_name}.")

            # We are only generating sql for temp tables, not for target song lists.
            # For this, we start with the base filter.
            # Note that base will be an empty string if the filter is built on the root
            # table, which provides the exit criterion for the loop (the root table
            # is not dependent on any other filter)
            this_filter = self._filter_definitions[filter_name].base
            while this_filter:
                if this_filter not in self._filter_definitions:
                    raise KeyError(f"No definition for filter {this_filter}.")

                # Do a quick check on circular filter definitions.
                if this_filter in pending_tables:
                    raise RSFilterError(
                        f"Filter {this_filter} is recursive - \nit appears as a "
                        f"parent filter to itself. "
                        f"Recursive filter list follows.\n   {pending_tables}"
                    )

                if this_filter not in self._table_map:
                    # Filter definition exists, but Table SQl doesn't.
                    # Add to list for generation later.
                    pending_tables.append(this_filter)

                    # But before we do generation, we also need to check that the base
                    # filter table SQL exists
                    this_filter = self._filter_definitions[this_filter].base
                else:
                    # Filter table SQL already defined, no more checking to do.
                    break

            # Now do the generation for this **filter_name**
            while pending_tables:
                # pop out the next table in the sequence.
                # Popping allows us to work our way from the deepest base filter
                # back up to the base filter for filter_name. Consequently, the
                # table_map should contain definitions for base tables before they
                # are needed.
                this_filter = pending_tables.pop()

                # Create a table name for this_filter - this should be the only place we
                # add entries to table map.
                self._table_map[this_filter] = self._next_table_name()

                # and then create the the table SQL.
                self._table_setup(this_filter)

    def _generate_song_list_sql(self) -> None:
        """Create the sql for the song lists in the song list set."""
        # temporary tables have already been created and consistency tests run
        # previously, so the code for the song list sql is a lot cleaner than that
        # for table generation.
        for filter_name in self._song_list_set:
            if not filter_name:
                # empty song list - mark this for skipping
                self.song_list_sql.append(("", ()))

            else:
                if filter_name not in self._filter_definitions:
                    raise KeyError(f"No definition for filter {filter_name}.")

                where_clause, where_values = self._where_clause(filter_name)

                sql_text = SQLTable(SONG_LIST_FIELDS).field_list(prefix="    ")

                sql_text = (
                    f"SELECT"
                    f"\n{sql_text}"
                    f"  FROM {self._base_table(filter_name)}"
                    f"\n{where_clause};"
                )

                self.song_list_sql.append((sql_text, where_values))

    def _where_clause(self, filter_name: str) -> SQLClause:
        """Return a SQL WHERE clause for a named filter.

        Arguments:
            filter_name {str} -- The name of the filter that will be used to generate
                the SQL.

        Raises:
            KeyError, ValueError, TypeError, RSFilterError -- For validation errors in
                the filter definition.

        Returns:
            Tuple[str, Tuple[Union[str, int, float], ...]] -- SQLClause, the WHERE
                clause for the filter and the tuple of values to be substituted into the
                filter.

        """
        try:
            clause, values = self._filter_definitions[filter_name].where_clause(
                self._list_validator
            )
        except RSFilterError as exc:
            raise RSFilterError(f"WHERE clause error for filter {filter_name}.\n{exc}")

        return clause, values


class ArrangementDB:
    """Create, update and query database of Rocksmith song arrangements.

    Public members:
        Constructor -- Sets up path to database, initialises data table descriptions.

        generate_song_lists -- Generates up to 6 song lists based on the first six
            filters named in song_list_set (list of strings). The song lists are
            returned as a list of (list of strings). The filter definitions are as
            described in module songlists.

        cl_update_player_data -- Runs a command line menu for the user to update
            player profile data in the database from a steam user profile.

        run_cl_reports -- Provides command line menu to a set of utility reports on the
            database.

        load_cfsm_arrangements -- Replaces all song specific arrangement data with data
            read from the cfsm xml file.

        load_player_profile -- Replaces all player specific arrangement data in the
            database with data read from the named profile in the profile_manager
            (an RSProfileManager instance).

        open_db -- Utility method for opening the database.

        flush_player_profile -- Deletes the player profile table and re-creates an empty
            player profile table.

        list_validator -- Returns a dictionary of all of the unique list field values in
            the database (e.g. unique tunings, artists, album names).

        has_arrangement_data -- Read only bool, True if the database contains song
            specific arrangement data (title, tuning, artist, etc).

        has_player_data -- Read only bool, True if the database contains player profile
            data (play count, badge performance, etc.).

    """

    # Type declarations
    _db_file_path: Path
    _arrangements_sql: SQLTable
    _profile_sql: SQLTable

    def __init__(self, db_path: Path = None) -> None:
        """Initialise instance path to database, initialise table structure classes.

        Keyword Arguments:
            db_path {Path} -- Path to directory containing SQLite3 database file.
                (default: {None})
        """
        if db_path is None:
            self._db_file_path = Path(DB_NAME)
        else:
            self._db_file_path = db_path.joinpath(DB_NAME)

        self._db_file_path = self._db_file_path.resolve()

        # table definitions
        self._arrangements_sql = SQLTable(
            ARRANGEMENT_FIELDS, ARRANGEMENTS_TABLE, ARRANGEMENT_ID
        )
        self._profile_sql = SQLTable(PROFILE_FIELDS, PROFILE_TABLE, ARRANGEMENT_ID)

    def open_db(self) -> sqlite3.Connection:
        """Open/connect to database."""
        return sqlite3.connect(self._db_file_path)

    def _table_has_data(self, name: str) -> bool:
        """Return boolean indicating if the named table contains data.

        Arguments:
            name {str} -- SQL table name.

        Raises:
            ValueError -- If the table name is invalid.

        Returns:
            bool -- True if the table contains one or more records.

        """
        if name not in (
            self._arrangements_sql.table_name,
            self._profile_sql.table_name,
        ):
            raise ValueError(f"Invalid table name {name}")

        conn = self.open_db()
        ret_val = True
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {name};").fetchone()
        except sqlite3.OperationalError:
            ret_val = False
        else:
            if count[0] == 0:
                ret_val = False

        conn.close()
        return ret_val

    @property
    def has_arrangement_data(self) -> bool:
        """Return True if the Arrangements table contains one or more records."""
        return self._table_has_data(self._arrangements_sql.table_name)

    @property
    def has_player_data(self) -> bool:
        """Return True if the player profile table contains one or more records."""
        return self._table_has_data(self._profile_sql.table_name)

    def load_cfsm_arrangements(self, cfsm_xml_file: Path) -> None:
        """Read CFSM arrangement file into arrangements table.

        Arguments:
            cfsm_xml_file {pathlib.Path} -- Path to the CFSM ArrangementsGrid.xml file.

        Replaces any existing table.
        """
        self._arrangements_sql.rebuild_table(self.open_db())
        # create file object from path to keep mypy happy
        # (etree seems to grok pathlikes, but annotations don't reflect this)
        with cfsm_xml_file.open("rt") as fp:
            tree = eTree.parse(fp)

        root = tree.getroot()

        conn = self.open_db()
        # keep mypy happy even though we will only fill with str or None values
        sql_values: Dict[str, Optional[Union[str, int, float]]] = dict()
        for data_row in root:
            for sql_key, cfsm_tag in CFSM_MAP.items():
                try:
                    element = data_row.find(cfsm_tag)
                    if element is None:
                        sql_values[sql_key.value] = None
                    else:
                        sql_values[sql_key.value] = element.text
                except AttributeError:
                    # some fields don't exist for e.g. Vocal arrangements.
                    # set as empty
                    sql_values[sql_key.value] = None

            # and the ugly hard coded manual handles
            try:
                element = data_row.find("colArtistTitleAlbumDate")
                if element is None or element.text is None:
                    sql_values[ListField.ALBUM.value] = None
                    sql_values[RangeField.YEAR.value] = None
                else:
                    _, _, sql_values[ListField.ALBUM.value], year = element.text.split(
                        ";"
                    )
                    sql_values[RangeField.YEAR.value] = year[:4]
            except AttributeError:
                sql_values[ListField.ALBUM.value] = None
                sql_values[RangeField.YEAR.value] = None

            # At this point we should have value entries for all fields in the table
            self._arrangements_sql.write_row(conn, sql_values)

        conn.commit()
        conn.close()

    def flush_player_profile(self) -> None:
        """Delete player profile table and create a new, empty one."""
        self._profile_sql.rebuild_table(self.open_db())

    def load_player_profile(
        self, profile_manager: RSProfileManager, profile_name: str
    ) -> None:
        """Load data from named player profile name into the corresponding table.

        Arguments:
            profile_manager {RSProfileManager} -- The profile manager instance
                that contains the player profile data.
            profile_name {str} -- The target player profile name.

        This method replaces all existing data in the table.
        """
        self.flush_player_profile()

        conn = self.open_db()

        # we are going to create and override the values in this dict() repeatedly.
        value_dict: Dict[str, Optional[Union[str, int, float]]] = dict()

        for a_id in profile_manager.player_arrangement_ids(profile_name):
            value_dict[ListField.ARRANGEMENT_ID.value] = a_id

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

                value_dict[key.value] = value

            # And a set of annoying manual fixes for accumulation/percent values.
            sa_played = 0
            for sa_key in (
                RangeField.SA_EASY_COUNT,
                RangeField.SA_MEDIUM_COUNT,
                RangeField.SA_HARD_COUNT,
                RangeField.SA_MASTER_COUNT,
            ):
                # If these aren't a numeric type, everything should blow up.
                sa_played = sa_played + cast(int, value_dict[sa_key.value])

            # These two are calculated fields, not directly available from the profile
            # Maybe it would have been better to do this in the database?
            value_dict[RangeField.SA_PLAYED_COUNT.value] = sa_played

            value_dict[RangeField.MASTERY_PEAK.value] = 100 * cast(
                float, value_dict[RangeField.MASTERY_PEAK.value]
            )

            # At this point we should have value entries for all fields in the table
            self._profile_sql.write_row(conn, value_dict)

        conn.commit()
        conn.close()

    def _no_player_data_report(self) -> None:
        """Report on on songs that don't appear in the player profile.

        This is a quick and dirty report - the most likely reason for a song to appear
        in this report is because it hasn't been played yet.
        """
        # readability variables
        arrangements_name = self._arrangements_sql.table_name
        profile_name = self._profile_sql.table_name

        conn = self.open_db()

        # Automatically exclude vocal data. There should never be any player data for
        # vocals anyway.
        sql_text = SQLTable(NO_PLAYER_FIELDS).field_list(prefix="    ")
        sql_text = (
            f"SELECT"
            f"\n{sql_text}"
            f"  FROM {arrangements_name}"
            f"\n  WHERE"
            f"\n    NOT EXISTS ("
            f"\n      SELECT {ARRANGEMENT_ID.value} FROM {profile_name}"
            f"\n        WHERE {arrangements_name}.{ARRANGEMENT_ID.value}"
            f"\n          == {profile_name}.{ARRANGEMENT_ID.value}"
            f"\n    )"
            f"\n    AND ("
            f"\n      {arrangements_name}.{ARRANGEMENT_NAME.value}"
            f'\n      != "Vocals"'
            f"\n    );"
        )

        for row in conn.execute(sql_text):
            print(row)

        conn.close()

    def _missing_song_data_report(self) -> None:
        """Report on song id that appear in player profile but not arrangement data.

        This is a quick and dirty report, and very experimental at the moment. Read
        the warnings in the method for more detail.
        """
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

        # readability variable.
        arrangements_name = self._arrangements_sql.table_name
        profile_name = self._profile_sql.table_name

        conn = self.open_db()

        query = (
            f"SELECT * FROM {profile_name}"
            f"\n  WHERE NOT EXISTS ("
            f"\n    SELECT {ARRANGEMENT_ID.value} FROM {arrangements_name}"
            f"\n      WHERE {arrangements_name}.{ARRANGEMENT_ID.value}"
            f"\n        == {profile_name}.{ARRANGEMENT_ID.value}"
            f"\n  );"
        )

        for row in conn.execute(query):
            print(row)

        conn.close()

    def list_validator(
        self, validator_report: Optional[ListField] = None
    ) -> ListValidator:
        """Create dictionary of list field validators.

        Keyword Arguments:
            validator_report {Optional[ListField]} -- If a list field is specified, the
                method prints a summary report of unique values for that field to
                stdout. If None, the method generates validator lists for
                all members of the ListField Enum without any reporting.
                (default: {None})

        Returns:
            Dict[ListField, List[str]] -- For each list field in the dictionary,
                a list of valid values for this field.

        The validator lists created by this method are intended for use in creating song
        lists or UI drop down lists.

        """
        if validator_report is None:
            # Create validators for ALL list fields.
            validators = tuple(ListField)
        else:
            # Create a validator for the single specfied field.
            validators = (validator_report,)

        ret_dict = dict()

        conn = self.open_db()

        for list_field in validators:
            # I assume we will never be interested in records relating to Vocals.
            query = (
                f"SELECT {list_field.value}, COUNT(*)"
                f"\n  FROM {self._arrangements_sql.table_name}"
                f'\n  WHERE {ARRANGEMENT_NAME.value} != "Vocals"'
                f"\n  GROUP BY {list_field.value};"
            )

            result = conn.execute(query).fetchall()
            value_list = [i[0] for i in result]
            ret_dict[list_field] = value_list

            if validator_report is not None:
                print()
                print(f"  {len(result)} unique records for {list_field.value}")
                print("    Unique item: Count")
                for i in result:
                    print(f"    {i[0]}: {i[1]}")

        conn.close()

        return ret_dict

    def generate_song_lists(
        self,
        song_list_set: List[str],
        filter_definitions: Dict[str, Filter],
        debug_target: Optional[TextIO] = None,
    ) -> List[Optional[List[str]]]:
        """Create a list of up to six song lists from the filters in song list set.

        Arguments:
            song_list_set {List[str]} -- A list of filter names that will be used to
                generate the song lists.
            filter_definitions {Dict[str, Filter]}

        Keyword Arguments:
            debug_target {Optional[TextIO]} -- Stream target for debug output. If set,
                writes output to this stream, if None, writes no output.
                (default: {None})

        Returns:
            List[Optional[List[str]]] -- Up to six lists of the song keys required by
                Rocksmith. A value of None in place of a list represents a skipped song
                list.

        """
        song_lists: List[Optional[List[str]]] = list()

        # I could have created a list_validator member. However this would need to be
        # refreshed after every routine that modified the SQL tables. It is easier to
        # just create it on demand.
        list_validator = self.list_validator()
        sql_queries = SongListSQLGenerator(
            song_list_set,
            filter_definitions,
            list_validator,
            arrangements_name=ARRANGEMENTS_TABLE,
            profile_name=PROFILE_TABLE,
        )

        conn = self.open_db()
        for query, values in sql_queries.tmp_table_sql:
            # create the temporary tables needed for the queries.
            conn.execute(query, values)

        for idx, (query, values) in enumerate(sql_queries.song_list_sql):
            if not query:
                # empty string = skipped song list
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
                        f"{len(results)} records for {song_list_set[idx]}",
                        file=debug_target,
                    )
                    print(file=debug_target)
                    for line in results:
                        print(line, file=debug_target)
                    print("-" * 80, file=debug_target)
        conn.close()

        return song_lists

    def run_cl_reports(self) -> None:
        """Command line utility for selecting and running reports on the database."""
        if not self.has_player_data or not self.has_arrangement_data:
            raise RSFilterError(
                "Cannot run reports, as database is missing player data and/or song "
                "arrangement data."
            )

        options = [
            ("Tunings.           Report unique tuning names.", ListField.TUNING),
            (
                "Arrangement Types. Report unique arrangement types.",
                ListField.ARRANGEMENT_NAME,
            ),
            ("Artists.           Report unique artist names.", ListField.ARTIST),
            ("Albums.            Report unique album names.", ListField.ALBUM),
            ("Titles.            Report unique song titles.", ListField.TITLE),
            (
                "Song Keys.         Report unique Rocksmith song keys.",
                ListField.SONG_KEY,
            ),
            (
                "No player data. Diagnostic. Reports on song arrangements that have "
                "no data in the player profile.",
                self._no_player_data_report,
            ),
            (
                "Missing song data. Do not use. Under development.",
                self._missing_song_data_report,
            ),
        ]

        while True:
            choice = choose(
                options=options,
                header="Choose report to run",
                no_action="Exit reports.",
            )

            if choice is None:
                return

            actor = choice[0]
            if isinstance(actor, ListField):
                self.list_validator(actor)
            if callable(actor):
                actor()

    def cl_update_player_data(self, working_dir: Path) -> None:
        """Command line/interactive update of player data."""
        # Calling profile manager without arguments will result in CLI calls to select
        # steam user id, copying of file set to working directory, and loading of
        # working set.
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
        "player profile data in the arrangements database (creates working "
        "directories/files if needed).",
        action="store_true",
    )
    parser.add_argument(
        "--reports",
        help="Runs the interactive diagnostic report generator. Updates to database "
        "are performed before running reports.",
        action="store_true",
    )

    args = parser.parse_args()

    db = ArrangementDB(Path(args.db_directory))

    if args.CFSMxml:
        db.load_cfsm_arrangements(Path(args.CFSMxml))

    if args.update_player_data:
        db.cl_update_player_data(Path(args.db_directory))

    if args.reports:
        db.run_cl_reports()


if __name__ == "__main__":
    main()
