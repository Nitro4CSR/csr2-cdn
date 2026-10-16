"""Prestige Cup discovery, independent of the Showdown-only event catalogue.

CSR2 6.8.0's RaceEventData.IsPrestigeEvent checks the parent's telemetry
classification (RVA 0x32d8d40); CupInvitationalRaceSeries is processed through
RaceEventDatabase.SetAndProcessCupInvitationalEvents (RVA 0x32f4920). The
standalone series and modular groups are independent inputs. Only groups with
an attached event leaderboard can be turned into a standings request.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
import json
from typing import Any, Callable, Mapping, Optional

from csr2cdn.service_events import EventResolutionError
from csr2cdn.service_showdown_resolution import (native_board_name, leaderboard_definition, ranking_direction)
from csr2cdn.service_prestige_runtime_inputs import (decode_prestige_template, calendar_occurrence, event_id)
from csr2cdn.service_discovery import ShowdownDiscovery, scan_showdowns, _content, _records

CUP_METADATA_BLOCK = "CupInvitationalRaceSeries"
# Additional native RaceEventDatabase consumers. The career block holds
# SMPRaceEvents (RaceEventDatabaseData.ProcessEvents RVA 0x32f3374); the
# invitational block is loaded by LoadInvitationalEventsConfig RVA 0x32f4554.
ADDITIONAL_PRESTIGE_BLOCKS = ("CareerRaceEvents", "InvitationalRaceSeries", "SpecialLadderEvents")


def seasonal_prestige_car(blocks: Mapping[str, Any], season: int) -> Optional[str]:
    """Look up a season's Prestige car from decoded seasonal event bundles.

    This does not identify an event group, leaderboard, or active season.
    The caller must obtain the exact season from authoritative metadata.
    """
    if isinstance(season, bool) or not isinstance(season, int) or season < 0:
        raise ValueError("season must be a nonnegative integer")
    records = _records(_content(blocks, "_RuntimeSeasonalRewardCars"), "SeasonalRewardCars")
    matches = [row.get("PrestigeCupCar") for row in records
               if row.get("_season_id") == str(season)]
    matches = [value for value in matches if isinstance(value, str) and value]
    if len(set(matches)) > 1:
        raise EventResolutionError("conflicting seasonal Prestige car definitions")
    return matches[0] if matches else None


def _is_prestige(group: Mapping[str, Any]) -> bool:
    """Follow RaceEventData.IsPrestigeEvent's native telemetry comparison.

    CSR2 6.8.0's RVA 0x32d8d40 compares the parent RaceEventGroup's
    TelemGroupName with the IL2CPP literal ``Silver_Prestige``. Earlier
    prototypes matched ``PRESTIGE``/``PRESTIGE_CUP``, which is not the native
    predicate. For a group with telemetry supplied, do not override the
    classification using a name that happens to contain 'prestige'.

    Without telemetry, explicit names remain a lower-confidence fallback.
    """
    telemetry = group.get("TelemGroupName", group.get("TelemetryGroupName"))
    if isinstance(telemetry, str) and telemetry.strip():
        return telemetry.strip().casefold() == "silver_prestige"
    for name in ("EventGroupName", "EventName"):
        value = group.get(name)
        if isinstance(value, str):
            token = value.strip().upper().replace("-", "_").replace(" ", "_")
            if token in ("PRESTIGE", "PRESTIGE_CUP") or token.startswith("PRESTIGE_CUP_"):
                return True
    return False


def _find_groups(value: Any, *, depth: int = 0, visited=None):
    """Locate cup race groups in RaceSeries/RaceEventTopLevelCategory structures.

    SeriesEvent rows have an EventFile reference but are not themselves
    RaceEventGroups; they cannot be used to invent a leaderboard.
    """
    if visited is None:
        visited = set()
    if depth > 18 or not isinstance(value, (Mapping, list, tuple)) or id(value) in visited:
        return []
    visited.add(id(value))
    if isinstance(value, Mapping):
        groups = []
        if (isinstance(value.get("EventGroupName"), str) or
                (str(value.get("TelemGroupName", value.get("TelemetryGroupName", ""))).casefold() == "silver_prestige"
                 and isinstance(value.get("id"), (str, int))
                 and not isinstance(value.get("id"), bool))) and (
                "RaceEvents" in value or "Leaderboard" in value):
            groups.append(value)
        for v in value.values():
            groups.extend(_find_groups(v, depth=depth + 1, visited=visited))
        return groups
    groups = []
    for child in value:
        groups.extend(_find_groups(child, depth=depth + 1, visited=visited))
    return groups


def _series_count(node: Any, *, depth=0, visited=None):
    if visited is None:
        visited = set()
    if depth > 18 or not isinstance(node, (Mapping, list, tuple)) or id(node) in visited:
        return 0
    visited.add(id(node))
    if isinstance(node, Mapping):
        count = len(node["RaceSeries"]) if isinstance(node.get("RaceSeries"), list) else 0
        return count + sum(_series_count(v, depth=depth + 1, visited=visited)
                           for v in node.values())
    return sum(_series_count(v, depth=depth + 1, visited=visited) for v in node)


def _cup_groups(blocks: Mapping[str, Any]):
    """Groups embedded in cup/invitational series, never EventFile paths."""
    cup = _content(blocks, CUP_METADATA_BLOCK)
    runtime = _content(blocks, "_RuntimeCupSeries")
    invitational = _content(blocks, "InvitationalRaceSeries")
    return _find_groups(cup) + _find_groups(runtime) + _find_groups(invitational)


def _career_groups(blocks: Mapping[str, Any]):
    """Traverse client-processed SMPRaceEvents and other career race categories.

    RaceEventDatabaseData.ProcessEvents calls RaceEventTopLevelCategory.ProcessEvents
    on SMPRaceEvents (+0x48) and SpeedTrapEvents (+0x50).  This scans their
    serialized RaceEventGroups, *without* classifying them as Prestige by default.
    """
    career = _content(blocks, "CareerRaceEvents")
    return _find_groups(career)


def _special_ladder_groups(blocks: Mapping[str, Any]):
    """Find client-registered race groups from SpecialLadderEvents.LadderEvents.

    Native SpecialLadderEventsDatabase.ReadSpecialLadderEvents (0x342bc4c)
    provides the object consumed by RaceEventDatabase.ProcessSpecialLadderRaceEventData
    (0x32f33fc). The latter visits LadderEvents' RaceEventGroups and calls
    RaceEventGroup.ProcessEvents. This category is independent of the standalone
    Showdown and CupInvitationalRaceSeries catalogues.

    Not every special-ladder group is a Prestige Cup. We preserve all registered
    groups for structural diagnostics and apply the native Prestige predicate
    separately. The source cannot by itself license a leaderboard request.
    """
    source = _content(blocks, "SpecialLadderEvents")
    if not isinstance(source, Mapping):
        return []
    # The serialized top-level object is SpecialLadderEvents, whose LadderEvents
    # member is the RaceEventTopLevelCategory processed by the native client.
    ladder = source.get("LadderEvents")
    if not isinstance(ladder, (Mapping, list, tuple)):
        return []
    return _find_groups(ladder)


def _numeric_eventfile_count(value: Any, *, seen=None, depth=0) -> int:
    """Value-free diagnostic only. Native EventFile is Int32, not an asset path."""
    if seen is None:
        seen = set()
    if depth > 18 or not isinstance(value, (Mapping, list, tuple)) or id(value) in seen:
        return 0
    seen.add(id(value))
    if isinstance(value, Mapping):
        file_id = value.get("EventFile")
        total = int(isinstance(file_id, int) and not isinstance(file_id, bool))
        return total + sum(_numeric_eventfile_count(v, seen=seen, depth=depth+1) for v in value.values())
    return sum(_numeric_eventfile_count(v, seen=seen, depth=depth+1) for v in value)


def scan_prestige_cups(blocks: Mapping[str, Any], *, at: Optional[datetime] = None):
    """Resolve only Prestige-classified groups, preserving unresolved candidates.

    The Showdown resolver is reused strictly for its common schedule and native
    event-leaderboard identity code, not its Showdown event classification.
    """
    from csr2cdn.service_discovery import _str
    showdown = list(_records(_content(blocks, "ShowdownEventsContainer"), "RaceEventGroups"))
    runtime_prestige = _find_groups(_content(blocks, "_RuntimePrestigeGroups"))
    source = showdown + runtime_prestige + _cup_groups(blocks) + _career_groups(blocks) + _special_ladder_groups(blocks)
    unique = {}
    for group in source:
        # The native Prestige predicate reads the parent group's TelemGroupName.
        # An EventFile integer is NOT a path to resolve and does not classify
        # a generic cup as a Prestige Cup. Reject unidentified groups.
        if not _is_prestige(group):
            continue
        # JSON id is the serialized native identity, not an invented display name.
        name = _str(group, "EventGroupName", "id")
        if name:
            unique.setdefault(name, group)
    isolated = dict(blocks)
    isolated["ShowdownEventsContainer"] = {"RaceEventGroups": list(unique.values())}
    return scan_showdowns(isolated, at=at)


@dataclass(frozen=True)
class PrestigeCupSelection:
    event_name: str
    leaderboard_name: str
    starts_at: datetime
    ends_at: datetime
    offset: int


def native_result_offset(starts_at: datetime, ends_at: datetime, *, at=None) -> int:
    """GetResultOffset from EventLeaderboard (native RVA 0x33895f8)."""
    if at is None:
        at = datetime.now(timezone.utc)
    if any(not isinstance(x, datetime) or x.tzinfo is None for x in (starts_at, ends_at, at)):
        raise ValueError("timestamps must be timezone aware")
    duration = (ends_at - starts_at).total_seconds()
    if duration <= 0:
        raise ValueError("event duration must be positive")
    after = (at - ends_at).total_seconds()
    offset = max(0, ceil(after / duration))
    if offset >= 2**31:
        raise ValueError("offset exceeds native int32")
    return offset


class PrestigeCupDiscovery:
    """Read metadata from the *cup* series as well as common event bundles.

    A series containing an integer EventFile but no Prestige-classified group is
    an incomplete discovery source; the integer is not an asset filename. Never synthesize its leaderboard or pretend
    that a missing candidate proves no live Prestige Cup exists.
    """
    def __init__(self, discovery: ShowdownDiscovery, *, cup_source: Optional[Callable[[], Any]] = None,
                 other_sources: Optional[Mapping[str, Callable[[], Any]]] = None,
                 native_binary_source: Optional[Callable[[], bytes]] = None,
                 native_season: Optional[int] = None,
                 native_car_tier: Optional[int] = None,
                 native_car_key: Optional[str] = None):
        if not isinstance(discovery, ShowdownDiscovery):
            raise TypeError("discovery must be ShowdownDiscovery")
        self.discovery = discovery
        self.cup_source = cup_source
        self._cup_loaded = False
        self._cup_data = None
        self._last = ()
        self.other_sources = dict(other_sources or {})
        self.native_binary_source = native_binary_source
        self.native_season = native_season
        self.native_car_tier = native_car_tier
        self.native_car_key = native_car_key
        self._native_template = None
        self._native_template_error = False
        self._native_selection = None
        self._other_data: dict[str, Any] = {}
        self._unavailable_sources: set[str] = set()
        self._attempted_sources: set[str] = set()

    @classmethod
    def from_json_directory(cls, directory):
        root = Path(directory)
        path = root / (CUP_METADATA_BLOCK + ".meta")
        cup_source = (lambda: json.loads(path.read_text(encoding="utf-8-sig"))) if path.is_file() else None
        other = {}
        for name in ADDITIONAL_PRESTIGE_BLOCKS:
            item = root / (name + ".meta")
            if item.is_file():
                other[name] = (lambda path=item: json.loads(path.read_text(encoding="utf-8-sig")))
        return cls(ShowdownDiscovery.from_json_directory(directory), cup_source=cup_source,
                   other_sources=other)

    @classmethod
    def from_metadata(cls, client, *, player_id: str, product_version: str, asset_cdn=None,
                      native_season=None, native_car_tier=None, native_car_key=None):
        discovery = ShowdownDiscovery.from_metadata(
            client, player_id=player_id, product_version=product_version,
            asset_cdn=asset_cdn)
        def load_cup():
            data = client.get((CUP_METADATA_BLOCK,), zid=player_id,
                              product_version=product_version)
            if CUP_METADATA_BLOCK not in data:
                raise EventResolutionError("cup series metadata unavailable")
            return data[CUP_METADATA_BLOCK].content
        def make_load(name):
            def load():
                data = client.get((name,), zid=player_id, product_version=product_version)
                if name not in data:
                    raise EventResolutionError("additional event source unavailable")
                return data[name].content
            return load
        return cls(discovery, cup_source=load_cup, other_sources={
            name: make_load(name) for name in ADDITIONAL_PRESTIGE_BLOCKS},
            native_binary_source=(lambda: load_native_prestige_bundle(asset_cdn)) if asset_cdn is not None else None,
            native_season=native_season, native_car_tier=native_car_tier,
            native_car_key=native_car_key)

    def list_cups(self, *, at=None, refresh=False):
        self.discovery.list_showdowns(at=at, refresh=refresh)
        if self.cup_source is not None and (refresh or not self._cup_loaded):
            # Do not change previous state on failed fetch.
            cup_data = self.cup_source()
            if not isinstance(cup_data, Mapping):
                raise EventResolutionError("cup series metadata has unsupported structure")
            self._cup_data = cup_data
            self._cup_loaded = True
        # Additional native sources are best-effort. A missing block must be
        # marked incomplete, not silently read as proof of no live Prestige Cup.
        for name, loader in self.other_sources.items():
            if refresh or (name not in self._other_data and name not in self._unavailable_sources):
                self._attempted_sources.add(name)
                try:
                    value = loader()
                    if not isinstance(value, Mapping):
                        raise EventResolutionError("unsupported event source structure")
                    self._other_data[name] = value
                    self._unavailable_sources.discard(name)
                except Exception:
                    self._unavailable_sources.add(name)
                    if refresh:
                        self._other_data.pop(name, None)
        blocks = dict(self.discovery._blocks)
        if self._cup_loaded:
            blocks[CUP_METADATA_BLOCK] = self._cup_data
        blocks.update(self._other_data)
        self._last = scan_prestige_cups(blocks, at=at)
        self._native_selection = None
        if self.native_binary_source is not None and (refresh or (self._native_template is None and not self._native_template_error)):
            try:
                self._native_template = decode_prestige_template(self.native_binary_source())
                self._native_template_error = False
            except Exception:
                self._native_template_error = True
                self._native_template = None
        if self._native_template is not None and self.native_season is not None and self.native_car_tier is not None:
            try:
                self._native_selection = resolve_native_prestige(
                    blocks, self._native_template, season=self.native_season,
                    tier=self.native_car_tier, expected_car_key=self.native_car_key, at=at)
            except (EventResolutionError, ValueError, TypeError, KeyError):
                self._native_selection = None
        return self._last

    def source_summary(self) -> dict:
        """Values-free coverage and resolution counts for authorized diagnostics."""
        blocks = self.discovery._blocks or {}
        names = list(_records(_content(blocks, "ShowdownEventsContainer"), "RaceEventGroups"))
        all_blocks = {**blocks, **self._other_data,
                      **({CUP_METADATA_BLOCK: self._cup_data} if self._cup_loaded else {})}
        extra = _cup_groups(all_blocks)
        career = _career_groups(all_blocks)
        special = _special_ladder_groups(all_blocks)
        special_source = _content(all_blocks, "SpecialLadderEvents")
        ladder = special_source.get("LadderEvents") if isinstance(special_source, Mapping) else None
        serialized_ladder_groups = ladder.get("RaceEventGroups") if isinstance(ladder, Mapping) else None
        special_serialized_count = (len(serialized_ladder_groups)
                                    if isinstance(serialized_ladder_groups, (Mapping, list, tuple)) else 0)
        modular_prestige = _find_groups(_content(blocks, "_RuntimePrestigeGroups"))
        if self._native_template_error:
            binary_blocker = "template_unavailable"
        elif self._native_template is None:
            binary_blocker = "template_not_loaded"
        elif self.native_season is None or self.native_car_tier is None:
            binary_blocker = "runtime_season_or_car_tier_not_supplied"
        elif self._native_selection is None:
            binary_blocker = "current_metadata_or_event_window_unresolved"
        else:
            binary_blocker = "none"
        return {
            "binary_prestige_resolution_blocker": binary_blocker,
            "binary_prestige_source_configured": self.native_binary_source is not None,
            "binary_prestige_template_loaded": self._native_template is not None,
            "binary_prestige_template_error": self._native_template_error,
            "binary_prestige_template_has_leaderboard": (bool(self._native_template.get("leaderboard_attached")) if self._native_template is not None else False),
            "binary_prestige_runtime_inputs_supplied": self.native_season is not None and self.native_car_tier is not None,
            "binary_prestige_resolved_active": self._native_selection is not None,
            "runtime_groups": len(names), "cup_series_loaded": self._cup_loaded,
            "cup_series_entries": _series_count(self._cup_data) if self._cup_loaded else 0,
            "cup_nested_groups": len(extra),
            "career_race_groups": len(career),
            "special_ladder_source_loaded": "SpecialLadderEvents" in self._other_data or "SpecialLadderEvents" in blocks,
            "special_ladder_has_ladder_events": isinstance(ladder, (Mapping, list, tuple)),
            "special_ladder_serialized_group_rows": special_serialized_count,
            "special_ladder_groups": len(special),
            "special_ladder_groups_with_leaderboard": sum(
                isinstance(g.get("Leaderboard"), Mapping) and bool(g.get("Leaderboard")) for g in special),
            "special_ladder_native_prestige_groups": sum(
                str(g.get("TelemGroupName", g.get("TelemetryGroupName", ""))).casefold() == "silver_prestige" for g in special),
            "runtime_prestige_groups": len(modular_prestige),
            "unnamed_runtime_prestige_groups": sum(
                not isinstance(g.get("EventGroupName"), str) or not g.get("EventGroupName")
                for g in modular_prestige),
            "numeric_eventfile_records": _numeric_eventfile_count(self._cup_data) if self._cup_loaded else 0,
            "seasonal_prestige_car_records": sum(
                isinstance(row.get("PrestigeCupCar"), str) and bool(row.get("PrestigeCupCar"))
                for row in _records(_content(blocks, "_RuntimeSeasonalRewardCars"), "SeasonalRewardCars")),
            "additional_sources_configured": len(self.other_sources),
            "additional_sources_attempted": len(self._attempted_sources),
            "additional_sources_loaded": len(self._other_data),
            "additional_sources_unavailable": len(self._unavailable_sources),
            "native_telemetry_prestige_groups": sum(
                _is_prestige(g)
                for g in [*names, *modular_prestige, *extra, *career, *special]),
            "positively_classified_prestige_groups": sum(
                _is_prestige(g) for g in [*names, *modular_prestige, *extra, *career, *special]),
            "metadata_group_candidates": len(self._last),
            "prestige_candidates": len(self._last) + int(self._native_selection is not None),
            "active_candidates": sum(x.time_status == "scheduled_now" for x in self._last) + int(self._native_selection is not None),
            "requestable_active": sum(x.time_status == "scheduled_now" and x.requestable for x in self._last) + int(self._native_selection is not None),
            "missing_inputs": sorted({value for x in self._last for value in x.unresolved_inputs}),
        }

    def resolve_current(self, *, at=None, refresh=False) -> PrestigeCupSelection:
        candidates = self.list_cups(at=at, refresh=refresh)
        active = [x for x in candidates if x.time_status == "scheduled_now"]
        if not active:
            if self._native_selection is not None:
                return self._native_selection
            raise EventResolutionError("no Prestige Cup candidate is active in discovered event sources")
        if len(active) != 1:
            raise EventResolutionError("multiple active Prestige Cup candidates require disambiguation")
        item = active[0]
        if not item.requestable or item.starts_at is None or item.ends_at is None:
            raise EventResolutionError("Prestige Cup leaderboard inputs are incomplete")
        return PrestigeCupSelection(item.event_id, item.leaderboard_name,
                                    item.starts_at, item.ends_at,
                                    native_result_offset(item.starts_at, item.ends_at, at=at))



SPECIAL_LADDER_ASSET_CODE = "assets_client_metadata_special_ladder_events_database"


def load_native_prestige_bundle(asset_cdn) -> bytes:
    """Fetch the type-46 special-ladder bundle using the current AssetDatabase.

    The asset version is obtained from the actual database, never hardcoded.
    Download bytes are bounded, and no sensitive network diagnostics are logged.
    """
    from csr2cdn.service_modular_assets import RuntimeEventSourceError
    if asset_cdn is None:
        raise RuntimeEventSourceError("special-ladder asset CDN unavailable")
    try:
        db = asset_cdn.get_database()
        asset = db.assets.get(SPECIAL_LADDER_ASSET_CODE)
        if asset is None or str(asset.type) != "46":
            raise RuntimeEventSourceError("special-ladder asset missing from database")
        size = asset.size("ASTC")
        if not 0 < size <= 1_048_576:
            raise RuntimeEventSourceError("special-ladder asset size invalid")
        if hasattr(asset_cdn, "_get") and hasattr(asset_cdn, "url_for"):
            response = asset_cdn._get(asset_cdn.url_for(asset, quality="ASTC"), stream=True)
            try:
                body = bytearray()
                for part in response.iter_content(chunk_size=65536):
                    body.extend(part)
                    if len(body) > 1_048_576:
                        raise RuntimeEventSourceError("special-ladder asset too large")
                return bytes(body)
            finally:
                response.close()
        body = asset_cdn.download_asset(asset, quality="ASTC")
        if not isinstance(body, bytes) or len(body) > 1_048_576:
            raise RuntimeEventSourceError("invalid special-ladder payload")
        return body
    except RuntimeEventSourceError:
        raise
    except Exception:
        raise RuntimeEventSourceError("special-ladder bundle unavailable") from None


def resolve_native_prestige(blocks: Mapping[str, Any], template: Mapping[str, Any], *,
                            season: int, tier: int, expected_car_key: Optional[str] = None,
                            at: Optional[datetime] = None) -> PrestigeCupSelection:
    """Resolve 6.8.0 timed-board ID from real binary template + current metadata.

    The selected crew season and Prestige car tier must be explicit, since their
    live runtime values are not present in type-46 template metadata. Fail
    closed if a seasonal car or ranking definition is missing or incompatible.
    """
    if type(season) is not int or not 0 <= season <= 999:
        raise EventResolutionError("invalid current crew season")
    if type(tier) is not int or not 1 <= tier <= 5:
        raise EventResolutionError("invalid Prestige car tier")
    if at is None:
        at = datetime.now(timezone.utc)
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise EventResolutionError("current timestamp must be timezone aware")
    if (template.get("template") != "PRESTIGE_CHAMPIONSHIP_SILVER_LADDERS"
            or str(template.get("telemetry", "")).casefold() != "silver_prestige"
            or template.get("cup_car_lookup") != 0
            or template.get("based_on_season") != 0
            or not template.get("leaderboard_attached")
            or template.get("serialized_leaderboard_template") not in (None, "")
            or template.get("race_events_count") != 31
            or template.get("repeat_seconds") != 14*86400):
        raise EventResolutionError("unsupported native Prestige template")
    car = seasonal_prestige_car(blocks, season)
    if car is None:
        raise EventResolutionError("seasonal Prestige car metadata unavailable")
    if expected_car_key is not None and (not isinstance(expected_car_key, str) or car != expected_car_key):
        raise EventResolutionError("Prestige car record does not match current season")
    template_name = f"LeaderboardSilver_T{tier}_New"
    definition = leaderboard_definition(_content(blocks, "EventLeaderboards"), template_name)
    if definition is None:
        raise EventResolutionError("Prestige ranking template not present in current metadata")
    if (definition.get("EntityRanked") != "Player"
            or definition.get("RankingBasedOn") != "FastestHalfMileTime"
            or definition.get("RankingType") != "Best"):
        raise EventResolutionError("unexpected Prestige ranking definition")
    direction = ranking_direction(definition.get("RankingOrder", definition.get("rankingOrder")))
    if direction is None:
        raise EventResolutionError("Prestige ranking direction unavailable")
    window = calendar_occurrence(dict(template), at)
    if not window["active"]:
        raise EventResolutionError("native Prestige template not active at requested time")
    start = datetime.fromisoformat(window["start_utc"])
    end = datetime.fromisoformat(window["end_utc"])
    duration = int((end-start).total_seconds())
    if duration != 7*86400 or template.get("active_duration_hours") != 168:
        raise EventResolutionError("Prestige event duration invalid")
    first = event_id(template["event_file"], season, template["index_in_season"], 0)
    board = native_board_name(start=start, duration_seconds=duration,
                              ranking_order=direction, first_event_id=first)
    return PrestigeCupSelection(template["template"], board, start, end,
                                native_result_offset(start, end, at=at))


__all__ = ["PrestigeCupDiscovery", "PrestigeCupSelection", "scan_prestige_cups", "native_result_offset", "resolve_native_prestige", "load_native_prestige_bundle"]
