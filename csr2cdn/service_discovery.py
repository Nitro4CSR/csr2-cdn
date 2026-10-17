"""Conservative, read-only Showdown schedule and leaderboard discovery.

The standalone ShowdownEventsContainer is not necessarily the entire client's
active event catalogue: CSR2 6.8.0 can merge runtime modular event groups.
No known event or board IDs are bundled. Schedule windows are a *time-only*
preflight: server activity, experiment gates, and player segmentation are
not established by the window alone. Unresolved IDs are never fabricated.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from csr2cdn.service_events import EventCatalog, EventResolutionError
from csr2cdn.service_showdown_resolution import (LeaderboardIdentityInputs,
    first_race_event_id, leaderboard_definition, group_explicit_window,
    group_has_recurrence, schedule_has_recurrence, repeated_group_window, ranking_direction,
    schedule_windows, select_window, select_showdown_by_name)

SHOWDOWN_METADATA_BLOCKS = ("ShowdownEventsContainer", "EventSchedule", "EventLeaderboards")
# From EventCommonMetadataDatabase.LoadMetadata RVA 0x3427ef8:
# AssetDatabaseData.GetAssetsOfType receives the literal integer 0x2f.
MODULAR_EVENT_ASSET_TYPE = 47


def modular_event_assets(database):
    """Return current asset-db entries in the client's common-event category.

    This is catalogue *inventory*, not metadata extraction. The native loader
    reads these bundles, but a code/name is not by itself a Showdown group, nor
    is the content format validated by this function. No requests are sent.
    """
    from csr2cdn.database import AssetDatabase
    if not isinstance(database, AssetDatabase):
        raise TypeError("database must be an AssetDatabase")
    return tuple(database.assets.of_type(MODULAR_EVENT_ASSET_TYPE))



def _obj(value):
    return value if isinstance(value, Mapping) else {}


def _content(blocks, name):
    value = _obj(blocks).get(name, {})
    if hasattr(value, "content"):
        value = value.content
    value = _obj(value)
    # Both MetadataBlock.content and locally archived .meta envelopes are accepted.
    return _obj(value.get(name, value))


def _records(node, key):
    source = _obj(node).get(key, ())
    if isinstance(source, Mapping):
        return tuple(dict(v, _map_id=str(k)) for k, v in source.items()
                     if isinstance(v, Mapping))
    if isinstance(source, (list, tuple)):
        return tuple(x for x in source if isinstance(x, Mapping))
    return ()


def merge_modular_showdown_groups(blocks: Mapping[str, Any], groups: Sequence[Mapping[str, Any]]):
    """Merge already-decoded runtime Showdown groups into standalone metadata.

    The 6.8.0 ShowdownEventsDatabase.LoadFromModularEventMetadata path
    appends an incoming group only if GetShowdownEventGroupWithName did not
    find an existing EventGroupName. It does not establish the wire format or
    retrieval service for the runtime groups. Callers must supply actual
    decoded records, not fabricated catalogue entries.

    The input and original blocks are not mutated. A duplicate name is kept
    from the standalone source; malformed or nameless groups are rejected.
    """
    if not isinstance(blocks, Mapping):
        raise EventResolutionError("Showdown metadata must be an object")
    if not isinstance(groups, (tuple, list)):
        raise EventResolutionError("runtime Showdown groups must be a list")
    merged = dict(blocks)
    base = _content(blocks, "ShowdownEventsContainer")
    old = _records(base, "RaceEventGroups")
    known = set()
    for group in old:
        name = _str(group, "EventGroupName")
        if name:
            known.add(name)
    rows = list(old)
    for group in groups:
        if not isinstance(group, Mapping):
            raise EventResolutionError("runtime Showdown group is not an object")
        name = _str(group, "EventGroupName")
        if not name:
            raise EventResolutionError("runtime Showdown group lacks event identity")
        if name not in known:
            rows.append(dict(group))
            known.add(name)
    merged["ShowdownEventsContainer"] = {**base, "RaceEventGroups": rows}
    return merged


def merge_modular_event_metadata(blocks: Mapping[str, Any], catalogue: Mapping[str, Any]):
    """Merge runtime groups, schedules and ranking definitions without replacing
    authoritative standalone records of the same identity."""
    if not isinstance(catalogue, Mapping):
        raise EventResolutionError("runtime event catalogue must be an object")
    groups = catalogue.get("RaceEventGroups", [])
    merged = merge_modular_showdown_groups(blocks, groups)
    for block_name, field, identity in (
        ("EventSchedule", "ScheduleList", ("ScheduleID", "_map_id")),
        ("EventLeaderboards", "EventLeaderboardsDefinitions", ("nameID", "_map_id")),
    ):
        additions = catalogue.get(field, [])
        if not isinstance(additions, list) or any(not isinstance(x, Mapping) for x in additions):
            raise EventResolutionError("runtime event catalogue has invalid record arrays")
        base = _content(merged, block_name)
        rows = list(_records(base, field))
        existing = {(_str(r, *identity)) for r in rows}
        for item in additions:
            marker = _str(item, *identity)
            if not marker:
                raise EventResolutionError("runtime schedule/leaderboard definition lacks identity")
            if marker not in existing:
                rows.append(dict(item))
                existing.add(marker)
        merged[block_name] = {**base, field: rows}
    # The game's CupInvitationalSeriesDatabase has a *different* modular
    # consumer from ShowdownEventsDatabase. Preserve these records for Prestige
    # discovery; don't mislabel every cup series as a Showdown event group.
    series = catalogue.get("RaceSeries", [])
    if not isinstance(series, list) or any(not isinstance(row, Mapping) for row in series):
        raise EventResolutionError("invalid modular cup series metadata")
    merged["_RuntimeCupSeries"] = {"RaceSeries": list(series)}
    # A native Prestige race group may have an explicit `id` and telemetry
    # identity without EventGroupName. Keep it separate from the named Showdown
    # catalogue. Never synthesize a name or board identifier here.
    prestige = catalogue.get("PrestigeRaceEventGroups", [])
    if not isinstance(prestige, list) or any(not isinstance(row, Mapping) for row in prestige):
        raise EventResolutionError("invalid modular Prestige race group records")
    merged["_RuntimePrestigeGroups"] = {"RaceEventGroups": list(prestige)}
    # Preserve seasonal PrestigeCupCar lookup records from the season-numbered
    # TextAsset bundles (e.g. assets_client_metadata_279). These are inputs to
    # game-side event generation, not Prestige groups or leaderboard IDs.
    season_cars = catalogue.get("SeasonalRewardCars", [])
    if not isinstance(season_cars, list) or any(not isinstance(row, Mapping) for row in season_cars):
        raise EventResolutionError("invalid seasonal reward-car definitions")
    seen_seasons = {}
    for row in season_cars:
        season = row.get("_season_id")
        if not isinstance(season, str) or not season.isdecimal():
            raise EventResolutionError("seasonal reward-car record lacks a numeric season")
        if season in seen_seasons and seen_seasons[season] != row:
            raise EventResolutionError("conflicting seasonal reward-car definitions")
        seen_seasons[season] = dict(row)
    merged["_RuntimeSeasonalRewardCars"] = {"SeasonalRewardCars": list(seen_seasons.values())}
    return merged


def _value(node, *keys):
    if not isinstance(node, Mapping):
        return None
    for key in keys:
        if key in node and node[key] not in (None, ""):
            return node[key]
    return None


def _str(node, *keys):
    value = _value(node, *keys)
    return str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else None



def _resolved_name(group, definitions):
    """Only a *full server board name* is accepted, never a template ID."""
    lb = _obj(_value(group, "Leaderboard", "leaderboard"))
    name = (_str(lb, "LeaderboardUniqueID", "leaderboardUniqueID", "resolved_leaderboard_name", "leaderboard_name")
            or _str(group, "LeaderboardUniqueID", "leaderboardUniqueID", "resolved_leaderboard_name", "leaderboard_name"))
    if name:
        return name
    # Some metadata adapters provide an explicit, event-keyed resolved map.
    # Do not assume definition names, templates, or race-event IDs are boards.
    event_id = _str(group, "id", "EventName", "event_id", "_map_id", "EventGroupName")
    for definition in definitions:
        if _str(definition, "EventName", "event_id", "EventID") == event_id:
            found = _str(definition, "LeaderboardUniqueID", "leaderboardUniqueID", "resolved_leaderboard_name", "leaderboard_name")
            if found:
                return found
    return None


@dataclass(frozen=True)
class ShowdownCandidate:
    """Snapshot of one metadata-scheduled Showdown event, without account gates."""
    event_id: str
    schedule_id: Optional[str]
    leaderboard_name: Optional[str]
    starts_at: Optional[datetime]
    ends_at: Optional[datetime]
    time_status: str  # scheduled_now, upcoming, elapsed, or unknown
    schedule_gates_unverified: bool = True
    leaderboard_template_id: Optional[str] = None
    leaderboard_group_identifier: Optional[str] = None
    identifier_source: str = "event_id"  # or EventGroupName (display label only)
    display_name: Optional[str] = None
    resolution_source: Optional[str] = None  # explicit or native_6_8_0
    unresolved_inputs: Tuple[str, ...] = ()  # categories only; no account data
    identity_inputs: Optional[LeaderboardIdentityInputs] = None

    @property
    def requestable(self) -> bool:
        return self.leaderboard_name is not None


def scan_showdowns(blocks: Mapping[str, Any], *, at: Optional[datetime] = None) -> Tuple[ShowdownCandidate, ...]:
    """Inspect native metadata block layouts without guessing leaderboard IDs.

    `ShowdownEventsContainer.RaceEventGroups` and
    `EventSchedule.ScheduleList` are observed client metadata keys. Schedule
    timing layouts and ranking definitions are decoded where the inputs
    are explicit and complete. Repeating or unknown schedule formats still
    require real metadata/authorized service validation.
    """
    if at is None:
        at = datetime.now(timezone.utc)
    if at.tzinfo is None:
        raise ValueError("at must have a timezone offset")
    at = at.astimezone(timezone.utc)
    groups = _records(_content(blocks, "ShowdownEventsContainer"), "RaceEventGroups")
    schedules = _records(_content(blocks, "EventSchedule"), "ScheduleList")
    data = _content(blocks, "EventLeaderboards")
    definitions = _records(data, "EventLeaderboardsDefinitions")
    if not definitions:
        definitions = _records(data, "EventLeaderboards")
    schedule_by_id = {}
    for schedule in schedules:
        for key in ("ScheduleID", "id", "EventName", "_map_id"):
            ident = _str(schedule, key)
            if ident is not None:
                # Two different schedule objects with the same lookup key are
                # ambiguous. Never make a board ID from an arbitrary first hit.
                if ident in schedule_by_id and schedule_by_id[ident] is not schedule:
                    schedule_by_id[ident] = None
                else:
                    schedule_by_id.setdefault(ident, schedule)
    found = []
    for group in groups:
        authoritative_id = _str(group, "id", "EventName", "event_id", "_map_id")
        event_id = authoritative_id or _str(group, "EventGroupName")
        if not event_id:
            continue
        identity_source = "event_id" if authoritative_id else "EventGroupName"
        sid = _str(group, "ScheduleID", "schedule_id", "scheduleID")
        group_name = _str(group, "EventName", "event_name", "EventGroupName")
        # The client uses the ScheduleID to resolve time when one exists; a
        # mismatched or ambiguous schedule must not silently fall back to the
        # group's static dates (or another event's schedule).
        lookup_id = sid or group_name or event_id
        schedule = schedule_by_id.get(lookup_id)
        ambiguous_schedule = lookup_id in schedule_by_id and schedule is None
        has_schedule = schedule is not None
        repeating = (group_has_recurrence(group) or
                     (has_schedule and schedule_has_recurrence(schedule, schedule_by_id)))
        windows = schedule_windows(schedule, schedule_by_id) if has_schedule else ()
        time_source = "event_schedule" if has_schedule else None
        # Group-local repeats are distinct from schedule-level cycles. The
        # native group count can be reproduced for explicit absolute times.
        group_repeat = group_has_recurrence(group)
        schedule_repeat = has_schedule and schedule_has_recurrence(schedule, schedule_by_id)
        if not sid and not ambiguous_schedule:
            if group_repeat and not schedule_repeat:
                windows = repeated_group_window(group, at=at)
                time_source = "group_repeat" if windows else None
            elif not windows and not repeating:
                windows = group_explicit_window(group)
                if windows:
                    time_source = "group_explicit"
        start, end, status = select_window(windows, at)
        if schedule_repeat or (group_repeat and not windows):
            # Native scheduler may require cycle/account-specific state.
            start = end = None
            status = "unknown"
        leaderboard = _obj(_value(group, "Leaderboard", "leaderboard"))
        template_id = _str(leaderboard, "LeaderboardTemplateID", "leaderboardTemplateID")
        group_identifier = _str(group, "LeaderboardGroupIdentifier", "leaderboard_group_identifier")
        resolved = _resolved_name(group, definitions)
        source = "explicit" if resolved else None
        first_id = first_race_event_id(group)
        definition = leaderboard_definition(data, template_id)
        rank = ranking_direction(_value(definition, "rankingOrder", "RankingOrder"))
        duration = int((end-start).total_seconds()) if start is not None and end is not None else None
        inputs = LeaderboardIdentityInputs(
            start, duration, rank, first_id,
            time_source=time_source if start is not None else None,
            ranking_source="EventLeaderboards" if rank is not None else None,
            group_source="RaceEvents[0].EventID" if first_id is not None else None,
        )
        missing = []
        if resolved is None:
            if not template_id:
                missing.append("leaderboard_template")
            if sid and not has_schedule:
                missing.append("schedule_not_found_or_ambiguous")
            if schedule_repeat or (group_repeat and not windows):
                missing.append("recurring_time_resolution")
            missing.extend(inputs.missing)
            if not missing:
                try:
                    resolved = inputs.board_name()
                    source = "native_6_8_0"
                    group_identifier = str(first_id)
                except ValueError:
                    missing.append("unsupported_time_or_duration")
        found.append(ShowdownCandidate(event_id, sid, resolved, start, end, status,
                                       leaderboard_template_id=template_id,
                                       leaderboard_group_identifier=group_identifier,
                                       identifier_source=identity_source,
                                       display_name=_str(group, "DisplayName", "EventGroupName", "EventName"),
                                       resolution_source=source,
                                       unresolved_inputs=tuple(dict.fromkeys(missing)), identity_inputs=inputs))
    return tuple(found)


class ShowdownDiscovery:
    """Refreshable metadata provider for finding time-window Showdown candidates.

    Does not fetch game data until its `source` callback is invoked. JSON
    fixture loaders are entirely offline; `from_metadata` supports later
    caller-controlled online metadata fetches using the existing CDN client.
    """

    def __init__(self, source: Callable[[], Mapping[str, Any]], *, ttl: float = 300.0,
                 modular_source: Optional[Callable[[], Sequence[Mapping[str, Any]]]] = None):
        if not callable(source):
            raise TypeError("source must be callable")
        if ttl < 0:
            raise ValueError("ttl must not be negative")
        if modular_source is not None and not callable(modular_source):
            raise TypeError("modular_source must be callable")
        self.source, self.ttl = source, ttl
        self._modular_source = modular_source
        self.source_coverage = "standalone_only" if modular_source is None else "runtime_groups_supplied"
        self._blocks = None
        self._updated = None

    @classmethod
    def from_json_directory(cls, directory, *, ttl: float = 300.0,
                            modular_groups_file=None):
        root = Path(directory)
        def load():
            return {name: json.loads((root / (name + ".meta")).read_text(encoding="utf-8-sig"))
                    for name in SHOWDOWN_METADATA_BLOCKS if (root / (name + ".meta")).is_file()}
        def runtime_groups():
            value = json.loads(Path(modular_groups_file).read_text(encoding="utf-8-sig"))
            if not isinstance(value, list):
                raise EventResolutionError("runtime Showdown groups fixture must be a list")
            return value
        return cls(load, ttl=ttl,
                   modular_source=runtime_groups if modular_groups_file is not None else None)

    @classmethod
    def from_metadata(cls, client, *, player_id: str, product_version: str, ttl: float = 300.0,
                      modular_source: Optional[Callable[[], Sequence[Mapping[str, Any]]]] = None,
                      asset_cdn=None):
        if not player_id:
            raise ValueError("player_id is required")
        if not product_version:
            raise ValueError("product_version is required")
        def load():
            blocks = client.get(SHOWDOWN_METADATA_BLOCKS, zid=player_id,
                                product_version=product_version)
            # Do not silently accept a partial cached metadata response as
            # a complete discovery snapshot.
            missing = set(SHOWDOWN_METADATA_BLOCKS) - set(blocks)
            if missing:
                raise EventResolutionError("discovery metadata was incomplete")
            return {name: block.content for name, block in blocks.items()}
        if asset_cdn is not None:
            if modular_source is not None:
                raise ValueError("select either an asset CDN or explicit modular source")
            from csr2cdn.service_modular_assets import load_modular_event_metadata
            modular_source = lambda: load_modular_event_metadata(asset_cdn)
        result = cls(load, ttl=ttl, modular_source=modular_source)
        if asset_cdn is not None:
            result.source_coverage = "runtime_asset_bundles"
        return result

    def refresh(self):
        result = self.source()
        if not isinstance(result, Mapping):
            raise EventResolutionError("Showdown metadata source must return blocks")
        if "ShowdownEventsContainer" not in result:
            raise EventResolutionError("ShowdownEventsContainer metadata is required")
        if self._modular_source is not None:
            # Keep the previous good snapshot if the supplied runtime source
            # fails validation. Never treat missing runtime data as an empty
            # successful update.
            runtime = self._modular_source()
            result = (merge_modular_event_metadata(result, runtime)
                      if isinstance(runtime, Mapping)
                      else merge_modular_showdown_groups(result, runtime))
        self._blocks = result
        self._updated = time.monotonic()
        return self._blocks

    def list_showdowns(self, *, at=None, refresh=False):
        if refresh or self._updated is None or time.monotonic()-self._updated >= self.ttl:
            self.refresh()
        return scan_showdowns(self._blocks, at=at)

    def scheduled_now(self, *, at=None, refresh=False):
        return tuple(x for x in self.list_showdowns(at=at, refresh=refresh)
                     if x.time_status == "scheduled_now")

    def requestable_now(self, *, at=None, refresh=False):
        return tuple(x for x in self.scheduled_now(at=at, refresh=refresh) if x.requestable)

    def resolve_current_board(self, *, at=None, refresh=False) -> str:
        scheduled = self.scheduled_now(at=at, refresh=refresh)
        if len(scheduled) != 1:
            raise EventResolutionError("current Showdown is absent or ambiguous; inspect discovered candidates")
        if not scheduled[0].requestable:
            raise EventResolutionError("current Showdown has no resolved leaderboard ID in metadata; cannot invent one")
        return scheduled[0].leaderboard_name

    def resolve_named(self, showdown_name: str, *, at=None, refresh=False,
                      only_current: bool = True) -> ShowdownCandidate:
        """Resolve a visible Showdown name to an actual, currently scheduled board.

        Case- and punctuation-insensitive *exact* matching. No bundled list,
        partial substring, numeric index, or event ID substitution.
        """
        return select_showdown_by_name(self.list_showdowns(at=at, refresh=refresh),
                                       showdown_name, only_current=only_current)

    def to_event_catalog(self) -> EventCatalog:
        def load():
            return {"events": [dict(event_id=x.event_id, kind="showdown",
                                    leaderboard_name=x.leaderboard_name)
                               for x in self.list_showdowns(refresh=True)
                               if x.requestable and x.identifier_source == "event_id"]}
        return EventCatalog(load, ttl=self.ttl)


__all__ = ["ShowdownDiscovery", "ShowdownCandidate", "SHOWDOWN_METADATA_BLOCKS", "scan_showdowns", "merge_modular_showdown_groups", "modular_event_assets", "MODULAR_EVENT_ASSET_TYPE", "merge_modular_event_metadata"]
