"""Helpers for the ``name`` table itself.

Small enough today to be one function; it has a module of its own because the
static side of the family model - legacy family names, RIBBI style bits, WWS
records - belongs here next, and both applications still carry their own copy
of it.
"""

from __future__ import annotations


def mac_roman_encodable(value: str) -> bool:
    """Whether the value can be stored in a Macintosh (1, 0, 0) name record.

    Variable fonts carry Mac duplicates of every Office-facing name; the static
    Office pass strips all Macintosh records instead. Either way the question is
    the same one: does this string survive the encoding.
    """
    try:
        value.encode("mac_roman")
        return True
    except (UnicodeEncodeError, LookupError):
        return False
