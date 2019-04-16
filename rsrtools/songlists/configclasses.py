#!/usr/bin/env python3

"""Provide song list creator configuration dataclasses and supporting elements."""

import toml

from enum import Enum
from pathlib import Path
from typing import Dict, List, Union

from dataclasses import field, asdict, replace
from pydantic.dataclasses import dataclass

from rsrtools import __version__ as RSRTOOLS_VERSION
from rsrtools.songlists.config import RangeField, ListField

# These string constants are used to parameterise the default TOML.
# They should be the same as the attribute names in the dataclasses below.
CONFIG_SONG_LISTS = "song_lists"
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
DEFAULT_TOML = f'''\
[{CONFIG_SONG_LISTS}]
"E Standard" = [
  "E Std 1",
  "E Std 2",
  "E Std 3",
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

[{CONFIG_FILTERS}."Easy E Plat Badge in progress"]
{CONFIG_BASE} = ""
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Easy E Plat Badge in progress".{CONFIG_SUB_FILTERS}\
.{RangeField.SA_EASY_BADGES.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} =  [ [ 0.95, 4.05] ]

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

[{CONFIG_FILTERS}."E Std 1"]
{CONFIG_BASE} = "E Standard 440"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."E Std 1".{CONFIG_SUB_FILTERS}.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[1, 12]]

[{CONFIG_FILTERS}."E Std 2"]
{CONFIG_BASE} = "E Standard 440"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."E Std 2".{CONFIG_SUB_FILTERS}.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[13,27]]

[{CONFIG_FILTERS}."E Std 3"]
{CONFIG_BASE} = "E Standard 440"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."E Std 3".{CONFIG_SUB_FILTERS}.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[27, 27]]

[{CONFIG_FILTERS}."E Std Non Concert"]
{CONFIG_BASE} = "E Standard"
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."E Std Non Concert".{CONFIG_SUB_FILTERS}.{RangeField.PITCH.value}]
{CONFIG_INCLUDE} = false
{CONFIG_RANGES} = [[439.5, 440.5]]

[{CONFIG_FILTERS}."E Std Non Concert".{CONFIG_SUB_FILTERS}\
.{RangeField.PLAYED_COUNT.value}]
{CONFIG_INCLUDE} = true
{CONFIG_RANGES} = [[1,5000]]

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
{CONFIG_RANGES} = [[1, 15]]

[{CONFIG_FILTERS}."Artist test"]
{CONFIG_BASE} = ""
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Artist test".{CONFIG_SUB_FILTERS}.{ListField.ARTIST.value}]
{CONFIG_INCLUDE} = true
{CONFIG_VALUES} = ["The Rolling Stones", "Franz Ferdinand"]

[{CONFIG_FILTERS}."Not Bass, Rhythm"]
{CONFIG_BASE} = ""
{CONFIG_MODE} = "AND"

[{CONFIG_FILTERS}."Not Bass, Rhythm".{CONFIG_SUB_FILTERS}\
.{ListField.ARRANGEMENT_NAME.value}]
{CONFIG_INCLUDE} = false
{CONFIG_VALUES} = ["Bass", "Rhythm", "Rhythm1", "Rhythm2"]
'''
# pylint: enable=no-member


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


@dataclass
class Configuration:
    """Provide general configuration settings, filter definitions and filter sets.

    Public attributes:
        settings {Settings} -- General configuration settings.
        filters {Dict[str, Filter]} -- Filter definitions, where the key is the filter
            name.
        song_lists {Dict[str, List[str]]} -- Song list definition, where the key is the
            name for song list, and the elements of the song list are the filter names
            for generating the song list (up to six names per list).

    Note: changes in attribute names should be reflected in default TOML.
    """

    # Always create a default instance/list/dictionary.
    settings: Settings = Settings()
    # Filters before filter sets to allow future validation of filter sets.
    filters: Dict[str, Filter] = field(default_factory=dict)
    song_lists: Dict[str, List[str]] = field(default_factory=dict)

    @classmethod
    def load_toml(cls, toml_path: Path) -> 'Configuration':
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

        if not configuration.filters and not configuration.song_lists:
            # No filter configurations, so set up a default set.
            # This will apply if data is missing or for a default setup.
            configuration = replace(
                configuration, **toml.loads(DEFAULT_TOML)
            )

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
