#! /usr/bin/env python
"""File exceptions for rsrtools."""

from typing import Optional


class RsrError(Exception):
    """Super class for rsrtools errors."""

    def __init__(self, message: Optional[str] = None) -> None:
        """Minimal constructor for RsrErrors.

        Keyword Arguments:
            message {str} -- Custom error text. If no message is supplied (default),
                the exception will supply a not very informative message.
                (default: {None})

        """
        if message is None:
            message = "An unspecified error has occurred in rsrtools."
        super().__init__(message)


class RSFileFormatError(RsrError):
    """Exception for errors in file format or data in a Rocksmith file."""

    def __init__(self, message: str) -> None:
        """Minimal constructor for rsrtools file format errors.

        Arguments:
            message {[type]} -- Custom error text.
        """
        super().__init__(
            f"{message}"
            f"\nPossible reasons:\n"
            f"- This may not be a Rocksmith file.\n"
            f"- This file may be corrupt.\n"
            f"- Ubisoft may have changed the file format (requires"
            f"  update to rsrtools).",
        )
