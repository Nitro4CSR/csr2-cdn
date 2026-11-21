"""The Weekly Elite Cup (``ET_WEEKLY_CREW_TRIAL``).

The Weekly Elite Cup is a weekly-repeating crew event: the crew collectively
races toward a goal, and each member may contribute a capped number of races.
It is not a leaderboard board and it is not a Collections Cup -- it is a single
repeating ``SeriesEvent`` whose per-week instance id is minted on the client,
so it never appears in the downloadable metadata by number.

Everything here was decoded from the 6.8.0 client (``SeriesEvent``
``ET_WEEKLY_CREW_TRIAL``) and confirmed against live ``events/crewEventProgress``
replies:

* ``SeriesID`` is :data:`SERIES_ID` (19999) and the per-member race cap
  (``CrewMemberContribution``) is :data:`CREW_MEMBER_CONTRIBUTION` (8).
* The schedule anchors at :data:`EPOCH_START` (2020-12-21 10:00 UTC), repeats
  every :data:`WEEK_SECONDS` and runs for :data:`RUN_SECONDS` of each week
  (Mon 10:00 -> Fri 10:00 UTC).
* ``iteration = (now - EPOCH_START) // WEEK_SECONDS + 1``.
* The race ``EventID`` for an iteration is
  ``int("08" + "%05d" % iteration + "999")`` -- this is the client's
  ``SeriesEvent.GenerateUniqueWeeklyEventID`` (``RaceEventGroup.IntToPaddedString``
  pads EventFile ``08`` to 2, the iteration to 5, and ``999`` to 3, then
  concatenates). ``events/crewEventProgress`` is read with
  ``(event_id=that id, series_id=19999)``; the server keeps roughly the two most
  recent iterations.

The progress figure is a crew total; no per-member breakdown exists on this
route (see :mod:`csr2cdn.crew_service_reads`).
"""
from __future__ import annotations

import datetime as _dt
import re
import time as _time
from dataclasses import dataclass
from typing import Optional

#: Unix seconds of the first Weekly Elite Cup (2020-12-21 10:00:00 UTC).
EPOCH_START = 1608544800
#: Seconds between successive cups (``TimeRepeatDuration``).
WEEK_SECONDS = 604800
#: Seconds each cup is live, from its start (``TimeDuration``: Mon -> Fri).
RUN_SECONDS = 345600
#: The event's ``SeriesID``, used as ``series_id`` on crewEventProgress.
SERIES_ID = 19999
#: ``EventFile`` for the series; the leading field of the minted event id.
EVENT_FILE = 8
#: Per-member race cap (``CrewMemberContribution``).
CREW_MEMBER_CONTRIBUTION = 8
#: Observed collective race goal. A soft reference only; the live total can
#: exceed it, so nothing here enforces or depends on it.
GOAL_RACES = 900

_EVENT_ID = re.compile(r"^0*%d(\d{5})999$" % EVENT_FILE)
_UTC = _dt.timezone.utc


def _now(now: Optional[int]) -> int:
    return int(now if now is not None else _time.time())


def current_iteration(now: Optional[int] = None) -> int:
    """The cup iteration number covering ``now`` (Unix seconds, default: now)."""
    return (_now(now) - EPOCH_START) // WEEK_SECONDS + 1


def event_id_for(iteration: int) -> int:
    """The minted race ``EventID`` for ``iteration`` (``GenerateUniqueWeeklyEventID``)."""
    if iteration < 0:
        raise ValueError("iteration must be non-negative")
    return int("%02d%05d999" % (EVENT_FILE, iteration))


def iteration_of_event_id(event_id) -> Optional[int]:
    """Recover the iteration from a minted WEC event id, or ``None`` if it is not one."""
    m = _EVENT_ID.match(str(event_id))
    return int(m.group(1)) if m else None


@dataclass(frozen=True)
class WeeklyEliteCup:
    """One week's Weekly Elite Cup instance, computed entirely offline."""

    iteration: int
    event_id: int
    series_id: int = SERIES_ID
    #: Per-member race cap for this cup.
    member_cap: int = CREW_MEMBER_CONTRIBUTION

    @classmethod
    def for_iteration(cls, iteration: int) -> "WeeklyEliteCup":
        return cls(iteration=iteration, event_id=event_id_for(iteration))

    @classmethod
    def current(cls, now: Optional[int] = None) -> "WeeklyEliteCup":
        return cls.for_iteration(current_iteration(now))

    @property
    def starts_at_unix(self) -> int:
        return EPOCH_START + (self.iteration - 1) * WEEK_SECONDS

    @property
    def ends_at_unix(self) -> int:
        return self.starts_at_unix + RUN_SECONDS

    @property
    def starts_at(self) -> _dt.datetime:
        return _dt.datetime.fromtimestamp(self.starts_at_unix, _UTC)

    @property
    def ends_at(self) -> _dt.datetime:
        return _dt.datetime.fromtimestamp(self.ends_at_unix, _UTC)

    def is_live(self, now: Optional[int] = None) -> bool:
        return self.starts_at_unix <= _now(now) < self.ends_at_unix


@dataclass(frozen=True)
class WeeklyEliteCupProgress:
    """The crew's total progress on one Weekly Elite Cup.

    ``progress`` is the whole crew's race count for the cup; it is not broken
    down per member on this route. ``participated`` is the querying account's
    own flag.
    """

    cup: WeeklyEliteCup
    progress: Optional[int] = None
    participated: Optional[bool] = None
    is_valid: Optional[bool] = None

    @classmethod
    def from_crew_event_progress(cls, cup: WeeklyEliteCup, cep) -> "WeeklyEliteCupProgress":
        """Wrap a :class:`csr2cdn.crew_service_reads.CrewEventProgress`."""
        return cls(cup=cup, progress=cep.progress,
                   participated=cep.participated_flag, is_valid=cep.is_valid)

    def remaining(self, goal: int = GOAL_RACES) -> Optional[int]:
        """Races left to ``goal`` (clamped at 0), or ``None`` if progress unknown."""
        if self.progress is None:
            return None
        return max(0, goal - self.progress)

    def goal_reached(self, goal: int = GOAL_RACES) -> Optional[bool]:
        if self.progress is None:
            return None
        return self.progress >= goal


# -- Participation ---------------------------------------------------------
#
# A frequent ask is "who in the crew contributed to this week's cup, and how
# many races each?". The exact per-member race count is NOT retrievable from
# the server: ``events/crewEventProgress`` returns only the crew total (see
# ``WeeklyEliteCupProgress``), there is no leaderboard board for the series,
# and no per-member parameter changes the reply (verified live against 6.8.0).
# Each member's own tally lives solely in that member's non-secure blob
# (``CrewEventsAttempted``), which is only ever returned to that account.
#
# What the server *does* expose crew-wide is the roster, with each member's
# identity and their cumulative activity counters (seasonal Crew RP, profile
# RP). Pairing the crew total with a roster snapshot gives an honest
# participation view: who is on the crew, their standing activity counters at
# one moment, and the crew's collective cup progress. Snapshot it at the cup's
# start and again near its end and diff the counters to see which members were
# active during the window -- an activity proxy, not an exact WEC race count.


@dataclass(frozen=True)
class WeeklyEliteCupMemberActivity:
    """One crew member's identity and activity counters at a single moment.

    These are the crew-wide roster values (``crews/viewMembers``); none of them
    is a Weekly Elite Cup race count, which the server does not break down per
    member. ``season_crew_rp`` and ``player_rp`` are cumulative counters useful
    for snapshot-and-diff over the cup window.
    """

    player_uid: Optional[str]
    zid: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    #: Roster seasonal Crew RP counter (``cc_contrib``), cumulative.
    season_crew_rp: Optional[int] = None
    #: Profile RP (``player_rp``), cumulative; not crew-season contribution.
    player_rp: Optional[int] = None

    @classmethod
    def from_crew_member(cls, member) -> "WeeklyEliteCupMemberActivity":
        """Build from a :class:`csr2cdn.service_models.CrewMember`."""
        return cls(
            player_uid=member.player_uid,
            zid=member.zid,
            name=member.nickname or member.name,
            role=member.role_normalized or member.role,
            season_crew_rp=member.season_crew_rp,
            player_rp=member.player_rp,
        )


@dataclass(frozen=True)
class WeeklyEliteCupParticipation:
    """The crew's Weekly Elite Cup progress paired with a roster snapshot.

    ``progress`` is the crew's collective race count for the cup. ``members``
    is every member with their identity and cumulative activity counters at
    ``captured_at`` (Unix seconds). There is deliberately no per-member race
    count here: the server does not expose one (see this module's docstring),
    so a caller wanting per-member activity diffs two snapshots over the cup
    window rather than reading an exact figure from any single call.
    """

    cup: WeeklyEliteCup
    progress: WeeklyEliteCupProgress
    members: tuple = ()
    captured_at: Optional[int] = None

    #: Why no exact per-member race count is present; surface this to callers.
    per_member_races_available: bool = False

    @classmethod
    def from_reads(cls, cup: WeeklyEliteCup, progress: WeeklyEliteCupProgress,
                   crew_members, *, now: Optional[int] = None) -> "WeeklyEliteCupParticipation":
        """Assemble from a WEC progress read and a ``CrewMembers`` roster."""
        roster = getattr(crew_members, "members", crew_members)
        rows = tuple(WeeklyEliteCupMemberActivity.from_crew_member(m) for m in roster)
        return cls(cup=cup, progress=progress, members=rows, captured_at=_now(now))

    @property
    def member_count(self) -> int:
        return len(self.members)

    @property
    def player_uids(self) -> tuple:
        """Every resolved member id (``player_uid`` falling back to ``zid``)."""
        return tuple(m.player_uid or m.zid for m in self.members
                     if (m.player_uid or m.zid) is not None)
