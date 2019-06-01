#!/usr/bin/env python

"""Provide database scanner for PSARC files."""

# cSpell:ignore steamapps, stat, rpartition, isdigit, CGCGGE, CGCGBE, firekorn
# cSpell:ignore CACGCE, EADG, etudes

import simplejson

from sys import platform

from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from rsrtools.songlists.config import ListField, RangeField
from rsrtools.files.steam import SteamAccounts, load_vdf
from rsrtools.files.welder import Welder

LIBRARY_VDF = "steamapps/libraryfolders.vdf"
ROCKSMITH_PATH = "steamapps/common/Rocksmith2014"
DLC_PATH = "dlc"
MAC_PSARC = "_m.psarc"
WIN_PSARC = "_p.psarc"
RS_COMPATABILITY = "rs1compatibility"
RS_INTERNAL = "Rocksmith Internal"
INTERNAL_SONGS = (
    "manifests/songs/rs2tails_combo.json"
    "manifests/songs/rs2levelbreak_combo4.json"
    "manifests/songs/rs2levelbreak_combo3.json"
    "manifests/songs/rs2levelbreak_combo2.json"
    "manifests/songs/rs2levelbreak_combo.json"
    "manifests/songs/rs2chordnamestress_rhythm.json"
    "manifests/songs/rs2arpeggios_combo.json"
)

track_types = {"_lead": "Lead", "_bass": "Bass", "_rhythm": "Rhythm", "_combo": "Combo"}

# E standard repeated here, as Rocksmith can be interally
# inconsistent.
# Tuning names taken from Rocksmith Song Custom Toolkit (Thanks firekorn)
# https://github.com/rscustom/rocksmith-custom-song-toolkit/blob/master/ ...
# RocksmithToolkitLib/RocksmithToolkitLib.TuningDefinition.xml
tuning_db = {
    # Standards
    "000000": "E Standard",
    "-200000": "Drop D",
    "-1-1-1-1-1-1": "Eb Standard",
    "-3-1-1-1-1-1": "Eb Drop Db",
    "-2-2-2-2-2-2": "D Standard",
    "-4-2-2-2-2-2": "D Drop C",
    "-3-3-3-3-3-3": "C# Standard",
    "-4-4-4-4-4-4": "C Standard",
    "-200-1-2-2": "Open D",
    "002220": "Open A",
    "-2-2000-2": "Open G",
    "022100": "Open E",
    # Custom tunings
    "111111": "F Standard",
    "-5-5-5-5-5-5": "B Standard",
    "-6-6-6-6-6-6": "Bb Standard",
    "-7-7-7-7-7-7": "A Standard",
    # Toolkit had -7 for this, think it should be -8
    "-8-8-8-8-8-8": "Ab Standard",
    # Drop tunings
    "-5-3-3-3-3-3": "C# Drop B",
    "-6-4-4-4-4-4": "C Drop A#",
    "-7-5-5-5-5-5": "B Drop A",
    "-8-6-6-6-6-6": "Bb Drop Ab",
    "-9-7-7-7-7-7": "A Drop G",
    # Double drops
    "-20000-2": "Double Drop D",
    "-3-1-1-1-1-3": "Double Drop Db",
    "-4-2-2-2-2-4": "Double Drop C",
    "-5-3-3-3-3-5": "Double Drop B",
    "-6-4-4-4-4-6": "Double Drop A#",
    # Open tuning
    "-200-21-2": "Open Dm7",
    "-4-2-20-40": "CGCGGE",
    "-4-2-2000": "CGCGBE",
    "0-2000-2": "Open Em9",
    "-4-4-2-2-2-4": "Open F",
    "-2000-2-2": "DADGAD",
    "-40-2010": "CACGCE",
    "-20023-2": "DADADd",
    # Variation around std tuning
    "0000-20": "EADGAe",
    "000012": "All Fourth",
    # 6 Strings Bass tuning
    "-5-5-5-5-4-4": "B standard 6 Strings Bass",
    "-6-6-6-6-5-5": "Bb standard 6 Strings Bass",
    "-7-7-7-7-6-6": "A standard 6 Strings Bass",
    "-8-8-8-8-7-7": "Ab standard 6 Strings Bass",
    "-7-5-5-5-4-4": "B Drop A 6 Strings Bass",
    "-8-6-6-6-5-5": "Bb Drop Ab 6 Strings Bass",
    "-9-7-7-7-6-6": "A Drop G 6 Strings Bass",
}


def rocksmith_path() -> Path:
    """Return the Rocksmith path."""
    steam_path = SteamAccounts.get_steam_path()

    try:
        rs_path: Optional[Path] = steam_path.joinpath(ROCKSMITH_PATH).resolve(True)
    except FileNotFoundError:
        # So it's not in the default location.
        rs_path = None

    if rs_path is None:
        try:
            library_info: Optional[Dict[Any, Any]] = load_vdf(
                steam_path.joinpath(LIBRARY_VDF), True
            )
        except FileNotFoundError:
            library_info = None

        if library_info is not None:
            for i in range(1, 8):
                path_str = library_info["LibraryFolders"].get(str(i), "")
                try:
                    rs_path = Path(path_str).joinpath(ROCKSMITH_PATH).resolve(True)
                    break
                except FileNotFoundError:
                    pass

    if rs_path is None:
        raise FileNotFoundError("Can't find Rocksmith installation.")

    return rs_path


def newer_songs(last_modifed: float) -> bool:
    """Check Rocksmith dlc against a timestamp and return True if new songs found.

    Arguments:
        last_modifed {float} -- The timestamp to check.

    Returns:
        bool -- True if at least one song file (psarc) has a timestamp newer than
            last_modified.

    """
    if platform == "win32":
        find_files = WIN_PSARC
    elif platform == "darwin":
        find_files = MAC_PSARC

    for scan_path in rocksmith_path().joinpath(DLC_PATH).glob("**/*" + find_files):
        if scan_path.stat().st_mtime > last_modifed:
            return True

    return False


class Scanner:
    """Provide arrangement iterator for filling the arrangements table in ArrangementDB.

    This class has one public member, db_entries, which provides an iterator that
    scans Rocksmith psarc files to yield value dictionaries for the arrangements table.
    """

    # Rocksmith install path
    _rs_path: Path
    # The file being scanned by _arrangement_rows
    _current_psarc: Path

    def __init__(self) -> None:
        """Get the Rocksmith directory for scanner iterator."""
        self._rs_path = rocksmith_path()

    @staticmethod
    def _get_tuning(attributes: Dict[str, Any]) -> str:
        """Return tuning from "Attributes" dictionary.

        Arguments:
            attributes {dict} -- The attributes dictionary that will be checked for
                the path.
        """
        # can't rely on standard tuning - ignore this and rely on strings.
        # std_tuning = (attributes["ArrangementProperties"]["standardTuning"] == 1)
        sub_dict = attributes["Tuning"]
        tuning = "".join(
            [
                str(sub_dict[x])
                for x in (
                    "string0",
                    "string1",
                    "string2",
                    "string3",
                    "string4",
                    "string5",
                )
            ]
        )

        if tuning in tuning_db:
            return tuning_db[tuning]
        else:
            return "Unknown Custom Tuning"

    @staticmethod
    def _get_sub_path(attributes: Dict[str, Any]) -> str:
        """Return sub_path from "Attributes" dictionary.

        Arguments:
            attributes {dict} -- The attributes dictionary that will be checked for
                the path.
        """
        sub_dict = attributes["ArrangementProperties"]
        represent = sub_dict["represent"] == 1
        bonus = sub_dict["bonusArr"] == 1

        if represent and not bonus:
            return "Representative"

        if not represent and bonus:
            return "Bonus"

        if not represent and not bonus:
            return "Alternative"

        raise ValueError("Invalid sub-path (both representative and bonus?).")

    @staticmethod
    def _get_path(attributes: Dict[str, Any]) -> str:
        """Return path from "Attributes" dictionary.

        Arguments:
            attributes {dict} -- The attributes dictionary that will be checked for
                the path.
        """
        # Note that the "ArrangementName" is completely misleading here. E.g. A Rhythm
        # arrangement could have a lead path!
        sub_dict = attributes["ArrangementProperties"]

        # Deal with special cases:
        if (sub_dict["routeMask"] == 7) and (attributes["SongKey"] == "RS2LevelBreak"):
            # Not sure where it is used, but this is a Rocksmith internal
            return "All"

        lead = (sub_dict["pathLead"] == 1) and (sub_dict["routeMask"] == 1)
        rhythm = (sub_dict["pathRhythm"] == 1) and (sub_dict["routeMask"] == 2)
        bass = (sub_dict["pathBass"] == 1) and (sub_dict["routeMask"] == 4)

        if int(lead) + int(rhythm) + int(bass) != 1:
            raise ValueError(
                "Arrangement either specifies no path or more than one path."
            )

        if lead:
            return "Lead"
        if rhythm:
            return "Rhythm"

        return "Bass"

    def _internal_data(self, data: bytes, last_modified: float) -> Dict[str, Any]:
        """Read attribute from json data, create Rocksmith internal arrangement row.

        Arguments:
            data {bytes} -- Arrangement JSON data string in bytes format.
            last_modified {float} -- Last modification time of the underlying psarc
                file.

        Returns:
            Dict[str, Any] -- Arrangement values - see db_entries.

        This is hard coded given the rows have a small number of entries and
        doing the mapping is irritating.

        """
        arrangement: Dict[str, Any] = dict()
        json = simplejson.loads(data.decode())

        sub_dict = json["Entries"]
        if len(sub_dict) != 1:
            raise IndexError(
                "Arrangement file with no or multiple Entries (must have one only)."
            )

        for arr_id in sub_dict.keys():
            pass

        arrangement[ListField.ARRANGEMENT_ID.value] = arr_id

        # Provide something modestly useful in song key, title in case anyone goes
        # digging. Cross check arr_id.
        if json["InsertRoot"].startswith("Static.SessionMode"):
            # Session mode entries don't have a persistent ID, so can't cross check.
            arrangement[ListField.SONG_KEY.value] = "Session Mode Entry"

        else:
            sub_dict = sub_dict[arr_id]["Attributes"]

            if arr_id != sub_dict["PersistentID"]:
                raise ValueError("Inconsistent persistent id data in Arrangement file.")

            if json["InsertRoot"].startswith("Static.Guitars"):
                arrangement[ListField.SONG_KEY.value] = "Guitar Entry"
            else:
                try:
                    arrangement[ListField.SONG_KEY.value] = sub_dict["SongKey"]
                except KeyError:
                    arrangement[ListField.SONG_KEY.value] = sub_dict["LessonKey"]

        arrangement[ListField.TITLE.value] = arrangement[ListField.SONG_KEY.value]

        # Dummy entries from here - the goal is just to know if RS is
        # using an arrangement id or not.
        arrangement[ListField.ARRANGEMENT_NAME.value] = RS_INTERNAL
        arrangement[ListField.PATH.value] = RS_INTERNAL
        arrangement[ListField.SUB_PATH.value] = RS_INTERNAL
        arrangement[ListField.TUNING.value] = RS_INTERNAL
        arrangement[RangeField.PITCH.value] = 440.0
        arrangement[ListField.ARTIST.value] = RS_INTERNAL
        arrangement[ListField.ALBUM.value] = RS_INTERNAL
        arrangement[RangeField.YEAR.value] = 0.0
        arrangement[RangeField.TEMPO.value] = 0.0
        arrangement[RangeField.NOTE_COUNT.value] = 0
        arrangement[RangeField.SONG_LENGTH.value] = 0
        arrangement[RangeField.LAST_MODIFIED.value] = last_modified

        return arrangement

    def _arrangement_data(
        self, data: bytes, expect_name: str, last_modified: float
    ) -> Dict[str, Any]:
        """Convert json data into dictionary suitable for loading into arrangement row.

        Arguments:
            data {bytes} -- Arrangement JSON data string in bytes format.
            expect_name {str} -- The expected name for the arrangement. An error will
                raised if this name is not found in the JSON.
            last_modified {float} -- Last modification time of the underlying psarc
                file.

        Returns:
            Dict[str, Any] -- Arrangement values - see db_entries.

        This is hard coded given the rows have a small number of entries and
        doing the mapping is irritating.

        """
        arrangement: Dict[str, Any] = dict()
        json = simplejson.loads(data.decode())

        sub_dict = json["Entries"]
        if len(sub_dict) != 1:
            raise IndexError(
                "Arrangement file with no or multiple Entries (must have one only)."
            )

        for arr_id in sub_dict.keys():
            pass

        sub_dict = sub_dict[arr_id]["Attributes"]

        if arr_id != sub_dict["PersistentID"]:
            raise ValueError("Inconsistent persistent id data in Arrangement file.")
        arrangement[ListField.ARRANGEMENT_ID.value] = arr_id

        if not sub_dict["FullName"].endswith(expect_name):
            err_str = sub_dict["FullName"]
            raise ValueError(
                f"Arrangement FullName suffix in JSON does not match JSON arrangement"
                "name in file."
                f"\n   JSON FullName: {err_str}"
                f"\n   Expected suffix: {expect_name}"
            )
        # This could be Lead[1-9], Rhythm[1-9], Bass[1-9] or Combo[1-9]
        arrangement[ListField.ARRANGEMENT_NAME.value] = expect_name

        # This should be Rhythm, Lead or Bass only.
        arrangement[ListField.PATH.value] = self._get_path(sub_dict)

        arrangement[ListField.SUB_PATH.value] = self._get_sub_path(sub_dict)
        arrangement[ListField.TUNING.value] = self._get_tuning(sub_dict)

        pitch = sub_dict["CentOffset"]
        if abs(pitch) < 0.1:
            pitch = 440.0
        else:
            pitch = round(440.0 * 2.0 ** (pitch / 1200.0), 2)
        arrangement[RangeField.PITCH.value] = pitch

        arrangement[ListField.SONG_KEY.value] = sub_dict["SongKey"]
        arrangement[ListField.ARTIST.value] = sub_dict["ArtistName"]
        arrangement[ListField.TITLE.value] = sub_dict["SongName"]
        arrangement[ListField.ALBUM.value] = sub_dict["AlbumName"]
        arrangement[RangeField.YEAR.value] = sub_dict["SongYear"]
        arrangement[RangeField.TEMPO.value] = sub_dict["SongAverageTempo"]
        arrangement[RangeField.NOTE_COUNT.value] = max(
            sub_dict["NotesHard"], sub_dict["Score_MaxNotes"]
        )
        arrangement[RangeField.SONG_LENGTH.value] = sub_dict["SongLength"]
        arrangement[RangeField.LAST_MODIFIED.value] = last_modified

        return arrangement

    def _arrangement_rows(
        self, psarc_path: Path, internal: bool = False
    ) -> Iterator[Dict[str, Any]]:
        """Return an iterator of arrangement row entries in a psarc file.

        Arguments:
            psarc_path {Path} -- The psarc file to scan for arrangement data.
            internal {bool} -- If specified as True, treats every arrangement found
                as a Rocksmith internal (provided for the etudes scan). Note that
                some files in songs.psarc will also be treated as internal.
                (default: False)

        Returns:
            Iterator[Dict[str, Any]] -- Iterator of arrangement values - see db_entries.

        """
        self._current_psarc = psarc_path
        last_modified = psarc_path.stat().st_mtime
        with Welder(psarc_path, "r") as psarc:
            for index in psarc:
                name = psarc.arc_name(index)
                if name.endswith(".json"):
                    if name.endswith("_vocals.json"):
                        continue

                    if internal:
                        # Cut out the middleman, fill an internal entry
                        yield self._internal_data(
                            psarc.arc_data(index), last_modified
                        )
                    elif name in INTERNAL_SONGS:
                        # There are a couple of internal tracks in songs.psarc.
                        # This traps them.
                        yield self._internal_data(psarc.arc_data(index), last_modified)

                    else:
                        name = name.replace(".json", "")
                        for sep in track_types.keys():
                            base, found, suffix = name.rpartition(sep)
                            if found and (not suffix or suffix.isdigit()):
                                # We are looking for a successful partition and either
                                # no suffix or digit only suffix
                                # To get here, this should be real song song.
                                expect_name = track_types[found] + suffix
                                yield self._arrangement_data(
                                    psarc.arc_data(index), expect_name, last_modified
                                )
                                # Prevent fall through to exception
                                break
                            else:
                                continue

                            # Not an arrangement file?
                            raise ValueError(
                                f"Unexpected json file found {psarc.arc_name(index)} "
                                f"in {psarc_path.name}."
                            )

    def db_entries(
        self, last_modified: Optional[float] = None
    ) -> Iterator[Dict[str, Any]]:
        """Provide an arrangement iterator for the arrangements table in ArrangementDB.

        Arguments:
            last_modified {Optional[float]} -- If specified, the iterator will only
                return arrangements for psarc files more recent than last_modifed
                (per Path.stat().st_mtime). (default: None)

        Yields:
            Iterator[Dict[str, Any]] -- Iterator of dictionary of values for writing to
                the Arrangements table. This dictionary is intended to be used as the
                values argument for ArrangementDB._arrangement_sql.write_row().

        """
        if last_modified is None:
            scan_all = True
            last_modified = -1
        else:
            scan_all = False
        pass

        # Gather paths to files we will scan for songs
        if platform == "win32":
            find_files = WIN_PSARC
        elif platform == "darwin":
            find_files = MAC_PSARC

        if scan_all:
            # Scan etudes, guitars, session mode first - happy to have these
            # overwritten by any actual song arrangements that clash.
            for arrangement in self._arrangement_rows(
                self._rs_path.joinpath("etudes.psarc"), True
            ):
                yield arrangement

            for arrangement in self._arrangement_rows(
                self._rs_path.joinpath("guitars.psarc"), True
            ):
                yield arrangement

            for arrangement in self._arrangement_rows(
                self._rs_path.joinpath("session.psarc"), True
            ):
                yield arrangement

            # Scan the core songs.
            for arrangement in self._arrangement_rows(
                self._rs_path.joinpath("songs.psarc"), False
            ):
                yield arrangement

        for scan_path in self._rs_path.joinpath(DLC_PATH).glob("**/*" + find_files):
            if not scan_all:
                if scan_path.name.startswith(RS_COMPATABILITY):
                    # Only scan RS1 compatability on full scan.
                    continue
                elif scan_path.stat().st_mtime < last_modified:
                    # skip anything older than last modified time.
                    continue

            for arrangement in self._arrangement_rows(scan_path, False):
                yield arrangement


if __name__ == "__main__":
    pass
