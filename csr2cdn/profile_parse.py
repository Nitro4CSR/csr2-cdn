"""Pure parsers for an already-decoded CSR2 profile non-secure blob.

Nothing in this module fetches, authenticates, decrypts, downloads, or writes.
Each function takes a mapping the caller has **already** decoded -- the game's
non-secure blob, i.e. the gzip-inflated JSON object from a profile fetch -- and
returns one small, specific result. The raw blob is never retained, returned,
copied, or persisted here: a caller that holds a full profile passes it in,
reads the narrow result, and is expected to discard the rest itself. This is
deliberately *only* a parser, so that publishing it exposes no way to obtain a
save, only a way to read two specific facts out of one the caller already has.

Two facts are read:

* **Weekly Elite Cup attempts** -- the per-member daily race count toward the
  8/day cap, from ``evca`` (``CrewEventsAttempted``) and ``cert``
  (``CrewEventAttemptResetTime``), scoped to one cup's minted event id.
* **Car ownership** -- whether the account owns a car (by its ``crdb`` car-db
  name), from the ``caow`` owned-cars list. Used for "owns the current prestige
  cup car?" once the caller supplies that cup's allowed ``crdb``(s).
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from .weekly_elite_cup import WeeklyEliteCup

_UTC = _dt.timezone.utc
#: ``cert`` wire format, e.g. ``"11/04/2026 00:00:00"`` (UTC, month-first).
_CERT_FORMAT = "%m/%d/%Y %H:%M:%S"


def _nonsecure_root(blob: Mapping) -> Mapping:
    """Accept the decoded non-secure blob, or a wrapper that contains it."""
    if not isinstance(blob, Mapping):
        raise TypeError("expected a decoded non-secure blob mapping")
    # Tolerate a caller passing a profile wrapper whose payload is nested under
    # a common key; otherwise treat the mapping itself as the blob root.
    for key in ("nonSecureBlob", "nonsecureBlob", "nsb"):
        inner = blob.get(key)
        if isinstance(inner, Mapping):
            return inner
    return blob


def _evca_map(blob: Mapping) -> dict:
    """``evca`` is a flat ``[eventId, count, eventId, count, ...]`` int list."""
    flat = _nonsecure_root(blob).get("evca") or []
    out: dict = {}
    it = iter(flat)
    for event_id in it:
        try:
            count = next(it)
        except StopIteration:
            break  # tolerate an odd-length list rather than raise
        try:
            out[int(event_id)] = int(count)
        except (TypeError, ValueError):
            continue
    return out


def _parse_cert(blob: Mapping) -> Optional[_dt.datetime]:
    raw = _nonsecure_root(blob).get("cert")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return _dt.datetime.strptime(raw.strip(), _CERT_FORMAT).replace(tzinfo=_UTC)
    except ValueError:
        return None


@dataclass(frozen=True)
class WeeklyEliteCupAttempts:
    """One account's own Weekly Elite Cup race count in the current window.

    ``attempts`` is this account's races logged toward the cup in the window
    that resets at ``reset_at``; ``cap`` is the per-member daily cap (8). This
    is the account's *own* figure: the game tracks it in this account's
    non-secure blob, and no other account can read it, so this never describes
    another crew member.
    """

    cup: WeeklyEliteCup
    attempts: int
    cap: int
    reset_at: Optional[_dt.datetime] = None

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.attempts)

    @property
    def exhausted(self) -> bool:
        return self.attempts >= self.cap


def parse_weekly_elite_cup_attempts(nonsecure_blob: Mapping,
                                    cup: WeeklyEliteCup) -> WeeklyEliteCupAttempts:
    """Read this account's WEC race count for ``cup`` from a decoded blob.

    Scoped to ``cup.event_id``; an account with no entry for the cup yields
    ``attempts=0``. Does not fetch -- the caller supplies the decoded blob.
    """
    attempts = _evca_map(nonsecure_blob).get(int(cup.event_id), 0)
    return WeeklyEliteCupAttempts(cup=cup, attempts=attempts, cap=cup.member_cap,
                                  reset_at=_parse_cert(nonsecure_blob))


def owned_car_db_names(nonsecure_blob: Mapping) -> frozenset:
    """The set of ``crdb`` car-db names the account owns (from ``caow``)."""
    caow = _nonsecure_root(nonsecure_blob).get("caow") or []
    names = set()
    for car in caow:
        if isinstance(car, Mapping):
            crdb = car.get("crdb")
            if isinstance(crdb, str) and crdb:
                names.add(crdb)
    return frozenset(names)


def owns_car(nonsecure_blob: Mapping, crdb: str) -> bool:
    """Whether the account owns the car with car-db name ``crdb``."""
    return str(crdb) in owned_car_db_names(nonsecure_blob)


def owns_any_car(nonsecure_blob: Mapping, crdbs: Iterable[str]) -> bool:
    """Whether the account owns any car in ``crdbs`` (by ``crdb`` name)."""
    owned = owned_car_db_names(nonsecure_blob)
    return any(str(c) in owned for c in crdbs)


def owns_prestige_cup_car(nonsecure_blob: Mapping, allowed_crdb) -> bool:
    """Whether the account owns the current prestige cup's eligible car.

    ``allowed_crdb`` is the cup's eligible car-db name, or an iterable of them
    when more than one car qualifies. The eligible ``crdb`` set is a property of
    the cup's configuration, not of the save, so the caller supplies it.
    """
    if isinstance(allowed_crdb, str):
        return owns_car(nonsecure_blob, allowed_crdb)
    return owns_any_car(nonsecure_blob, allowed_crdb)
