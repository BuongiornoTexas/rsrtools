#!/usr/bin/env python3

"""Provide type aliases, shared strings and JSON schemas used by song list creator."""

from typing import Dict, List, Union

# type aliases
DBConfig = Dict[str, str]

FilterSet = List[str]
FilterSetDict = Dict[str, FilterSet]

FilterField = str
FilterInclude = bool
FilterValue = str
FilterRange = List[List[Union[float, int]]]
FilterQuery = Dict[str,
    Union[FilterField, FilterInclude, FilterValue, FilterRange]
]
BaseFilter = str
# Filters dict - can provide a base filter name or Filter definition.
FilterDict = Dict[str, Union[BaseFilter, FilterQuery]]

# The first Union describes the "db_config" entry
JSONConfig = Dict[str, Union[DBConfig, FilterSetDict, FilterDict]]

# Setup strings for config, should be consistent with type aliases and 
# json schema where applicable (lists are anonymous in schema).
DB_CONFIG = "db_config"
CFSM_FILE = "CFSM_Arrangement_File"
STEAM_USER_ID = "steam_user_id"
PLAYER_PROFILE = "player_profile"

FILTER_SET_DICT = "FilterSetDict"

FILTER_DICT = "FilterDict"

# json schema for config file. Should have a one for one correspondence with
# type aliases above.
CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        f"{DB_CONFIG}": {
            "type": "object",
            "description": "Dictionary of configuration parameters",
            "properties": {
                f"{CFSM_FILE}": {"type": "string"},
                f"{STEAM_USER_ID}": {"type": "string"},
                f"{PLAYER_PROFILE}": {"type": "string"},
            },
        },
        f"{FILTER_SET_DICT}": {
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
        f"{FILTER_DICT}": {
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
                                    "minItems": 1,
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
                                        "maxItems": 2,
                                    },
                                },
                            },
                            "required": ["Field", "Include"],
                            "oneOf": [
                                {"required": ["Values"]},
                                {"required": ["Ranges"]},
                            ],
                        },
                    },
                },
                "required": ["QueryFields"],
            },
        },
    },
    "required": [f"{FILTER_DICT}", f"{FILTER_SET_DICT}"],
}
