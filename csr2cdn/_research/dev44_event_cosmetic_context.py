"""Dev44: offline, context-aware EVENT cosmetic source evidence.

This module reads ONLY six explicitly named public metadata blocks from an
existing cache, plus a separately exported public source-ID catalogue. It
never reads game/ members/crew paths, never performs network requests, and
never claims event AI field evidence establishes a player-roster join.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Optional
from zipfile import ZipFile

from .dev42_customization_schema_audit import _write_new

EVENT_BLOCKS = (
    "CareerRaceEvents", "DailyBattleEventCollection", "ECBRaceEvents",
    "ECBRaceEvents_2", "ECBRaceEvents_3", "IconsCampaign",
)
EVENT_SLOTS = {"AIPaintID": "paint", "AIInteriorID": "interior", "AICalliperID": "calliper"}
SENTINEL_CANDIDATE = 2147483647
MAX_METADATA_BYTES = 12_000_000
MAX_CATALOG_BYTES = 16_000_000
MAX_MANIFEST_BYTES = 4_000_000
MAX_JSON_DEPTH = 75


def _regular_read(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("source must be a bounded, regular file (not a symlink)")
    return path.read_bytes()


def _catalogue(path: Path) -> tuple[dict[str, set[int]], dict[str, Any]]:
    payload = _regular_read(path, MAX_CATALOG_BYTES)
    data = json.loads(payload)
    if not isinstance(data, dict) or not isinstance(data.get("individual_source_ids"), list):
        raise ValueError("expected Dev36 source-ID catalogue")
    result: dict[str, set[int]] = {slot: set() for slot in EVENT_SLOTS.values()}
    for item in data["individual_source_ids"]:
        if not isinstance(item, dict):
            raise ValueError("invalid source-ID row")
        slot, numeric = item.get("slot"), item.get("numeric_id")
        if slot not in result or type(numeric) is not int:
            raise ValueError("unsupported source-ID row")
        result[slot].add(numeric)
    return result, {
        "branch": data.get("branch"),
        "database_version": data.get("database_version"),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "individual_source_rows": len(data["individual_source_ids"]),
    }


class _MetadataReader:
    """Manifest-verified public metadata only; ignore all private cache entries."""
    def __init__(self, *, cache_zip: Optional[Path], cache_dir: Optional[Path]):
        if (cache_zip is None) == (cache_dir is None):
            raise ValueError("provide exactly one of --cache-zip and --cache-dir")
        self._zip = None
        self._root = cache_dir
        if cache_zip is not None:
            self._zip = ZipFile(_check_archive(cache_zip))
            names = self._zip.namelist()
            if len(names) != len(set(names)):
                raise ValueError("duplicate archive members")
            # Use exact archive members, not arbitrary user-controlled paths.
            self._prefix = "endpoint-cache/"
            manifest_info = self._zip.getinfo(self._prefix + "manifest.json")
            if (manifest_info.file_size > MAX_MANIFEST_BYTES
                    or ((manifest_info.external_attr >> 16) & 0o170000) == 0o120000):
                raise ValueError("unsafe cache ZIP manifest")
            manifest_bytes = self._zip.read(manifest_info)
        else:
            assert cache_dir is not None
            if cache_dir.is_symlink() or (cache_dir / "metadata").is_symlink():
                raise ValueError("cache directory cannot use symlinked root or metadata")
            manifest_bytes = _regular_read(cache_dir / "manifest.json", MAX_MANIFEST_BYTES)
        if len(manifest_bytes) > MAX_MANIFEST_BYTES:
            raise ValueError("cache manifest exceeds size limit")
        manifest = json.loads(manifest_bytes)
        if not isinstance(manifest, dict) or not isinstance(manifest.get("responses"), list):
            raise ValueError("invalid cache manifest")
        self._expected: dict[str, tuple[str, int]] = {}
        for row in manifest["responses"]:
            if not isinstance(row, dict):
                raise ValueError("invalid cache manifest response")
            f = row.get("file")
            if f in {f"metadata/{name}.meta" for name in EVENT_BLOCKS}:
                if f in self._expected or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256", ""))):
                    raise ValueError("duplicate or invalid metadata manifest entry")
                if type(row.get("bytes")) is not int or not 0 <= row["bytes"] <= MAX_METADATA_BYTES:
                    raise ValueError("invalid metadata manifest size")
                self._expected[f] = (row["sha256"], row["bytes"])

    def close(self) -> None:
        if self._zip:
            self._zip.close()

    def load(self, block: str) -> tuple[Any, str]:
        if block not in EVENT_BLOCKS:
            raise ValueError("unapproved metadata block")
        relative = f"metadata/{block}.meta"
        if relative not in self._expected:
            raise ValueError(f"missing cached metadata evidence for {block}")
        if self._zip:
            member = self._zip.getinfo(self._prefix + relative)
            if member.file_size > MAX_METADATA_BYTES or (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("unsafe metadata ZIP member")
            content = self._zip.read(member)
        else:
            assert self._root is not None
            content = _regular_read(self._root / relative, MAX_METADATA_BYTES)
        digest, size = self._expected[relative]
        if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError(f"cached metadata integrity mismatch: {block}")
        return json.loads(content), digest


def _check_archive(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError("cache ZIP must be a regular file")
    return path


def _wheel_shape(value: str) -> str:
    if not value.strip():
        return "blank"
    if re.fullmatch(r"[0-9]+", value):
        return "decimal_string"
    if re.fullmatch(r"[A-Za-z0-9_]+", value):
        return "ascii_underscore_or_alphanumeric"
    if re.fullmatch(r"[A-Za-z0-9-]+", value):
        return "ascii_hyphen_or_alphanumeric"
    return "other_string_syntax"


def _block_audit(root: Any, available: dict[str, set[int]]) -> dict[str, Any]:
    counters = {k: Counter() for k in EVENT_SLOTS}
    absent = {k: Counter() for k in EVENT_SLOTS}
    wheel = Counter()
    nonempty_wheels: set[str] = set()
    wheel_lengths = Counter()
    restrictions = Counter()
    event_rows = 0
    masks = Counter()

    def visit(node: Any, segments: tuple[str, ...], depth: int) -> None:
        nonlocal event_rows
        if depth > MAX_JSON_DEPTH:
            raise ValueError("metadata nesting exceeds safety limit")
        if isinstance(node, list):
            for item in node:
                visit(item, segments, depth + 1)
            return
        if not isinstance(node, dict):
            return
        # Field classifications depend on the enclosing source record.
        is_event = "Restrictions" not in segments
        is_restriction = "Restrictions" in segments
        if is_event and any(k in node for k in (*EVENT_SLOTS, "AIWheelType")):
            event_rows += 1
            mask = []
            for field, slot in EVENT_SLOTS.items():
                if field not in node:
                    counters[field]["missing"] += 1
                    continue
                value = node[field]
                if type(value) is not int:
                    counters[field]["non_integer"] += 1
                    continue
                counters[field]["observations"] += 1
                if value == SENTINEL_CANDIDATE:
                    counters[field]["max_int_candidate"] += 1
                if value == 0:
                    counters[field]["zero"] += 1
                if value == 15:
                    counters[field]["fifteen"] += 1
                if value in available[slot]:
                    counters[field]["source_match"] += 1
                    mask.append(field)
                else:
                    counters[field]["source_absent"] += 1
                    absent[field][str(value)] += 1
            masks["+".join(mask) if mask else "none"] += 1
            if "AIWheelType" in node:
                w = node["AIWheelType"]
                wheel["observations"] += 1
                if w is None or w == "":
                    wheel["empty_or_null"] += 1
                elif isinstance(w, str):
                    wheel["nonempty_string"] += 1
                    wheel[f"shape:{_wheel_shape(w)}"] += 1
                    nonempty_wheels.add(w)
                    wheel_lengths[str(min(64, (len(w) // 8) * 8))] += 1
                else:
                    wheel["non_string"] += 1
            else:
                wheel["missing"] += 1
        if is_restriction and "CarPaintID" in node:
            value = node["CarPaintID"]
            restrictions["observations"] += 1
            if type(value) is int:
                restrictions["integer"] += 1
                if value == 0:
                    restrictions["zero"] += 1
                if value == 15:
                    restrictions["fifteen"] += 1
            else:
                restrictions["non_integer"] += 1
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                visit(value, segments + (key,), depth + 1)

    visit(root, (), 0)
    return {
        "event_rows_with_cosmetic_keys": event_rows,
        "ai_fields": {
            name: {
                "observations": counters[name]["observations"],
                "source_match_occurrences": counters[name]["source_match"],
                "source_absent_occurrences": counters[name]["source_absent"],
                "max_int_sentinel_candidate_occurrences": counters[name]["max_int_candidate"],
                "zero_occurrences": counters[name]["zero"],
                "fifteen_occurrences": counters[name]["fifteen"],
                "missing_occurrences": counters[name]["missing"],
                "noninteger_occurrences": counters[name]["non_integer"],
                "absent_value_counts": {
                    str(SENTINEL_CANDIDATE): absent[name][str(SENTINEL_CANDIDATE)],
                    "other_unlisted": sum(n for key, n in absent[name].items() if key != str(SENTINEL_CANDIDATE)),
                },
            }
            for name in EVENT_SLOTS
        },
        "ai_source_match_field_combination_counts": dict(sorted(masks.items())),
        "ai_wheel_type": {
            "observations": wheel["observations"],
            "nonempty_strings": wheel["nonempty_string"],
            "distinct_nonempty_strings": len(nonempty_wheels),
            "empty_or_null": wheel["empty_or_null"],
            "nonstring": wheel["non_string"],
            "missing": wheel["missing"],
            "syntax_counts": {key[6:]: v for key, v in sorted(wheel.items()) if key.startswith("shape:")},
            "length_buckets_eight_chars_capped_64": dict(sorted(wheel_lengths.items(), key=lambda kv: int(kv[0]))),
            "wheel_string_to_rim_mapping_verified": False,
        },
        "restriction_fields": {
            "CarPaintID": {
                "observations": restrictions["observations"],
                "zero_occurrences": restrictions["zero"],
                "fifteen_occurrences": restrictions["fifteen"],
                "noninteger_occurrences": restrictions["non_integer"],
                "semantic_context": "race_restriction_not_selected_ai_or_roster_paint",
            },
        },
        "event_ai_fields_are_player_roster_fields": False,
    }


def analyze(*, cache_zip: Optional[Path] = None, cache_dir: Optional[Path] = None,
            source_catalog: Path, baseline_evidence: Optional[Path] = None) -> dict[str, Any]:
    available, cat = _catalogue(source_catalog)
    reader = _MetadataReader(cache_zip=cache_zip, cache_dir=cache_dir)
    try:
        blocks = {}
        for name in EVENT_BLOCKS:
            metadata, sha = reader.load(name)
            blocks[name] = {"metadata_sha256": sha, **_block_audit(metadata, available)}
    finally:
        reader.close()
    totals = {field: {key: sum(block["ai_fields"][field][key] for block in blocks.values())
                      for key in ("observations", "source_match_occurrences", "source_absent_occurrences",
                                  "max_int_sentinel_candidate_occurrences", "zero_occurrences",
                                  "fifteen_occurrences", "missing_occurrences", "noninteger_occurrences")}
              for field in EVENT_SLOTS}
    candidate_only = all(
        block["ai_fields"][field]["absent_value_counts"]["other_unlisted"] == 0
        for block in blocks.values() for field in EVENT_SLOTS
    )
    baseline = {"provided": False}
    if baseline_evidence is not None:
        base = json.loads(_regular_read(baseline_evidence, MAX_CATALOG_BYTES))
        if not isinstance(base, dict) or not isinstance(base.get("metadata_event_blocks_with_cosmetic_field_checks"), list):
            raise ValueError("invalid Dev44 reference evidence")
        comparison = {}
        if {b.get("block") for b in base["metadata_event_blocks_with_cosmetic_field_checks"]} != set(EVENT_BLOCKS) or len(base["metadata_event_blocks_with_cosmetic_field_checks"]) != len(EVENT_BLOCKS):
            raise ValueError("baseline must include the six exact event blocks")
        for b in base["metadata_event_blocks_with_cosmetic_field_checks"]:
            name = b.get("block")
            if name not in blocks:
                raise ValueError("unexpected baseline block")
            comparison[name] = {field: {
                "observations_equal": b[field]["observations"] == blocks[name]["ai_fields"][field]["observations"],
                "source_matches_equal": b[field]["source_match_occurrences"] == blocks[name]["ai_fields"][field]["source_match_occurrences"],
                "source_absences_equal": b[field]["source_absent_occurrences"] == blocks[name]["ai_fields"][field]["source_absent_occurrences"],
            } for field in EVENT_SLOTS}
        baseline = {"provided": True, "per_block_comparison": comparison,
                    "all_compared_fields_equal": all(all(all(v.values()) for v in fields.values()) for fields in comparison.values())}
    return {
        "status": "dev44_offline_event_ai_field_context_evidence",
        "source_catalogue": cat,
        "metadata_original_database_version": "not_established",
        "cross_version_join_verified": False,
        "source_library_id_membership_evidence_for_event_ai": True,
        "source_library_validity_for_player_roster_fields_verified": False,
        "sentinel_2147483647_semantics_verified": False,
        "observed_nonlibrary_ai_values_only_maxint": candidate_only,
        "paint_zero_transparent": "operator_approved_display_label_only_not_native_semantics",
        "paint_fifteen": "unresolved_in_player_roster_not_promoted",
        "source_field_contexts": {
            "ai": "event_race_record",
            "restriction_paint": "nested_RaceEvents_Restrictions_CarPaintID",
            "player_roster": "not_read_or_evaluated",
        },
        "blocks": blocks,
        "totals": totals,
        "baseline_evidence_comparison": baseline,
        "private_player_or_roster_content_opened": False,
        "raw_event_string_values_included": False,
        "mapping_promoted": False,
        "network_requests": 0,
        "gameplay_read_operations": 0,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Dev44 offline, context-aware AI cosmetic source audit")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--cache-zip", type=Path, help="original endpoint-cache.zip; only six public metadata members read")
    source.add_argument("--cache-dir", type=Path, help="existing endpoint-cache directory; only six public metadata files read")
    parser.add_argument("--source-catalog", required=True, type=Path, help="Dev36 public source-ID catalogue")
    parser.add_argument("--baseline-evidence", type=Path, help="optional Dev44 counts-only evidence report")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink() or args.output.parent.is_symlink() or not args.output.parent.is_dir():
            raise ValueError("output must be a new file in an existing regular directory")
        report = analyze(cache_zip=args.cache_zip, cache_dir=args.cache_dir,
                         source_catalog=args.source_catalog, baseline_evidence=args.baseline_evidence)
        _write_new(args.output, report)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print("Dev44 offline event cosmetic contexts audited; zero requests; no mappings promoted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
