"""Static 6.8.0 Showdown event-leaderboard identity and time-window logic.

This module never contacts a server.  Only a *complete* set of native inputs
produces a server board name. Unknown schedule encodings, unresolved ranking
metadata and absent first-race IDs remain unresolved rather than guessed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
import re
from typing import Mapping, Optional, Sequence

# The game's 6.8.0 EventLeaderboard.get_LeaderboardUniqueID uses this epoch.
# It is *not* the Unix epoch. Refer to RVA 0x3388010, address 0x3388198.
CLIENT_EPOCH = 1514764800  # 2018-01-01T00:00:00Z
SERVER_UID_TEMPLATE = "evnt-off-{0}-dur-{1}-hours-{2}---{3}"


def _field(obj, *names):
    if not isinstance(obj, Mapping):
        return None
    for name in names:
        if name in obj and obj[name] is not None and obj[name] != "":
            return obj[name]
    return None


@dataclass(frozen=True)
class LeaderboardIdentityInputs:
    """Four client-side inputs, including missing values and evidence provenance.

    The UI can display a sanitized resolution status without printing service
    requests or session material. ``None`` always means unresolved, never zero.
    """
    start: Optional[datetime]
    duration_seconds: Optional[int]
    ranking_order: Optional[str]
    first_event_id: Optional[int]
    time_source: Optional[str] = None
    ranking_source: Optional[str] = None
    group_source: Optional[str] = None

    @property
    def missing(self):
        return tuple(name for name, value in (
            ("schedule_window", self.start),
            ("duration", self.duration_seconds),
            ("ranking_order", self.ranking_order),
            ("first_race_event_id", self.first_event_id),
        ) if value is None)

    @property
    def complete(self) -> bool:
        return not self.missing

    def board_name(self) -> str:
        if not self.complete:
            raise ValueError("Showdown leaderboard inputs are incomplete")
        return native_board_name(
            start=self.start, duration_seconds=self.duration_seconds,
            ranking_order=self.ranking_order, first_event_id=self.first_event_id)


def native_board_name(*, start: datetime, duration_seconds: int,
                      ranking_order: str, first_event_id: int) -> str:
    """Derive the ordinary, timed event leaderboard name used by CSR2 6.8.0.

    ABI evidence: EventLeaderboard.get_LeaderboardUniqueID RVA 0x3388010.
    Native four-object format array: offset hours, duration hours, asc/dsc,
    first RaceEventData.EventID. Debug quarter-hour profile mode is excluded.
    """
    if not isinstance(start, datetime) or start.tzinfo is None:
        raise ValueError("start must be a timezone-aware datetime")
    if type(duration_seconds) is not int or duration_seconds <= 0 or duration_seconds >= 2**31:
        raise ValueError("duration_seconds must be a positive integer")
    if ranking_order not in ("asc", "dsc"):
        raise ValueError("ranking_order must be asc or dsc")
    if type(first_event_id) is not int or first_event_id < 0 or first_event_id >= 2**31:
        raise ValueError("first_event_id must be a nonnegative signed 32-bit integer")
    if duration_seconds < 3600:
        # Native truncates duration to hours. Such a board cannot be assumed
        # to use this normal timed-board mode (15-minute debug is separate).
        raise ValueError("duration under one hour is not a supported normal event board")
    stamp = int(start.astimezone(timezone.utc).timestamp())
    if stamp < CLIENT_EPOCH or stamp > 2**31 - 1:
        raise ValueError("start outside the native signed epoch range")
    offset_hours = ((stamp - CLIENT_EPOCH) % duration_seconds) // 3600
    duration_hours = duration_seconds // 3600
    return SERVER_UID_TEMPLATE.format(offset_hours, duration_hours, ranking_order, first_event_id)


def first_race_event_id(group) -> Optional[int]:
    """Native group identifier = first race's EventID; never group label.

    RaceEventGroup.get_LeaderboardGroupIdentifier RVA 0x32fb0dc calls
    RaceEventData.get_EventID RVA 0x32cfe10 for the first RaceEvents entry.
    """
    races = _field(group, "RaceEvents", "raceEvents", "race_events")
    if isinstance(races, Mapping):
        # Dictionaries do not promise the native ordered list's first member.
        return None
    if not isinstance(races, (list, tuple)) or not races:
        return None
    raw = _field(races[0], "EventID", "eventID", "event_id")
    if type(raw) is int:
        return raw if 0 <= raw < 2**31 else None
    if isinstance(raw, str) and raw.isdecimal():
        number = int(raw)
        return number if number < 2**31 else None
    return None


def ranking_direction(value) -> Optional[str]:
    """Native rankingOrder int 0 = asc, other supported enum = dsc.

    String values are recognized when explicit; arbitrary values are not
    guessed to be descending. Metadata's score type is not the ordering.
    """
    if type(value) is int and value in (0, 1):
        return "asc" if value == 0 else "dsc"
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in ("asc", "ascending", "0"):
            return "asc"
        if lowered in ("dsc", "desc", "descending", "1"):
            return "dsc"
    return None


def leaderboard_definition(block, template_id):
    """Find a unique leaderboard definition by its nameID/template ID.

    Accepts common parsed metadata container shapes. Ambiguous or absent
    definitions cannot be used for server ID derivation.
    """
    if not template_id or not isinstance(block, Mapping):
        return None
    if "EventLeaderboards" in block and isinstance(block["EventLeaderboards"], Mapping):
        block = block["EventLeaderboards"]
    matches = []
    for key in ("EventLeaderboardsDefinitions", "EventLeaderboards", "leaderboards",
                "Leaderboards", "mLeaderboards"):
        records = block.get(key)
        if isinstance(records, Mapping):
            for name, record in records.items():
                if isinstance(record, Mapping) and str(_field(record, "nameID", "NameID", "LeaderboardTemplateID") or name) == str(template_id):
                    matches.append(record)
        elif isinstance(records, (list, tuple)):
            for record in records:
                if isinstance(record, Mapping) and str(_field(record, "nameID", "NameID", "LeaderboardTemplateID", "id", "_map_id") or "") == str(template_id):
                    matches.append(record)
    if len(matches) != 1:
        return None
    return matches[0]


def _parse_instant(value) -> Optional[datetime]:
    if type(value) in (int, float):
        if value <= 0 or value > 10**13:
            return None
        seconds = value / 1000 if value >= 10**11 else value
        try:
            return datetime.fromtimestamp(seconds, timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(value, str):
        value = value.strip()
        # Some JSON readers encode a Unix timestamp as a decimal string.
        # Require the conventional full seconds/milliseconds precision: do
        # not reinterpret arbitrary small integers as a different epoch.
        if value.isdecimal() and len(value) in (10, 13):
            return _parse_instant(int(value))
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return stamp.astimezone(timezone.utc) if stamp.tzinfo is not None else None
        except ValueError:
            return None
    return None


def _one_window(value):
    if isinstance(value, Mapping):
        start = _field(value, "Start", "start", "From", "from", "startTime", "StartTime", "min", "Min", "TimeStart")
        end = _field(value, "End", "end", "To", "to", "endTime", "EndTime", "max", "Max", "TimeEnd")
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        start, end = value
    else:
        return None
    start, end = _parse_instant(start), _parse_instant(end)
    return (start, end) if start is not None and end is not None and start < end else None


def _parse_windows(value):
    single = _one_window(value)
    if single is not None:
        return (single,)
    if not isinstance(value, (list, tuple)) or not value:
        return ()
    windows = []
    for item in value:
        window = _one_window(item)
        if window is None:
            return ()  # Unknown format must not silently discard a gate.
        windows.append(window)
    return tuple(windows)


def schedule_windows(schedule, schedules_by_id, *, seen=()):
    """Follow BasedOn_ScheduleID only when a time gate is inherited.

    Native EventScheduleDataItem getters fall through to `.basedOn` for
    missing local criteria; treat explicitly present unsupported criteria as
    unknown, rather than falling through or ignoring them.
    """
    if not isinstance(schedule, Mapping):
        return ()
    sid = _field(schedule, "ScheduleID", "id", "_map_id")
    if sid in seen or len(seen) > 32:
        return ()
    seen = seen + (sid,)
    for key in ("Time_ActiveBetweenAny", "_Time_ActiveBetweenAny",
                "_Time_ActiveBetween", "Time_ActiveBetween"):
        if key in schedule:
            return _parse_windows(schedule[key])
    direct = _one_window({"Start": _field(schedule, "start_time", "startTime", "TimeStart"),
                          "End": _field(schedule, "end_time", "endTime", "TimeEnd")})
    if direct:
        return (direct,)
    inherited = _field(schedule, "BasedOn_ScheduleID", "basedOn_ScheduleID", "basedOnScheduleID")
    if inherited is not None:
        return schedule_windows(schedules_by_id.get(str(inherited)), schedules_by_id, seen=seen)
    return ()



def schedule_has_recurrence(schedule, schedules_by_id, *, seen=()):
    """Conservatively detect recurrence controls that affect GetTimeData.

    EventScheduleDataItem.IsRecurringEvent checks initial start, duration and
    time between events, including values inherited via BasedOn_ScheduleID.
    A normal Start/End window alone does not reproduce the native repeat-cycle
    selection and must not be used to fabricate a repeated board name.
    """
    if not isinstance(schedule, Mapping):
        return False
    sid = str(_field(schedule, "ScheduleID", "id", "_map_id") or "")
    if sid in seen or len(seen) >= 32:
        return True  # a cycle/unknown inheritance must fail closed
    keys = (
        "RepeatEventInitialStartTime", "repeatEventInitialStartTime",
        "RepeatEventDuration", "repeatEventDuration",
        "RepeatEventTimeBetweenEvents", "repeatEventTimeBetweenEvents",
        "RepeatEventCycleEndTime", "repeatEventCycleEndTime",
        "RepeatEventPlayerLevelRange", "repeatEventPlayerLevelRange",
        "TimeRepeatDuration", "timeRepeatDuration",
    )
    for key in keys:
        if key in schedule and schedule[key] not in (None, "", -1, "-1", 0, "0"):
            return True
    parent = _field(schedule, "BasedOn_ScheduleID", "basedOn_ScheduleID", "basedOnScheduleID")
    if parent is None:
        return False
    inherited = schedules_by_id.get(str(parent))
    return inherited is None or schedule_has_recurrence(inherited, schedules_by_id, seen=seen+(sid,))


def group_has_recurrence(group):
    """Guard RaceEventGroup's native repeat-count branch when metadata uses it."""
    for key in ("TimeRepeatDuration", "timeRepeatDuration", "RepeatEventDuration"):
        value = _field(group, key)
        if value not in (None, -1, "-1", 0, "0"):
            return True
    return False


def group_explicit_window(group):
    """Read direct group times only if both are explicit and unambiguous."""
    if not isinstance(group, Mapping):
        return ()
    start = _field(group, "TimeStart", "timeStart")
    end = _field(group, "TimeEnd", "timeEnd")
    value = _one_window({"Start": start, "End": end})
    return (value,) if value else ()


def repeated_group_window(group, *, at: datetime):
    """Calculate direct RaceEventGroup repeat-cycle time from native 6.8.0.

    GetTimeStart/GetTimeEnd add CalculateCurrentRepeatCount * TimeRepeatDuration.
    The count is floor((now - (base_end + stay_on_map)) / period) for a
    positive difference, otherwise zero. Only use this for a *direct* group
    with explicit absolute TimeStart/TimeEnd and TimeRepeatDuration, not for
    inherited EventSchedule repeat settings or account-relative spam events.
    """
    value = _field(group, "TimeRepeatDuration", "timeRepeatDuration")
    if type(value) is str and value.isdecimal():
        value = int(value)
    if type(value) is not int or not (1 <= value < 2**31):
        return ()
    windows = group_explicit_window(group)
    if len(windows) != 1:
        return ()
    (start, end), = windows
    stay = _field(group, "TimeStayOnMapAfterCompletion", "timeStayOnMapAfterCompletion")
    if stay is None:
        stay = 0  # the JsonData integer field is zero-initialized
    if isinstance(stay, str) and stay.isdecimal():
        stay = int(stay)
    if type(stay) is not int or not (0 <= stay < 2**31):
        return ()
    # Keep the normal signed 32-bit game-time bound and avoid float rounding
    # at a repeat boundary. Native uses float32; without the live client state
    # a boundary within two seconds cannot be reliably classified.
    base_end = int(end.timestamp())
    now = int(at.astimezone(timezone.utc).timestamp())
    boundary = base_end + stay
    if abs((now - boundary) % value) <= 2 or value - (now - boundary) % value <= 2:
        return ()
    count = max(0, (now - boundary) // value) if now > boundary else 0
    new_start = start + timedelta(seconds=count * value)
    new_end = end + timedelta(seconds=count * value)
    if int(new_end.timestamp()) > 2**31 - 1:
        return ()
    return ((new_start, new_end),)

def select_window(windows, at: datetime):
    """One matching interval, nearest upcoming, or last completed interval."""
    if not windows:
        return None, None, "unknown"
    current = [(a,b) for a,b in windows if a <= at < b]
    if len(current) > 1:
        return None, None, "unknown"  # overlapping scoped instances
    if current:
        return *current[0], "scheduled_now"
    next_ = sorted(((a,b) for a,b in windows if a > at),key=lambda w:w[0])
    if next_:
        return *next_[0], "upcoming"
    previous = sorted(windows, key=lambda w:w[1])
    return *previous[-1], "elapsed"


def select_showdown_by_name(candidates: Sequence, showdown_name: str,
                            *, only_current: bool = True):
    from csr2cdn.service_events import EventResolutionError, ShowdownInactiveError
    if not isinstance(showdown_name, str) or not showdown_name.strip():
        raise EventResolutionError("showdown_name must be a nonempty event name")
    # Ignore separators/casing but never fuzzy-match an unrelated event.
    def normal(name):
        return "".join(ch for ch in name.casefold() if ch.isalnum())
    needle = normal(showdown_name)
    # User-facing labels are selectors for the *currently scheduled* W1/W2
    # event. Season numbers are discovered from metadata, never inferred from
    # the local calendar. A season may have no active event in the given slot.
    aliases = {"championshipshowdown": 2, "eliteshowdown": 1}
    slot = aliases.get(needle)
    active = [x for x in candidates if not only_current or x.time_status == "scheduled_now"]
    if slot is None:
        pool = [x for x in active if any(
            normal(s) == needle for s in (x.event_id, getattr(x, "display_name", None) or ""))]
    else:
        pattern = re.compile(r"SMP_SHOWDOWN_([0-9]+)_W([12])", re.IGNORECASE)
        pool = []
        for x in active:
            ids = (x.event_id, getattr(x, "display_name", None) or "")
            if any((match := pattern.fullmatch(str(value))) and int(match.group(2)) == slot
                   for value in ids):
                pool.append(x)
    if len(pool) != 1:
        if not pool:
            if slot is not None:
                raise ShowdownInactiveError("no currently active matching Showdown")
            raise EventResolutionError("Showdown name not found among scheduled events")
        raise EventResolutionError("ambiguous: multiple currently active matching Showdowns")
    if not pool[0].leaderboard_name:
        raise EventResolutionError("Showdown identified but leaderboard inputs are incomplete")
    return pool[0]
