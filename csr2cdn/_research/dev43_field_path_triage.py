"""Dev43: cautious lexical triage of LOCAL JSON metadata key paths.

Keys and value *types* are sampled by the Dev42 bounded reader.  No values,
network requests, native-NMG interpretation, semantic joins or mapping updates.
Only the explicitly requested private output contains exact metadata key paths.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from typing import Any, Optional

from ..customization_evidence import CUSTOMIZATION_BLOCKS
from .dev42_customization_schema_audit import (
    _provenance, _regular_file, _write_new, examine_cache, MAX_REPORT_BYTES,
)

# Roster names are from the independently documented Dev41 provenance report.
# These are syntax checks, NOT accepted foreign-key definitions.
EXPECTED_WIRE_TYPES = {
    "car_paint_id": "integer",
    "car_interior_id": "integer",
    "car_calliper_id": "integer",
    "car_livery_id": "integer",
    "car_liveryZonesSet_id": "integer",
    "car_wheel_name": "string",
    "car_decal_flag_id": "integer",
    "car_decal_number_id": "integer",
    "car_decal_numberplate_style_id": "integer",
    "car_decal_number_color_id": "integer",
    "car_decal_number_shape_color_id": "integer",
    "car_decal_number_zone_id": "integer",
    "car_decal_playername_state": "integer",
    "car_decal_crewname_state": "integer",
}

# Avoid substring false positives such as "repaint" for "paint"; preserve
# field specificity and count related keys only if explicit component token(s).
TOPIC_TOKENS = {
    "car_paint_id": ("paint",),
    "car_interior_id": ("interior",),
    "car_calliper_id": ("calliper", "caliper"),
    "car_livery_id": ("livery", "liveries"),
    "car_liveryZonesSet_id": ("livery", "liveries", "zone"),
    "car_wheel_name": ("wheel", "rim"),
    "car_decal_flag_id": ("decal", "flag"),
    "car_decal_number_id": ("decal", "number"),
    "car_decal_numberplate_style_id": ("numberplate", "plate", "style"),
    "car_decal_number_color_id": ("number", "color", "colour"),
    "car_decal_number_shape_color_id": ("shape", "color", "colour"),
    "car_decal_number_zone_id": ("zone", "number"),
    "car_decal_playername_state": ("playername", "player", "name"),
    "car_decal_crewname_state": ("crewname", "crew", "name"),
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.casefold())


def _tokens(s: str) -> set[str]:
    # Camel-case token boundaries before lowercasing; no substring joins.
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    return set(re.findall(r"[a-z0-9]+", spaced.casefold()))


def _degree(wire_field: str, path: str) -> Optional[str]:
    """Lexical compatibility grades, never source/roster ID correspondence."""
    if type(path) is not str or len(path) > 1024 or not path.startswith("$."):
        raise ValueError("malformed private sampled key path")
    leaf = path.rsplit(".", 1)[-1]
    if leaf.endswith("[]"):
        leaf = leaf[:-2]
    norm = _norm(leaf)
    wire = _norm(wire_field)
    if norm == wire:
        return "exact_wire_key_spelling"
    if wire.startswith("car") and norm == wire[3:]:
        return "without_car_prefix_spelling"
    terms = _tokens(leaf)
    if terms.intersection(TOPIC_TOKENS[wire_field]):
        return "related_key_token_only"
    return None


def analyze(*, provenance_report: Path, cache_dir: Optional[Path] = None
            ) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline = _provenance(provenance_report)
    if set(baseline["roster_wire_fields_from_provenance"]) != set(EXPECTED_WIRE_TYPES):
        raise ValueError("Dev41 roster field inventory is not the expected 14-field schema")
    # Verify the wire types too, since path type plausibility depends on them.
    data = json.loads(_regular_file(provenance_report, MAX_REPORT_BYTES))
    actual_types = {row["wire_field"]: row.get("wire_type") for row in data["wire_fields"]}
    if actual_types != EXPECTED_WIRE_TYPES:
        raise ValueError("Dev41 wire types differ from the expected baseline")

    if cache_dir is None:
        cached = {name: {"present": False} for name in CUSTOMIZATION_BLOCKS}
        paths: dict[str, Any] = {}
    else:
        cached, paths = examine_cache(cache_dir)
    summary: dict[str, Any] = {}
    private: dict[str, Any] = {}
    truncated_blocks = []
    for name in CUSTOMIZATION_BLOCKS:
        item = cached[name]
        if not item["present"]:
            continue
        if paths[name].get("path_limit_reached") or item["profile"]["arrays_partially_sampled"]:
            truncated_blocks.append(name)
        private[name] = {}

    for wire in baseline["roster_wire_fields_from_provenance"]:
        counts = Counter()
        type_compatible = Counter()
        match_blocks: set[str] = set()
        private_rows = []
        for block in CUSTOMIZATION_BLOCKS:
            if not cached[block]["present"]:
                continue
            for sampled in paths[block]["key_paths_sampled"]:
                degree = _degree(wire, sampled["path"])
                if degree is None:
                    continue
                value_type = sampled["value_type"]
                if value_type not in ("integer", "number", "boolean", "string", "null", "object", "array"):
                    raise ValueError("unexpected sampled value type")
                counts[degree] += 1
                if value_type == EXPECTED_WIRE_TYPES[wire]:
                    type_compatible[degree] += 1
                match_blocks.add(block)
                private_rows.append({
                    "block": block,
                    "key_path": sampled["path"],
                    "lexical_grade": degree,
                    "sampled_value_type": value_type,
                    "same_wire_value_type": value_type == EXPECTED_WIRE_TYPES[wire],
                    "join_verified": False,
                })
        summary[wire] = {
            "candidate_key_path_counts_by_lexical_grade": dict(sorted(counts.items())),
            "candidate_path_type_agreement_counts_by_lexical_grade": dict(sorted(type_compatible.items())),
            "candidate_source_blocks": sorted(match_blocks),
            "number_of_candidate_paths_in_sample": sum(counts.values()),
            "value_equality_tested": False,
            "foreign_key_relationship_verified": False,
            "source_namespace_verified": False,
        }
        private[wire] = sorted(private_rows, key=lambda e: (e["block"], e["key_path"]))

    report = {
        "status": "dev43_local_json_field_path_lexical_triage_not_native_join",
        "source_database_version_from_provenance": baseline["source_database_version_from_provenance"],
        "provenance_sha256": baseline["provenance_sha256"],
        "metadata_cache_present_blocks": [name for name in CUSTOMIZATION_BLOCKS if cached[name]["present"]],
        "metadata_cache_block_sha256": {name: cached[name]["sha256"] for name in CUSTOMIZATION_BLOCKS if cached[name]["present"]},
        "sampled_or_truncated_blocks": truncated_blocks,
        "analysis_incomplete_without_local_metadata": cache_dir is None or not any(v["present"] for v in cached.values()),
        "wire_field_candidates": summary,
        "key_paths_or_values_in_report": False,
        "lexical_grade_is_not_mapping_evidence": True,
        "json_cache_is_not_apk_native_nmg_schema": True,
        "verified_roster_to_source_joins": 0,
        "native_schema_decoded": False,
        "trusted_mappings_changed": False,
        "network_requests": 0,
        "gameplay_read_count": 0,
    }
    private_report = {
        "status": "dev43_opt_in_private_lexical_key_paths_only",
        "contains_original_key_paths": True,
        "contains_source_values": False,
        "key_names_may_be_sensitive": True,
        "join_verified": False,
        "candidate_paths_by_wire_field": private,
    }
    return report, private_report


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Dev43 offline-only metadata key-path / roster wire-field lexical triage")
    p.add_argument("--provenance-report", required=True, type=Path, help="existing Dev41 field-source provenance JSON")
    p.add_argument("--metadata-cache-dir", type=Path, help="optional preexisting local JSON .meta files; never synced")
    p.add_argument("--output", required=True, type=Path, help="new redacted report file")
    p.add_argument("--private-candidate-paths-output", type=Path, help="optional PRIVATE local report, no values")
    args = p.parse_args(argv)
    if args.private_candidate_paths_output == args.output:
        p.error("private candidate paths require a separate file")
    try:
        for path in (args.output, args.private_candidate_paths_output):
            if path and (not path.parent.is_dir() or path.parent.is_symlink() or path.exists() or path.is_symlink()):
                raise ValueError("output must be a new file in an existing normal directory")
        report, private = analyze(provenance_report=args.provenance_report, cache_dir=args.metadata_cache_dir)
        if args.private_candidate_paths_output:
            _write_new(args.private_candidate_paths_output, private)
        _write_new(args.output, report)
    except (ValueError, OSError) as exc:
        p.error(str(exc))
    print("Dev43: redacted local-source triage written; zero requests; no verified source joins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
