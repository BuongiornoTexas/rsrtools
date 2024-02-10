#!/usr/bin/env python

"""Provide song list creator configuration dataclasses and supporting elements."""

# cSpell: ignore pydantic, parameterise

from enum import Enum
from pathlib import Path
from typing import Dict, List, Tuple, Union, Optional
import tomllib

from dataclasses import field, asdict, replace  # cSpell: disable-line
from pydantic.dataclasses import dataclass

import tomli_w

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
# Note the substitutions which are intended as helpers in case of future field renaming.
# pylint directive because of issue with sub-classed enums.
# pylint: disable=no-member
DEFAULT_TOML = f"""\
[{CONFIG_SONG_LISTS}]
"E Standard" = [
  "E Std Low Plays",
  "E Std Mid Plays",
  "E Std High Plays",
  "E Std Non Concert",
  "E Std with Bonus or Alternate",
  "Easy E Std Plat Badge in progress",
]

"Non E Std Tunings" = [
  "Drop D",
  "Eb Standard",
  "Eb Drop Db",
  "D Standard",
  "D Drop C",
  "Other Tunings",
]

"Bass or Rhythm" = [
  "B or R E Low Plays",
  "B or R E Mid Plays",
  "B or R E High Plays",
  "",
  "",
  "Easy Plat Badge in progress",
]

"Standard Tunings" = [
  "Standard Low Plays",
  "Standard Mid Plays",
  "Standard High Plays",
  "Standard Off 440 Tunings",
  "With Bonus or Alternate",
  "Easy Plat Badge in progress",
]

"Drop Tunings" = [
  "Drop Low Plays",
  "Drop Mid Plays",
  "Drop High Plays",
  "Drop Off 440 Tunings",
  "Non standard Tunings",
  "Easy Plat Badge in progress",
]

Testing = [
  "Artist test",
  "Played Count of 0 to 15",
]

"Recursive_2_test" = ["Recursive2A"]

"Recursive_3_test" = ["Recursive1A"]

[{CONFIG_FILTERS}."Easy Plat Badge in progress"]
{CONFIG_BASE} = ""
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Easy Plat Badge in progress".{CONFIG_SUB_FILTERS}\
.{RangeField.SA_EASY_BADGES.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} =  [ [ 1, 4] ]

[{CONFIG_FILTERS}."Easy E Std Plat Badge in progress"]
{CONFIG_BASE} = "Easy Plat Badge in progress"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Easy E Std Plat Badge in progress".{CONFIG_SUB_FILTERS}\
.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} =  [ "E Standard" ]

[{CONFIG_FILTERS}."Med Plat Badge in progress"]
{CONFIG_BASE} = ""
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Med Plat Badge in progress".{CONFIG_SUB_FILTERS}\
.{RangeField.SA_MEDIUM_BADGES.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} =  [ [ 1, 4] ]

[{CONFIG_FILTERS}."Easy Plat Badges"]
{CONFIG_BASE} = ""
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Easy Plat Badges".{CONFIG_SUB_FILTERS}\
.{RangeField.SA_EASY_BADGES.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} =  [ [ 5, 50] ]

[{CONFIG_FILTERS}."Hard Plat Badges"]
{CONFIG_BASE} = ""
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Hard Plat Badges".{CONFIG_SUB_FILTERS}\
.{RangeField.SA_HARD_BADGES.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} =  [ [ 5, 50] ]

[{CONFIG_FILTERS}."With Bonus or Alternate"]
{CONFIG_BASE} = "Lead-ish"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."With Bonus or Alternate".{CONFIG_SUB_FILTERS}\
.{ListField.SUB_PATH.value}]
{CONFIG_INCLUDE} = false
{CONFIG_VALUES} = ["Representative"]

[{CONFIG_FILTERS}."E Std with Bonus or Alternate"]
{CONFIG_BASE} = "Lead-ish"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."E Standard with Bonus or Alternate".{CONFIG_SUB_FILTERS}.\
{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["E Standard"]

[{CONFIG_FILTERS}."E Std with Bonus or Alternate".{CONFIG_SUB_FILTERS}\
.{ListField.SUB_PATH.value}]
{CONFIG_INCLUDE} = false
{CONFIG_VALUES} = ["Representative"]

[{CONFIG_FILTERS}."E Standard"]
{CONFIG_BASE} = "Representative Lead-ish"
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

[{CONFIG_FILTERS}."E Std Low Plays".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[0, 12]]

[{CONFIG_FILTERS}."E Std Mid Plays"]
{CONFIG_BASE} = "E Standard 440"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."E Std Mid Plays".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[13,27]]

[{CONFIG_FILTERS}."E Std High Plays"]
{CONFIG_BASE} = "E Standard 440"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."E Std High Plays".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[28, 5000]]

[{CONFIG_FILTERS}."E Std Non Concert"]
{CONFIG_BASE} = "E Standard"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."E Std Non Concert".{CONFIG_SUB_FILTERS}.{RangeField.PITCH.value}]
{CONFIG_INCLUDE} = false
{CONFIG_RANGES} = [[439.5, 440.5]]

[{CONFIG_FILTERS}."E Std Non Concert".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[0,5000]]

[{CONFIG_FILTERS}."Drop D"]
{CONFIG_BASE} = "Representative Lead-ish"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Drop D".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["Drop D"]

[{CONFIG_FILTERS}."Eb Standard"]
{CONFIG_BASE} = "Representative Lead-ish"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Eb Standard".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["Eb Standard"]

[{CONFIG_FILTERS}."Eb Drop Db"]
{CONFIG_BASE} = "Representative Lead-ish"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Eb Drop Db".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["Eb Drop Db"]

[{CONFIG_FILTERS}."D Standard"]
{CONFIG_BASE} = "Representative Lead-ish"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."D Standard".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["D Standard"]

[{CONFIG_FILTERS}."D Drop C"]
{CONFIG_BASE} = "Representative Lead-ish"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."D Drop C".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["D Drop C"]

[{CONFIG_FILTERS}."Other Tunings"]
{CONFIG_BASE} = "Representative Lead-ish"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Other Tunings".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = false
{CONFIG_VALUES} = [
    "E Standard", "Drop D", "Eb Standard", "Eb Drop Db", "D Standard", "D Drop C"
]

# This all the standard (non-drop) starting at E Standard and dropping from there.
# Good for use with a drop tuning pedal.
[{CONFIG_FILTERS}."Standard Tunings"]
{CONFIG_BASE} = "Representative Lead-ish"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Standard Tunings".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = [
    "E Standard", "Eb Standard", "D Standard", "C# Standard", "C Standard",
    "B Standard", "Bb Standard", "A Standard",
]

[{CONFIG_FILTERS}."Standard 440 Tunings"]
{CONFIG_BASE} = "Standard Tunings"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Standard 440 Tunings".{CONFIG_SUB_FILTERS}.{RangeField.PITCH.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [ [439.5, 440.5 ] ]

[{CONFIG_FILTERS}."Standard Off 440 Tunings"]
{CONFIG_BASE} = "Standard Tunings"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Standard Off 440 Tunings".{CONFIG_SUB_FILTERS}.\
{RangeField.PITCH.value}]
{CONFIG_INCLUDE} = false
{CONFIG_RANGES} = [ [439.5, 440.5 ] ]

# This all the standard drop tunings starting at Drop D and dropping from there.
# Good for use with a drop tuning pedal.
[{CONFIG_FILTERS}."Drop Tunings"]
{CONFIG_BASE} = "Representative Lead-ish"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Drop Tunings".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = [
    "Drop D", "Eb Drop Db", "D Drop C", "C# Drop B", "C Drop A#", "B Drop A",
    "Bb Drop Ab", "A Drop G",
]

[{CONFIG_FILTERS}."Drop 440 Tunings"]
{CONFIG_BASE} = "Drop Tunings"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Drop 440 Tunings".{CONFIG_SUB_FILTERS}.{RangeField.PITCH.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [ [439.5, 440.5 ] ]

[{CONFIG_FILTERS}."Drop Off 440 Tunings"]
{CONFIG_BASE} = "Drop Tunings"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Drop Off 440 Tunings".{CONFIG_SUB_FILTERS}.{RangeField.PITCH.value}]
{CONFIG_INCLUDE} = false
{CONFIG_RANGES} = [ [439.5, 440.5 ] ]

# This anything that doesn't fit the two "standard tunings above"
# Good for use with a drop tuning pedal.
[{CONFIG_FILTERS}."Non standard Tunings"]
{CONFIG_BASE} = "Representative Lead-ish"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Non standard Tunings".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = false
{CONFIG_VALUES} = [
    "E Standard", "Eb Standard", "D Standard", "C# Standard", "C Standard",
    "B Standard", "Bb Standard", "A Standard",
    "Drop D", "Eb Drop Db", "D Drop C", "C# Drop B", "C Drop A#", "B Drop A",
    "Bb Drop Ab", "A Drop G",
]

[{CONFIG_FILTERS}."Standard Low Plays"]
{CONFIG_BASE} = "Standard 440 Tunings"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Standard Low Plays".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[0, 12]]

[{CONFIG_FILTERS}."Standard Mid Plays"]
{CONFIG_BASE} = "Standard 440 Tunings"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Standard Mid Plays".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[13, 27]]

[{CONFIG_FILTERS}."Standard High Plays"]
{CONFIG_BASE} = "Standard 440 Tunings"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Standard High Plays".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[28, 5000]]

[{CONFIG_FILTERS}."Drop Low Plays"]
{CONFIG_BASE} = "Drop 440 Tunings"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Drop Low Plays".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[0, 12]]

[{CONFIG_FILTERS}."Drop Mid Plays"]
{CONFIG_BASE} = "Drop 440 Tunings"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Drop Mid Plays".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[13, 27]]

[{CONFIG_FILTERS}."Drop High Plays"]
{CONFIG_BASE} = "Drop 440 Tunings"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Drop High Plays".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[28, 5000]]

[{CONFIG_FILTERS}."Played Count of 0 to 15"]
{CONFIG_BASE} = ""
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Played Count of 0 to 15".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[0, 15]]

[{CONFIG_FILTERS}."Artist test"]
{CONFIG_BASE} = ""
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Artist test".{CONFIG_SUB_FILTERS}.{ListField.ARTIST.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["The Rolling Stones", "Franz Ferdinand"]

[{CONFIG_FILTERS}."Lead-ish"]
{CONFIG_BASE} = ""
{CONFIG_MODE} = "OR"

[{CONFIG_FILTERS}."Lead-ish".{CONFIG_SUB_FILTERS}\
.{ListField.PATH.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["Lead"]

# This captures songs that have Rhythm and/or Bass, but no lead arrangement
[{CONFIG_FILTERS}."Lead-ish".{CONFIG_SUB_FILTERS}\
.{ListField.TITLE.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = [
    "Should I Stay or Should I Go",
    "What's Going On",
    "Blister in the Sun"
]

[{CONFIG_FILTERS}."Representative Lead-ish"]
{CONFIG_BASE} = "Lead-ish"
{CONFIG_MODE} = "OR"

[{CONFIG_FILTERS}."Representative Lead-ish".{CONFIG_SUB_FILTERS}\
.{ListField.SUB_PATH.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["Representative"]

# basic test filters for Bass, Rhythm.
[{CONFIG_FILTERS}."Bass or Rhythm"]
{CONFIG_BASE} = ""
{CONFIG_MODE} = "OR"

[{CONFIG_FILTERS}."Bass or Rhythm".{CONFIG_SUB_FILTERS}\
.{ListField.PATH.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["Bass", "Rhythm"]

[{CONFIG_FILTERS}."B or R E 440"]
{CONFIG_BASE} = "Bass or Rhythm"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."B or R E 440".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["E Standard"]

[{CONFIG_FILTERS}."B or R E 440".{CONFIG_SUB_FILTERS}.{RangeField.PITCH.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [ [439.5, 440.5 ] ]

[{CONFIG_FILTERS}."B or R E Low Plays"]
{CONFIG_BASE} = "B or R E 440"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."B or R E Low Plays".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[0, 12]]

[{CONFIG_FILTERS}."B or R E Mid Plays"]
{CONFIG_BASE} = "B or R E 440"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."B or R E Mid Plays".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[13,27]]

[{CONFIG_FILTERS}."B or R E High Plays"]
{CONFIG_BASE} = "B or R E 440"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."B or R E High Plays".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[28, 5000]]

# recursion testing
[{CONFIG_FILTERS}."Recursive1A"]
{CONFIG_BASE} = "Recursive1B"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Recursive1A".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["D Drop C"]

[{CONFIG_FILTERS}."Recursive1B"]
{CONFIG_BASE} = "Recursive1C"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Recursive1B".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["D Drop C"]

[{CONFIG_FILTERS}."Recursive1C"]
{CONFIG_BASE} = "Recursive1A"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Recursive1C".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["D Drop C"]

[{CONFIG_FILTERS}."Recursive2A"]
{CONFIG_BASE} = "Recursive2B"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Recursive2A".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["D Drop C"]

[{CONFIG_FILTERS}."Recursive2B"]
{CONFIG_BASE} = "Recursive2A"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Recursive2B".{CONFIG_SUB_FILTERS}.{ListField.TUNING.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["D Drop C"]
"""
# pylint: enable=no-member


class RSFilterError(Exception):
    """Provide base exception for song list filtering/SQL classes."""

    def __init__(self, message: Optional[str] = None) -> None:
        """Provide base exception for song list filtering/SQL classes."""
        if message is None:
            message = "An unspecified Rocksmith Filter Error has occurred."
        super().__init__(message)


class FilterMode(Enum):
    """Logical mode for combining sub-filters in a filter."""

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
            arrangements file, or the empty string if it has not been set. Deprecated,
            due for removal.
        steam_account_id {str} -- String representation of Steam account id, or
            the empty string if it has not been set yet.
        player_profile {str} -- The player profile name. Get returns the empty string if
            the player profile it has not been set yet.
        version {str} -- Future functionality for configuration changes.
        dlc_mtime {float} -- The last modified time of the most recently modified dlc
            found in the last scan for arrangement data. Used for checks for new dlc
            and for scans to update (rather than rebuild) the database.

    Note: changes in attribute names should be reflected in default TOML.
    """

    # instance variables
    CFSM_file_path: str = ""  # pylint: disable=invalid-name
    steam_account_id: str = ""
    player_profile: str = ""
    version: str = ""
    dlc_mtime: float = -1.0


@dataclass
class SubFilter:
    """Super class for sub-filters. This should not be instantiated.

    Public attributes:
        include {bool} -- Inclusion/exclusion criteria for filters. See subclasses for
            implementation specifics.

    Note: changes in attribute names should be reflected in default TOML.
    """

    # instance variables
    include: bool


@dataclass
class RangeSubFilter(SubFilter):
    """Range list for a range sub-filter.

    Public attributes/methods:
        ranges {List[List[float]]} -- A list of low/high value range pairs of the form:
            [[low1, high1], [low2, high2], ...]
        range_clause: returns the range clause and values tuple for the filter.

    The low/high pairs are used to build SQL IN BETWEEN queries.

    Implementation note: Pydantic will convert integer values to floats as part of
    constructor input validation. The range_clause method will try to convert integer
    values back to integer form before generating the range clause. However, if you
    are getting odd results from integer range queries, you may want to switch to
    floating values with appropriate small margins to insure integer values are
    captured correctly. For example [0.99, 2.01] to capture integer values in the
    range 1 to 2 inclusive. A future update may address this issues (requires
    pydantic to support dataclasses validators (0.24+?), converting the type of ranges
    to List[List[Union[int, float]]] and adding the appropriate validator).

    include implementation -- If True if the filter will return records where the
        field value lies int the specified ranges. If False, it will return records
        where the field value lies outside the specific ranges.

    Note: changes in attribute names should be reflected in default TOML.
    """

    # instance variables
    # When pydantic supports dataclass validators, change this to
    # ranges: List[List[Union[int, float]]]
    ranges: List[List[float]]

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
                list of values to be substituted into the clause.

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

            # temporary fix until I can validate and assign Union[int, float] correctly
            if low_val.is_integer() and high_val.is_integer():
                low_val = int(low_val)
                high_val = int(high_val)

            # and finally the SQL
            text_list.append(f"{field_type.value} {not_text}BETWEEN ? AND ?")
            ret_values.append(low_val)
            ret_values.append(high_val)

        sql_text = joiner.join(text_list)
        sql_text = f"({sql_text})"

        return sql_text, ret_values


@dataclass
class ListSubFilter(SubFilter):
    """Value list for a value sub-filter.

    Public attributes/methods:
        values {List[str} -- A list of string values that will be used to build the
            filter.
        list_clause: returns the list clause and values tuple for the filter.

    The values are used to build SQL IN queries.

    include implementation -- If True if the filter will return records where the
        field value matches any of the Filter values in the list. If False, it will
        return records where the field value does not match any of the Filter values.

    Note: changes in attribute names should be reflected in default TOML.
    """

    # instance variables
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

        values: List[str] = list()

        # Silently ignore invalid values (better then the old message of
        # failing unceremoniously)
        for value in self.values:
            if value in list_validator[field_type]:
                values.append(value)

        if not values:
            raise RSFilterError(
                f"WHERE clause error: Empty value list or invalid entries for "
                f"field type {field_type.value}."
            )

        if len(values) > 1:
            q_marks = "?, " * (len(values) - 1)
        else:
            q_marks = ""

        if self.include:
            not_text = ""
        else:
            not_text = "NOT "

        sql_text = f"{field_type.value} {not_text}IN ({q_marks}?)"

        return sql_text, values


@dataclass(config=EnumConfig)  # type: ignore
class Filter:
    """Provide configuration for a named filter.

    Public attributes:
        sub_filters {Dict[]} -- A dictionary of sub-filters that will be used to build
            the named filter. Each key/value pair should be typed as either:

                {RangeField: RangeSubFilter} or
                {ListField: ListSubFilter}

            The is the target database field for the sub-filter (query), and the value
            provides the sub-filter parameters (logic and values).

        base {str} -- The name of another named filter that will provides the base data
            for this filter.

        mode {FilterMode} -- Defines the logic for combining sub_filters. For
            FilterMode.AND, the filter will return only records that match all of the
            the sub-filters, while FilterMode.OR will return all records that match any
            of the sub-filters.

    Note: changes in attribute names should be reflected in default TOML.
    """

    # instance variables
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
                    except ValueError as v_e:
                        raise RSFilterError(
                            f"WHERE clause error: Invalid field type ({field_name}) "
                            f"for range type sub-filter.\nThis should be a member of "
                            f"RangeField Enum. "
                        ) from v_e

                    sub_text, range_list = sub_filter.range_clause(field_type)
                    where_values.extend(range_list)
                    sub_clauses.append(sub_text)

                elif isinstance(sub_filter, ListSubFilter):
                    try:
                        field_type = ListField(field_name)
                    except ValueError as v_e:
                        raise RSFilterError(
                            f"WHERE clause error: Invalid field type ({field_name}) "
                            f"for list type sub-filter.\nThis should be a member of "
                            f"ListField Enum."
                        ) from v_e

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
                ) from exc

        try:
            mode_text = FilterMode(self.mode).value
        except ValueError as v_e:
            raise RSFilterError(
                f"WHERE clause error: Invalid mode '{self.mode}''. Should be a member "
                f"of FilterMode Enum."
            ) from v_e

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
            # tomllib, tomli-w require binary file open/close for utf-8
            with toml_path.open("rb") as file_handle:
                data_dict = tomllib.load(file_handle)
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
            # Should be OK as python strings are all in UTF-8 already?
            configuration = replace(configuration, **tomllib.loads(DEFAULT_TOML))

        return configuration

    def save_toml(self, toml_path: Path) -> None:
        """Write configuration instance to toml file.

        Arguments:
            toml_path {Path} -- Path to the toml file.
        """
        # Hopefully using sorted with tomli-w allows me keep filter structures
        # together in the toml? If not, figure out what needs to be done to
        # emulate the previous version using toml.
        with toml_path.open("wb") as file_handle:
            toml = dict(sorted(asdict(self).items()))
            tomli_w.dump(toml, file_handle)
