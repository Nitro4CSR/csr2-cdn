"""The weekly collections cups: when they run, their races, and their rules.

A Grand Crew Championship season carries two collections cups, one per week.
They are defined across two blocks that have to be joined on the schedule id:

``EventSchedule.ScheduleList``
    ``COLLECTIONS_CUP_V2_<season>_W<1|2>`` with ``Time_ActiveBetweenAny``, a
    three-day window, ``BasedOn_ScheduleID: "COLLECTIONS"`` and a
    ``DurationForeshadow`` of three days, which is why the next cup is visible
    before it opens.

``SpecialLadderEvents.LadderEvents.RaceEventGroups``
    the matching group, with ``SpecialLadderType: "CollectionsCup"``, a
    ``LockinNamespace``, and the week's ``RaceEvents``.

Season 279, read live on 2026-11-06::

    W1  Nov 8 10:00 -> Nov 11 10:00 UTC   44 races   Silver
    W2  Nov 15 10:00 -> Nov 18 10:00 UTC  68 races   Gold

44 and 68 are also exactly where the ``COLLECTIONS_CUP_V2_W1`` and ``_W2``
reward ladders top out, so the two blocks corroborate each other: six reward
rungs, the last of which needs every race in the week.

**The ladder most likely counts races, not wins.** The metadata spells the
rung field ``WinsRequired``, but each week's top rung equals that week's race
count exactly (44 and 68), which reads as "complete every race" rather than
"win N". That is an inference from the numbers, not from client code.
``WinsRequired`` is retained below as the wire key it is.

**Not the crew-against-crew tournament.** These weekly ladders are a separate
event from the Collections Tournament (three crews, three days of two time
trials, every fourteen days), which is decoded by
``csr2cdn.crew_optional_data.CrewTournament``. Earlier 0.7.2 drafts mixed the
two up; the time-trial, cooldown and trophy mechanics belong to the
tournament.

Each race names the collection slot its car must come from
(``LockinRequirements: ["{Slot 1}"]``) and may carry restrictions. The
restriction vocabulary observed across the tournament and ladder blocks is
``CarModel``, ``MinRarityStars``, ``IsSuperRare``, ``PPRange``, ``EPRange``
and the ``No<Part>Allowed`` family.

**No standings, no progress read.** These groups publish ``Leaderboard:
null`` and empty ``ShowdownDataContainerID``/``ShowdownPointsID``. Watched
live through W2 of season 279 (2026-11-15), no service read reflected the
ladder: every board spelling answered 403 and ``events/crewEventProgress``
stayed at 0 while the crew raced. Ladder progress is held in the player's own
save profile, which this package does not download. This module describes
cups and their rules only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Tuple

#: Schedule and group ids for a weekly cup.
CUP_ID = re.compile(r"^COLLECTIONS_CUP_V2_(?P<season>\d+)_W(?P<week>[12])$")
#: ``SpecialLadderType`` these groups declare.
LADDER_TYPE = "CollectionsCup"
#: Restriction kinds seen across the tournament and ladder blocks.
RESTRICTION_KINDS = (
    "CarModel", "MinRarityStars", "IsSuperRare", "PPRange", "EPRange",
    "NoEngineAllowed", "NoNitrousAllowed", "NoTyresAllowed", "NoBodyAllowed",
    "NoIntakeAllowed", "NoTransmissionAllowed", "NoTurboAllowed",
)
#: ``EventPanelOverride`` suffix to the tier the UI shows.
_TIERS = {"Silver": "Silver", "Gold": "Gold", "Bronze": "Bronze"}


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _text(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


@dataclass(frozen=True)
class Restriction:
    """One entry requirement, as published."""
    kind: Optional[str] = None
    details: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def known_kind(self) -> bool:
        return self.kind in RESTRICTION_KINDS

    @classmethod
    def from_wire(cls, raw: Any) -> "Restriction":
        if not isinstance(raw, Mapping):
            return cls()
        kind = _text(raw.get("RestrictionType"))
        return cls(kind, {k: v for k, v in raw.items() if k != "RestrictionType"})


@dataclass(frozen=True)
class CupRace:
    """One race of a weekly cup."""
    event_id: Optional[int] = None
    reward_group_id: Optional[str] = None
    #: Collection slots the entered car must satisfy, e.g. ``("{Slot 1}",)``.
    lockin_requirements: Tuple[str, ...] = ()
    restrictions: Tuple[Restriction, ...] = ()
    cash_prize: Optional[int] = None
    rp_prize: Optional[int] = None
    is_half_mile: Optional[bool] = None
    race_type: Optional[str] = None
    description_id: Optional[str] = None

    @classmethod
    def from_wire(cls, raw: Any) -> "CupRace":
        if not isinstance(raw, Mapping):
            return cls()
        reward = raw.get("RaceReward")
        reward = reward if isinstance(reward, Mapping) else {}
        lockin = raw.get("LockinRequirements")
        slots = tuple(x for x in lockin if isinstance(x, str)) \
            if isinstance(lockin, list) else ()
        restrictions = raw.get("Restrictions")
        rules = tuple(Restriction.from_wire(x) for x in restrictions) \
            if isinstance(restrictions, list) else ()
        half = raw.get("IsHalfMile")
        return cls(
            _int(raw.get("EventID")), _text(raw.get("RewardGroupID")), slots, rules,
            _int(reward.get("CashPrize")), _int(reward.get("RpPrize")),
            half if isinstance(half, bool) else None,
            _text(raw.get("ECBRaceType")), _text(raw.get("EventDescription")))


@dataclass(frozen=True)
class CollectionsCup:
    """One week's cup: its window, its races and its rules."""
    season: Optional[int] = None
    week: Optional[int] = None
    schedule_id: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    tier: Optional[str] = None
    lockin_namespace: Optional[str] = None
    races: Tuple[CupRace, ...] = field(default_factory=tuple, repr=False)
    #: Three days on every observed cup; the window the next cup is visible for.
    foreshadow_seconds: Optional[int] = None
    #: True only when the group published a leaderboard id, which none does.
    has_leaderboard: bool = False

    @property
    def race_count(self) -> int:
        return len(self.races)

    @property
    def reward_container(self) -> Optional[str]:
        """The ``EventMilestoneRewards`` container holding this week's ladder."""
        return "COLLECTIONS_CUP_V2_W%d" % self.week if self.week in (1, 2) else None

    def is_active(self, *, now: Optional[datetime] = None) -> Optional[bool]:
        if self.starts_at is None or self.ends_at is None:
            return None
        when = now if now is not None else datetime.now(timezone.utc)
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return self.starts_at <= when <= self.ends_at

    def as_dict(self) -> dict:
        return {
            "season": self.season, "week": self.week,
            "schedule_id": self.schedule_id, "tier": self.tier,
            "starts_at_utc": self.starts_at.isoformat() if self.starts_at else None,
            "ends_at_utc": self.ends_at.isoformat() if self.ends_at else None,
            "race_count": self.race_count,
            "reward_container": self.reward_container,
            "lockin_namespace": self.lockin_namespace,
            "has_leaderboard": self.has_leaderboard,
        }


def _window(row: Mapping[str, Any]):
    windows = row.get("Time_ActiveBetweenAny")
    if not isinstance(windows, list):
        return (None, None)
    for pair in windows:
        if isinstance(pair, list) and len(pair) == 2:
            start, end = _int(pair[0]), _int(pair[1])
            if start is not None and end is not None and start < end:
                return (datetime.fromtimestamp(start, timezone.utc),
                        datetime.fromtimestamp(end, timezone.utc))
    return (None, None)


def _tier(row: Mapping[str, Any]) -> Optional[str]:
    panel = _text(row.get("EventPanelOverride")) or ""
    for suffix, name in _TIERS.items():
        if panel.endswith(suffix):
            return name
    return None


@dataclass(frozen=True)
class CollectionsCupCalendar:
    """Every weekly cup the metadata defines, joined across both blocks."""
    cups: Mapping[Tuple[int, int], CollectionsCup] = field(default_factory=dict,
                                                           repr=False)

    def __len__(self) -> int:
        return len(self.cups)

    @classmethod
    def from_blocks(cls, event_schedule: Any, special_ladder_events: Any
                    ) -> "CollectionsCupCalendar":
        schedules: Dict[Tuple[int, int], Mapping[str, Any]] = {}
        rows = event_schedule.get("ScheduleList") \
            if isinstance(event_schedule, Mapping) else None
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            match = CUP_ID.match(str(row.get("id") or row.get("ScheduleID") or ""))
            if match:
                schedules[(int(match.group("season")), int(match.group("week")))] = row

        groups: Dict[Tuple[int, int], Mapping[str, Any]] = {}
        ladder = special_ladder_events.get("LadderEvents") \
            if isinstance(special_ladder_events, Mapping) else None
        group_rows = ladder.get("RaceEventGroups") if isinstance(ladder, Mapping) else None
        for row in group_rows if isinstance(group_rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            match = CUP_ID.match(str(row.get("EventGroupName") or ""))
            if match:
                groups[(int(match.group("season")), int(match.group("week")))] = row

        out: Dict[Tuple[int, int], CollectionsCup] = {}
        for key in sorted(set(schedules) | set(groups)):
            season, week = key
            sched = schedules.get(key) or {}
            group = groups.get(key) or {}
            start, end = _window(sched)
            races = group.get("RaceEvents")
            out[key] = CollectionsCup(
                season=season, week=week,
                schedule_id=_text(sched.get("id") or group.get("ScheduleID")),
                starts_at=start, ends_at=end, tier=_tier(group),
                lockin_namespace=_text(group.get("LockinNamespace")),
                races=tuple(CupRace.from_wire(r) for r in races)
                if isinstance(races, list) else (),
                foreshadow_seconds=_int(sched.get("DurationForeshadow")),
                has_leaderboard=bool(group.get("Leaderboard")))
        return cls(out)

    @property
    def seasons(self) -> Tuple[int, ...]:
        return tuple(sorted({season for season, _ in self.cups}))

    def for_season(self, season: int) -> Tuple[CollectionsCup, ...]:
        return tuple(cup for (s, _), cup in sorted(self.cups.items()) if s == season)

    def get(self, season: int, week: int) -> Optional[CollectionsCup]:
        return self.cups.get((season, week))

    def active(self, *, now: Optional[datetime] = None) -> Optional[CollectionsCup]:
        when = now if now is not None else datetime.now(timezone.utc)
        for _, cup in sorted(self.cups.items()):
            if cup.is_active(now=when):
                return cup
        return None

    def next_after(self, *, now: Optional[datetime] = None) -> Optional[CollectionsCup]:
        """The soonest cup that has not started yet."""
        when = now if now is not None else datetime.now(timezone.utc)
        upcoming = [cup for _, cup in sorted(self.cups.items())
                    if cup.starts_at is not None and cup.starts_at > when]
        upcoming.sort(key=lambda c: c.starts_at)
        return upcoming[0] if upcoming else None
