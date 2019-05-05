#!/usr/bin/env python
"""Provide a basic Rocksmith importer for set lists created by rs-manager.

As the functionality of this module is straightforward and linear, I have provided
it as a set of linked functions rather than multiple classes. This also allows it to
provide a second service as an example of how to implement a profile editor using
rsrtools profile manager facility.

If the module complexity increases, I may re-implement in class form.
"""

# cSpell:ignore CDLC, faves, isalnum, isdigit, prfldb

import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import simplejson

from rsrtools.files.profilemanager import PROFILE_DB_STR, RSProfileManager
from rsrtools.files.steam import RS_APP_ID, STEAM_REMOTE_DIR, SteamAccounts
from rsrtools.songlists.config import ListField
from rsrtools.songlists.database import ArrangementDB
from rsrtools.utils import yes_no_dialog

# We are going to use the logger all over the place.
logger: "SimpleLog"


class SimpleLog:
    """Dead simply logger, which either writes to stdout or is silent.

    Essentially a class wrapping an if statement. Too much effort to learn how to use
    the python logging properly for this module!

    If needed, I could extend this class to write to file.

    Note that this class does not trap exceptions.
    """

    _silent: bool

    def __init__(self, silent: bool = False) -> None:
        """Construct simple logger."""
        self._silent = silent

    def log_this(self, log: str) -> None:
        """Write log."""
        if not self._silent:
            print(log)


def find_paths(definitions: List[List[str]], working: Path) -> Dict[str, Path]:
    """Return a dictionary containing the Paths to the json files containing song lists.

    Arguments:
        definitions {List[List[song_id, file_name]]} -- The list of song list
            definitions. Each sublist should contain two elements: the list id, which
            should be one of the following string values of '1', '2', ..., '6' or 'F',
            and the name of the file that contains the song list as a JSON list of Song
            Keys. E.g. ['F', 'new_faves.json'] for a favorites song list in file
            new_faves.json.
        working {Path} -- The working directory path.

    Returns:
        {Dict[str, Path]} -- The keys are the song list ids specified in definitions
            and the values are the resolved paths to json song list files.

    """
    paths: Dict[str, Path] = dict()

    for id, file_name in definitions:
        if id not in ("1", "2", "3", "4", "5", "6", "F"):
            raise ValueError(
                f"Undefined list id '{id}', should be a number from '1' to '6' or 'F'."
            )

        try:
            song_file = working.joinpath(file_name).resolve(True)
        except FileNotFoundError:
            # try again, but allow a fail on this one
            song_file = Path(file_name).resolve(True)

        if id in paths:
            logger.log_this(
                f"WARNING: You have specified song list '{id}' more than once."
                "\n  Are you sure you meant to to this?"
            )
        paths[id] = song_file
        logger.log_this(f"Found json file for song list '{id}'")

    return paths


def validate_song_keys(song_lists_dict: Dict[str, List[str]], working: Path) -> None:
    """Validate song lists against string pattern or list of available song keys.

    Arguments:
        Dict[str, List[str]] -- A dictionary of song lists, where each list of values
            requires validation (validation ignores the key values).
        working {Path} -- A working directory that will be checked for an arrangement
            database.

    Raises:
        ValueError -- If any value fails.

    """
    # get a song key list from Arrangement db if possible
    arr = ArrangementDB(working)
    if arr.has_arrangement_data:
        key_list: Optional[List[str]] = arr.list_validator(ListField.SONG_KEY)[
            ListField.SONG_KEY
        ]
    else:
        key_list = None

    if key_list is None:
        # do the most basic checks possible
        for id, song_list in song_lists_dict.items():
            failed = [x for x in song_list if not x.isalnum()]
            if failed:
                raise ValueError(
                    f"Song Key(s) for song list '{id}' are not alphanumeric."
                    f"\n    {failed}"
                )

    else:
        for id, song_list in song_lists_dict.items():
            failed = [x for x in song_list if x not in key_list]
            if failed:
                raise ValueError(
                    f"Song Key(s) for song list '{id}' are not in the arrangement "
                    f"database."
                    f"\n    {failed}"
                )

    logger.log_this("All song lists validated.")


def read_lists(paths: Dict[str, Path]) -> Dict[str, List[str]]:
    """Return a dictionary of song lists read from file.

    Arguments:
        paths {Dict[str, Path]} -- A dictionary of type returned by find_paths.

    Returns:
        Dict[str, List[str]] -- The keys are a string song list id ('1' to '6' or 'F'),
            and the value lists contains the song keys to be written to that list.

    """
    sl_dict: Dict[str, List[str]] = dict()
    for id, file_path in paths.items():
        logger.log_this(f"Reading file '{file_path.name}'' for song list '{id}'.")

        with open(file_path, "rt") as fp:
            song_list = simplejson.load(fp)

        # structure checks - could have used a schema for this.
        # because I'm a bit lazy here, might also fail if a song key
        # is pure digits and has been converted to a number on the way in
        # We can tidy this up if it ever happens.
        if not isinstance(song_list, list):
            raise TypeError(
                f"Invalid format in file '{file_path.name}'."
                f"\n  This should be a JSON list of strings, but I found "
                f"a {type(song_list)}."
            )

        for val in song_list:
            if not isinstance(val, str):
                raise TypeError(
                    f"Invalid song list member in file '{file_path.name}'."
                    f"\n  This should be a JSON list of strings, but I found "
                    f"a member with {type(val)}."
                )

        # just to be sure, clean out white space and empty strings silently.
        song_list = [x for x in song_list if x.strip() != ""]

        sl_dict[id] = song_list

    logger.log_this("All song list files passed structure tests.")
    return sl_dict


def get_profile_manager(
    user_id: Optional[str], no_interactive: bool, working: Path
) -> RSProfileManager:
    """Get a profile manager for the importer.

    Arguments:
        user_id {str} -- User id provided by the caller, which could be any of the
            steam account identifiers or None. If None, an interactive process for
            account id selection will be triggered.
        no_interactive {bool} -- If true, interactive processes are disabled and an
            error is raised if the caller has not provided a user id.
        working {Path} -- Path to the working directory.

    Returns:
        RSProfileManager -- The profile manager for user id supplied, or for the user
            id selected interactively.

    """
    if user_id is None:
        if no_interactive:
            raise ValueError(
                "A Steam account argument must be specified for silent operation."
            )

        else:
            # select account interactively
            pm = RSProfileManager(working, auto_setup=True, flush_working_set=True)
            account_id = pm.steam_account_id

    else:
        # Find the steam account and load a profile manager, throwing exceptions
        # as we run into problems.
        sa = SteamAccounts()
        account_id = sa.find_account_id(user_id)
        pm = RSProfileManager(
            working,
            steam_account_id=account_id,
            auto_setup=True,
            flush_working_set=True,
        )

    return pm


def select_profile(
    pm: RSProfileManager, input_profile: Optional[str], no_interactive: bool
) -> str:
    """Select the Rocksmith profile for profile updates.

    Arguments:
        input_profile {str} -- Profile name provided by the caller, which could be a
            Rocksmith profile name or None. If None, an interactive process for profile
            selection will be triggered.
        no_interactive {bool} -- If true, interactive processes are disabled and an
            error is raised if the caller has not provided a profile name.

    Returns:
        RSProfileManager -- The selected profile name.

    """
    if input_profile is None:
        if no_interactive:
            raise ValueError(
                "A profile name argument must be specified for silent operation."
            )

        else:
            # select account interactively
            profile = pm.cl_choose_profile(
                header_text="Select the target profile for song list importing.",
                no_action_text="To exit without applying updates (raises error).",
            )
            if not profile:
                raise ValueError("No profile name selected for song list import.")

    else:
        if input_profile in pm.profile_names():
            profile = input_profile

        else:
            raise ValueError(
                f"'{input_profile}' is not a valid profile name for' Steam "
                f"account '{pm.steam_account_id}'"
            )

    return profile


def import_faves_by_replace(
    pm: RSProfileManager, profile: str, song_list_dict: Dict[str, List[str]]
) -> None:
    """Replace favorites song list in profile.

    Arguments:
        pm {RSProfileManager} -- Profile manager for the target Steam account.
        profile {str} -- Target Rocksmith profile.
        song_list_dict {Dict[str, List[str]]} -- Dictionary of song lists as defined in
            read_lists.

    This method demonstrates how to use the RSProfileManager.set_json_subtree method for
    editing data in a Rocksmith profile. Note that this method edits instance data,
    but doesn't save or move the profiles.

    """
    song_list = song_list_dict.get("F", None)
    if song_list is not None:
        # We have a Favorites list to update, so let's do it!
        # This is a easy as it gets - replace the song list in the profile, and as a
        # by product, set_json_subtree marks the profile as dirty for saving.
        # From a python object perspective, this corresponds to the following statement:
        #   profile_json["FavoritesListRoot"]["Favorites"] = song_list
        pm.set_json_subtree(profile, ("FavoritesListRoot", "FavoritesList"), song_list)


def import_song_lists_by_mutable(
    pm: RSProfileManager, profile: str, song_list_dict: Dict[str, List[str]]
) -> None:
    """Replace one or more of song lists 1 to 6 in profile.

    Arguments:
        pm {RSProfileManager} -- Profile manager for the target Steam account.
        profile {str} -- Target Rocksmith profile.
        song_list_dict {Dict[str, List[str]]} -- Dictionary of song lists as defined in
            read_lists.

    This method demonstrates how to use the RSProfileManager.get_json_subtree method for
    editing data in a Rocksmith profile.  Note that this method edits instance data,
    but doesn't save or move the profiles.

    """
    list_of_song_lists = pm.get_json_subtree(profile, ("SongListsRoot", "SongLists"))
    for key, song_list in song_list_dict.items():
        if key.isdigit() and 1 <= int(key) <= 6:
            # We have a song list to update, so let's do it!
            # We already have the profile list of song lists. As this is a mutable,
            # any changes in the lists are also reflected in the profile instance data.
            # So all we need to do is replace the relevant sublist with a new one.
            # From a python object perspective, this corresponds to the following
            # statements:
            #   list_of_song_lists = profile_json["SongListsRoot"]["SongLists"]
            #   list_of_song_lists[key-1] = song_list
            list_of_song_lists[int(key) - 1] = song_list

            # While we know we have modified the instance data, the profile manager
            # doesn't. So we tell it explicitly.
            pm.mark_as_dirty(profile)


def parse_prfldb_path(raw_path: str) -> Tuple[str, str]:
    """Convert prfldb path into an account id and profile unique id.

    Arguments:
        path {str} -- A path as described in the argument for --prfldb-path.

    Returns:
        {Tuple[str, str]} -- A steam account id and the unique profile corresponding to
            the file in the path.

    """
    # Eliminate relative path elements, get the path
    path = Path(raw_path).resolve(False)

    unique_id = path.name
    if not unique_id.upper().endswith(PROFILE_DB_STR.upper()):
        raise ValueError(
            f"Profile db path must end with file name "
            f"'*<unique_id>{PROFILE_DB_STR}'."
        )

    unique_id = unique_id[: -len(PROFILE_DB_STR)]

    logger.log_this(f"Found unique id '{unique_id}' from path.")

    path = path.parent
    for id in (STEAM_REMOTE_DIR, RS_APP_ID):
        if path.name.upper() == id.upper():
            path = path.parent
        else:
            raise ValueError(
                f"Path to profile id must have the following elements:"
                f"<Steam account id>\\{RS_APP_ID}\\{STEAM_REMOTE_DIR}\\<profile name>."
                f"\nFailed on element '{id}'."
            )

    account_id = path.name
    if len(account_id) != 8 or not account_id.isdigit():
        raise ValueError(
            f"Steam account id must be 8 digits. '{account_id}' is invalid."
        )

    logger.log_this(f"Found account id '{account_id}' from path.")

    return account_id, unique_id


def main() -> None:
    """Provide command line entry point for rsm importer."""
    parser = argparse.ArgumentParser(
        description="Command line interface for loading song lists/set lists generated "
        "by rs-manager into Rocksmith."
    )
    parser.add_argument(
        "working_dir",
        help="Working directory for working files and arrangement database (if any).",
    )

    parser.add_argument(
        "-a",
        "--account-id",
        help="Specify the steam account id for the Rocksmith profile. This can be the "
        "the account alias/profile (probably easiest to find - this is the name next "
        "to the Community menu on the steam interface), the steam account login name, "
        "an 8 digit account id, or a 17 digit steam id. If omitted, an interactive "
        "selection will be triggered.",
        metavar="<steam_id>",
    )

    parser.add_argument(
        "-p",
        "--profile",
        help="The name of the profile that the song list will be written to. If "
        "omitted, an interactive selection will be triggered.",
        metavar="<profile_name>",
    )

    parser.add_argument(
        "--prfldb-path",
        help="The path to a target Rocksmith profile. This option is provided as a "
        "helper function for rs-manager. The path should be of the form: "
        "<steam path>/userdata/<account id>/221680/remote/<profile name>. Everything "
        "up to to ...userdata/ is optional and will be ignored. The profile name must "
        "end in _prfldb (case insensitive). If the path does not correspond to a valid "
        "account and profile, an exception will be raised. Finally, the prfldb_path "
        "option cannot be used with either --profile or --account-id.",
        metavar="<profile_path>",
    )

    parser.add_argument(
        "--no-check",
        help="If specified, the importer will not check the song keys in the import "
        "file. Otherwise the importer will check the song keys against either: an "
        "arrangement database (if available), or against a basic character pattern "
        "(currently a-zA-Z0-9). This may be useful if you have CDLC that has accented "
        " characters or other characters outside the character pattern (if so, please "
        "raise a github issue or PR so we can update the pattern).",
        action="store_true",
    )

    parser.add_argument(
        "--silent",
        help="If specified, the importer will not log progress and will not ask the "
        "you to confirm the update to the Rocksmith profile. Silent mode will also "
        "disable interactive account and profile selection (i.e. these arguments"
        "must be specified if silent is specified).",
        action="store_true",
    )

    parser.add_argument(
        "-sl",
        "--song-list",
        nargs=2,  # cSpell:disable-line
        action="append",
        help="Specifies a song list replacement. list_id specifies the song list to "
        "replace and must be either the letter 'F' for Favorites or a number from "
        "1 to 6 for a numbered song list. song_file is the file containing the song "
        "keys for the new song list.  If the file is in the working directory, it "
        "should be the file name without any path information. Otherwise, it should be "
        "the full path to the file. This must be a text file containing a single JSON "
        "form list of the song keys for the song list. That is, the file contents "
        'should look like ["<key 1>", "<key 2>", "<key 3>, ..., "<key N>"]. This is '
        "the structure of files exported by rs-manager. This argument can be repeated, "
        "so that you can update all 6 song lists and Favorites in single call. Note "
        "that you can repeat a list_id - if you do, the corresponding song list will "
        "be overwritten again without warning  and order of writing cannot be "
        "guaranteed. Lastly, this is an optional argument, but if you don't make at "
        "least one song list specification, this program will do nothing.",
        metavar=("list_id", "song_file"),
    )

    args = parser.parse_args()

    # Share the logger everywhere.
    global logger
    logger = SimpleLog(args.silent)

    if args.song_list is None:
        logger.log_this("No song lists specified, so I can't do anything.")
        return

    working = Path(args.working_dir).resolve(True)

    # resolve file names into paths.
    paths = find_paths(args.song_list, working)

    # read song list and do basic validation
    song_list_dict = read_lists(paths)

    if not args.no_check:
        # do more detailed checks on the song lists.
        validate_song_keys(song_list_dict, working)

    # Now we have a valid set of song lists, so the next thing is to get the
    # steam account id and set up the profile manager.
    if args.prfldb_path is not None and (
        args.account_id is not None or args.profile is not None
    ):
        raise ValueError(
            "--prfldb-path can't be used at the same time as either --account-id "
            "or --profile.\n    (--account-id and --profile can be used together.)"
        )

    if args.prfldb_path is not None:
        account_id, unique_id = parse_prfldb_path(args.prfldb_path)

    else:
        account_id = args.account_id
        unique_id = ""

    pm = get_profile_manager(account_id, args.silent, working)

    if unique_id:
        profile = pm.unique_id_to_profile(unique_id)
        logger.log_this(f"Unique id '{unique_id}' corresponds to profile '{profile}'.")
    else:
        profile = select_profile(pm, args.profile, args.silent)

    logger.log_this(f"Loaded Steam account {pm.steam_description(pm.steam_account_id)}")
    logger.log_this(f"Selected profile '{profile}' for song list updates.")

    # and now we can write the updates.
    # This could all be done in the one routine, but I wanted to demonstrate
    # the two different ways of writing data to a profile

    import_faves_by_replace(pm, profile, song_list_dict)

    import_song_lists_by_mutable(pm, profile, song_list_dict)

    # Save the files into the update folder in the working directory
    # and then move them to the Steam account
    dialog = (
        f"Please confirm that you want to update song lists in profile '{profile}' of "
        f"Steam account:\n{pm.steam_description(pm.steam_account_id)}"
    )

    if args.silent or yes_no_dialog(dialog):
        pm.write_files()
        pm.move_updates_to_steam(pm.steam_account_id)


if __name__ == "__main__":
    main()
