"""Working out which asset database branch to use, without hard coding one.

The game does not guess branch names. ``Account.get_AssetDatabaseBranch`` picks,
in order:

1. ``FeatureKillswitches.ExplicitDataBranchName``, when it is not empty
2. the ``asset_data_branch_name`` baked into the build's ``BranchConfig`` asset
3. ``"Default_Android"``

When preemptive downloading is enabled the client separately polls
``FeatureKillswitches.PreemptiveDownloadDataBranchName``, which points at data
for a release that has not shipped yet.

This module reaches the same answer from nothing at all::

    store version (6.7.1) -> release (6.7.0) -> base branch (6_7_0_Release)
    -> database version -> product_version (6.7.81) -> FeatureKillswitches
    -> the current branch

Step one lives in :mod:`csr2cdn.store`; the rest is here.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, NamedTuple, Optional

from csr2cdn.errors import BranchNotFoundError, Csr2CdnError, MissingZidError
from csr2cdn.metadata import MetadataClient
from csr2cdn.patterns import (
    BranchName as ParsedBranch,
    PREEMPTIVE,
    RELEASE,
    build_branch,
    parse_branch,
    release_candidates,
    successors,
)
from csr2cdn.store import CSR2, AppIds, latest_store_version, previous_releases

EXPLICIT_KEY = "ExplicitDataBranchName"
PREEMPTIVE_KEY = "PreemptiveDownloadDataBranchName"
DEFAULT_ANDROID_BRANCH = "Default_Android"


class BranchNames(NamedTuple):
    """The two branch names the metadata service can announce."""

    explicit: str
    preemptive: str

    def candidates(self, allow_preemptive: bool = True) -> List[str]:
        """Both names, most authoritative first, without the empty ones."""
        names = [self.explicit]
        if allow_preemptive:
            names.append(self.preemptive)
        return [name for name in names if name]


def branch_names(
    zid: str,
    product_version: str,
    metadata: Optional[MetadataClient] = None,
) -> BranchNames:
    """Read both branch names out of ``FeatureKillswitches``.

    Either one is an empty string when the service is not announcing it.
    """
    if not zid:
        raise MissingZidError("a zid is required to read FeatureKillswitches")
    client = metadata or MetadataClient()
    try:
        config = client.killswitches(zid, product_version)
    finally:
        if metadata is None:
            client.close()
    return BranchNames(
        explicit=(config.get(EXPLICIT_KEY) or "").strip(),
        preemptive=(config.get(PREEMPTIVE_KEY) or "").strip(),
    )


def base_branch_candidates(
    release_version: Optional[str] = None,
    app: AppIds = CSR2,
    session: Optional[Any] = None,
    lookback: int = 2,
    lookahead: int = 1,
    timeout: float = 15.0,
) -> List[str]:
    """Release branch names to try when bootstrapping, newest first.

    Without *release_version* the current app version is looked up in the store.
    Both the exact version and the ``x_y_0`` form are tried, since the patch
    component is part of the branch name in some eras and not others. The next
    minor is tried first because a store listing can lag its own release, and
    earlier releases are appended because the CDN keeps old branches.
    """
    if release_version is None:
        release_version = latest_store_version(app, session=session, timeout=timeout)
    versions: List[tuple] = []

    def add_release(dotted: str) -> None:
        for version in release_candidates(dotted):
            if version not in versions:
                versions.append(version)

    major, minor, _patch = release_candidates(release_version)[0]
    for step in range(lookahead, 0, -1):
        add_release(f"{major}.{minor + step}.0")
    add_release(release_version)
    for earlier in previous_releases(release_version, lookback):
        add_release(earlier)
    return [build_branch(version, RELEASE) for version in versions]


def probe_branches(
    cdn: Any,
    branch: str,
    allow_preemptive: bool = True,
    include_self: bool = True,
    **depths: int,
) -> Dict[str, int]:
    """Ask the CDN which of *branch*'s possible successors exist.

    Returns the ones that answer, mapped to their database version. The
    candidate list comes from :func:`csr2cdn.patterns.successors`, so this is a
    fixed round of requests rather than a search. Database versions increase
    globally, so ``max(result, key=result.get)`` is the newest branch.
    """
    candidates = successors(
        branch, include_preemptive=allow_preemptive, include_self=include_self, **depths
    )
    found: Dict[str, int] = {}
    for candidate in candidates:
        version = cdn.try_database_version(candidate)
        if version is not None:
            found[candidate] = int(version) if str(version).isdigit() else 0
    return found


def resolve_branch(
    zid: Optional[str] = None,
    product_version: Optional[str] = None,
    cdn: Any = None,
    metadata: Optional[MetadataClient] = None,
    allow_preemptive: bool = True,
    fallback: Optional[Iterable[str]] = None,
    verify: bool = True,
    probe: bool = False,
    probe_options: Optional[Dict[str, int]] = None,
) -> str:
    """Return the branch to download from.

    With a *zid* the metadata service is asked what it announces, which is what
    the game itself does. With *probe* the CDN is also asked about the plausible
    successors of every candidate, which catches a branch that is already
    uploaded but not yet announced. Either route alone works: probing needs no
    zid, and announcement needs no probing.

    Candidates are then checked against the CDN and the one reporting the
    highest database version wins, since those versions increase globally.
    ``verify=False`` returns the first candidate without any request, and is
    ignored when probing, which is itself a form of verification.

    :param allow_preemptive: consider preemptive branches, announced or probed.
    :param fallback: branch names to consider when nothing is announced.
    :param probe_options: depth overrides for :func:`csr2cdn.patterns.successors`.
    """
    candidates: List[str] = []
    if zid:
        if not product_version:
            raise Csr2CdnError("resolve_branch needs a product_version alongside a zid")
        names = branch_names(zid, product_version, metadata=metadata)
        candidates.extend(names.candidates(allow_preemptive))
    for name in fallback or ():
        if name and name not in candidates:
            candidates.append(name)
    if not candidates:
        raise BranchNotFoundError(
            "nothing to go on: supply a zid, a fallback branch, or both"
        )
    if not allow_preemptive:
        candidates = [
            name
            for name in candidates
            if (parse_branch(name) or ParsedBranch(0, 0, 0, RELEASE, None, name)).kind != PREEMPTIVE
        ]
    if not verify and not probe:
        return candidates[0]

    from csr2cdn.cdn import CDN

    client = cdn or CDN()
    try:
        if probe:
            found: Dict[str, int] = {}
            for candidate in list(candidates):
                if parse_branch(candidate) is None:
                    version = client.try_database_version(candidate)
                    if version is not None:
                        found[candidate] = int(version) if str(version).isdigit() else 0
                    continue
                found.update(
                    probe_branches(
                        client,
                        candidate,
                        allow_preemptive=allow_preemptive,
                        **(probe_options or {}),
                    )
                )
        else:
            found = {}
            for candidate in candidates:
                version = client.try_database_version(candidate)
                if version is not None:
                    found[candidate] = int(version) if str(version).isdigit() else 0
    finally:
        if cdn is None:
            client.close()
    if not found:
        raise BranchNotFoundError(f"none of the branches {candidates!r} exist on the CDN")
    return max(found, key=lambda name: (found[name], name))


__all__ = [
    "BranchNames",
    "DEFAULT_ANDROID_BRANCH",
    "EXPLICIT_KEY",
    "PREEMPTIVE_KEY",
    "base_branch_candidates",
    "branch_names",
    "probe_branches",
    "resolve_branch",
]
