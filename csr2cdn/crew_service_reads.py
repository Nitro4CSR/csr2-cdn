"""Decoders for the 0.7.2 crew-service read replies.

Four routes, all read-only, reconstructed from the 6.8.0 IL2CPP metadata:

``events/crewEventProgress``
    crew-aggregate progress for one event series
``crews/showCrewsRanks``
    the crew's leaderboard standing plus its neighbours
``crews/checkCrewPerks``
    perk milestones and unlocks
``wildcards/status``
    crew wildcard season state

Provenance and its limits
-------------------------
Request keys are hand-built dictionaries in the game and their spellings are
compiled in as string literals, so they are quoted exactly (see
``_service_reads``). Response objects are a different matter: their field names
are *not* in the literal table, which is the signature of reflection-based
deserialization -- the serializer walks the class's fields, so no literal is
needed and the wire key is normally the field name itself.

"Normally" is doing work in that sentence. ``CheckUserCrewResponse`` declares
``memberCount``, but the live 6.8.0 reply spells that value ``members``, which
is why ``OwnCrew`` reads several candidate spellings. Every decoder here does
the same: the declared field name first, then plausible snake_case and legacy
variants, and the raw node is always preserved so a miss can be diagnosed from
a real reply instead of guessed at again.

Live status, 2026-11-06 to 2026-11-15: ``crews/checkCrewPerks`` and
``wildcards/status`` answer, and their decoders follow the real replies;
``events/crewEventProgress`` answers but has returned ``progress: 0`` for
every id pairing tried; ``crews/showCrewsRanks`` answers HTTP 500 to every
request shape tried. Treat an absent attribute as "not found in this reply",
never as zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from .service_models import (
    ServiceResponseError, _field, _int, _mapping, _optional_str, _payload, _str,
)

_MAX_I64 = 2**63 - 1


def _rows(node: Mapping[str, Any], *names: str) -> Tuple[Mapping[str, Any], ...]:
    """Candidate list-of-objects under any of ``names``; () when absent."""
    value = _field(node, *names)
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _flag(node: Mapping[str, Any], *names: str) -> Optional[bool]:
    value = _field(node, *names)
    return value if type(value) is bool else None


def _bounded_int(node: Mapping[str, Any], *names: str) -> Optional[int]:
    value = _int(node, *names)
    return value if value is not None and -_MAX_I64 <= value <= _MAX_I64 else None


# ---------------------------------------------------------------------------
# events/crewEventProgress


@dataclass(frozen=True)
class CrewEventProgress:
    """`CrewEventProgress` {isValid, progress, participated}.

    ``progress`` is a crew total for one ``(crew, event, series)`` triple. The
    server publishes no per-member breakdown on this route, even though the
    client submits each race on its own with an ``m_is_win`` flag.

    ``participated`` has an unestablished type on the wire, so it is kept raw
    and offered through three accessors that each return ``None`` unless the
    value actually has that shape. Reading it as a count when it is a flag, or
    as a flag when it is a roster, would be a silent fabrication.
    """

    progress: Optional[int] = None
    is_valid: Optional[bool] = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def participated_flag(self) -> Optional[bool]:
        value = self.raw.get("participated")
        return value if type(value) is bool else None

    @property
    def participated_count(self) -> Optional[int]:
        value = self.raw.get("participated")
        return value if type(value) is int and not isinstance(value, bool) else None

    @property
    def participated_member_ids(self) -> Optional[Tuple[str, ...]]:
        value = self.raw.get("participated")
        if not isinstance(value, (list, tuple)):
            return None
        return tuple(str(item) for item in value
                     if isinstance(item, (str, int)) and not isinstance(item, bool))

    @property
    def participated_shape(self) -> str:
        """Name the wire shape without exposing the value, for diagnostics."""
        value = self.raw.get("participated")
        if "participated" not in self.raw:
            return "absent"
        if type(value) is bool:
            return "bool"
        if type(value) is int:
            return "int"
        if isinstance(value, (list, tuple)):
            return f"list[{len(value)}]"
        if isinstance(value, Mapping):
            return "object"
        return type(value).__name__

    @classmethod
    def from_response(cls, response: Any) -> "CrewEventProgress":
        node = _payload(response)
        inner = _field(node, "crewEventProgress", "crew_event_progress")
        # The nested object carries its own isValid, which is a legitimate
        # "no progress recorded" signal rather than a transport failure, so it
        # must not go through the envelope's rejection check.
        if isinstance(inner, Mapping):
            node = inner
        elif not any(key in node for key in ("progress", "participated")):
            raise ServiceResponseError("crew event progress fields missing from response")
        return cls(_bounded_int(node, "progress"),
                   _flag(node, "isValid", "is_valid"),
                   dict(node))


# ---------------------------------------------------------------------------
# crews/showCrewsRanks


@dataclass(frozen=True)
class CrewRankEntry:
    """One crew on the crew leaderboard.

    The row shape is not declared by ``FetchCrewRankResponse``, which types
    ``topCrews``/``crewsJustAbove``/``crewsJustBelow`` as collections. Each
    candidate spelling below is a guess until a live reply arrives; the raw row
    is retained so the real keys can be read off one response.
    """

    crew_uid: Optional[str] = None
    name: Optional[str] = None
    rank: Optional[int] = None
    score: Optional[int] = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "CrewRankEntry":
        return cls(_optional_str(row, "crewUID", "crew_uid", "crewId", "crew_id"),
                   _optional_str(row, "crewName", "crew_name", "name"),
                   _bounded_int(row, "crewRank", "crew_rank", "rank"),
                   _bounded_int(row, "crewRP", "crew_rp", "score", "RP", "rp"),
                   dict(row))


@dataclass(frozen=True)
class CrewRankings:
    """`FetchCrewRankResponse` {crewUID, crewRank, topCrews, crewsJustAbove, crewsJustBelow}."""

    crew_uid: Optional[str] = None
    crew_rank: Optional[int] = None
    top: Tuple[CrewRankEntry, ...] = ()
    just_above: Tuple[CrewRankEntry, ...] = ()
    just_below: Tuple[CrewRankEntry, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def neighbourhood(self) -> Tuple[CrewRankEntry, ...]:
        """Above, own crew's bracket and below, in leaderboard order.

        The own crew's own row is not separately published; ``crew_rank``
        carries it. This is the two neighbour lists joined, nothing more.
        """
        return self.just_above + self.just_below

    @classmethod
    def from_response(cls, response: Any) -> "CrewRankings":
        node = _payload(response)
        markers = ("crewRank", "crew_rank", "topCrews", "top_crews",
                   "crewsJustAbove", "crewsJustBelow")
        if not any(key in node for key in markers):
            raise ServiceResponseError("crew ranking fields missing from response")
        decode = CrewRankEntry.from_row
        return cls(
            _optional_str(node, "crewUID", "crew_uid"),
            _bounded_int(node, "crewRank", "crew_rank"),
            tuple(decode(r) for r in _rows(node, "topCrews", "top_crews")),
            tuple(decode(r) for r in _rows(node, "crewsJustAbove", "crews_just_above")),
            tuple(decode(r) for r in _rows(node, "crewsJustBelow", "crews_just_below")),
            dict(node))


# ---------------------------------------------------------------------------
# crews/checkCrewPerks
#
# Verified live on 2026-11-06. The reply does not use any of the field names
# `PlayerCrewPerks` declares. It is:
#
#     {"crew_uid", "crew_respect_rank", "perkGroupsUnlocked",
#      "perksUnlocked": [...], "milestone_achieved": {...}, "error_code",
#      "app_ver"}
#
# `milestone_achieved` is a flat map, not a list of rungs, with four key
# patterns per family:
#
#     Milestone_<Family>                    the tier reached
#     Milestone_<Family>_quantity           the crew's running total
#     Milestone_<Family>_quantity_target    what the next tier needs
#     Milestone_<Family>_Reward             the payout, when one is published
#
# Nine families were present: Crew_CE, Crew_GV, Crew_Level, EVO_Points,
# Fresh_RP, Fusion_Parts_Fitted, Gacha_Pulls, Races and Tuning_Attempts. The
# families are not a fixed list in this decoder -- whatever the server sends
# is what comes back -- because a future release may add one.

_MILESTONE_PREFIX = "Milestone_"
#: Suffixes, longest first so `_quantity_target` is not read as `_quantity`.
_MILESTONE_SUFFIXES = ("_quantity_target", "_quantity", "_Reward")


@dataclass(frozen=True)
class CrewMilestone:
    """One crew milestone family out of ``milestone_achieved``.

    ``target`` is what the next tier needs. A target of 0 alongside a non-zero
    tier is how the server marks a family with nothing left to reach, so it is
    reported through ``is_maxed`` rather than as a requirement of zero.
    """

    family: str
    tier: Optional[int] = None
    quantity: Optional[int] = None
    target: Optional[int] = None
    reward: Optional[int] = None

    @property
    def is_maxed(self) -> Optional[bool]:
        """True when no further tier is published for this family."""
        if self.target is None:
            return None
        return self.target == 0

    @property
    def remaining(self) -> Optional[int]:
        """How much more the crew needs, or ``None`` when that is unknowable.

        ``None`` for a maxed family and for one missing either number; never a
        negative value, since overshooting a target is normal.
        """
        if self.quantity is None or self.target is None or self.target == 0:
            return None
        return max(0, self.target - self.quantity)

    @property
    def fraction(self) -> Optional[float]:
        """Progress toward the next tier in 0..1, or ``None`` if not derivable."""
        if self.quantity is None or not self.target or self.target < 0:
            return None
        return min(1.0, self.quantity / self.target)


def _milestones(node: Any) -> Tuple[CrewMilestone, ...]:
    """Fold the flat ``milestone_achieved`` map into one record per family."""
    if not isinstance(node, Mapping):
        return ()
    families: dict = {}
    for key, value in node.items():
        if not isinstance(key, str) or not key.startswith(_MILESTONE_PREFIX):
            continue
        name = key[len(_MILESTONE_PREFIX):]
        slot = "tier"
        for suffix in _MILESTONE_SUFFIXES:
            if name.endswith(suffix):
                name, slot = name[: -len(suffix)], suffix.lstrip("_")
                break
        if not name:
            continue
        number = value if type(value) is int and not isinstance(value, bool) else None
        families.setdefault(name, {})[slot] = number
    out = []
    for name in sorted(families):
        slots = families[name]
        out.append(CrewMilestone(name, slots.get("tier"), slots.get("quantity"),
                                 slots.get("quantity_target"), slots.get("Reward")))
    return tuple(out)


@dataclass(frozen=True)
class CrewPerks:
    """`crews/checkCrewPerks`, decoded against the live 6.8.0 reply.

    ``perks_unlocked`` is a list on the wire -- empty on the account this was
    verified against -- so it is kept as a tuple of raw entries rather than
    guessed at a count.
    """

    crew_uid: Optional[str] = None
    crew_respect_rank: Optional[int] = None
    perk_groups_unlocked: Optional[int] = None
    perks_unlocked: Tuple[Any, ...] = ()
    milestones: Tuple[CrewMilestone, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def families(self) -> Tuple[str, ...]:
        return tuple(m.family for m in self.milestones)

    def milestone(self, family: str) -> Optional[CrewMilestone]:
        for record in self.milestones:
            if record.family == family:
                return record
        return None

    @classmethod
    def from_response(cls, response: Any) -> "CrewPerks":
        node = _payload(response)
        markers = ("crew_respect_rank", "milestone_achieved", "perksUnlocked",
                   "perkGroupsUnlocked")
        if not any(key in node for key in markers):
            raise ServiceResponseError("crew perk fields missing from response")
        unlocked = _field(node, "perksUnlocked", "perks_unlocked")
        return cls(
            _optional_str(node, "crew_uid", "crewUID"),
            _bounded_int(node, "crew_respect_rank", "crewRespectRank"),
            _bounded_int(node, "perkGroupsUnlocked", "perk_groups_unlocked"),
            tuple(unlocked) if isinstance(unlocked, (list, tuple)) else (),
            _milestones(_field(node, "milestone_achieved", "milestoneAchieved")),
            dict(node))


# ---------------------------------------------------------------------------
# wildcards/status
#
# Verified live on 2026-11-06, which settled two things the metadata could
# not. The route is the **plural** `wildcards/status`; the singular
# `wildcard/status` is also a compiled literal but answers with something that
# is not JSON. And the reply uses none of `WildcardData`'s 17 field names:
#
#     {"season_end_time", "token", "period_mod", "last_message_id",
#      "cards": [{"cost", "level", "paid", "rarity", "seq", "status"}],
#      "error_code", "app_ver"}
#
# `rarity` is a string ("bronze"), not the integer the C# field implied, and
# `status` is the `WildcardStatus` enum as text.


#: `WildcardStatus` enum members, which the live `status` field spells out.
WILDCARD_STATES = ("NOT_SET", "incomplete", "complete", "active")


@dataclass(frozen=True)
class Wildcard:
    """One entry of the live ``cards`` list.

    Only what the server sends is modelled. The C# type also declares
    `awaitingNetwork_Donate`, `pendingDonationAmount` and similar, but those
    are client-side bookkeeping and do not appear on the wire.
    """

    seq: Optional[int] = None
    rarity: Optional[str] = None
    status: Optional[str] = None
    level: Optional[int] = None
    cost: Optional[int] = None
    paid: Optional[int] = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def is_known_state(self) -> bool:
        """Whether ``status`` is one of the four compiled enum members."""
        return self.status in WILDCARD_STATES

    @property
    def is_complete(self) -> Optional[bool]:
        if self.status is None:
            return None
        return self.status == "complete"

    @property
    def is_active(self) -> Optional[bool]:
        if self.status is None:
            return None
        return self.status == "active"

    @property
    def remaining(self) -> Optional[int]:
        """Tokens still needed, or ``None`` when either number is missing."""
        if self.cost is None or self.paid is None:
            return None
        return max(0, self.cost - self.paid)

    @property
    def fraction(self) -> Optional[float]:
        if self.paid is None or not self.cost or self.cost < 0:
            return None
        return min(1.0, self.paid / self.cost)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Wildcard":
        return cls(_bounded_int(row, "seq", "sequentialIndex"),
                   _optional_str(row, "rarity"),
                   _optional_str(row, "status"),
                   _bounded_int(row, "level", "initialCrewLevel"),
                   _bounded_int(row, "cost"),
                   _bounded_int(row, "paid"),
                   dict(row))


@dataclass(frozen=True)
class CrewWildcardStatus:
    """`wildcards/status`, decoded against the live 6.8.0 reply.

    ``token`` is the crew's donatable token balance, not a credential.
    ``period_mod`` is published by the server and its meaning is not
    established, so it is carried without interpretation.
    """

    season_end_time: Optional[int] = None
    token: Optional[int] = None
    period_mod: Optional[int] = None
    last_message_id: Optional[int] = None
    cards: Tuple[Wildcard, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def active(self) -> Tuple[Wildcard, ...]:
        return tuple(c for c in self.cards if c.is_active)

    @classmethod
    def from_response(cls, response: Any) -> "CrewWildcardStatus":
        node = _payload(response)
        markers = ("season_end_time", "seasonEndTime", "cards",
                   "wildcardDataList", "token")
        if not any(key in node for key in markers):
            raise ServiceResponseError("wildcard status fields missing from response")
        return cls(_bounded_int(node, "season_end_time", "seasonEndTime"),
                   _bounded_int(node, "token", "tokens"),
                   _bounded_int(node, "period_mod", "periodMod"),
                   _bounded_int(node, "last_message_id", "lastmessage_ID"),
                   tuple(Wildcard.from_row(r) for r in _rows(
                       node, "cards", "wildcardDataList", "wildcard_data_list")),
                   dict(node))


__all__ = [
    "CrewEventProgress",
    "CrewRankEntry", "CrewRankings",
    "CrewMilestone", "CrewPerks",
    "WILDCARD_STATES", "Wildcard", "CrewWildcardStatus",
]
