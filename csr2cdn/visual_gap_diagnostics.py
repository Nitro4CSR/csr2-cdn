"""Offline, evidence-separated diagnostics for unmatched crew vehicle cosmetics.

No network, filesystem writes, player identity, raw server responses, display
names or model identifiers. `show_unmatched_ids` is an explicit opt-in for
bounded numeric code frequency *without member association*. Wheel strings are
never printed or saved. Standalone color and Tuner Stars rim records are only
candidate *overlaps*, not verified roster-field joins.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .crew_optional_data import CrewOptionalSnapshot
from .customization_evidence import SLOT_FIELDS
from .game_labels import GameVisualLibrary

JOIN_UNVERIFIED = frozenset((
    "wheel", "decal_number_color", "decal_number_shape_color", "decal_number_zone",
))
MAX_CREW_MEMBERS = 30


@dataclass(frozen=True)
class VisualGapSlot:
    """Coverage for one observed appearance field; absence is not a mismatch."""
    present: int = 0
    resolved: int = 0
    unresolved: int = 0
    join_unverified: int = 0
    library_id_missing: int = 0
    palette_id_overlap: int = 0
    tuner_rim_name_overlap: int = 0
    unresolved_numeric_ids: tuple[tuple[int, int], ...] = field(default_factory=tuple, repr=False)

    def as_dict(self, *, include_ids: bool = False) -> dict[str, Any]:
        out = {
            "present": self.present,
            "resolved": self.resolved,
            "unresolved": self.unresolved,
            "join_unverified": self.join_unverified,
            "library_id_missing": self.library_id_missing,
            "palette_id_overlap_candidate_only": self.palette_id_overlap,
            "tuner_rim_name_overlap_candidate_only": self.tuner_rim_name_overlap,
        }
        if include_ids:
            out["unresolved_numeric_ids"] = [
                {"id": code, "occurrences": count}
                for code, count in self.unresolved_numeric_ids
            ]
        return out


@dataclass(frozen=True)
class VisualGapDiagnostics:
    """Attribute-first offline cosmetic gap analysis (e.g. ``report.paint``)."""
    slots: Mapping[str, VisualGapSlot] = field(repr=False)
    unmatched_ids_opted_in: bool = False

    def __getattr__(self, name: str) -> VisualGapSlot:
        if name in SLOT_FIELDS:
            return self.slots[name]
        raise AttributeError(name)

    @property
    def unresolved_total(self) -> int:
        return sum(slot.unresolved for slot in self.slots.values())

    @property
    def present_total(self) -> int:
        return sum(slot.present for slot in self.slots.values())

    @property
    def resolved_total(self) -> int:
        return sum(slot.resolved for slot in self.slots.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "offline_visual_gap_diagnostics_candidate_only",
            "present": self.present_total,
            "resolved": self.resolved_total,
            "unresolved": self.unresolved_total,
            "unverified_join_slots": sorted(JOIN_UNVERIFIED),
            "palette_overlap_is_not_join_proof": True,
            "tuner_rim_overlap_is_not_join_proof": True,
            "numeric_id_disclosure_opt_in": self.unmatched_ids_opted_in,
            "member_names_or_ids_included": False,
            "network_requests": 0,
            "slots": {name: item.as_dict(include_ids=self.unmatched_ids_opted_in)
                      for name, item in self.slots.items()},
        }


def analyze_visual_gaps(snapshot: CrewOptionalSnapshot, library: GameVisualLibrary,
                        *, show_unmatched_ids: bool = False) -> VisualGapDiagnostics:
    """Evaluate exact supported joins; do not auto-bind speculative joins.

    A known supported cosmetic slot is unresolved when its (model, slot, ID)
    cannot be found in the supplied visual library. Wheel and three decal
    color/zone fields remain pending irrespective of coincidental catalog IDs.
    Their possible standalone palette/rim overlaps are counted separately.
    The optional numeric-ID listing contains no member or car associations;
    wheel strings are never disclosed.
    """
    if not isinstance(snapshot, CrewOptionalSnapshot) or not isinstance(library, GameVisualLibrary):
        raise TypeError("typed crew snapshot and visual library required")
    if type(show_unmatched_ids) is not bool:
        raise TypeError("show_unmatched_ids must be boolean")
    if len(snapshot.members) > MAX_CREW_MEMBERS:
        raise ValueError("crew roster exceeds maximum member count")

    slots: dict[str, VisualGapSlot] = {}
    tuner_rim_names = {r.name for r in library.records if r.slot == "tuner_rim"}
    for slot, field_name in SLOT_FIELDS.items():
        present = resolved = pending = missing = palette = rims = 0
        unmatched: Counter[int] = Counter()
        for member in snapshot.members:
            appearance = member.vehicle.appearance
            code = getattr(appearance, field_name) if appearance is not None else None
            if code is None:
                continue
            present += 1
            if slot in JOIN_UNVERIFIED:
                pending += 1
                if slot == "wheel":
                    # This is an equality coincidence, NOT a universal rim join.
                    rims += int(type(code) is str and code in tuner_rim_names)
                elif type(code) is int:
                    palette += int(library.match(None, "color", code) is not None)
                # No pending field is treated as a verified match.
            elif library.match(member.vehicle.model_key, slot, code) is not None:
                resolved += 1
            else:
                missing += 1
            if show_unmatched_ids and (slot in JOIN_UNVERIFIED or
                                       library.match(member.vehicle.model_key, slot, code) is None):
                if type(code) is int:  # raw wheel strings intentionally never exported
                    unmatched[code] += 1
        slots[slot] = VisualGapSlot(
            present=present, resolved=resolved,
            unresolved=present - resolved, join_unverified=pending,
            library_id_missing=missing, palette_id_overlap=palette,
            tuner_rim_name_overlap=rims,
            unresolved_numeric_ids=tuple(sorted(unmatched.items())),
        )
    return VisualGapDiagnostics(slots, show_unmatched_ids)
