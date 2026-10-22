"""Privacy-safe, deterministic review of a single 0.7.1 crew feature batch.

This is a *decision aid*, not automatic acceptance, server pagination proof, or
validation of native field semantics. It consumes only the already-redacted
bulk report; it never makes requests or saves raw server data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

_REFERENCE_FORMAT = "csr2cdn.crew-bulk-ui-reference.v1"
_MAX_I64 = 2**63 - 1


@dataclass(frozen=True)
class BulkUIReference:
    """Optional operator-observed UI values; never independently authenticated.

    Values should be taken as close as possible to the read; rank and score may
    change in the meantime. No names, player identifiers, or private texts are
    accepted or repeated in the review output.
    """

    own_crew_rank: Optional[int] = None
    own_crew_score: Optional[int] = None
    crew_member_count: Optional[int] = None

    @classmethod
    def from_mapping(cls, value: Any) -> "BulkUIReference":
        if not isinstance(value, Mapping) or value.get("format") != _REFERENCE_FORMAT:
            raise ValueError("unrecognized UI reference format")
        permitted = {"format", "own_crew_rank", "own_crew_score", "crew_member_count"}
        if set(value) - permitted:
            raise ValueError("UI reference contains unexpected fields")
        parsed = []
        for key, minimum, maximum in (("own_crew_rank", 1, _MAX_I64),
                                      ("own_crew_score", 0, _MAX_I64),
                                      ("crew_member_count", 0, 30)):
            field = value.get(key)
            if field is not None and (type(field) is not int or not minimum <= field <= maximum):
                raise ValueError("UI reference contains invalid numeric field")
            parsed.append(field)
        if all(v is None for v in parsed):
            raise ValueError("UI reference must contain at least one value")
        return cls(*parsed)


def _coverage(values: Any) -> dict[str, int]:
    """Return coverage counts only, never raw labels or source values."""
    if not isinstance(values, Mapping):
        return {"fields_with_rows": 0, "field_count": 0}
    return {"fields_with_rows": sum(type(v) is int and v > 0 for v in values.values()),
            "field_count": len(values)}


def _reference_agreement(observed: Any, reference: Optional[int]) -> str:
    if reference is None:
        return "not_supplied"
    if type(observed) is not int:
        return "not_observed"
    return "agrees" if observed == reference else "differs_review_snapshot_timing"


def review_bulk_evidence(report: Mapping[str, Any], *,
                         ui_reference: Optional[BulkUIReference] = None) -> dict[str, Any]:
    """Summarize offline coverage and next decisions, retaining uncertainty.

    This function is suitable for fixtures, explicitly authorized live reads,
    and partial results. It cannot promote a candidate into a validated
    feature, and it does not infer that expanded GCC ranges were honored.
    """
    optional = report.get("optional", {})
    gcc = report.get("gcc", {})
    labels = report.get("game_labels", {})
    common = gcc.get("common", {})
    experimental = gcc.get("experimental", {})
    overlap = gcc.get("common_vs_experimental", {})
    range_evidence = gcc.get("range_evidence", {})
    members = optional.get("member_rows", 0)
    roster_ok = (type(members) is int and members > 0 and
                 optional.get("distinct_member_identities") is True and
                 optional.get("roster_count_matches_own_crew") is True)
    common_ok = (common.get("status") == "decoded_common_gcc" and
                 common.get("own_crew_exact_id_matches") == 1)
    experimental_ok = (experimental.get("status") ==
                       "decoded_exploratory_gcc_range_unverified" and
                       experimental.get("own_crew_exact_id_matches") == 1)
    comparison = ("consistent_candidate" if common_ok and
                  common.get("roster_gcc_comparable") is True and
                  common.get("roster_gcc_delta") == 0 else
                  "non_atomic_mismatch" if common_ok and
                  common.get("roster_gcc_comparable") is True and
                  common.get("roster_gcc_delta") is not None else
                  "not_comparable")
    if not experimental_ok:
        expanded = "investigate_or_retry"
    elif not common_ok or not isinstance(overlap, Mapping):
        expanded = "decoded_no_common_comparison"
    elif overlap.get("changed_rank_or_score", 0) != 0:
        expanded = "shared_rows_changed_non_atomic"
    elif range_evidence.get("more_rows_than_common") is True:
        expanded = "more_rows_observed_not_pagination_proof"
    else:
        expanded = "no_extra_rows_observed"
    crew_fields = optional.get("crew_field_presence", {})
    crew_present = sum(v is True for v in crew_fields.values()) if isinstance(crew_fields, Mapping) else 0
    stats_coverage = _coverage(optional.get("member_stat_coverage"))
    vehicle_coverage = _coverage(optional.get("vehicle_field_coverage"))
    appearance_coverage = _coverage(optional.get("vehicle_appearance_coverage"))
    translated = labels.get("car_names_resolved", 0)
    name_coverage = ("not_supplied" if "game_labels" not in report or
                     labels.get("translation_records", 0) == 0 else
                     "resolved_on_roster" if type(translated) is int and translated > 0 else
                     "no_exact_matches")
    source_codes = labels.get("visual_codes_present") or {}
    resolved_codes = labels.get("visual_codes_resolved") or {}
    present_visuals = sum(v for v in source_codes.values() if type(v) is int)
    resolved_visuals = sum(v for v in resolved_codes.values() if type(v) is int)
    visuals_coverage = ("not_supplied" if "game_labels" not in report or
                        labels.get("visual_library_records", 0) == 0 else
                        "no_codes_in_roster" if present_visuals == 0 else
                        "exact_matches_present" if resolved_visuals > 0 else
                        "no_exact_matches")
    reference = ui_reference
    reference_checks = {
        "rank": _reference_agreement(common.get("own_crew_rank"),
                                     reference.own_crew_rank if reference else None),
        "score": _reference_agreement(common.get("own_crew_score"),
                                      reference.own_crew_score if reference else None),
        "member_count": _reference_agreement(members,
                                             reference.crew_member_count if reference else None),
    }
    return {
        "status": "operator_review_required",
        "automatic_feature_acceptance": False,
        "ui_reference_supplied": reference is not None,
        "ui_reference_provenance": "operator_supplied_not_independently_verified",
        "ui_reference_temporal_comparability_verified": False,
        "ui_comparison": reference_checks,
        "features": {
            "roster": {"status": "complete_against_server_count" if roster_ok else "check_coverage",
                       "rows": members if type(members) is int else 0},
            "crew_rp_vs_gcc": {"status": comparison,
                               "ui_acceptance_from_this_report": False},
            "gcc_expanded_range": {"status": expanded,
                                   "full_pagination_verified": False,
                                   "requested_range_honored_verified": False,
                                   "common_rows": common.get("rows") if common_ok else None,
                                   "experimental_rows": experimental.get("rows") if experimental_ok else None,
                                   "shared_rows": overlap.get("shared_crew_ids") if isinstance(overlap, Mapping) else None,
                                   "matching_shared_rows": overlap.get("matching_rank_and_score") if isinstance(overlap, Mapping) else None},
            "crew_stats": {"status": "candidate_fields_present" if crew_present else "no_fields_observed",
                           "fields_present": crew_present},
            "member_stats": {"status": "candidate_fields_present" if stats_coverage["fields_with_rows"] else "no_fields_observed",
                             **stats_coverage},
            "vehicle_details": {"status": "candidate_fields_present" if vehicle_coverage["fields_with_rows"] else "no_fields_observed",
                                **vehicle_coverage},
            "vehicle_appearance": {"status": "candidate_fields_present" if appearance_coverage["fields_with_rows"] else "no_fields_observed",
                                   **appearance_coverage},
            "translated_car_names": {"status": name_coverage,
                                     "roster_rows_with_name": translated if type(translated) is int else 0},
            "visual_names": {"status": visuals_coverage,
                             "codes_present": present_visuals,
                             "codes_named": resolved_visuals},
        },
        "next_review_actions": [
            "Compare operator UI against near-contemporaneous common GCC and roster fields",
            "Inspect experimental GCC row growth and ID-based overlap; never infer arbitrary offset pagination",
            "Confirm optional stat units and vehicle field meanings before promoting public guarantees",
            "Investigate unmatched raw visual codes and never guess wheel or color joins",
            "Keep, fix, or prune candidates only after evidence and operator review",
        ],
        "gameplay_requests_for_review": 0,
        "raw_identifiers_included": False,
    }
