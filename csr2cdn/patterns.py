"""Branch name shapes, and generating the small set of plausible successors.

Every branch name seen on the CDN fits ``{major}_{minor}_{patch}_Release`` plus
one of four suffixes:

==========================================  ==========  =======================
branch                                      kind        product_version
==========================================  ==========  =======================
``4_1_0_Release``                           release     4.1.0
``4_3_0_Release_OTA_1``                     ota         4.3.1
``4_3_2_Release_1``                         numbered    4.3.2
``4_0_1_Release_Preemptive_OTA``            preemptive  4.0.0 (the one before)
==========================================  ==========  =======================

Two things follow. The patch component is not always zero (``4_0_1``, ``4_3_2``,
``4_5_1`` all shipped branches), so a branch name cannot be derived from a store
version by rule alone. And ``product_version`` in a database header does not
match its own branch name reliably, so it is read, never computed.

:func:`successors` turns a known branch into the dozen or so names that could
follow it. That is a bounded probe, not a search: you ask the CDN about each
one's ``.version`` file and keep the ones that answer. Because database versions
are globally increasing integers, the highest one is the newest branch.
"""

from __future__ import annotations

import re
from typing import List, NamedTuple, Optional, Tuple

#: Suffix shapes, in the order a probe should try them.
RELEASE = "release"
OTA = "ota"
NUMBERED = "numbered"
PREEMPTIVE = "preemptive"

_BRANCH_RE = re.compile(
    r"^(?P<major>\d+)_(?P<minor>\d+)_(?P<patch>\d+)_Release"
    r"(?:_OTA_(?P<ota>\d+)|_Preemptive_OTA|_(?P<numbered>\d+))?$"
)


class BranchName(NamedTuple):
    """A parsed branch name."""

    major: int
    minor: int
    patch: int
    kind: str
    ordinal: Optional[int]
    raw: str

    @property
    def version(self) -> Tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    @property
    def release(self) -> str:
        """The version part as a dotted string, e.g. ``"4.5.1"``."""
        return f"{self.major}.{self.minor}.{self.patch}"

    def with_version(self, version: Tuple[int, int, int]) -> "BranchName":
        return self._replace(
            major=version[0],
            minor=version[1],
            patch=version[2],
            raw=build_branch(version, self.kind, self.ordinal),
        )

    def __str__(self) -> str:
        return self.raw


def build_branch(
    version: Tuple[int, int, int],
    kind: str = RELEASE,
    ordinal: Optional[int] = None,
) -> str:
    """Assemble a branch name: ``(6, 7, 0), OTA, 2`` -> ``6_7_0_Release_OTA_2``."""
    stem = f"{version[0]}_{version[1]}_{version[2]}_Release"
    if kind == RELEASE:
        return stem
    if kind == OTA:
        return f"{stem}_OTA_{ordinal if ordinal is not None else 1}"
    if kind == NUMBERED:
        return f"{stem}_{ordinal if ordinal is not None else 1}"
    if kind == PREEMPTIVE:
        return f"{stem}_Preemptive_OTA"
    raise ValueError(f"unknown branch kind {kind!r}")


def parse_branch(name: str) -> Optional[BranchName]:
    """Parse a branch name, or ``None`` when it does not fit the pattern."""
    match = _BRANCH_RE.match(name.strip())
    if not match:
        return None
    if match.group("ota") is not None:
        kind, ordinal = OTA, int(match.group("ota"))
    elif match.group("numbered") is not None:
        kind, ordinal = NUMBERED, int(match.group("numbered"))
    elif name.endswith("_Preemptive_OTA"):
        kind, ordinal = PREEMPTIVE, None
    else:
        kind, ordinal = RELEASE, None
    return BranchName(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        kind=kind,
        ordinal=ordinal,
        raw=name.strip(),
    )


def release_candidates(version: str, patch_zero_first: bool = False) -> List[Tuple[int, int, int]]:
    """Version tuples to try for a dotted app version like ``"6.7.1"``.

    Both the exact version and the ``x_y_0`` form are returned, because the
    current era cuts branches at ``x_y_0`` while older releases used the patch
    number. Order is exact first unless *patch_zero_first* says otherwise.
    """
    parts = [int(p) for p in str(version).strip().split(".")[:3] if p.isdigit()]
    while len(parts) < 3:
        parts.append(0)
    exact = (parts[0], parts[1], parts[2])
    zeroed = (parts[0], parts[1], 0)
    ordered = [zeroed, exact] if patch_zero_first else [exact, zeroed]
    out: List[Tuple[int, int, int]] = []
    for item in ordered:
        if item not in out:
            out.append(item)
    return out


def successors(
    branch: str,
    ota_depth: int = 3,
    numbered_depth: int = 2,
    patch_depth: int = 2,
    minor_depth: int = 1,
    include_preemptive: bool = True,
    include_self: bool = True,
) -> List[str]:
    """Branch names that could follow *branch*, newest shapes last.

    The list is small and fixed: more OTAs of the same release, the numbered
    variant, the preemptive branch, then the next patches and the next minor
    with their own first OTA. Twelve to twenty names for the defaults, which is
    one cheap round of requests rather than an open-ended search.
    """
    parsed = parse_branch(branch)
    if parsed is None:
        raise ValueError(f"{branch!r} does not look like a branch name")

    names: List[str] = []

    def add(name: str) -> None:
        if name not in names:
            names.append(name)

    if include_self:
        add(parsed.raw)

    version = parsed.version
    start = (parsed.ordinal or 0) + 1 if parsed.kind == OTA else 1
    for ordinal in range(start, start + ota_depth):
        add(build_branch(version, OTA, ordinal))
    start = (parsed.ordinal or 0) + 1 if parsed.kind == NUMBERED else 1
    for ordinal in range(start, start + numbered_depth):
        add(build_branch(version, NUMBERED, ordinal))
    if include_preemptive:
        add(build_branch(version, PREEMPTIVE))

    for step in range(1, patch_depth + 1):
        later = (parsed.major, parsed.minor, parsed.patch + step)
        add(build_branch(later, RELEASE))
        add(build_branch(later, OTA, 1))
        if include_preemptive:
            add(build_branch(later, PREEMPTIVE))

    for step in range(1, minor_depth + 1):
        later = (parsed.major, parsed.minor + step, 0)
        add(build_branch(later, RELEASE))
        add(build_branch(later, OTA, 1))
        if include_preemptive:
            add(build_branch(later, PREEMPTIVE))

    return names


__all__ = [
    "NUMBERED",
    "OTA",
    "PREEMPTIVE",
    "RELEASE",
    "BranchName",
    "build_branch",
    "parse_branch",
    "release_candidates",
    "successors",
]
