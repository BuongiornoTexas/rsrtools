#!/usr/bin/env python
"""Provide steam related utilities for rsrtools."""

# Consider creating separate classes if these become extensive

# cSpell:ignore HKEY, isdigit

from sys import platform
from pathlib import Path
from collections import abc
from typing import Any, Dict, Iterator, List, Mapping, NamedTuple, Optional, Tuple

from rsrtools.utils import double_quote

if platform == "win32":
    import winreg  # type: ignore

ACCOUNT_MASK = 0xFFFFFFFF
VDF_SECTION_START = "{"
VDF_SECTION_END = "}"
VDF_INDENT = "\t"
VDF_SEPARATOR = "\t\t"
RS_APP_ID = "221680"
STEAM_REMOTE_DIR = "remote"
REMOTE_CACHE_NAME = "remotecache.vdf"


class SteamMetadataError(Exception):
    """Base class for Steam metadata handling errors."""

    def __init__(self, message: str = None) -> None:
        """Minimal constructor.

        Keyword Arguments:
            message {str} -- Custom error text. If no message is supplied (default),
                the exception will supply a not very informative message.
                (default: {None})
        """
        if message is None:
            message = "An unspecified Steam cloud metadata handling error had occurred."

        super().__init__(message)


def load_vdf(vdf_path: Path, strip_quotes: bool = False) -> Dict[Any, Any]:
    """Load a Steam .vdf file into a dictionary.

    Arguments:
        vdf_path {Path} -- The path to the .vdf file.

    Keyword Arguments:
        strip_quotes {bool} -- If True, strips leading and trailing double quotes from
            both key and values. If False, returns keys and values as read - typically
            both are double quoted. (default: {False})

    Returns:
        Dict[Any, Any] -- The .vdf contents as a dictionary.

    This is a primitive .vdf loader. It makes minimal assumptions about .vdf file
    structure and attempts to parse a dictionary based on this structure. It is suitable
    for use in rsrtools, but should not be relied on more broadly.

    """
    vdf_dict: Dict[Any, Any] = dict()

    # ugly custom parser, cos Steam doesn't do standard file formats
    # node needs a type to stop mypy collapsing during the walk
    node: Dict[Any, Any] = vdf_dict
    section_label = ""
    branches = list()
    with vdf_path.open("rt") as fh:
        for line in fh:
            line_str = line.strip()
            try:
                (key, value) = line_str.split()
            except ValueError:
                if line_str == VDF_SECTION_START:
                    node[section_label] = dict()
                    branches.append(node)
                    node = node[section_label]
                    section_label = ""
                elif line_str == VDF_SECTION_END:
                    node = branches.pop()
                else:
                    section_label = line_str
                    if strip_quotes:
                        section_label = line_str.strip('"')
            else:
                if strip_quotes:
                    key = key.strip('"')
                    value = value.strip('"')
                node[key] = value

    # sense check
    if branches:
        raise SteamMetadataError(
            "Incomplete Steam metadata file: at least one section is not "
            'terminated.\n  (Missing "}".)'
        )

    return vdf_dict


def _iter_vdf_tree(tree: Mapping[Any, Any]) -> Iterator[Tuple[Any, Any]]:
    """Iterate (walk) the Steam vdf tree.

    Arguments:
        tree {dict} -- A node in a steam .vdf dictionary.

    Helper method for write_vdf_file.

    """
    for key, value in tree.items():
        if isinstance(value, abc.Mapping):
            yield key, VDF_SECTION_START
            for inner_key, inner_value in _iter_vdf_tree(value):
                yield inner_key, inner_value
            yield key, VDF_SECTION_END
        else:
            yield key, value


def save_vdf(
    vdf_dict: Dict[Any, Any], vdf_path: Path, add_quotes: bool = False
) -> None:
    """Write a vdf dictionary to file.

    Arguments:
        vdf_dict {Dict[Any, Any]} -- The vdf dictionary to write.
        vdf_path {Path} -- The save path for the file.

    Keyword Arguments:
        add_quotes {bool} -- If True, adds double quotes to all keys and
            values before writing. If False, writes the keys and values as they
            appear in the vdf_dict (default: {False})

    """
    indent = ""
    file_lines = list()
    for key, value in _iter_vdf_tree(vdf_dict):
        if add_quotes:
            key = double_quote(key)

        if value == VDF_SECTION_START:
            file_lines.append(f"{indent}{key}\n")
            file_lines.append(f"{indent}{VDF_SECTION_START}\n")
            indent = indent + VDF_INDENT
        elif value == VDF_SECTION_END:
            indent = indent[:-1]
            file_lines.append(f"{indent}{VDF_SECTION_END}\n")
        else:
            if add_quotes:
                value = double_quote(value)
            file_lines.append(f"{indent}{key}{VDF_SEPARATOR}{value}\n")

    with vdf_path.open("wt") as fh:
        fh.writelines(file_lines)


class SteamAccountInfo(NamedTuple):
    """Provide Steam account information."""

    name: str
    persona: str
    description: str
    path: Optional[Path]
    valid: bool


class SteamAccounts:
    """Provide data on Steam user accounts on the local machine.

    Public methods:
        account_ids --  Return a list Steam account ids in string form (8 digit
            account ids as strings).
        account_info -- Return a SteamAccountInfo named tuple for a specific account.
    """

    # instance variables
    # Steam data is unlikely to change for the duration of the program, so
    # we could use class variables here. But it'll be a lot effort, as this class
    # probably only be instaniated once or twice.
    # Path to the Steam application.
    _steam_path: Optional[Path]
    _account_info: Dict[str, SteamAccountInfo]

    def __init__(self) -> None:
        """Initialise steam account data for use."""
        self._steam_path = self._get_steam_path()

        self._account_info = self._find_info()

    @staticmethod
    def _get_steam_path() -> Optional[Path]:
        """Return Steam installation path as a string. Return None if not found."""
        ret_val = None

        # At the moment, this is the only OS dependent code in the package
        if platform == "win32":
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"
                ) as steam_key:
                    str_path, _ = winreg.QueryValueEx(steam_key, "SteamPath")

                ret_val = Path(str_path).resolve(strict=True)
            except (OSError, FileNotFoundError):
                # Looks like we have no steam installation?
                # Up to the user to decide what to do here.
                pass

        elif platform == "darwin":
            # I believe this should work.
            try:
                ret_val = (
                    Path.home()
                    .joinpath("Library/Application Support/Steam")
                    .resolve(strict=True)
                )
            except FileNotFoundError:
                # Looks like we have no steam installation?
                # Up to the user to decide what to do here.
                pass

        else:
            raise OSError(
                f"rsrtools doesn't know how to find Steam folder on {platform}"
            )

        return ret_val

    def _find_info(self) -> Dict[str, SteamAccountInfo]:
        """Find and record Steam account information on local machine."""
        info: Dict[str, SteamAccountInfo] = dict()

        if self._steam_path is not None:
            # create info based on both login vdf file and userdata folder names.
            user_dirs = self._user_data_dirs()
            user_config = self._login_info()

            user_path: Optional[Path]
            for account, user_path in user_dirs.items():
                if account not in user_config:
                    # user folder with no account information.
                    info[account] = SteamAccountInfo(
                        name="",
                        persona="",
                        description=f"{account}, no Steam account info.",
                        path=user_path,
                        valid=False,
                    )

            for account, login_info in user_config.items():
                if account in user_dirs:
                    # We have account info and a userdata folder exists
                    user_path = user_dirs[account]
                    valid = True
                else:
                    # Account with no path. Shouldn't happen, but who knows ...
                    user_path = None
                    valid = False

                name = login_info["AccountName"]
                persona = login_info["PersonaName"]
                if login_info["mostrecent"] == "1":
                    most_recent = ", most recent Steam login"
                else:
                    most_recent = ""

                info[account] = SteamAccountInfo(
                    name=name,
                    persona=persona,
                    description=f"'{account}', ({persona}[{name}]){most_recent}.",
                    path=user_path,
                    valid=valid,
                )

        return info

    def _login_info(self) -> Dict[str, Dict[str, str]]:
        """Read the Steam loginusers.vdf file and returns a dictionary of account data.

        Returns:
            Dict[str, Dict[str, str]] -- A dictionary of:
                Dict[Account id, Dict[Account Field, Field value].

        """
        info: Dict[str, Dict[str, str]] = dict()
        if self._steam_path is not None:
            vdf_dict = load_vdf(
                self._steam_path.joinpath("config/loginusers.vdf"), strip_quotes=True
            )

            for steam_id, data in vdf_dict["users"].items():
                # account id is low 32 bits of steam id.
                account_id = str(int(steam_id) & ACCOUNT_MASK)

                info[account_id] = data

        return info

    def _user_data_dirs(self) -> Dict[str, Path]:
        """Return a dictionary of all userdata directories found in the Steam directory.

        The dictionary keys are local Steam account ids as strings, values are the
        directory paths. Returns an empty dict if no userdata directories are found.

        """
        ret_val = dict()

        users_dir = self._steam_path
        if users_dir is not None:
            # noinspection SpellCheckingInspection
            users_dir = users_dir.joinpath("userdata")

            if users_dir.is_dir():
                for child in users_dir.iterdir():
                    if child.is_dir():
                        if len(child.name) == 8 and child.name.isdigit():
                            # Expecting an 8 digit integer account id.
                            ret_val[child.name] = child

        return ret_val

    def account_ids(self, only_valid: bool = True) -> List[str]:
        """Return list of Steam account ids found on the local machine.

        Keyword Arguments:
            only_valid {bool} -- If True, the list will contain only account ids that
                have userdata folder and account details in the loginusers.vdf file.
                If False, the list will also contain account ids with partial
                information (either userdata folder or login information is missing).
                (default: {True})

        Returns:
            List[str] -- A list of 8 digit account ids in string form.

        """
        if only_valid:
            ids = [x for x in self._account_info.keys() if self._account_info[x].valid]
        else:
            ids = list(self._account_info.keys())

        return ids

    def account_info(self, account_id: str) -> SteamAccountInfo:
        """Return the account info for the specified Steam account id.

        Arguments:
            account_id {str} -- An 8 digit steam id in string form.

        Raises:
            KeyError -- If account_id doesn't exist.

        Returns:
            SteamAccountInfo -- The account information object for account_id.

        """
        return self._account_info[account_id]

    def find_account_id(self, test_value: str, only_valid: bool = True) -> str:
        """Convert test value into an 32 bit (8 digit) Steam account id.

        Arguments:
            test_value {str} -- This may be a 32 bit Steam ID, an 32 bit steam account
                ID, a Steam account name, or a Steam profile alias.
            only_valid {bool} -- If True, the method will only return the account id
                for an account with a userdata directory and a loginusers.vdf entry.
                If False, it will return an account id for records which have partial
                data (either a userdata directory or login information is missing).
                (default: {True})

        Raises:
            KeyError -- If the account id does not exist on the local machine, or if
                a partial record is found and only_valid is True.

        Returns:
            str -- A 32 bit/8 digit Steam account id.

        """
        if not test_value:
            raise KeyError("Empty string is not a valid Steam account ID.")

        account_id = ""
        if test_value in self._account_info:
            # Maybe we have been given what we need.
            account_id = test_value

        else:
            if len(test_value) == 17 and test_value.isdigit():
                # test 64 bit id.
                test_id = str(int(test_value) & ACCOUNT_MASK)
                if test_id in self._account_info:
                    account_id = test_id

        upper_value = test_value.upper()
        if not account_id:
            # lastly check the account dictionary.
            for test_id, info in self._account_info.items():
                if (
                    info.name.upper() == upper_value
                    or info.persona.upper() == upper_value
                ):
                    account_id = test_id
                    break

        if not account_id:
            raise KeyError(f"No Steam account id found for {test_value}.")

        elif only_valid and not self._account_info[account_id].valid:
            raise KeyError(f"No valid Steam account id found for {test_value}.")

        return account_id
