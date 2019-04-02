#!/usr/bin/env python3
"""Provides a default configuration set for the song list creator."""

import rsrtools.songlists.sldefs as SLDEF

DEFAULT_SL_CONFIG = f'''
{{
  "{SLDEF.DB_CONFIG}": {{
    "{SLDEF.CFSM_FILE}": "",
    "{SLDEF.STEAM_USER_ID}": "",
    "{SLDEF.PLAYER_PROFILE}": ""
  }},
  "{SLDEF.FILTER_SET_DICT}": {{
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
  "{SLDEF.FILTER_DICT}": {{
    "Easy E Plat Badge in progress": {{
      "QueryFields": [
        {{
          "Field": "SA_EASY_BADGES",
          "Include": true,
          "Ranges": [
            [
              1,
              4
            ]
          ]
        }}
      ]
    }},
    "E Standard": {{
      "QueryFields": [
        {{
          "Field": "TUNING",
          "Include": true,
          "Values": [
            "E Standard"
          ]
        }}
      ]
    }},
    "E Standard 440": {{
      "BaseFilter": "E Standard",
      "QueryFields": [
        {{
          "Field": "PITCH",
          "Include": true,
          "Ranges": [
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
      "QueryFields": [
        {{
          "Field": "PLAYED_COUNT",
          "Include": true,
          "Ranges": [
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
      "QueryFields": [
        {{
          "Field": "PLAYED_COUNT",
          "Include": true,
          "Ranges": [
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
      "QueryFields": [
        {{
          "Field": "PLAYED_COUNT",
          "Include": true,
          "Ranges": [
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
      "QueryFields": [
        {{
          "Field": "PITCH",
          "Include": false,
          "Ranges": [
            [
              439.5,
              440.5
            ]
          ]
        }},
        {{
          "Field": "PLAYED_COUNT",
          "Include": true,
          "Ranges": [
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
      "QueryFields": [
        {{
          "Field": "TUNING",
          "Include": true,
          "Values": [
            "Drop D"
          ]
        }}
      ]
    }},
    "Eb Standard": {{
      "BaseFilter": "Not Bass, Rhythm",
      "QueryFields": [
        {{
          "Field": "TUNING",
          "Include": true,
          "Values": [
            "Eb Standard"
          ]
        }}
      ]
    }},
    "Eb Drop Db": {{
      "BaseFilter": "Not Bass, Rhythm",
      "QueryFields": [
        {{
          "Field": "TUNING",
          "Include": true,
          "Values": [
            "Eb Drop Db"
          ]
        }}
      ]
    }},
    "D Standard": {{
      "BaseFilter": "Not Bass, Rhythm",
      "QueryFields": [
        {{
          "Field": "TUNING",
          "Include": true,
          "Values": [
            "D Standard"
          ]
        }}
      ]
    }},
    "D Drop C": {{
      "BaseFilter": "Not Bass, Rhythm",
      "QueryFields": [
        {{
          "Field": "TUNING",
          "Include": true,
          "Values": [
            "D Drop C"
          ]
        }}
      ]
    }},
    "Other Tunings": {{
      "BaseFilter": "Not Bass, Rhythm",
      "QueryFields": [
        {{
          "Field": "TUNING",
          "Include": false,
          "Values": [
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
      "QueryFields": [
        {{
          "Field": "PLAYED_COUNT",
          "Include": true,
          "Ranges": [
            [
              1,
              15
            ]
          ]
        }}
      ]
    }},
    "Artist test": {{
      "QueryFields": [
        {{
          "Field": "ARTIST",
          "Include": true,
          "Values": [
            "The Rolling Stones",
            "Franz Ferdinand"
          ]
        }}
      ]
    }},
    "Not Bass, Rhythm": {{
      "QueryFields": [
        {{
          "Field": "ARRANGEMENT_NAME",
          "Include": false,
          "Values": [
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
