#!/usr/bin/env python3
"""Provide steam related utilities for rsrtools."""

# Consider creating separate classes if these become extensive

# cSpell:ignore HKEY

from sys import platform
from pathlib import Path
from collections import abc
from typing import Any, Dict, Iterator, Mapping, Optional, Tuple

from rsrtools.utils import double_quote

if platform == "win32":
    import winreg  # type: ignore

VDF_SECTION_START = "{"
VDF_SECTION_END = "}"
VDF_INDENT = "\t"
VDF_SEPARATOR = "\t\t"


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


def steam_path() -> Optional[Path]:
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
            pass

    elif platform == "darwin":
        # Bad form, but at least this way I can't forget it later.
        raise NotImplementedError()

    else:
        raise OSError(f"rsrtools doesn't know how to find Steam folder on {platform}")

    return ret_val


def steam_user_data_dirs() -> Dict[str, Path]:
    """Return a dictionary of all userdata directories found in the Steam directory.

    The dictionary keys are local Steam account ids as strings, values are the directory
    paths. Returns an empty dict if no userdata directories are found.

    """
    ret_val = dict()

    users_dir = steam_path()
    if users_dir is not None:
        # noinspection SpellCheckingInspection
        users_dir = users_dir.joinpath("userdata")

        if users_dir.is_dir():
            for child in users_dir.iterdir():
                if child.is_dir():
                    ret_val[child.name] = child

    return ret_val


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


# replace this with a function that returns a dictionary of Steam user descriptions
# dict[steam_account_id, <PersonaName> (account_name), most recently logged in account]
def steam_active_user() -> int:
    """Return Steam active user as an integer, or 0 for no active user."""
    ret_val = 0
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess"
        ) as sub_key:
            ret_val, _ = winreg.QueryValueEx(sub_key, "ActiveUser")
    except OSError:
        pass

    return ret_val
