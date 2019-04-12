#!/usr/bin/env python3

"""Provide type aliases, shared strings and JSON schemas used by song list creator."""

from enum import Enum
from typing import Dict, List, Optional, Union

# type aliases
DBConfig = Dict[str, str]

FilterSet = List[str]
FilterSetDict = Dict[str, FilterSet]

FilterFieldName = str
FilterInclude = bool
FilterValues = List[str]
FilterRanges = List[List[Union[float, int]]]
FieldFilter = Dict[
    str, Union[FilterFieldName, FilterInclude, FilterValues, FilterRanges]
]
FieldFilterList = List[FieldFilter]
BaseFilter = str
# Contains the definition for a single filter: FieldFilterList + Optional  BaseFilter
NamedFilter = Dict[str, Union[BaseFilter, FieldFilterList]]
# Filters dict: Collection of Named Filter Definitions
FilterDict = Dict[str, NamedFilter]

# The first Union describes the "db_config" entry
JSONConfig = Dict[str, Union[DBConfig, FilterSetDict, FilterDict]]

# Setup dictionary key strings for config, should be consistent with type aliases and
# json schema where applicable (lists are anonymous in schema).
DB_CONFIG_KEY = "DBConfig"
CFSM_FILE_KEY = "CFSMArrangementFile"
STEAM_USER_ID_KEY = "SteamUserID"
PLAYER_PROFILE_KEY = "PlayerProfile"

FILTER_SET_DICT_KEY = "FilterSetDict"

FIELD_NAME_KEY = "Field"
INCLUDE_KEY = "Include"
VALUES_KEY = "Values"
RANGES_KEY = "Ranges"
FIELD_FILTER_LIST_KEY= "FieldFilterList"
FILTER_DICT_KEY = "FilterDict"

# json schema for config file. Should have a one for one correspondence with
# type aliases above.
CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        DB_CONFIG_KEY: {
            "type": "object",
            "description": "Dictionary of configuration parameters",
            "properties": {
                CFSM_FILE_KEY: {"type": "string"},
                STEAM_USER_ID_KEY: {"type": "string"},
                PLAYER_PROFILE_KEY: {"type": "string"},
            },
        },
        FILTER_SET_DICT_KEY: {
            "type": "object",
            "description": "Dictionary of filter sets.",
            "additionalProperties": {
                "type": "array",
                "description": "List of song list filters (empty string skips a list).",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 6,
            },
        },
        FILTER_DICT_KEY: {
            "type": "object",
            "description": "Dictionary of filters.",
            "additionalProperties": {
                "type": "object",
                "description": "Dictionary for definition of a single filter",
                "properties": {
                    # Note: we only want one or zero basefilters, so keep this
                    # separate from the repeatable subfilters
                    "BaseFilter": {"type": "string"},
                    FIELD_FILTER_LIST_KEY: {
                        "type": "array",
                        "description": "List of field filter dictionaries.",
                        "items": {
                            "type": "object",
                            "description": "Single field filter dictionary.",
                            "minItems": 1,
                            "properties": {
                                FIELD_NAME_KEY: {"type": "string"},
                                INCLUDE_KEY: {"type": "boolean"},
                                VALUES_KEY: {
                                    "type": "array",
                                    "description": "List of string values.",
                                    "items": {"type": "string"},
                                    "minItems": 1,
                                },
                                RANGES_KEY: {
                                    "type": "array",
                                    "description": "Array of pairs of low/high values.",
                                    "minItems": 1,
                                    "items": {
                                        "description": "Array of low high/values.",
                                        "type": "array",
                                        "items": {"type": "number", "minimum": 0},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                },
                            },
                            "required": [FIELD_NAME_KEY, INCLUDE_KEY],
                            "oneOf": [
                                {"required": [VALUES_KEY]},
                                {"required": [RANGES_KEY]},
                            ],
                        },
                    },
                },
                "required": [FIELD_FILTER_LIST_KEY],
            },
        },
    },
    "required": [FILTER_DICT_KEY, FILTER_SET_DICT_KEY],
}

# We use some SQL field information in constants, so declare these here (may move to a
# config later if used by other modules as well).
class SQLField(Enum):
    """Provide for abuse of the Enum class to set standard field types."""

    @classmethod
    def getsubclass(cls, value: str) -> 'SQLField':
        """Create a subclass Enum value from a string value.
        
        This assumes that a) all SQLField subclass constants are strings and b) there
        are no repeated strings between the subclasses.""" 
        ret_val: Optional[SQLField] = None
        for field_class in cls.__subclasses__():
            try:
                ret_val = field_class(value)
                # found it if we got here!
                break
            except ValueError:
                # skip to the next subclass
                pass

        if ret_val is None:
            raise ValueError(f"{value} is a not a valid subclass of SQLField")

        return ret_val

class ListField(SQLField):
    """Provide Enum of list type SQL fields that can be used as filters."""

    # list types. Automatically validated before use.
    # RSSongId  was the name I came up with for rsrtools. May need to migrate to SongKey
    RS_SONG_ID = "RSSongId"
    TUNING = "Tuning"
    ARRANGEMENT_NAME = "ArrangementName"
    ARRANGEMENT_ID = "ArrangementId"
    ARTIST = "Artist"
    TITLE = "Title"
    ALBUM = "Album"


class RangeField(SQLField):
    """Provide Enum of numerical type SQL fields names that can be used as filters."""

    # list types. Automatically validated before use.
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
