#!/usr/bin/env python3

"""Provide song list creator configuration dataclasses and supporting elements."""

import toml

from enum import Enum
from pathlib import Path
from typing import Dict, List, Tuple, Union

from dataclasses import field, asdict, replace
from pydantic.dataclasses import dataclass

from rsrtools import __version__ as RSRTOOLS_VERSION
from rsrtools.songlists.config import RangeField, ListField, SQLField

# SQL Clause type alias - SQL text + Value tuple for substitution
SQLClause = Tuple[str, Tuple[Union[str, int, float], ...]]

# These string constants are used to parameterise the default TOML.
# They should be the same as the attribute names in the dataclasses below.
CONFIG_SONG_LISTS = "song_list_sets"
CONFIG_FILTERS = "filters"
CONFIG_BASE = "base"
CONFIG_MODE = "mode"
CONFIG_SUB_FILTERS = "sub_filters"
CONFIG_INCLUDE = "include"
CONFIG_RANGES = "ranges"
CONFIG_VALUES = "values"

# Set up the default TOML. In this format for readability and to test the toml loader.
# Note the substutions which are intended as helpers in case of future field renaming.
# pylint directive because of issue with subclassed enums.
# pylint: disable=no-member
DEFAULT_TOML = f"""\
[{CONFIG_SONG_LISTS}]
"E Standard" = [
  "E Std Low Plays",
  "E Std Mid Plays",
  "E Std High Plays",
  "E Std Non Concert",
  "",
  "Easy E Plat Badge in progress",
]

"Non E Std Tunings" = [
  "Drop D",
  "Eb Standard",
  "Eb Drop Db",
  "D Standard",
  "D Drop C",
  "Other Tunings",
]

Testing = [
  "Artist test",
  "Played Count of 1 to 15",
]

"Recurse_2_test" = ["Recurse2A"]

"Recurse_3_test" = ["Recurse1A"]

[{CONFIG_FILTERS}."Easy E Plat Badge in progress"]
{CONFIG_BASE} = ""
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Easy E Plat Badge in progress".{CONFIG_SUB_FILTERS}\
.{RangeField.SA_EASY_BADGES.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} =  [ [ 0.9, 4.1] ]

[{CONFIG_FILTERS}."E Standard"]
{CONFIG_BASE} = "Not Bass, Rhythm"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."E Standard".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["E Standard"]

[{CONFIG_FILTERS}."E Standard 440"]
{CONFIG_BASE} = "E Standard"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."E Standard 440".{CONFIG_SUB_FILTERS}.{RangeField.PITCH.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [ [439.5, 440.5 ] ]

[{CONFIG_FILTERS}."E Std Low Plays"]
{CONFIG_BASE} = "E Standard 440"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."E Std Low Plays".{CONFIG_SUB_FILTERS}.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[0.9, 12.1]]

[{CONFIG_FILTERS}."E Std Mid Plays"]
{CONFIG_BASE} = "E Standard 440"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."E Std Mid Plays".{CONFIG_SUB_FILTERS}.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[12.9,27.1]]

[{CONFIG_FILTERS}."E Std High Plays"]
{CONFIG_BASE} = "E Standard 440"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."E Std High Plays".{CONFIG_SUB_FILTERS}.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[27.9, 5000]]

[{CONFIG_FILTERS}."E Std Non Concert"]
{CONFIG_BASE} = "E Standard"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."E Std Non Concert".{CONFIG_SUB_FILTERS}.{RangeField.PITCH.value}]
{CONFIG_INCLUDE} = false
{CONFIG_RANGES} = [[439.5, 440.5]]

[{CONFIG_FILTERS}."E Std Non Concert".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[0.9,5000]]

[{CONFIG_FILTERS}."Drop D"]
{CONFIG_BASE} = "Not Bass, Rhythm"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Drop D".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["Drop D"]

[{CONFIG_FILTERS}."Eb Standard"]
{CONFIG_BASE} = "Not Bass, Rhythm"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Eb Standard".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["Eb Standard"]

[{CONFIG_FILTERS}."Eb Drop Db"]
{CONFIG_BASE} = "Not Bass, Rhythm"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Eb Drop Db".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["Eb Drop Db"]

[{CONFIG_FILTERS}."D Standard"]
{CONFIG_BASE} = "Not Bass, Rhythm"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."D Standard".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["D Standard"]

[{CONFIG_FILTERS}."D Drop C"]
{CONFIG_BASE} = "Not Bass, Rhythm"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."D Drop C".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["D Drop C"]

[{CONFIG_FILTERS}."Other Tunings"]
{CONFIG_BASE} = "Not Bass, Rhythm"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Other Tunings".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = false
{CONFIG_VALUES} = [
    "E Standard", "Drop D", "Eb Standard", "Eb Drop Db", "D Standard", "D Drop C"
]

[{CONFIG_FILTERS}."Played Count of 1 to 15"]
{CONFIG_BASE} = ""
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Played Count of 1 to 15".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[0.9, 15.1]]

[{CONFIG_FILTERS}."Artist test"]
{CONFIG_BASE} = ""
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Artist test".{CONFIG_SUB_FILTERS}.{ListField.ARTIST.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["The Rolling Stones", "Franz Ferdinand"]

[{CONFIG_FILTERS}."Not Bass, Rhythm"]
{CONFIG_BASE} = ""
{CONFIG_MODE} = "OR"

[{CONFIG_FILTERS}."Not Bass, Rhythm".{CONFIG_SUB_FILTERS}\
.{ListField.ARRANGEMENT_NAME.value}]
{CONFIG_INCLUDE} = false
{CONFIG_VALUES} = ["Bass", "Bass2", "Rhythm", "Rhythm1", "Rhythm2"]

# This captures a song that has Rhythm and Bass, but no lead arrangement
[{CONFIG_FILTERS}."Not Bass, Rhythm".{CONFIG_SUB_FILTERS}\
.{ListField.TITLE.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["Cissy Strut"]

[{CONFIG_FILTERS}."Recurse1A"]
{CONFIG_BASE} = "Recurse1B"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Recurse1A".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["D Drop C"]

[{CONFIG_FILTERS}."Recurse1B"]
{CONFIG_BASE} = "Recurse1C"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Recurse1B".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["D Drop C"]

[{CONFIG_FILTERS}."Recurse1C"]
{CONFIG_BASE} = "Recurse1A"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Recurse1C".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["D Drop C"]

[{CONFIG_FILTERS}."Recurse2A"]
{CONFIG_BASE} = "Recurse2B"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Recurse2A".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["D Drop C"]

[{CONFIG_FILTERS}."Recurse2B"]
{CONFIG_BASE} = "Recurse2A"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Recurse2B".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["D Drop C"]
"""
# pylint: enable=no-member


class RSFilterError(Exception):
    """Provide base exception for song list filtering/SQL classes."""

    def __init__(self, message: str = None) -> None:
        """Provide base exception for song list filtering/SQL classes."""
        if message is None:
            message = "An unspecified Rocksmith Filter Error has occurred."
        super().__init__(message)


class FilterMode(Enum):
    """Logical mode for combining subfilters in a filter."""

    AND = "AND"
    OR = "OR"


class EnumConfig:
    """Configuration settings for pydantic dataclasses."""

    use_enum_values = True


@dataclass
class Settings:
    """General settings for song list creator.

    Public attributes:
        CFSM_file_path {str} -- The string form path the Customs Forge Song Manager
            arrangements file, or the empty string if it has not been set.
        steam_user_id {str} -- String representation of Steam user id, or the empty
            string if it has not been set yet.
        player_profile {str} -- The player profile name. Get returns the empty string if
            the player profile it has not been set yet.
        version {str} -- Future functionality for configuration changes.

    Note: changes in attribute names should be reflected in default TOML.
    """

    CFSM_file_path: str = ""
    steam_user_id: str = ""
    player_profile: str = ""
    version: str = ""


@dataclass
class SubFilter:
    """Super class for SubFilters. This should not be instantiated.

    Public attributes:
        include {bool} -- Inclusion/exclusion criteria for filters. See subclasses for
            implementation specifics.

    Note: changes in attribute names should be reflected in default TOML.
    """

    include: bool


@dataclass
class RangeSubFilter(SubFilter):
    """Range list for a range subfilter.

    Public attributes:
        ranges {List[Union[int, float]]} -- A list of low/high value range pairs of the
            form:
                [[low1, high1], [low2, high2], ...]

    The low/high pairs are used to build SQL IN BETWEEN queries. Note that ints will
    tend to be promoted to floats by one of the serialisation or validation libraries
    (outside rsrtools control), so allow a small margin if you want to insure integer
    values are captured correctly. e.g. [0.99, 2.01] to capture integer values in the
    range 1 to 2 inclusive.

    include implementation -- If True if the filter will return records where the
        field value lies int the specified ranges. If False, it will return records
        where the field value lies outside the specifie ranges.

    Note: changes in attribute names should be reflected in default TOML.
    """

    ranges: List[List[Union[int, float]]]

    def range_clause(
        self, field_name: RangeField
    ) -> Tuple[str, List[Union[float, int]]]:
        """Create (positive) range field SQL clause with limited validation.

        Arguments:
            field_type {RangeField} -- The range field target for the clause.

        Raises:
            RSFilterError -- On validation errors in the ranges values.

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

        # Convert any constants to enum type.
        field_type = RangeField(field_name)

        if not self.ranges:
            raise RSFilterError(
                f"WHERE clause error: Ranges is empty for " 
                f"field type {field_type.value}."
            )

        if self.include:
            not_text = ""
            joiner = "\n      OR "
        else:
            not_text = "NOT "
            joiner = "\n      AND "

        for value_pair in self.ranges:
            if not isinstance(value_pair, list) or len(value_pair) != 2:
                raise RSFilterError(
                    f"WHERE clause error: Range field type '{field_type.value}' "
                    f"expected [low, high] pair, got {value_pair}."
                )

            if not all(isinstance(x, (int, float)) for x in value_pair):
                raise RSFilterError(
                    f"WHERE clause error: Range field type {field_type} expects "
                    f"numeric pairs of values to define range. Got {value_pair}."
                )

            if any(x < 0 for x in value_pair):
                raise ValueError(
                    f"WHERE clause error: Range field type {field_type} expects "
                    f"numeric pairs of values to >= 0 to define range."
                    f"\nGot {value_pair}."
                )

            # silent tidy.
            low_val = min(value_pair)
            high_val = max(value_pair)

            # and finally the SQL
            text_list.append(f"{field_type.value} {not_text}BETWEEN ? AND ?")
            ret_values.append(low_val)
            ret_values.append(high_val)

        sql_text = joiner.join(text_list)
        sql_text = f"({sql_text})"

        return sql_text, ret_values


@dataclass
class ListSubFilter(SubFilter):
    """Value list for a value subfilter.

    Public attributes:
        values {List[str} -- A list of string values that will be used to build the
            filter.

    The values are used to build SQL IN queries.

    include implementation -- If True if the filter will return records where the
        field value matches any of the Filter values in the list. If False, it will
        return records where the field value does not match any of the Filter values.

    Note: changes in attribute names should be reflected in default TOML.
    """

    values: List[str]

    def list_clause(
        self, field_name: ListField, list_validator: Dict[ListField, List[str]]
    ) -> Tuple[str, List[str]]:
        """Create SQL list field clause.

        Arguments:
            field_name {ListField} -- The list field target for the clause.
            list_validator {Dict[ListField, List[str]]} -- For each list field in the
                dictionary, a list of valid values for this field.

        Raises:
            RSFilterError -- If a filter value is not valid (doesn't appear in the
                database).

        Returns:
            Tuple[str, List[str]] -- The SQL clause for the field, including question
                marks for value substitution, and the list of values for substitution.
                For example, a for a field type of ARTIST, and values of ["Queen",
                "Big Country"] will result in the following clause (depending on the
                value of include):

                    Artist IN (? ?)
                    Artist NOT IN (? ?)

        """
        # Convert any constants to enum type.
        field_type = ListField(field_name)

        if not self.values:
            raise RSFilterError(
                f"WHERE clause error: Empty value list for "
                f"field type {field_type.value}."
            )

        for value in self.values:
            if value not in list_validator[field_type]:
                raise RSFilterError(
                    f"WHERE clause error: Invalid filter value ({value}) for "
                    f"field type {field_type.value}."
                )

        if len(self.values) > 1:
            q_marks = "?, " * (len(self.values) - 1)
        else:
            q_marks = ""

        if self.include:
            not_text = ""
        else:
            not_text = "NOT "

        sql_text = f"{field_type.value} {not_text}IN ({q_marks}?)"

        return sql_text, self.values


@dataclass(config=EnumConfig)  # type: ignore
class Filter:
    """Provide configuration for a named filter.

    Public attributes:
        sub_filters {Dict[]} -- A dictionary of sub-filters that will be used to build
            the named filter. Each key/value pair should be typed as either:

                {RangeField: RangeSubFilter} or
                {ListField: ListSubFilter}

            The is the target database field for the subfilter (query), and the value
            provides the subfilter parameters (logic and values).

        base {str} -- The name of another named filter that will provides the base data
            for this filter.

        mode {FilterMode} -- Defines the logic for combining sub_filters. For
            FilterMode.AND, the filter will return only records that match all of the
            the sub-filters, while FilterMode.OR will return all records that match any
            of the subfilters.

    Note: changes in attribute names should be reflected in default TOML.
    """

    sub_filters: Dict[
        Union[RangeField, ListField], Union[RangeSubFilter, ListSubFilter]
    ] = field(default_factory=dict)
    base: str = ""
    mode: FilterMode = FilterMode.AND

    def where_clause(self, list_validator: Dict[ListField, List[str]]) -> SQLClause:
        """Return a SQL WHERE clause for the filter.

        Arguments:
            list_validator {Dict[ListField, List[str]]} -- For each list field in the
                dictionary, a list of valid values for this field.

        Raises:
            RSFilterError -- For validation errors in the filter definition.

        Returns:
            Tuple[str, Tuple[Union[str, int, float], ...]] -- SQLClause, the WHERE
                clause for the filter and the tuple of values to be substituted into the
                filter.

        """
        field_type: SQLField
        sub_clauses: List[str] = list()
        where_values: List[Union[str, int, float]] = list()

        # work through each sub filter in the list.
        for field_name, sub_filter in self.sub_filters.items():
            try:
                if isinstance(sub_filter, RangeSubFilter):
                    try:
                        field_type = RangeField(field_name)
                    except ValueError:
                        raise RSFilterError(
                            f"WHERE clause error: Invalid field type ({field_name}) "
                            f"for range type sub-filter.\nThis should be a member of "
                            f"RangeField Enum. "
                        )

                    sub_text, range_list = sub_filter.range_clause(field_type)
                    where_values.extend(range_list)
                    sub_clauses.append(sub_text)

                elif isinstance(sub_filter, ListSubFilter):
                    try:
                        field_type = ListField(field_name)
                    except ValueError:
                        raise RSFilterError(
                            f"WHERE clause error: Invalid field type ({field_name}) "
                            f"for list type sub-filter.\nThis should be a member of "
                            f"ListField Enum."
                        )

                    sub_text, value_list = sub_filter.list_clause(
                        field_type, list_validator
                    )
                    where_values.extend(value_list)
                    sub_clauses.append(sub_text)

                else:
                    raise RSFilterError(
                        f"WHERE clause error: Unrecognised sub_filter type"
                        f"\nGot {type(sub_filter)}, expected ListSubFilter or "
                        f"RangeSubFilter."
                    )

            except RSFilterError as exc:
                raise RSFilterError(
                    f"WHERE clause error for sub filter {field_name}.\n{exc}"
                )

        try:
            mode_text = FilterMode(self.mode).value
        except ValueError:
            raise RSFilterError(
                f"WHERE clause error: Invalid mode '{self.mode}''. Shoud be a member "
                f"of FilterMode Enum."
            )

        # This is clumsy, but allows dumping of SQL for debugging.
        where_text = f"\n    {mode_text} "
        where_text = where_text.join(sub_clauses)
        where_text = f"  WHERE\n    {where_text}"

        return where_text, tuple(where_values)


@dataclass
class Configuration:
    """Provide general configuration settings, filter definitions and filter sets.

    Public attributes:
        settings {Settings} -- General configuration settings.
        filters {Dict[str, Filter]} -- Filter definitions, where the key is the filter
            name.
        song_list_sets {Dict[str, List[str]]} -- Each key is the name for a set of song
            lists, and the list values for that key are the filter names for generating
            the song lists in the named set (up to six names per set).

    Note: changes in attribute names should be reflected in default TOML.
    """

    # Always create a default instance/list/dictionary.
    settings: Settings = Settings()
    # Filters before filter sets to allow future validation of filter sets.
    filters: Dict[str, Filter] = field(default_factory=dict)
    song_list_sets: Dict[str, List[str]] = field(default_factory=dict)

    @classmethod
    def load_toml(cls, toml_path: Path) -> "Configuration":
        """Create a configuration instance from a TOML file.

        Arguments:
            toml_path {Path} -- Path to the toml file.

        This helper function will also fill in sample defaults if these are missing from
        the file.
        """
        try:
            with toml_path.open("rt") as fp:
                data_dict = toml.load(fp)
        except FileNotFoundError:
            data_dict = dict()

        if data_dict:
            # Load and validate the data we have
            configuration = cls(**data_dict)
        else:
            # Create a default configuration if we have no data
            configuration = Configuration()
            # And because it truly is default, set the version info.
            configuration.settings.version = RSRTOOLS_VERSION

        if not configuration.filters and not configuration.song_list_sets:
            # No filter configurations, so set up a default set.
            # This will apply if data is missing or for a default setup.
            configuration = replace(configuration, **toml.loads(DEFAULT_TOML))

        return configuration

    def save_toml(self, toml_path: Path) -> None:
        """Write configuration instance to toml file.

        Arguments:
            toml_path {Path} -- Path to the toml file.
        """
        with toml_path.open("wt") as fp:
            for key, item in asdict(self).items():
                if key != "filters":
                    toml.dump({key: item}, fp)
                    fp.write("\n")
                else:
                    # force toml to keep filter structures together
                    sub_dict = {}
                    for sub_key, sub_item in item.items():
                        sub_dict["filters"] = {sub_key: sub_item}
                        toml.dump(sub_dict, fp)
                        fp.write("\n")
