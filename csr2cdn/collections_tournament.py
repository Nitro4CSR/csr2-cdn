"""The Collections Tournament: three crews, three days, six time trials.

Each tournament groups three crews. Over three days their members race six
fixed time trials (two a day), one leaderboard of best times per race. This
module composes those race boards, decodes the tournament configuration, and
folds the six boards into per-crew and per-member standings.

Where it comes from (CSR2 6.8.0, verified live 2026-11-15)
---------------------------------------------------------
``crews/checkUserCrew`` -> ``tournament``
    The crew's tournament history (``csr2cdn.crew_optional_data.CrewTournament``).
    Each ``events`` key is a tournament id; its ``hash`` is the group id.

``TournamentConfig`` (metadata block, and the
``assets_client_metadata_tournament_<id>`` bundles)
    ``TemplateConfigs`` (day length, schedule) and ``TournamentEvents`` -> each
    event's ``PeriodDetails`` (``Day1``..``Day3`` each with ``Race1``/``Race2``),
    with each race's restriction, cooldown, retries and underlying event id.

The race board
    ``TournamentLeaderboardRequestBase.GetLeaderboardId`` concatenates::

        "csr2-collections-tournament---" + tournamentId + "-" + groupId
            + "-" + dayId + "_" + raceId

    e.g. ``csr2-collections-tournament---279-88997819_89025506_89125558-Day1_Race1``.
    ``leaderboard/{board}/top`` (request type 5) returns one row per member with
    the best time in milliseconds (``score``; rank 1 is fastest) and the number
    of attempts (``races``).

The crew ranking the game shows is computed on the client as trophies
(``CrewRaceResult``: participation plus leaderboard trophies, scaled by each
race's multipliers). That trophy rule is not recovered here, so standings
report the boards as they are -- ranks, best times, attempts -- and a crew's
summed best time, without inventing a trophy total.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Optional, Sequence, Tuple

from .service_models import LeaderboardPage, ServiceResponseError, _field, _int, _payload

#: Fixed prefix of every tournament race board; the triple dash is literal.
BOARD_PREFIX = "csr2-collections-tournament---"
#: The client's debug variant, so a debug board is never taken for a live one.
BOARD_DEBUG_PREFIX = "csr2-collections-tournament-debug---"
#: Metadata block with the templates and (older) events.
CONFIG_BLOCK = "TournamentConfig"
#: Per-event modular bundle: ``assets_client_metadata_tournament_<id>``.
BUNDLE_PREFIX = "assets_client_metadata_tournament_"

_TID = re.compile(r"[0-9]{1,9}")
_GROUP = re.compile(r"[0-9]{1,12}(?:_[0-9]{1,12}){1,7}")
_DAY = re.compile(r"Day[0-9]{1,2}")
_RACE = re.compile(r"Race[0-9]{1,2}")
_MAX_I64 = 2**63 - 1


class TournamentError(ServiceResponseError):
    """A tournament input or reply is not admissible."""


def _text(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _num(node: Mapping[str, Any], *names: str) -> Optional[int]:
    value = _int(node, *names)
    return value if value is not None and -_MAX_I64 <= value <= _MAX_I64 else None


def _check(pattern: "re.Pattern[str]", value: Any, name: str) -> str:
    text = _text(value)
    if text is None or not pattern.fullmatch(text):
        raise TournamentError("%s is not a valid tournament identifier" % name)
    return text


# ---------------------------------------------------------------------------
# board identifiers


def board_id(tournament_id: Any, group_id: Any, day_id: Any, race_id: Any, *,
             debug: bool = False) -> str:
    """Compose a race board identifier from its four parts.

    Nothing is defaulted: ``group_id`` is the crew's ``hash`` and
    ``day_id``/``race_id`` are ``PeriodDetails`` keys. ``debug=True`` selects
    the non-production prefix and is never implied.
    """
    prefix = BOARD_DEBUG_PREFIX if debug else BOARD_PREFIX
    return "%s%s-%s-%s_%s" % (prefix,
                              _check(_TID, tournament_id, "tournament_id"),
                              _check(_GROUP, group_id, "group_id"),
                              _check(_DAY, day_id, "day_id"),
                              _check(_RACE, race_id, "race_id"))


def parse_board_id(board: Any) -> Optional[Tuple[str, str, str, str, bool]]:
    """Split a race board into (tournament, group, day, race, debug), or None."""
    if not isinstance(board, str):
        return None
    for prefix, debug in ((BOARD_DEBUG_PREFIX, True), (BOARD_PREFIX, False)):
        if board.startswith(prefix):
            rest = board[len(prefix):].split("-")
            if len(rest) != 3 or "_" not in rest[2]:
                return None
            tid, group, name = rest
            day, race = name.split("_", 1)
            if (_TID.fullmatch(tid) and _GROUP.fullmatch(group)
                    and _DAY.fullmatch(day) and _RACE.fullmatch(race)):
                return tid, group, day, race, debug
            return None
    return None


def _day_order(key: str) -> Tuple[int, str]:
    digits = re.sub(r"\D", "", key)
    return (int(digits) if digits else 10**6, key)


#: The standard tournament grid: three days of two races (the ``3Days`` template).
STANDARD_DAYS = 3
STANDARD_RACES_PER_DAY = 2


def standard_board_ids(tournament_id: Any, group_id: Any, *, days: int = STANDARD_DAYS,
                       races_per_day: int = STANDARD_RACES_PER_DAY,
                       debug: bool = False) -> Tuple[Tuple[str, str, str], ...]:
    """(day_id, race_id, board_id) for a standard grid, without the event config.

    Every live tournament seen uses the ``3Days`` template -- ``Day1``..``Day3``
    each with ``Race1``/``Race2`` -- so the six boards can be composed from just
    the tournament id and the crew's group id. Use this when the per-event
    ``TournamentConfig`` is not in hand; use ``TournamentConfig.board_ids`` when
    it is, to get the exact races and their restrictions.
    """
    if not 1 <= days <= 9 or not 1 <= races_per_day <= 9:
        raise TournamentError("day/race counts out of range")
    out = []
    for d in range(1, days + 1):
        for r in range(1, races_per_day + 1):
            day_id, race_id = "Day%d" % d, "Race%d" % r
            out.append((day_id, race_id, board_id(tournament_id, group_id, day_id, race_id,
                                                   debug=debug)))
    return tuple(out)


# ---------------------------------------------------------------------------
# configuration


@dataclass(frozen=True)
class TournamentRace:
    """One race of a tournament day, from ``PeriodDetails``."""

    day_id: str
    race_id: str
    journal_id: Optional[str] = None
    slot_id: Optional[str] = None
    multiplier: Optional[int] = None
    participation_multiplier: Optional[int] = None
    restrictions: Tuple[str, ...] = ()
    event_id: Optional[int] = None
    cooldown_time: Optional[int] = None
    retries_per_cooldown: Optional[int] = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_entry(cls, day_id: str, race_id: str, entry: Mapping[str, Any]) -> "TournamentRace":
        restr = _field(entry, "Restrictions")
        kinds = tuple(str(r.get("RestrictionType")) for r in restr
                      if isinstance(r, Mapping) and r.get("RestrictionType") is not None) \
            if isinstance(restr, (list, tuple)) else ()
        race_event = _field(entry, "RaceEvent")
        event_id = _num(race_event, "EventID") if isinstance(race_event, Mapping) else None
        return cls(day_id, race_id,
                   _text(_field(entry, "JournalId")),
                   _text(_field(entry, "SlotId")),
                   _num(entry, "Multiplier"),
                   _num(entry, "ParticipationMultiplier"),
                   kinds, event_id,
                   _num(entry, "CooldownTime"),
                   _num(entry, "RetriesPerCooldown"),
                   dict(entry))


@dataclass(frozen=True)
class TournamentConfig:
    """One ``TournamentEvents`` entry: a tournament's template and race grid."""

    tournament_id: str
    template_id: Optional[str] = None
    period_seconds: Optional[int] = None
    schedule_id: Optional[str] = None
    leaderboard_reward_id: Optional[str] = None
    milestone_reward_id: Optional[str] = None
    races: Tuple[TournamentRace, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def day_ids(self) -> Tuple[str, ...]:
        seen = []
        for race in self.races:
            if race.day_id not in seen:
                seen.append(race.day_id)
        return tuple(seen)

    def race(self, day_id: str, race_id: str) -> Optional[TournamentRace]:
        return next((r for r in self.races
                     if r.day_id == day_id and r.race_id == race_id), None)

    def board_ids(self, group_id: str, *, debug: bool = False) -> Tuple[Tuple[str, str, str], ...]:
        """(day_id, race_id, board_id) for every race, given the crew's group id."""
        return tuple((r.day_id, r.race_id, board_id(self.tournament_id, group_id,
                                                     r.day_id, r.race_id, debug=debug))
                     for r in self.races)

    @classmethod
    def from_block(cls, block: Any, tournament_id: Any) -> "TournamentConfig":
        """Decode one tournament event from a `TournamentConfig` block or bundle.

        ``block`` may be the metadata block (``{TemplateConfigs, TournamentEvents}``)
        or a modular bundle wrapping the same. ``tournament_id`` selects the event.
        """
        tid = _check(_TID, tournament_id, "tournament_id")
        node = _payload(block)
        events = _deep_find(node, "TournamentEvents")
        if not isinstance(events, Mapping) or tid not in events:
            raise TournamentError("tournament %s not in config" % tid)
        event = events[tid]
        if not isinstance(event, Mapping):
            raise TournamentError("tournament %s entry is not an object" % tid)
        template_id = _text(_field(event, "TemplateId"))
        templates = _deep_find(node, "TemplateConfigs")
        period = None
        schedule = None
        if isinstance(templates, Mapping) and template_id in templates:
            tpl = templates[template_id]
            if isinstance(tpl, Mapping):
                period = _num(tpl, "PeriodDuration")
                schedule = _text(_field(tpl, "ScheduleId"))
        races = []
        details = _field(event, "PeriodDetails")
        if isinstance(details, Mapping):
            for day_id in sorted(details, key=_day_order):
                day = details[day_id]
                if not isinstance(day, Mapping):
                    continue
                for race_id in sorted(day, key=_day_order):
                    entry = day[race_id]
                    if isinstance(entry, Mapping):
                        races.append(TournamentRace.from_entry(day_id, race_id, entry))
        return cls(tid, template_id, period, schedule,
                   _text(_field(event, "LeaderboardRewardId")),
                   _text(_field(event, "MilestoneRewardId")),
                   tuple(races), dict(event))


def _deep_find(node: Any, key: str, depth: int = 0) -> Any:
    """First value for ``key`` anywhere in a nested mapping (bundles nest it)."""
    if depth > 6 or not isinstance(node, Mapping):
        return None
    if key in node:
        return node[key]
    for value in node.values():
        found = _deep_find(value, key, depth + 1)
        if found is not None:
            return found
    return None


# ---------------------------------------------------------------------------
# standings: the six race boards folded per member and per crew


@dataclass(frozen=True)
class MemberRaceTime:
    """One member's result on one race board."""

    day_id: str
    race_id: str
    #: Best time in milliseconds (the board's ``score``); lower is better.
    best_time_ms: Optional[int] = None
    #: Number of attempts the member made on this board (the board's ``races``).
    attempts: Optional[int] = None
    rank: Optional[int] = None

    @property
    def best_time_seconds(self) -> Optional[float]:
        return None if self.best_time_ms is None else self.best_time_ms / 1000.0


@dataclass(frozen=True)
class TournamentMemberResult:
    """One member's results across every race they entered."""

    member_id: Optional[str]
    name: Optional[str]
    crew_id: Optional[str]
    times: Tuple[MemberRaceTime, ...] = ()

    def race_time(self, day_id: str, race_id: str) -> Optional[MemberRaceTime]:
        return next((t for t in self.times
                     if t.day_id == day_id and t.race_id == race_id), None)

    @property
    def races_entered(self) -> int:
        return sum(1 for t in self.times if t.best_time_ms is not None)

    @property
    def total_attempts(self) -> Optional[int]:
        got = [t.attempts for t in self.times if t.attempts is not None]
        return sum(got) if got else None

    @property
    def sum_best_time_ms(self) -> Optional[int]:
        got = [t.best_time_ms for t in self.times if t.best_time_ms is not None]
        return sum(got) if got else None

    @property
    def sum_best_time_seconds(self) -> Optional[float]:
        total = self.sum_best_time_ms
        return None if total is None else total / 1000.0


@dataclass(frozen=True)
class TournamentCrewResult:
    """One crew's members and aggregate across the tournament's races."""

    crew_id: Optional[str]
    members: Tuple[TournamentMemberResult, ...] = ()

    @property
    def member_count(self) -> int:
        return len(self.members)

    @property
    def participating_member_count(self) -> int:
        return sum(1 for m in self.members if m.races_entered > 0)

    @property
    def sum_best_time_ms(self) -> Optional[int]:
        got = [m.sum_best_time_ms for m in self.members if m.sum_best_time_ms is not None]
        return sum(got) if got else None

    @property
    def total_attempts(self) -> Optional[int]:
        got = [m.total_attempts for m in self.members if m.total_attempts is not None]
        return sum(got) if got else None


@dataclass(frozen=True)
class CollectionsTournamentStandings:
    """The six race boards of one tournament, folded per member and per crew.

    Built from already-fetched board replies, so this class issues no I/O; use
    ``config.board_ids(group_id)`` to know which boards to read, then pass the
    replies here. Trophies and crew rank are not computed (see the module note).
    """

    tournament_id: str
    group_id: str
    members: Tuple[TournamentMemberResult, ...] = ()
    crews: Tuple[TournamentCrewResult, ...] = ()
    boards_read: Tuple[Tuple[str, str], ...] = ()

    def member(self, member_id: str) -> Optional[TournamentMemberResult]:
        return next((m for m in self.members if m.member_id == str(member_id)), None)

    def crew(self, crew_id: str) -> Optional[TournamentCrewResult]:
        return next((c for c in self.crews if c.crew_id == str(crew_id)), None)

    @classmethod
    def from_boards(cls, tournament_id: Any, group_id: Any,
                    boards: Sequence[Tuple[str, str, Any]]) -> "CollectionsTournamentStandings":
        """Fold ``(day_id, race_id, reply)`` board replies into standings.

        Each ``reply`` is a ``leaderboard/{board}/top`` response (or an already
        decoded ``LeaderboardPage``). A reply that is not a readable board is
        skipped, so a single closed race does not lose the rest.
        """
        tid = _check(_TID, tournament_id, "tournament_id")
        gid = _check(_GROUP, group_id, "group_id")
        # member_id -> {"name","crew", {(day,race): MemberRaceTime}}
        members: dict = {}
        read: list = []
        for day_id, race_id, reply in boards:
            page = reply if isinstance(reply, LeaderboardPage) else _as_page(day_id, race_id, reply)
            if page is None:
                continue
            read.append((day_id, race_id))
            for row in page.entries:
                mid = row.player_id
                if mid is None:
                    continue
                rec = members.setdefault(mid, {"name": None, "crew": None, "times": {}})
                if rec["name"] is None:
                    rec["name"] = row.player_name
                if rec["crew"] is None:
                    rec["crew"] = row.crew_id
                rec["times"][(day_id, race_id)] = MemberRaceTime(
                    day_id, race_id, row.score, row.races, row.rank)
        member_results = []
        for mid, rec in members.items():
            times = tuple(rec["times"][k] for k in sorted(rec["times"]))
            member_results.append(TournamentMemberResult(mid, rec["name"], rec["crew"], times))
        # group members by crew, preserving first-seen crew order
        crew_order: list = []
        by_crew: dict = {}
        for m in member_results:
            by_crew.setdefault(m.crew_id, []).append(m)
            if m.crew_id not in crew_order:
                crew_order.append(m.crew_id)
        crews = tuple(TournamentCrewResult(cid, tuple(by_crew[cid])) for cid in crew_order)
        return cls(tid, gid, tuple(member_results), crews, tuple(read))


def _as_page(day_id: str, race_id: str, reply: Any) -> Optional[LeaderboardPage]:
    try:
        return LeaderboardPage.from_response("%s_%s" % (day_id, race_id), reply)
    except ServiceResponseError:
        return None


def current_tournament(tournament_block: Any) -> Optional[Tuple[str, str]]:
    """(tournament_id, group_id) of the latest event in a raw ``tournament`` block.

    ``tournament_block`` is the ``tournament`` value of a ``crews/checkUserCrew``
    reply (``OwnCrew.extras["tournament"]``). The current tournament is the
    highest-numbered event that carries a group ``hash``; returns ``None`` when
    the block has no such event. The ``hash`` is returned verbatim, since the
    board id depends on its exact crew-id order.
    """
    events = _deep_find(tournament_block, "events") if isinstance(tournament_block, Mapping) else None
    if not isinstance(events, Mapping):
        return None
    best: Optional[Tuple[int, str, str]] = None
    for key, event in events.items():
        if not isinstance(event, Mapping):
            continue
        group = event.get("hash")
        tid = _text(key)
        if not isinstance(group, str) or tid is None or not _GROUP.fullmatch(group):
            continue
        try:
            rank = int(tid)
        except ValueError:
            continue
        if best is None or rank > best[0]:
            best = (rank, tid, group)
    return (best[1], best[2]) if best else None


__all__ = [
    "BOARD_PREFIX", "BOARD_DEBUG_PREFIX", "CONFIG_BLOCK", "BUNDLE_PREFIX",
    "TournamentError", "board_id", "parse_board_id", "standard_board_ids",
    "STANDARD_DAYS", "STANDARD_RACES_PER_DAY",
    "TournamentRace", "TournamentConfig",
    "MemberRaceTime", "TournamentMemberResult", "TournamentCrewResult",
    "CollectionsTournamentStandings", "current_tournament",
]
