"""Offline-only exact-key lookups against an operator-provided HUB CarData export.

CSR2-HUB ``TextData/CarData.json`` is a community catalogue, not authoritative
runtime vehicle identity or an asset-ID translation table. Its ``DBName`` is
an exact candidate match to ``current_car`` in crew roster replies. The
catalogue is never downloaded by this module; consumers supply a local export.
No arbitrary descriptions, links, profiles or opaque objects are retained.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence, Tuple

MAX_CATALOG_ROWS = 10000


def _valid_key(value: Any) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= 180
            and value.strip() == value and not any(ord(c) < 32 for c in value))


@dataclass(frozen=True)
class VehicleCatalogEntry:
    """A source-backed *catalogue* observation, not a decoded in-game label."""
    db_name: str
    tier_candidate: Optional[int] = None
    star_marker_candidate: Optional[str] = None
    is_ev_candidate: Optional[bool] = None
    provenance: str = "operator_supplied_hub_cardata"

    def as_candidate_dict(self) -> dict:
        return {
            "db_name": self.db_name,
            "tier_candidate": self.tier_candidate,
            "star_marker_candidate": self.star_marker_candidate,
            "is_ev_candidate": self.is_ev_candidate,
            "provenance": self.provenance,
            "verified_in_game": False,
        }


@dataclass(frozen=True)
class VehicleCatalog:
    """Bounded catalogue with exact, case-sensitive DBName lookups only.

    Ambiguous duplicates fail closed. No invented manufacturer, car display
    name or translated cosmetic IDs. Caller controls when/whether the local
    catalogue was fetched; this class never performs I/O.
    """
    rows: Tuple[VehicleCatalogEntry, ...] = field(default_factory=tuple, repr=False)

    @classmethod
    def from_car_data(cls, data: Any) -> "VehicleCatalog":
        if not isinstance(data, list) or len(data) > MAX_CATALOG_ROWS:
            raise ValueError("CarData must be a bounded list of records")
        seen: set[str] = set()
        entries = []
        for row in data:
            if not isinstance(row, Mapping) or not _valid_key(row.get("DBName")):
                raise ValueError("CarData contains an invalid DBName record")
            key = row["DBName"]
            if key in seen:
                raise ValueError("ambiguous duplicate CarData DBName")
            seen.add(key)
            tier_raw = row.get("Tier")
            tier = tier_raw if type(tier_raw) is int and 0 <= tier_raw <= 10 else None
            star_raw = row.get("Star")
            star = (star_raw if isinstance(star_raw, str) and
                    len(star_raw) <= 32 and not any(ord(c) < 32 for c in star_raw)
                    else None)
            ev_raw = row.get("isEV")
            is_ev = (bool(ev_raw) if type(ev_raw) is int and ev_raw in (0, 1)
                     else ev_raw if type(ev_raw) is bool else None)
            entries.append(VehicleCatalogEntry(key, tier, star, is_ev))
        return cls(tuple(entries))

    def match(self, current_car: Optional[str]) -> Optional[VehicleCatalogEntry]:
        if not _valid_key(current_car):
            return None
        return next((row for row in self.rows if row.db_name == current_car), None)

    @property
    def size(self) -> int:
        return len(self.rows)


def resolve_vehicle_report(snapshot: Any, catalog: VehicleCatalog, *,
                           show_members: bool = False) -> dict:
    """Return aggregate coverage; per-member catalogue fields require opt-in.

    Never print member IDs, player names or unmatched current-car keys in
    default output. Do not use fuzzy matching: a near match is unresolved.
    """
    matched = [catalog.match(member.vehicle.model_key) for member in snapshot.members]
    total = len(matched)
    result = {
        "status": "offline_catalogue_candidates",
        "provenance": "operator_supplied_hub_cardata",
        "catalog_records": catalog.size,
        "roster_rows": total,
        "model_keys_present": sum(m.vehicle.model_key is not None for m in snapshot.members),
        "exact_dbname_matches": sum(entry is not None for entry in matched),
        "unresolved_rows": sum(entry is None for entry in matched),
        "name_labels_verified": False,
        "numeric_cosmetic_ids_resolved": False,
        "catalogue_freshness_verified": False,
        "network_requests": 0,
    }
    if show_members:
        result["member_catalogue_candidates"] = [
            entry.as_candidate_dict() if entry is not None else {"status": "unresolved"}
            for entry in matched
        ]
    return result
