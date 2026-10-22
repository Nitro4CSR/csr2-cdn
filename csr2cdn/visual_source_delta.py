"""Offline, privacy-safe source drift and unresolved-ID recheck tools.

Compares official visual library versions by exact (model, slot, code), not
approximate labels. No guessed wheel/palette joins and no gameplay/CDN I/O.
Optional historic unmatched numeric IDs can be rechecked without exposing
those IDs or any player data in the output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .customization_evidence import SLOT_FIELDS
from .game_labels import GameVisualLibrary, VisualCodeName
from .visual_gap_diagnostics import JOIN_UNVERIFIED

_MAX_RECORDS = 50000
_MAX_GAP_IDS_PER_SLOT = 256
_SUPPORTED_SLOTS = frozenset(SLOT_FIELDS).difference(JOIN_UNVERIFIED)
_KNOWN_SLOTS = frozenset(SLOT_FIELDS) | {"color", "wrap", "livery_set", "tuner_rim"}


@dataclass(frozen=True)
class VisualSourceDeltaSlot:
    """Per-slot exact key comparison, never raw ID or label disclosure."""
    before: int = 0
    after: int = 0
    added: int = 0
    removed: int = 0
    label_changed: int = 0
    zone_names_changed: int = 0
    unchanged: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(before=self.before, after=self.after, added=self.added,
                    removed=self.removed, label_changed=self.label_changed,
                    zone_names_changed=self.zone_names_changed, unchanged=self.unchanged)


@dataclass(frozen=True)
class VisualSourceDelta:
    """Attribute-first comparison of two decoded offline source library sets."""
    slots: Mapping[str, VisualSourceDeltaSlot] = field(repr=False)

    def __getattr__(self, name: str) -> VisualSourceDeltaSlot:
        if name in self.slots:
            return self.slots[name]
        raise AttributeError(name)

    @property
    def added_total(self) -> int:
        return sum(s.added for s in self.slots.values())

    @property
    def removed_total(self) -> int:
        return sum(s.removed for s in self.slots.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "offline_visual_source_version_comparison",
            "network_requests": 0,
            "join_evidence_added": False,
            "unverified_join_slots": sorted(JOIN_UNVERIFIED),
            "no_ui_equivalence_claim": True,
            "added_total": self.added_total,
            "removed_total": self.removed_total,
            "slots": {k: v.as_dict() for k, v in sorted(self.slots.items())},
        }


def _index(library: GameVisualLibrary) -> dict[tuple[str, str, int | str], VisualCodeName]:
    if not isinstance(library, GameVisualLibrary):
        raise TypeError("expected decoded GameVisualLibrary")
    if len(library.records) > _MAX_RECORDS:
        raise ValueError("too many visual library records")
    result: dict[tuple[str, str, int | str], VisualCodeName] = {}
    for record in library.records:
        if not isinstance(record, VisualCodeName):
            raise ValueError("invalid visual record type")
        if (type(record.model_key) is not str or not record.model_key or
            type(record.slot) is not str or record.slot not in _KNOWN_SLOTS or
            type(record.code) not in (str, int) or
            type(record.name) is not str or not record.name or
            type(record.names) is not tuple or
            any(type(v) is not str for v in record.names)):
            raise ValueError("invalid visual record fields")
        key = (record.model_key, record.slot, record.code)
        if key in result:
            raise ValueError("ambiguous duplicate visual record")
        result[key] = record
    return result


def compare_visual_sources(before: GameVisualLibrary, after: GameVisualLibrary) -> VisualSourceDelta:
    """Compare official library versions. A changed label is not proof of UI drift.

    Changing only library hashes or record ordering does not count as a
    content change. Interior zone names are compared separately from the
    primary label (which corresponds to zone one).
    """
    old, new = _index(before), _index(after)
    by_slot: dict[str, VisualSourceDeltaSlot] = {}
    slots = sorted({k[1] for k in old} | {k[1] for k in new})
    for slot in slots:
        old_keys = {k for k in old if k[1] == slot}
        new_keys = {k for k in new if k[1] == slot}
        shared = old_keys & new_keys
        labels_changed = sum(old[k].name != new[k].name for k in shared)
        zones_changed = sum(old[k].names != new[k].names for k in shared)
        unchanged = sum((old[k].name, old[k].names) == (new[k].name, new[k].names)
                        for k in shared)
        by_slot[slot] = VisualSourceDeltaSlot(len(old_keys), len(new_keys),
            len(new_keys - old_keys), len(old_keys - new_keys),
            labels_changed, zones_changed, unchanged)
    return VisualSourceDelta(by_slot)


@dataclass(frozen=True)
class VisualMissingIDSlot:
    """Counts for previously unmatched *global-library* numeric IDs only."""
    distinct_ids: int = 0
    occurrences: int = 0
    newly_available_ids: int = 0
    newly_available_occurrences: int = 0
    still_missing_ids: int = 0
    still_missing_occurrences: int = 0
    already_available_ids: int = 0

    def as_dict(self) -> dict[str, int]:
        return vars(self).copy()


@dataclass(frozen=True)
class VisualMissingIDRecheck:
    slots: Mapping[str, VisualMissingIDSlot] = field(repr=False)

    def __getattr__(self, name: str) -> VisualMissingIDSlot:
        if name in _SUPPORTED_SLOTS:
            return self.slots.get(name, VisualMissingIDSlot())
        raise AttributeError(name)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "offline_numeric_id_recheck_global_sources_only",
            "network_requests": 0,
            "no_live_snapshot_taken": True,
            "new_source_matches_are_candidates_not_ui_verification": True,
            "model_specific_joins_not_checked": True,
            "unverified_join_slots_excluded": sorted(JOIN_UNVERIFIED),
            "slots": {k: v.as_dict() for k, v in sorted(self.slots.items())},
        }


def _read_gap_rows(report: Mapping[str, Any]) -> dict[str, list[tuple[int, int]]]:
    """Read only the opt-in diagnostic schema, never player/model data."""
    if not isinstance(report, Mapping):
        raise ValueError("expected sanitised visual diagnostics mapping")
    # Allow the saved full bulk report, but select only its established section.
    data = report.get("visual_gap_diagnostics", report)
    if (not isinstance(data, Mapping) or
        data.get("status") != "offline_visual_gap_diagnostics_candidate_only" or
        data.get("numeric_id_disclosure_opt_in") is not True or
        data.get("member_names_or_ids_included") is not False):
        raise ValueError("explicit opt-in numeric diagnostics are required")
    slots = data.get("slots")
    if not isinstance(slots, Mapping):
        raise ValueError("missing diagnostics slots")
    parsed = {}
    for slot, body in slots.items():
        if slot in JOIN_UNVERIFIED:
            # These IDs cannot be mapped even with matching standalone palette IDs.
            continue
        if slot not in _SUPPORTED_SLOTS or not isinstance(body, Mapping):
            raise ValueError("unexpected visual diagnostics slot")
        entries = body.get("unresolved_numeric_ids")
        if (not isinstance(entries, list) or len(entries) > _MAX_GAP_IDS_PER_SLOT):
            raise ValueError("missing or oversized unmatched ID list")
        observed = set()
        result = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ValueError("invalid unmatched ID row")
            ident, count = entry.get("id"), entry.get("occurrences")
            if (type(ident) is not int or not 0 <= ident < 2**31 or
                type(count) is not int or not 1 <= count <= 30 or
                ident in observed):
                raise ValueError("invalid or duplicate unmatched ID")
            observed.add(ident)
            result.append((ident, count))
        parsed[slot] = result
    return parsed


def recheck_visual_missing_ids(report: Mapping[str, Any], before: GameVisualLibrary,
                               after: GameVisualLibrary) -> VisualMissingIDRecheck:
    """Assess an opt-in past numeric-ID report against two local library versions.

    Supports only exact **global** library mappings for already-supported roster
    slots. An ID mapping in another model scope is ignored. No raw IDs, names,
    model keys, labels or player data enter the result.
    """
    old, new = _index(before), _index(after)
    rows = _read_gap_rows(report)
    result = {}
    for slot, ids in rows.items():
        before_available = lambda v: ('*', slot, v) in old
        after_available = lambda v: ('*', slot, v) in new
        newly = [(v, n) for v, n in ids if not before_available(v) and after_available(v)]
        missing = [(v, n) for v, n in ids if not after_available(v)]
        present = [(v, n) for v, n in ids if before_available(v)]
        result[slot] = VisualMissingIDSlot(len(ids), sum(n for _, n in ids),
            len(newly), sum(n for _, n in newly),
            len(missing), sum(n for _, n in missing), len(present))
    return VisualMissingIDRecheck(result)


def main(argv: Optional[list[str]] = None) -> int:
    """Compare two local asset-library generations; NEVER access the network."""
    import argparse
    import json
    from pathlib import Path

    from .visual_library_bundle import load_visual_libraries_unityfs

    parser = argparse.ArgumentParser(description="Compare two offline decoded ASTC visual asset sets")
    parser.add_argument("--before-bundle", action="append", default=[], metavar="PATH",
                        help="old ASTC bundle (repeat for multiple libraries)")
    parser.add_argument("--after-bundle", action="append", default=[], metavar="PATH",
                        help="new ASTC bundle (repeat for multiple libraries)")
    parser.add_argument("--unmatched-report", metavar="PATH",
                        help="opt-in numeric-ID diagnostic JSON from an earlier run")
    args = parser.parse_args(argv)
    if not args.before_bundle and not args.after_bundle and args.unmatched_report is None:
        print(json.dumps({"mode": "dry_run", "network_requests": 0,
                          "required": ["--before-bundle", "--after-bundle"],
                          "optional": ["--unmatched-report"],
                          "wheel_and_decal_color_joins_verified": False}))
        return 0
    if not args.before_bundle or not args.after_bundle or len(args.before_bundle) > 24 or len(args.after_bundle) > 24:
        parser.error("both source generations require 1–24 local ASTC bundles")
    try:
        before = load_visual_libraries_unityfs(args.before_bundle)
        after = load_visual_libraries_unityfs(args.after_bundle)
        output = compare_visual_sources(before, after).as_dict()
        if args.unmatched_report is not None:
            file = Path(args.unmatched_report)
            if not file.is_file() or file.stat().st_size > 1024 * 1024:
                raise ValueError("invalid offline gap report")
            report = json.loads(file.read_text(encoding="utf-8"))
            output["previously_missing_global_ids"] = recheck_visual_missing_ids(report, before, after).as_dict()
        print(json.dumps(output, sort_keys=True, indent=2))
        return 0
    except (ValueError, OSError, UnicodeError, TypeError, KeyError, json.JSONDecodeError):
        print(json.dumps({"status": "offline_source_compare_failed", "details": "suppressed",
                          "network_requests": 0}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
