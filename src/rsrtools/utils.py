#!/usr/bin/env python
"""Provide utilities for rsrtools."""

# cSpell:ignore HKEY, rsrpad

# Not even trying to get stubs for winreg
from typing import List, Optional, Tuple, Union, Any, Sequence


def rsrpad(data: bytes, block_size_bytes: int) -> bytes:
    """Return data padded to match the specified block_size_bytes.

    Arguments:
        data {bytes} -- Data string to pad.
        block_size_bytes {int} -- Block size for padding.

    Returns:
        bytes -- Padded data.

    The first byte of the padding is null to match the rocksmith standard,
    the remainder fill with the count of bytes padded (RS appears to use
    random chars).

    """
    padding = (block_size_bytes - len(data)) % block_size_bytes
    if padding > 0:
        null_bytes = 1
        pad_byte = chr(padding).encode()
        padding -= 1
    else:
        null_bytes = 0
        pad_byte = b"\x00"

    return data + b"\x00" * null_bytes + pad_byte * padding


def double_quote(raw_string: str) -> str:
    """Return raw_string after stripping white space and double quoting."""
    raw_string = raw_string.strip('"')
    return '"' + raw_string + '"'


def choose(
    options: Sequence[Union[str, Tuple[str, Any]]],
    header: Optional[str] = None,
    allow_multi: bool = False,
    no_action: Optional[str] = None,
    help_text: Optional[str] = None,
) -> Optional[List[Any]]:
    """Return user selection or multi-selection from a list of options.

    Arguments:
        options {Sequence[Union[str, Tuple[str, Any]]]} -- A list of options, where
            each may be either:
            * a string, where string is returned if the option is selected; or
            * a of tuple (option_description, return_value), where the return_value
              is returned if the option is selected.

    Keyword Arguments:
        header {str} -- Header/description text for the selection (default: {None})
        allow_multi {bool} -- Allow multi-selection if True (default: {False})
        no_action {str} -- Description value for no selection. If this argument is not
            set or is None, the user must select from the options list.
            (default: {None})
        help_text {str} -- Detailed help text. (default: {None})

    Returns:
        Optional[List[Any]] -- List of return values. If the allow_multi is False, the
        list will contain only one element. If the user has selected no_action, the
        return value is None.

    To select multiple options, enter a comma separated list of values.

    """
    opt_tuple_list = list()
    for this_opt in options:
        if isinstance(this_opt, tuple):
            opt_tuple_list.append(this_opt)
        else:
            opt_tuple_list.append((this_opt, this_opt))

    while True:
        print()
        if header is not None:
            print(header)
            print()

        for i, (key, value) in enumerate(opt_tuple_list):
            print(f"{i + 1: 3d}) {key}")
        if no_action is not None:
            print("  0) " + no_action)
        if help_text is not None:
            print("  h) Help.")

        values: Any = ""
        try:
            # splits on commas, strips white space from values, converts to int
            print()
            values = input("Choose> ").strip()
            values = list(map(lambda x: int(x.strip()) - 1, values.split(",")))

            if no_action is not None and -1 in values:
                return None

            values = [
                opt_tuple_list[value][1]
                for value in values
                if 0 <= value < len(opt_tuple_list)
            ]

            if not values:
                continue

            if allow_multi:
                return values

            if len(values) == 1:
                return values[0:1]

        except (ValueError, IndexError):
            if help_text is not None and values == "h":
                print("-" * 80)
                print()
                print(help_text)
                print()
                print("-" * 80)
                continue
            else:
                print("Invalid input, please try again")


def yes_no_dialog(prompt: str) -> bool:
    """Return true/false based on prompt string and Y/y or N/n response."""
    while True:
        print()
        print(prompt)
        print()

        response = input("Y/n to confirm, N/n to reject >")
        if response in ("Y", "y"):
            return True

        if response in ("N", "n"):
            return False
