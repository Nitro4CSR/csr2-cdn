"""Read-only discovery of modular event metadata from the game's asset CDN.

This module does not distribute asset binaries, persist player information or
assume that a bundled event has a known leaderboard name. UnityPy is optional
until the runtime event feature is used (``pip install csr2-cdn[events]``).
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Callable, Optional

from csr2cdn.service_events import EventResolutionError

class RuntimeEventSourceError(EventResolutionError):
    """Incomplete/unavailable runtime event source; not evidence of no events."""


MAX_BUNDLE_BYTES = 128 * 1024 * 1024
MAX_CATALOGUE_BYTES = 512 * 1024 * 1024
MAX_ASSETS = 256
MAX_OBJECTS = 50000


def _groups(node: Any, *, depth: int = 0, seen: Optional[set] = None):
    """Extract explicit Showdown groups without confusing other event types."""
    if depth > 18 or not isinstance(node, (Mapping, list, tuple)):
        return []
    if seen is None:
        seen = set()
    identity = id(node)
    if identity in seen:
        return []
    seen.add(identity)
    if isinstance(node, (list, tuple)):
        result = []
        for value in node:
            result.extend(_groups(value, depth=depth + 1, seen=seen))
        return result
    if (isinstance(node.get("EventGroupName"), str)
            and node["EventGroupName"].strip()
            and ("RaceEvents" in node or "Leaderboard" in node or "ScheduleID" in node)):
        return [dict(node)]
    # Some assets wrap event groups in a standalone ShowdownEventsContainer,
    # others embed them in a MonoBehaviour's EventCommonMetadata payload.
    result = []
    for key, value in node.items():
        # Cup series is a separate consumer in RaceEventDatabase. Descending
        # through it as though it were ShowdownEventsContainer conflates event
        # types and can surface cups as "Showdowns".
        if key == "RaceSeries":
            continue
        if isinstance(value, (Mapping, list, tuple)):
            result.extend(_groups(value, depth=depth + 1, seen=seen))
    return result


def _prestige_groups(node: Any, *, depth: int = 0, seen: Optional[set] = None):
    """Preserve authoritative native-telemetry groups without requiring a UI name.

    The compiled RaceEventGroup_JsonData has independent ``id`` and
    ``EventGroupName`` fields. The Showdown extractor needs a display name,
    but a race group used for Prestige may have only the serialized ID.
    Do not invent a group name or count a lone telemetry marker as a race.
    """
    if depth > 18 or not isinstance(node, (Mapping, list, tuple)):
        return []
    if seen is None:
        seen = set()
    if id(node) in seen:
        return []
    seen.add(id(node))
    if isinstance(node, Mapping):
        telemetry = node.get("TelemGroupName", node.get("TelemetryGroupName"))
        identity = node.get("id")
        if identity is None or identity == "":
            identity = node.get("EventGroupName")
        valid_identity = (isinstance(identity, str) and bool(identity.strip())) or (
            isinstance(identity, int) and not isinstance(identity, bool))
        has_races = isinstance(node.get("RaceEvents"), (list, tuple))
        result = ([dict(node)] if isinstance(telemetry, str) and telemetry.casefold() == "silver_prestige" and valid_identity
                  and has_races else [])
        for value in node.values():
            if isinstance(value, (Mapping, list, tuple)):
                result.extend(_prestige_groups(value, depth=depth+1, seen=seen))
        return result
    result = []
    for value in node:
        result.extend(_prestige_groups(value, depth=depth+1, seen=seen))
    return result


def _additional_records(node: Any, *, depth: int = 0, seen: Optional[set] = None):
    """Recover schedule/definition arrays when a modular payload includes them."""
    if depth > 18 or not isinstance(node, (Mapping, list, tuple)):
        return {}
    if seen is None:
        seen = set()
    if id(node) in seen:
        return {}
    seen.add(id(node))
    result = {"ScheduleList": [], "EventLeaderboardsDefinitions": [], "RaceSeries": [], "SeasonalRewardCars": []}
    if isinstance(node, Mapping):
        for key in result:
            values = node.get(key)
            if isinstance(values, list):
                result[key].extend(row for row in values if isinstance(row, Mapping))
            elif isinstance(values, Mapping):
                # In seasonal event bundles, CrewLeaderboardRewardDefinitions
                # stores SeasonalRewardCars as a season-number keyed mapping.
                # Preserve this lookup; it is an input to the client's
                # repeatable Prestige event processing, NOT a leaderboard ID.
                marker = "_season_id" if key == "SeasonalRewardCars" else "_map_id"
                result[key].extend(dict(row, **{marker: str(k)}) for k, row in values.items()
                                   if isinstance(row, Mapping))
        children = node.values()
    else:
        children = node
    for value in children:
        if isinstance(value, (Mapping, list, tuple)):
            for key, rows in _additional_records(value, depth=depth+1, seen=seen).items():
                result[key].extend(rows)
    return result


def extract_modular_event_metadata(payload: bytes, *, loader: Optional[Callable] = None) -> dict:
    """Decode a Unity asset bundle and extract explicit event data.

    TextAsset JSON and type-tree MonoBehaviours are supported. Unity bundles
    with unavailable stripped type trees are deliberately not guessed from
    arbitrary binary strings. The decoder processes every recognized object;
    corrupt candidate objects result in a safe failure rather than fake data.
    """
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_BUNDLE_BYTES:
        raise RuntimeEventSourceError("event bundle is absent or exceeds the size limit")
    if loader is None:
        try:
            import UnityPy
        except ImportError:
            raise RuntimeEventSourceError("runtime event decoder is unavailable; install csr2-cdn[events]") from None
        loader = UnityPy.load
    try:
        environment = loader(payload)
        objects = environment.objects
    except Exception:
        raise RuntimeEventSourceError("runtime event asset bundle could not be opened") from None
    catalogue = {"RaceEventGroups": [], "PrestigeRaceEventGroups": [], "ScheduleList": [], "EventLeaderboardsDefinitions": [], "RaceSeries": [], "SeasonalRewardCars": []}
    count, recognized = 0, 0
    try:
        for obj in objects:
            count += 1
            if count > MAX_OBJECTS:
                raise RuntimeEventSourceError("event bundle contains too many objects")
            kind = getattr(getattr(obj, "type", None), "name", "")
            if kind not in ("MonoBehaviour", "TextAsset"):
                continue
            node = None
            if kind == "MonoBehaviour":
                try:
                    if hasattr(obj, "read_typetree"):
                        node = obj.read_typetree()
                    elif hasattr(obj, "parse_as_dict"):
                        node = obj.parse_as_dict()
                except Exception:
                    continue  # stripped type tree: do not invent event properties
            else:
                try:
                    data = obj.read()
                    raw = getattr(data, "m_Script", getattr(data, "script", None))
                    if isinstance(raw, str):
                        raw = raw.encode("utf-8")
                    if isinstance(raw, (bytes, bytearray)) and len(raw) <= MAX_BUNDLE_BYTES:
                        node = json.loads(raw.decode("utf-8-sig"))
                except (UnicodeError, ValueError, TypeError, AttributeError):
                    continue  # not every TextAsset is JSON event metadata
            if not isinstance(node, (Mapping, list, tuple)):
                continue
            extracted = _groups(node)
            prestige = _prestige_groups(node)
            more = _additional_records(node)
            if extracted or prestige or any(more.values()):
                recognized += 1
                catalogue["RaceEventGroups"].extend(extracted)
                catalogue["PrestigeRaceEventGroups"].extend(prestige)
                for key, rows in more.items():
                    catalogue[key].extend(rows)
    except RuntimeEventSourceError:
        raise
    except Exception:
        raise RuntimeEventSourceError("runtime event asset objects could not be decoded") from None
    # A well-formed bundle may contain no Showdown group at all; this is not
    # a decoder failure unless none of its serialized data could be examined.
    return catalogue


def load_modular_event_metadata(cdn, *, database=None, decoder=extract_modular_event_metadata,
                                max_assets: int = MAX_ASSETS,
                                max_total_bytes: int = MAX_CATALOGUE_BYTES) -> dict:
    """Fetch current type-47 ASTC bundles and extract their structured events.

    Uses the existing CDN's versioned AssetDatabase and asset downloader. No
    persistent raw bundles, snapshot files, credentials, or logs are produced.
    Failure of ANY required bundle is fatal: partial runtime discovery must
    never be advertised as complete or as proof that an event is absent.
    """
    from csr2cdn.service_discovery import modular_event_assets
    try:
        assets = modular_event_assets(database if database is not None else cdn.get_database())
    except Exception:
        raise RuntimeEventSourceError("current event asset catalogue is unavailable") from None
    if not assets:
        raise RuntimeEventSourceError("current asset catalogue contains no modular event bundles")
    if len(assets) > max_assets:
        raise RuntimeEventSourceError("too many modular event assets for safe discovery")
    total = 0
    merged = {"RaceEventGroups": [], "PrestigeRaceEventGroups": [], "ScheduleList": [], "EventLeaderboardsDefinitions": [], "RaceSeries": [], "SeasonalRewardCars": []}
    for asset in assets:
        try:
            # Quality is explicit: the asset database lists ASTC-compatible
            # Unity bundles. ASTC texture decoding is not needed for metadata.
            size = asset.size("ASTC")
            if size > MAX_BUNDLE_BYTES:
                raise RuntimeEventSourceError("modular event bundle exceeds size limit")
            total += size
            if total > max_total_bytes:
                raise RuntimeEventSourceError("modular event catalogue exceeds size limit")
            if hasattr(cdn, "_get") and hasattr(cdn, "url_for"):
                # The standard CDN client supports streaming. Limit bytes while
                # receiving, not after allocating the complete bundle.
                response = cdn._get(cdn.url_for(asset, quality="ASTC"), stream=True)
                try:
                    received = bytearray()
                    for chunk in response.iter_content(chunk_size=65536):
                        received.extend(chunk)
                        if len(received) > MAX_BUNDLE_BYTES:
                            raise RuntimeEventSourceError("modular event bundle exceeds size limit")
                    payload = bytes(received)
                finally:
                    response.close()
            else:
                # Compatible injected test doubles can implement download_asset.
                payload = cdn.download_asset(asset, quality="ASTC")
                if len(payload) > MAX_BUNDLE_BYTES:
                    raise RuntimeEventSourceError("modular event bundle exceeds size limit")
            total += max(0, len(payload) - size)
            if total > max_total_bytes:
                raise RuntimeEventSourceError("modular event catalogue exceeds size limit")
            result = decoder(payload)
            for key in merged:
                values = result.get(key, [])
                if not isinstance(values, list):
                    raise RuntimeEventSourceError("event bundle produced an unsupported schema")
                merged[key].extend(values)
        except RuntimeEventSourceError:
            raise
        except Exception:
            raise RuntimeEventSourceError("modular event bundle could not be retrieved or decoded") from None
    # If no event metadata was decoded, we cannot distinguish a legitimately
    # empty runtime catalogue from stripped type trees or wrong bundle types.
    if not any(merged.values()):
        raise RuntimeEventSourceError("runtime bundles contained no decodable event metadata")
    return merged


__all__ = ["extract_modular_event_metadata", "load_modular_event_metadata", "RuntimeEventSourceError"]
