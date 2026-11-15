"""The player's Grand Tour season: ``grand_tour/get_season_details``.

The Grand Tour shard wallet, the universal-card count, and per-segment state:
status, window, the cards claimed, and each studio pack's next-purchase time.
Verified live on 2026-11-15 (Season 4).

The request shape
-----------------
Unlike the other reads, the parameter nests under an ``extra`` object::

    {"app_ver": "6.8.0", "extra": {"activeScheduleId": "GRAND_TOUR_SEASON_4_SEG_0"}}

``GrandTourWebRequestBase.TriggerRequest`` puts the feature's additional
params under ``extra``, which the server digs into; sending ``extra`` as a bare
value fails server-side (``TrueClass does not have #dig``). The schedule id is
any live ``GRAND_TOUR_SEASON_<n>_SEG_<m>`` from ``EventSchedule`` -- the server
answers with the player's own segment regardless of which segment is asked for.

Reads only. The matching ``grand_tour/acquire_packs`` write is out of scope.
The segmented-leaderboard id used by this feature's leaderboard is documented
in ``docs/0.7.2-service-surface.md`` but not built: no segmented board was
active when this was written.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Optional, Tuple

from .service_models import ServiceResponseError, _field, _int, _payload

#: A Grand Tour schedule id, e.g. ``GRAND_TOUR_SEASON_4_SEG_0``.
SCHEDULE_ID = re.compile(r"GRAND_TOUR_SEASON_\d{1,4}_SEG_\d{1,2}")
_MAX_I64 = 2**63 - 1


def _num(node: Mapping[str, Any], *names: str) -> Optional[int]:
    value = _int(node, *names)
    return value if value is not None and -_MAX_I64 <= value <= _MAX_I64 else None


@dataclass(frozen=True)
class StudioPack:
    """One ``StudioPacks`` entry: a pack colour and its next-purchase time."""

    name: str
    next_purchased_time: Optional[int] = None


@dataclass(frozen=True)
class GrandTourSegment:
    """One segment's state under ``GrandTour``.

    ``claimed_cards`` are the card ids the player has claimed this segment
    (e.g. ``"S4_Card34"``); ``claimed_card_count`` is their number.
    """

    schedule_id: str
    status: Optional[str] = None
    start_time: Optional[int] = None
    duration: Optional[int] = None
    claimed_cards: Tuple[str, ...] = ()
    studio_packs: Tuple[StudioPack, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def claimed_card_count(self) -> int:
        return len(self.claimed_cards)

    @property
    def is_started(self) -> bool:
        return self.status == "Started"

    @property
    def end_time(self) -> Optional[int]:
        if self.start_time is None or self.duration is None:
            return None
        return self.start_time + self.duration

    @classmethod
    def from_entry(cls, schedule_id: str, entry: Mapping[str, Any]) -> "GrandTourSegment":
        cards = _field(entry, "ClaimedCardsData")
        claimed = tuple(str(c) for c in cards if isinstance(c, (str, int))) \
            if isinstance(cards, (list, tuple)) else ()
        packs_node = _field(entry, "StudioPacks")
        packs = []
        if isinstance(packs_node, Mapping):
            for name, detail in packs_node.items():
                nxt = _num(detail, "NextPurchasedTime") if isinstance(detail, Mapping) else None
                packs.append(StudioPack(str(name), nxt))
        return cls(schedule_id,
                   _field(entry, "Status") if isinstance(_field(entry, "Status"), str) else None,
                   _num(entry, "StartTime"), _num(entry, "Duration"),
                   claimed, tuple(packs), dict(entry))


@dataclass(frozen=True)
class GrandTourSeason:
    """``grand_tour/get_season_details`` -> ``data``."""

    shards: Optional[int] = None
    universal_cards: Optional[int] = None
    segments: Tuple[GrandTourSegment, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def active_segment(self) -> Optional[GrandTourSegment]:
        """The segment currently in progress (``Status == "Started"``)."""
        return next((s for s in self.segments if s.is_started), None)

    def segment(self, schedule_id: str) -> Optional[GrandTourSegment]:
        return next((s for s in self.segments if s.schedule_id == schedule_id), None)

    @classmethod
    def from_response(cls, response: Any) -> "GrandTourSeason":
        node = _payload(response)
        data = _field(node, "data")
        if isinstance(data, Mapping):
            node = data
        gt = _field(node, "GrandTour")
        if not isinstance(gt, Mapping):
            raise ServiceResponseError("grand tour season data missing from response")
        segments = tuple(GrandTourSegment.from_entry(sid, entry)
                         for sid, entry in gt.items() if isinstance(entry, Mapping))
        return cls(_num(node, "Shards"), _num(node, "UniversalCards"),
                   segments, dict(node))


__all__ = ["GrandTourSeason", "GrandTourSegment", "StudioPack", "SCHEDULE_ID"]
