"""The player's collections wallet: ``collections/get_collections_blob_data``.

The Car Credits balance, the cars bought with Car Credits (each with the
purchase timestamps), and the ids of events played toward collections.
Verified live on 2026-11-15.

Reads only. The matching ``collections/*`` writes (``add_car_credits``,
``deduct_car_credits``, ``validate_*``) are out of scope.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from .service_models import ServiceResponseError, _field, _int, _payload

_MAX_I64 = 2**63 - 1


def _num(node: Mapping[str, Any], *names: str) -> Optional[int]:
    value = _int(node, *names)
    return value if value is not None and -_MAX_I64 <= value <= _MAX_I64 else None


@dataclass(frozen=True)
class PurchasedWithCredits:
    """One ``CarsPurchasedViaCarCredits`` entry: a car and its purchase times."""

    car_db_id: str
    #: Purchase timestamps in epoch milliseconds, as the server records them.
    timestamps: Tuple[int, ...] = ()

    @property
    def count(self) -> int:
        return len(self.timestamps)


@dataclass(frozen=True)
class CollectionsBlob:
    """``collections/get_collections_blob_data`` -> ``data``."""

    car_credits: Optional[int] = None
    cars_purchased: Tuple[PurchasedWithCredits, ...] = ()
    events_played: Tuple[int, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def cars_purchased_count(self) -> int:
        return len(self.cars_purchased)

    def purchase(self, car_db_id: str) -> Optional[PurchasedWithCredits]:
        return next((c for c in self.cars_purchased if c.car_db_id == car_db_id), None)

    @classmethod
    def from_response(cls, response: Any) -> "CollectionsBlob":
        node = _payload(response)
        data = _field(node, "data")
        if isinstance(data, Mapping):
            node = data
        elif "CarCredits" not in node:
            raise ServiceResponseError("collections blob missing from response")
        bought = _field(node, "CarsPurchasedViaCarCredits")
        cars = []
        if isinstance(bought, Mapping):
            for car_db_id, stamps in bought.items():
                times = tuple(int(s) for s in stamps
                              if type(s) is int and not isinstance(s, bool)) \
                    if isinstance(stamps, (list, tuple)) else ()
                cars.append(PurchasedWithCredits(str(car_db_id), times))
        played = _field(node, "EventsIDPlayed")
        events = tuple(int(e) for e in played
                       if type(e) is int and not isinstance(e, bool)) \
            if isinstance(played, (list, tuple)) else ()
        return cls(_num(node, "CarCredits"), tuple(cars), events, dict(node))


__all__ = ["CollectionsBlob", "PurchasedWithCredits"]
