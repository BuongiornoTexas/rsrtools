#!/usr/bin/env python3
"""Provide shared constants and definitions for Rocksmith files and profiles."""

from enum import Enum

MAX_SONG_LIST_COUNT = 6


class ProfileKey(Enum):
    """Provides a list of Rocksmith profile key strings."""

    FAVORITES_LIST = "FavoritesList"
    FAVORITES_LIST_ROOT = "FavoritesListRoot"
    PLAY_NEXTS = "Playnexts"
    PLAYED_COUNT = "PlayedCount"
    SONGS = "Songs"
    SONG_LISTS = "SongLists"
    SONG_LISTS_ROOT = "SongListsRoot"
    SONG_SA = "SongSA"
    STATS = "Stats"
