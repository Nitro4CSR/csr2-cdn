"""Exact display conversion for Prestige Cup FastestHalfMileTime scores.

The verified game UI shows integer server scores as seconds with six decimal
places (e.g. 7102993 -> 7.102993). Never use binary floating point here.
This conversion is Prestige-specific: GCC scores remain Crew RP, not times.
"""
from __future__ import annotations

import re
from typing import Optional

MICROSECONDS_PER_SECOND = 1_000_000
_MAX_SCORE = 2**63 - 1
_TIME_PATTERN = re.compile(r"([0-9]+)(?:\.([0-9]{1,6}))?\Z")


def format_prestige_time(score_microseconds: int) -> str:
    """Format a nonnegative raw Prestige score as fixed-six-decimal seconds.

    Returns the number only (e.g. ``'7.102993'``), allowing callers to append
    their own unit labels without introducing locale-dependent separators.
    """
    if type(score_microseconds) is not int or not 0 <= score_microseconds <= _MAX_SCORE:
        raise ValueError("Prestige score must be a nonnegative int64 microsecond count")
    whole, fraction = divmod(score_microseconds, MICROSECONDS_PER_SECOND)
    return f"{whole}.{fraction:06d}"


def format_prestige_time_optional(score: Optional[int]) -> Optional[str]:
    """Never display absent or invalid leaderboard score sentinels as a time."""
    if type(score) is not int or not 0 <= score <= _MAX_SCORE:
        return None
    return format_prestige_time(score)


def parse_prestige_ui_time(time_seconds: str) -> int:
    """Parse operator UI seconds exactly, allowing up to six decimal digits.

    Strings only: integers/floats, exponent notation, negative signs, grouping
    separators, and sub-microsecond precision are deliberately rejected.
    """
    if not isinstance(time_seconds, str) or len(time_seconds) > 32:
        raise ValueError("Prestige UI time must be a decimal seconds string")
    match = _TIME_PATTERN.fullmatch(time_seconds)
    if match is None:
        raise ValueError("Prestige UI time must contain up to six fractional digits")
    whole, frac = match.group(1), match.group(2) or ""
    value = int(whole) * MICROSECONDS_PER_SECOND + int(frac.ljust(6, "0"))
    if value > _MAX_SCORE:
        raise ValueError("Prestige UI time exceeds int64 range")
    return value


def format_prestige_time_delta(delta_microseconds: int) -> str:
    """Return a signed six-decimal seconds difference, including + for zero."""
    if type(delta_microseconds) is not int or abs(delta_microseconds) > _MAX_SCORE:
        raise ValueError("Prestige time delta out of range")
    return ("-" if delta_microseconds < 0 else "+") + format_prestige_time(abs(delta_microseconds))
