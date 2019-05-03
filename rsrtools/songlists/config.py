#!/usr/bin/env python

"""Provide type aliases, shared strings and JSON schemas used by song list creator."""

from enum import Enum
from typing import Optional


# We use some SQL field information in constants, so declare these here (may move to a
# config later if used by other modules as well).
class SQLField(Enum):
    """Provide for abuse of the Enum class to set standard field types."""

    @classmethod
    def getsubclass(cls, value: str) -> "SQLField":
        """Create a subclass Enum value from a string value.

        This assumes that a) all SQLField subclass constants are strings and b) there
        are no repeated strings between the subclasses.
        """
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

    @classmethod
    def report_field_values(cls) -> None:
        """Print a list of the Enum values, which correspond to database field names."""
        print()
        print("Field names:")
        for field in cls:
            print(f"  {field.value}")
        print()


class ListField(SQLField):
    """Provide Enum of list type SQL fields that can be used as filters."""

    # list types. Automatically validated before use.
    # RSSongId  was the name I came up with for rsrtools. May need to migrate to SongKey
    SONG_KEY = "SongKey"
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
