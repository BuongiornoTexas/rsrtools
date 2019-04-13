#!/usr/bin/env python3
"""Provides a default configuration set for the song list creator."""

import rsrtools.songlists.config as config
from rsrtools.songlists.config import ListField, RangeField

DEFAULT_SONG_LIST_CONFIG = f'''
{{
  "{config.DB_CONFIG_KEY}": {{
    "{config.CFSM_FILE_KEY}": "",
    "{config.STEAM_USER_ID_KEY}": "",
    "{config.PLAYER_PROFILE_KEY}": ""
  }},
  "{config.FILTER_SET_DICT_KEY}": {{
    "E Standard": [
      "E Std 1",
      "E Std 2",
      "E Std 3",
      "E Std Non Concert",
      "",
      "Easy E Plat Badge in progress"
    ],
    "Non E Std Tunings": [
      "Drop D",
      "Eb Standard",
      "Eb Drop Db",
      "D Standard",
      "D Drop C",
      "Other Tunings"
    ],
    "Testing": [
      "Artist test",
      "Played Count of 1 to 15"
    ]
  }},
  "{config.FILTER_DICT_KEY}": {{
    "Easy E Plat Badge in progress": {{
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{RangeField.SA_EASY_BADGES.value}",
          "{config.INCLUDE_KEY}": true,
          "{config.RANGES_KEY}": [
            [
              1,
              4
            ]
          ]
        }}
      ]
    }},
    "E Standard": {{
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{ListField.TUNING.value}",
          "{config.INCLUDE_KEY}": true,
          "{config.VALUES_KEY}": [
            "E Standard"
          ]
        }}
      ]
    }},
    "E Standard 440": {{
      "BaseFilter": "E Standard",
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{RangeField.PITCH.value}",
          "{config.INCLUDE_KEY}": true,
          "{config.RANGES_KEY}": [
            [
              439.5,
              440.5
            ]
          ]
        }}
      ]
    }},
    "E Std 1": {{
      "BaseFilter": "E Standard 440",
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{RangeField.PLAYED_COUNT.value}",
          "{config.INCLUDE_KEY}": true,
          "{config.RANGES_KEY}": [
            [
              1,
              12
            ]
          ]
        }}
      ]
    }},
    "E Std 2": {{
      "BaseFilter": "E Standard 440",
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{RangeField.PLAYED_COUNT.value}",
          "{config.INCLUDE_KEY}": true,
          "{config.RANGES_KEY}": [
            [
              13,
              27
            ]
          ]
        }}
      ]
    }},
    "E Std 3": {{
      "BaseFilter": "E Standard 440",
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{RangeField.PLAYED_COUNT.value}",
          "{config.INCLUDE_KEY}": true,
          "{config.RANGES_KEY}": [
            [
              27,
              27
            ]
          ]
        }}
      ]
    }},
    "E Std Non Concert": {{
      "BaseFilter": "E Standard",
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{RangeField.PITCH.value}",
          "{config.INCLUDE_KEY}": false,
          "{config.RANGES_KEY}": [
            [
              439.5,
              440.5
            ]
          ]
        }},
        {{
          "{config.FIELD_NAME_KEY}": "{RangeField.PLAYED_COUNT.value}",
          "{config.INCLUDE_KEY}": true,
          "{config.RANGES_KEY}": [
            [
              1,
              5000
            ]
          ]
        }}
      ]
    }},
    "Drop D": {{
      "BaseFilter": "Not Bass, Rhythm",
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{ListField.TUNING.value}",
          "{config.INCLUDE_KEY}": true,
          "{config.VALUES_KEY}": [
            "Drop D"
          ]
        }}
      ]
    }},
    "Eb Standard": {{
      "BaseFilter": "Not Bass, Rhythm",
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{ListField.TUNING.value}",
          "{config.INCLUDE_KEY}": true,
          "{config.VALUES_KEY}": [
            "Eb Standard"
          ]
        }}
      ]
    }},
    "Eb Drop Db": {{
      "BaseFilter": "Not Bass, Rhythm",
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{ListField.TUNING.value}",
          "{config.INCLUDE_KEY}": true,
          "{config.VALUES_KEY}": [
            "Eb Drop Db"
          ]
        }}
      ]
    }},
    "D Standard": {{
      "BaseFilter": "Not Bass, Rhythm",
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{ListField.TUNING.value}",
          "{config.INCLUDE_KEY}": true,
          "{config.VALUES_KEY}": [
            "D Standard"
          ]
        }}
      ]
    }},
    "D Drop C": {{
      "BaseFilter": "Not Bass, Rhythm",
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{ListField.TUNING.value}",
          "{config.INCLUDE_KEY}": true,
          "{config.VALUES_KEY}": [
            "D Drop C"
          ]
        }}
      ]
    }},
    "Other Tunings": {{
      "BaseFilter": "Not Bass, Rhythm",
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{ListField.TUNING.value}",
          "{config.INCLUDE_KEY}": false,
          "{config.VALUES_KEY}": [
            "E Standard",
            "Drop D",
            "Eb Standard",
            "Eb Drop Db",
            "D Standard",
            "D Drop C"
          ]
        }}
      ]
    }},
    "Played Count of 1 to 15": {{
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{RangeField.PLAYED_COUNT.value}",
          "{config.INCLUDE_KEY}": true,
          "{config.RANGES_KEY}": [
            [
              1,
              15
            ]
          ]
        }}
      ]
    }},
    "Artist test": {{
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{ListField.ARTIST.value}",
          "{config.INCLUDE_KEY}": true,
          "{config.VALUES_KEY}": [
            "The Rolling Stones",
            "Franz Ferdinand"
          ]
        }}
      ]
    }},
    "Not Bass, Rhythm": {{
      "{config.FIELD_FILTER_LIST_KEY}": [
        {{
          "{config.FIELD_NAME_KEY}": "{ListField.ARRANGEMENT_NAME.value}",
          "{config.INCLUDE_KEY}": false,
          "{config.VALUES_KEY}": [
            "Bass",
            "Rhythm",
            "Rhythm1",
            "Rhythm2"
          ]
        }}
      ]
    }}
  }}
}}
'''
