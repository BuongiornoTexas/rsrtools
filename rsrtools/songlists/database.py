#!/usr/bin/env python3
"""Provide methods and classes for creating and querying a Rocksmith song arrangement
database. The primary function of the module is to provide the song list generator used
by the SongListCreator class.

The core public class provided by this module is ArrangementDB, which uses
SongListSQLGenerator as a helper class.

TODO: fix/check this. For command line options (database setup, reporting), run 
    'python database.py -h'.
"""

import sqlite3
import argparse

import xml.etree.ElementTree as eTree

from pathlib import Path

# I'd prefer to import OrderedDict from typing, but this isn't quite working as at 3.7.3
from collections import OrderedDict
from typing import Dict, List, MutableMapping, Optional, TextIO, Tuple, Union

import rsrtools.songlists.config as config
from rsrtools.songlists.config import ListField, RangeField, SQLField
from rsrtools.utils import choose
from rsrtools.files.config import MAX_SONG_LIST_COUNT
from rsrtools.files.profilemanager import RSProfileManager

# type aliases
ListValidator = Dict[ListField, List[str]]
# SQL Clause - SQL text + Value tuple for substitution
SQLClause = Tuple[Optional[str], Optional[Tuple[Union[str, int, float], ...]]]
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
        (ListField.RS_SONG_ID, "text"),
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
        (ListField.RS_SONG_ID, ""),
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


class RSFilterError(Exception):
    def __init__(self, message: str = None) -> None:
        """Base exception for song list filtering/SQL classes."""
        if message is None:
            message = "An unspecified Rocksmith Filter Error has occurred."
        super().__init__(message)


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
            if new_table:
                type_text = f" {type_str}"
                if field is self._primary:
                    primary = " PRIMARY KEY"
            else:
                type_text = ""

            sql_text = f"{sql_text}{prefix}{field.value}{type_text}{primary}\n"

        return sql_text

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
        self, conn: sqlite3.Connection, values: Dict[SQLField, Union[float, int, str]]
    ) -> None:
        """Write a dictionary of values into a a row in the database.

        Arguments:
            conn {sqlite3.Connection} -- Connection to database for table. 
            values {Dict[SQLField, Union[float, int, str]]} -- The dictionary of values
                to be written. There should be one value per field in the table, and
                the method will raise an exception if the primary key does not exist
                or if the values dictionary does not contain value for the primary key.
        
        As this routine should be called repeatedly, the caller is responsible for
        commit and close.
        """
        if not self._write_row_script:
            if self._primary is None:
                raise RSFilterError(
                    f"\nTable named '{self._table_name}'' has no primary key."
                )

            try:
                values[self._primary]
            except:
                raise RSFilterError(
                    f"There is no value for primary key {self._primary} in "
                    f"table named '{self._table_name}'."
                )

            # create the script.
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
    """Single use class for generating song list sql. This is a helper class for ArrangementDB.

    The class creates two sets of sql queries for song list generation, both of which
    are public attributes:
        tmp_table_sql -- An attribute that provides the sql for the temporary tables.
        song_list_sql -- An attribute that provides the sql for the song lists.

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
    _filter_names: config.FilterSet
    _filter_definitions: config.FilterDict
    # table_map maps filter names to table names
    _table_map: Dict[str, str]
    _root_table: str

    def _next_table_name(self) -> str:
        """Return the next temporary table name.
        
        Returns:
            str -- SQL temporary table name
        """
        table_name = f"{TEMP_TABLE_BASE}{self._next_table_index}"
        self._next_table_index = self._next_table_index + 1
        return table_name

    def _table_setup(
        self,
        filter_name: str,
        where_clause: str,
        where_values: Tuple[Union[str, int, float]],
    ) -> None:
        """Construct the SQL query for temporary table that represents a filter.
        
        Arguments:
            filter_name {str} -- The filter that the temporary table will represent.
            where_clause {str} -- The SQL WHERE clause text for the filter.
            where_values {Tuple[Union[str, int, float]]} -- Values for ? substitution
                into the where_clause.
        
        The temporary table will be used as a foundation for either further temporary
        tables or as a foundation for one or more song list queries.
        based on where_clause, where_values and the base filter for
        filter_name.
        """

        new_table = self._next_table_name()
        self._table_map[filter_name] = new_table
        # find the name of the base table this table will be built on.
        base_table = self._table_map[self._base_filter(filter_name)]

        # set up the start of the SQL query for the table
        self.tmp_table_sql.append((f"DROP TABLE IF EXISTS {new_table};", ()))

        query = (
            f"CREATE TEMP TABLE {new_table} AS SELECT * FROM {base_table}"
            f"\n{where_clause};"
        )
        self.tmp_table_sql.append((query, where_values))

    def __init__(
        self,
        filter_set: config.FilterSet,
        filter_definitions: config.FilterDict,
        list_validator: ListValidator,
        arrangements_name: str,
        profile_name: str,
    ) -> None:
        """Generate song list sql queries for a filter set and filter definitions.
        
        Arguments:
            filter_set {config.FilterSet} -- A list of filter names that will be used
                for song list definition. That is, each song list corresponds to a
                filter name in this list, and SQL will be generated for each of these
                names.
            filter_definitions {config.FilterDict} -- A dictionary of filter definitions
                that will be used for SQL generation. Refer to the package
                documentation, songlists.config and songlists.defaults for more details.
            list_validator {Dict[ListField, List[str]]} -- For each list field in the
                dictionary, a list of valid values for this field.
            arrangements_name {str} -- Rocksmith arrangements table name.
            profile_name {str} -- Player profile table name.
        
        After initialisation, the sql queries are provided in fields tmp_table_sql and
        song_list_sql. Refer to the class documentation for more details.
        """
        self._filter_definitions = filter_definitions
        self._list_validator = list_validator
        if len(filter_set) > MAX_SONG_LIST_COUNT:
            # Rocksmith supports up to 6 song lists. Discard any beyond this.
            self._filter_names = filter_set[0 : MAX_SONG_LIST_COUNT - 1]
        else:
            self._filter_names = filter_set[:]

        self.tmp_table_sql = list()
        self.song_list_sql = list()
        self._table_map = dict()
        self._next_table_index = 1

        # set up for the root table for all filters
        self._root_table = self._next_table_name()
        # Map the root table name to itself. This might be a problem if someone cleverly
        # names their base table to match the root table.
        self._table_map[self._root_table] = self._root_table

        # note that we exclude vocals here
        self.tmp_table_sql.append((f"DROP TABLE IF EXISTS {self._root_table};", ()))

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

    def _base_filter(self, filter_name):
        """Returns the name of the base filter for filter_name, or if it is not defined, the root table for song list
        queries.
        """
        return self._filter_definitions[filter_name].get("BaseFilter", self._root_table)

    def _generate_table_sql(self):
        """Creates the sql queries for all temporary tables required by the filter set."""
        pending_tables = list()

        for filter_name in self._filter_names:
            if not filter_name:
                # nothing needed for empty filter set.
                continue

            if filter_name not in self._filter_definitions:
                raise KeyError(f"No definition for filter {filter_name}.")

            # only generating sql for temp tables, not for target song lists.
            this_filter = self._base_filter(filter_name)
            while True:
                if this_filter not in self._table_map:
                    if this_filter not in self._filter_definitions:
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
        """Create the sql for the song lists in the filter set."""
        # temporary tables have already been created and consistency tests run previously,
        # so the code for the song list sql is a lot cleaner than that for table generation.
        for filter_name in self._filter_names:
            if not filter_name:
                # empty song list
                self.song_list_sql.append((None, None))
            else:
                base_table = self._table_map[self._base_filter(filter_name)]
                where_clause, where_values = self._where_clause(filter_name)

                sql_text = SQLTable(SONG_LIST_FIELDS).field_list(prefix="    ")

                sql_text = (
                    f"SELECT"
                    f"\n{sql_text}"
                    f"  FROM {base_table}"
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
            Tuple[str, Tuple[Union[str, int, float], ...]] -- The WHERE clause for the
                filter and the tuple of values to be substituted into the filter.

        """
        field_clauses: List[str] = list()
        where_values: List[Union[str, int, float]] = list()

        if config.FIELD_FILTER_LIST_KEY not in self._filter_definitions[filter_name]:
            raise KeyError(
                f"Missing '{config.FIELD_FILTER_LIST_KEY}'/field filter list pair in "
                f"filter '{filter_name}'."
            )

        # work through each field filter in the list.
        for idx, field_filter in enumerate(
            self._filter_definitions[filter_name][config.FIELD_FILTER_LIST_KEY],
        ):
            # do a whack of validation here to provide help debugging json. It would
            # have been better to learn how to use the json schema validator, but I
            # found it a bit late.
            field_name = field_filter.get(config.FIELD_NAME_KEY, None)
            if field_name is None:
                raise KeyError(
                    f"Missing '{config.FIELD_NAME_KEY}'/value pair in "
                    f"'{config.FIELD_FILTER_LIST_KEY}[{idx}]' "
                    f"for filter '{filter_name}'."
                )

            # Convert field name to enum.
            try:
                field = SQLField.getsubclass(field_name)
            except ValueError:
                raise ValueError(
                    f"Invalid field name '{field_name}' in "
                    f"'{config.FIELD_FILTER_LIST_KEY}[{idx}]' of "
                    f"filter '{filter_name}'."
                    f"\n(No SQLField subclass with Enum value of '{field_name}'.)"
                )

            include = field_filter.get(config.INCLUDE_KEY, None)
            if include is None:
                raise KeyError(
                    f"Missing '{config.INCLUDE_KEY}'/value definition in "
                    f"'{config.FIELD_FILTER_LIST_KEY}[{idx}]' for "
                    f"filter '{filter_name}'."
                )
            if not isinstance(include, bool):
                raise TypeError(
                    f"'{config.INCLUDE_KEY}' value "
                    f"in '{config.FIELD_FILTER_LIST_KEY}[{idx}]' "
                    f"of filter '{filter_name}'' is not a valid boolean."
                )

            # Process the filter based on type.
            if isinstance(field, ListField):
                if (field not in self._list_validator) or not self._list_validator[
                    field
                ]:
                    raise ValueError(
                        f"Validator list for field '{field.value}' in "
                        f"'{config.FIELD_FILTER_LIST_KEY}[{idx}]' of "
                        f"filter '{filter_name}' either"
                        f"\n doesn't exist or is empty."
                    )

                values: config.FilterValues = field_filter.get(config.VALUES_KEY, None)
                if values is None or not values:
                    raise KeyError(
                        f"Missing or empty '{config.VALUES_KEY}' field definition in "
                        f"'{config.FIELD_FILTER_LIST_KEY}[{idx}]' for "
                        f"filter '{filter_name}'."
                    )

                sql_text = self._list_clause(field, include, values)
                # grab the list values for later use
                where_values.extend(values)

            elif isinstance(field, RangeField):
                ranges: config.FilterRanges = field_filter.get(config.RANGES_KEY, None)
                if ranges is None or not ranges:
                    raise KeyError(
                        f"Missing or empty '{config.RANGES_KEY}' field definition in "
                        f"'{config.FIELD_FILTER_LIST_KEY}[{idx}]' for "
                        f"filter '{filter_name}'."
                    )
                sql_text, range_values = self._positive_range_clause(
                    field, include, ranges
                )
                # grab the range values for later use
                where_values.extend(range_values)

            else:
                raise RSFilterError(
                    f"Clause generator not implemented for SQL field type {field.name}."
                )

            # Capture the text clause from this iteration of the loop
            field_clauses.append(sql_text)

        # This is clumsy, but allows dumping of SQL for debugging.
        where_text = "\n    AND ".join(field_clauses)
        where_text = f"  WHERE\n    {where_text}"

        return where_text, tuple(where_values)

    def _list_clause(
        self, field_type: ListField, include: bool, filter_values: config.FilterValues
    ) -> str:
        """Create SQL list field clause.
        
        Arguments:
            field_type {ListField} -- The list field target for the clause.
            include {bool} -- True if the clause includes the values, False if the
                clause excludes the values. 
            filter_values {config.FilterValues} -- The values that will be used for the
                field filter.
        
        Raises:
            RSFilterError -- If a filter value is not valid (doesn't appear in the
                database).
        
        Returns:
            str -- SQL clause for the field, including question marks for
                value substitution. For example, a for a field type of ARTIST, and
                values of ["Queen", "Big Country"] will result in the following
                clause (depending on the value of include):

                    Artist IN (? ?)
                    Artist NOT IN (? ?)

        """
        for value in filter_values:
            if value not in self._list_validator[field_type]:
                raise RSFilterError(
                    f"Invalid filter value ({value}) for field type {field_type.value}"
                )

        if include:
            not_text = ""
        else:
            not_text = "NOT "

        if len(filter_values) > 1:
            q_marks = "?, " * (len(filter_values) - 1)
        else:
            q_marks = ""

        sql_text = f"{field_type.value} {not_text}IN ({q_marks}?)"

        return sql_text

    @staticmethod
    def _positive_range_clause(
        field_type: RangeField, include: bool, ranges: config.FilterRanges
    ) -> Tuple[str, List[Union[float, int]]]:
        """Create (positive) range field SQL clause with limited validation.
        
        Arguments:
            field_type {RangeField} -- The list field target for the clause.
            include {bool} -- True if the filter will include the specified ranges,
                False if the filter will exclude them.
            ranges {config.FilterRanges} -- Nested list of low/high value pairs that
                will form the basis of the filter. E.g. [[1, 2], [5, 10]]
        
        Raises:
            IndexError, RSFilterError, ValueError -- On validation errors in the ranges
                values.

        Returns:
            Tuple[str, List[Union[float, int]]] -- The text of the SQL clause and the 
                list of values to be subsituted into the clause.

        For example, for the field PLAYED_COUNT and ranges [[1,10], [25, 20]], and
        include of True, the clause will be:

            PlayedCount BETwEEN ? AND ?
            OR PlayedCount BETWEEN ? AND ?

        The returned values will be [1, 10, 20, 25]. The method does not check for
        overlapping ranges - weird things may happen if you try.

        For an include value of False, the expression changes to:

            PlayedCount NOT BETwEEN ? AND ?
            AND PlayedCount NOT BETWEEN ? AND ?            

        """
        ret_values: List[Union[float, int]] = list()
        text_list: List[str] = list()

        if include:
            not_text = ""
        else:
            not_text = "NOT "

        for value_pair in ranges:
            if len(value_pair) != 2:
                raise IndexError(
                    f"Range field type '{field_type.value}' expected [high, low] pair, "
                    f"got {value_pair}."
                )

            if not isinstance(value_pair[0], (int, float)) or not isinstance(
                value_pair[1], (int, float)
            ):
                raise RSFilterError(
                    f"Range field type {field_type} expects numeric pairs of values to "
                    f"define range. Got {value_pair}."
                )

            if value_pair[0] < 0 or value_pair[1] < 0:
                raise ValueError(
                    f"Range field type {field_type} expects numeric pairs of values "
                    f">= 0 to define range. Got {value_pair}."
                )

            # silent tidy.
            if value_pair[1] > value_pair[0]:
                high_val = value_pair[1]
                low_val = value_pair[0]
            else:
                high_val = value_pair[0]
                low_val = value_pair[1]

            # and finally the SQL
            text_list.append(f"{field_type.value} {not_text}BETWEEN ? AND ?")
            ret_values.append(low_val)
            ret_values.append(high_val)

        if include:
            joiner = "\n      OR "
        else:
            joiner = "\n      AND "

        sql_text = joiner.join(text_list)
        sql_text = f"({sql_text})"

        return sql_text, ret_values


class ArrangementDB:
    """Create, update and query database of Rocksmith song arrangements.

    Public members:
        Constructor -- Sets up path to database, initialises data table descriptions.

        method:: generate_song_lists(filter_set, filter_definitions, debug_target=None)
            Generates up to 6 song lists based on the first six filters named in filter_set (list of strings).
            The song lists are returned as a list of (list of strings). The filter definitions are as described
            in module songlists.

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
        """Utility for opening/connecting to database."""
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
        """Reads CFSM arrangement file into arrangements table. 
        
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

            self._arrangements_sql.write_row(conn, sql_values)

        conn.commit()
        conn.close()

    def flush_player_profile(self) -> None:
        """Deletes Player Profile table and creates a new, empty one."""
        self._profile_sql.rebuild_table(self.open_db())

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
            self._profile_sql.write_row(conn, value_dict)

        conn.commit()
        conn.close()

    def _no_player_data_report(self):
        """Quick and dirty report on song data that doesn't appear in the player profile. Most likely to occur if an
        arrangement hasn't been played yet."""

        # readability variables
        arrangements_name = self._arrangements_sql.table_name
        profile_name = self._profile_sql.table_name

        conn = self.open_db()

        # Automatically exclude vocal data. There should never be any player data for vocals anyway.
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

        # I could have created a list_validator member. However this would need to be
        # refreshed after every routine that modified the SQL tables. It is easier to
        # just create it on demand.
        list_validator = self.list_validator()
        sql_queries = SongListSQLGenerator(
            filter_set, filter_definitions, list_validator
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
                "Song Keys.         Report unique Rocksmith song keys.",
                FieldTypes.RS_SONG_ID,
            ),
            (
                "No player data. Diagnostic. Reports on song arrangements that have no data in the player profile.",
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
