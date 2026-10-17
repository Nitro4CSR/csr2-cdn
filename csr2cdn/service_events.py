"""Refreshable, non-bundled event -> leaderboard resolution.

An EventCatalog accepts a caller-supplied source of current authoritative
metadata. The input format is an *adapter format*, not a claim about the game's
undocumented event-metadata wire schema. Event identifiers are not treated as
leaderboard identifiers unless the data source explicitly maps them.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

from csr2cdn._service_reads import _identifier
from csr2cdn.errors import Csr2CdnError


class EventResolutionError(Csr2CdnError):
    """Event mapping missing or ambiguous: requires authoritative discovery."""


class ShowdownInactiveError(EventResolutionError):
    """Requested seasonal Showdown slot has no active instance in metadata."""


@dataclass(frozen=True)
class EventLeaderboard:
    event_id: str
    kind: str
    leaderboard_name: str
    season: Optional[str] = None
    segment: Optional[str] = None
    instance: Optional[str] = None
    crew_id: Optional[str] = None
    score_unit: Optional[str] = None

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "EventLeaderboard":
        if not isinstance(record, Mapping):
            raise EventResolutionError("event mapping record must be an object")
        kind = str(record.get("kind", "")).lower().replace("-", "_")
        if kind not in ("showdown", "showdown_leagues", "prestige_cup"):
            raise EventResolutionError("event kind must be showdown, showdown_leagues or prestige_cup")
        try:
            eid = _identifier(record["event_id"], name="event_id")
            board = _identifier(record["leaderboard_name"], name="leaderboard_name")
        except (KeyError, ValueError, Csr2CdnError) as exc:
            raise EventResolutionError("event mapping requires event_id and leaderboard_name") from exc
        return cls(eid, kind, board, *(
            str(record[key]) if record.get(key) is not None else None
            for key in ("season", "segment", "instance", "crew_id", "score_unit")
        ))


class EventCatalog:
    """Event identifiers resolved by refreshing an external source, never a built-in list.

    `source` is a callback returning `{'events': [{event_id, kind,
    leaderboard_name, ...}, ...]}` or an iterable of records. The caller is
    responsible for adapting game metadata to this exact documented format.
    """

    def __init__(self, source: Callable[[], Any], *, ttl: float = 300.0):
        if not callable(source):
            raise TypeError("event source must be callable")
        if ttl < 0:
            raise ValueError("ttl must not be negative")
        self.source = source
        self.ttl = ttl
        self._last_refresh: Optional[float] = None
        self._items: Tuple[EventLeaderboard, ...] = ()

    @classmethod
    def from_json_file(cls, path, *, ttl: float = 300.0) -> "EventCatalog":
        return cls(lambda: json.loads(Path(path).read_text(encoding="utf-8")), ttl=ttl)

    @classmethod
    def from_metadata(cls, client, *, block_names, zid: str,
                      product_version: str, extract: Callable[[Mapping[str, Any]], Any],
                      ttl: float = 300.0) -> "EventCatalog":
        """Live/current metadata adapter with caller-defined event extraction.

        No game block IDs or event-to-board relationships are invented here.
        `extract` receives `{block_name: block.content}` and must return the
        documented event-mapping adapter format. This allows configuration
        to change independently of the installed Python package.
        """
        if not callable(extract):
            raise TypeError("extract must be callable")
        names = tuple(block_names)
        if not names:
            raise ValueError("block_names must not be empty")
        def load():
            blocks = client.get(names, zid=zid, product_version=product_version)
            return extract({key: value.content for key, value in blocks.items()})
        return cls(load, ttl=ttl)

    def refresh(self) -> Tuple[EventLeaderboard, ...]:
        data = self.source()
        if isinstance(data, Mapping):
            data = data.get("events")
        if not isinstance(data, (tuple, list)):
            raise EventResolutionError("event source must provide an events array")
        items = tuple(EventLeaderboard.from_record(v) for v in data)
        # Deduplicate exact entries but never collapse differing scopes.
        unique = tuple(dict.fromkeys(items))
        self._items = unique  # update only after the entire refresh succeeded
        self._last_refresh = time.monotonic()
        return unique

    def list_events(self, *, refresh: bool = False) -> Tuple[EventLeaderboard, ...]:
        if refresh or self._last_refresh is None or time.monotonic() - self._last_refresh >= self.ttl:
            return self.refresh()
        return self._items

    def resolve(self, event_id: str, kind: str, *, season: Optional[str] = None,
                segment: Optional[str] = None, instance: Optional[str] = None,
                crew_id: Optional[str] = None, refresh: bool = False) -> EventLeaderboard:
        _identifier(event_id, name="event_id")
        choices = [item for item in self.list_events(refresh=refresh)
                   if item.event_id == event_id and item.kind == kind and
                   all(val is None or getattr(item, key) == str(val) for key, val in
                       (("season", season), ("segment", segment), ("instance", instance), ("crew_id", crew_id)))]
        if not choices:
            raise EventResolutionError("no matching event-to-leaderboard mapping; supply a leaderboard name or refresh discovery")
        if len(choices) != 1:
            raise EventResolutionError("ambiguous leaderboard scope; specify season, segment, instance or crew ID")
        return choices[0]


__all__ = ["EventCatalog", "EventLeaderboard", "EventResolutionError"]
