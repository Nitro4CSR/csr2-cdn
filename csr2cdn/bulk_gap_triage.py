"""Offline, counts-only triage of Dev17 sanitized 0.7.1 bulk reports.

This is not a second network probe, acceptance decision or cosmetics decoder.
No raw visual IDs, vehicle models, member names, crew IDs or source response
values are ever printed. The input may be a local full report; output uses a
strict allowlist of aggregate numeric counts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .customization_evidence import SLOT_FIELDS

_MAX_INPUT = 2 * 1024 * 1024
_MAX_CREW_MEMBERS = 30
_JOIN_PENDING = frozenset({"wheel", "decal_number_color", "decal_number_shape_color", "decal_number_zone"})


def _safe_count(value: Any, *, limit: int) -> int:
    if type(value) is not int or not 0 <= value <= limit:
        raise ValueError("invalid aggregate coverage count")
    return value


def triage_bulk_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return deterministic gap counts and provisional actions, without private data.

    Only the standardized Dev17 aggregate counts are read. This cannot
    recover unknown codes or prove a visual-ID join from sanitized evidence.
    """
    if not isinstance(report, Mapping):
        raise ValueError("bulk report must be an object")
    optional = report.get("optional")
    if not isinstance(optional, Mapping):
        raise ValueError("bulk report lacks optional section")
    roster = _safe_count(optional.get("member_rows"), limit=_MAX_CREW_MEMBERS)
    labels = report.get("game_labels")
    if not isinstance(labels, Mapping):
        raise ValueError("bulk report lacks game_labels section")
    present = labels.get("visual_codes_present")
    resolved = labels.get("visual_codes_resolved")
    if not isinstance(present, Mapping) or not isinstance(resolved, Mapping):
        raise ValueError("bulk report lacks per-slot coverage")
    if set(present) != set(SLOT_FIELDS) or set(resolved) != set(SLOT_FIELDS):
        raise ValueError("unrecognized visual coverage slots")
    slots: list[dict[str, Any]] = []
    total_present = total_resolved = 0
    for slot in SLOT_FIELDS:
        n = _safe_count(present[slot], limit=roster)
        matches = _safe_count(resolved[slot], limit=n)
        missing = n - matches
        total_present += n
        total_resolved += matches
        category = ("unverified_roster_to_library_join" if slot in _JOIN_PENDING else
                    "source_id_or_catalog_coverage_gap")
        slots.append({
            "slot": slot,
            "present": n,
            "resolved": matches,
            "unresolved": missing,
            "state": ("not_present" if n == 0 else
                      "complete_in_observed_roster" if missing == 0 else
                      "investigate"),
            "investigation": category if missing else None,
        })
    slots.sort(key=lambda row: (-row["unresolved"], row["slot"]))
    missing = total_present - total_resolved
    join_missing = sum(row["unresolved"] for row in slots
                       if row["slot"] in _JOIN_PENDING)
    # The report may be partial (a failed common or experimental read), or
    # may contain only synthetic offline fixture counts. Do not promote
    # gameplay evidence on the strength of its cosmetics section.
    gcc = report.get("gcc")
    gcc = gcc if isinstance(gcc, Mapping) else {}
    common = gcc.get("common")
    expanded = gcc.get("experimental")
    overlap = gcc.get("common_vs_experimental")
    range_evidence = gcc.get("range_evidence")
    bounded_supported = (isinstance(common, Mapping) and
                         common.get("status") == "decoded_common_gcc" and
                         isinstance(expanded, Mapping) and
                         expanded.get("status") == "decoded_exploratory_gcc_range_unverified" and
                         isinstance(range_evidence, Mapping) and
                         range_evidence.get("more_rows_than_common") is True and
                         isinstance(overlap, Mapping) and
                         type(overlap.get("shared_crew_ids")) is int and
                         overlap.get("shared_crew_ids") > 0 and
                         overlap.get("shared_crew_ids") == overlap.get("matching_rank_and_score") and
                         overlap.get("changed_rank_or_score") == 0)
    crew_rp_supported = (isinstance(common, Mapping) and
                         common.get("status") == "decoded_common_gcc" and
                         common.get("roster_gcc_comparable") is True and
                         common.get("roster_gcc_delta") == 0)
    translation_coverage = labels.get("car_names_resolved")
    translations_complete = (roster > 0 and type(translation_coverage) is int
                             and translation_coverage == roster)
    return {
        "status": "offline_triage_operator_review_required",
        "source": "dev17_sanitized_bulk_counts",
        "network_requests": 0,
        "person_or_crew_identifiers_included": False,
        "raw_cosmetic_codes_included": False,
        "automatic_pruning": False,
        "game_ui_meanings_verified": False,
        "arbitrary_gcc_pagination_verified": False,
        "roster_rows": roster,
        "cosmetics": {
            "present": total_present,
            "resolved": total_resolved,
            "unresolved": missing,
            "coverage_percent": round(100 * total_resolved / total_present, 1)
            if total_present else None,
            "pending_join_investigation": join_missing,
            "other_source_mapping_gaps": missing - join_missing,
            "slots": slots,
        },
        "recommended_review": {
            "gcc": ("keep_bounded_expansion_candidate_verify_offset_separately"
                    if bounded_supported else "insufficient_gcc_evidence"),
            "crew_rp": ("retain_guarded_comparison" if crew_rp_supported
                          else "requires_comparable_gcc_read"),
            "car_names": ("retain_exact_translations" if translations_complete
                          else "check_translation_roster_coverage"),
            "optional_statistics": "hold_until_units_and_ui_semantics_confirmed",
            "cosmetics": "investigate_unresolved_slots_keep_raw_codes",
            "prune": "none_automatically",
        },
        "limitations": [
            "Only presence and exact-match coverage are known; these counts do not reveal missing IDs.",
            "Wheels and three decal-color slots require independent join evidence.",
            "Source coverage cannot establish in-game display accuracy or active asset freshness.",
            "One larger GCC window cannot establish arbitrary offset pagination.",
        ],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Dev17 bulk cosmetics/gap triage")
    parser.add_argument("report", nargs="?", help="existing sanitized Dev17 bulk JSON report")
    args = parser.parse_args(argv)
    if not args.report:
        print(json.dumps({"mode": "dry_run", "network_requests": 0,
                          "usage": "python -m csr2cdn.bulk_gap_triage bulk-live-report.json"}, indent=2))
        return 0
    try:
        path = Path(args.report)
        if not path.is_file() or path.stat().st_size > _MAX_INPUT:
            raise ValueError("report missing or too large")
        with path.open("r", encoding="utf-8") as f:
            result = triage_bulk_report(json.load(f))
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        # Never echo source paths or raw input, including possible account IDs.
        print(json.dumps({"status": "invalid_aggregate_report", "details": "suppressed",
                          "network_requests": 0}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
