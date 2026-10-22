"""Dev42: offline-only customization metadata *schema-shape* research.

The seven named APK blocks are binary NMG metadata; local MetadataCache
blocks use JSON. Neither a key that looks like ``PaintID`` nor an APK checksum
proves that a roster wire field joins a native cosmetic source. No network,
credentials, player data, semantic field decoding, or mapping promotions.

Normal reports disclose no JSON keys or values. An independently requested
private key-path export is optional, exclusive-create, and permission-restricted.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping, Optional

from ..customization_evidence import CUSTOMIZATION_BLOCKS, inspect_customization_apk

MAX_BLOCK_BYTES = 8 * 1024 * 1024
MAX_JSON_NODES = 50000
MAX_JSON_DEPTH = 9
MAX_OBJECT_KEYS = 512
MAX_ARRAY_SAMPLES = 16
MAX_PATHS = 120
MAX_REPORT_BYTES = 256 * 1024

# These are lexical labels for *field names*, never decoded meanings.
FAMILIES = (
    ("paint", ("paint",)),
    ("interior", ("interior",)),
    ("calliper", ("calliper", "caliper")),
    ("wheel", ("wheel", "rim")),
    ("livery", ("livery", "liveries")),
    ("color", ("color", "colour")),
    ("customization", ("custom", "aftermarket", "hypermod")),
    ("preset", ("preset",)),
    ("vehicle_reference", ("car", "vehicle", "model")),
    ("generic_identifier", ("id", "identifier", "key")),
)


def _family(name: str) -> str:
    norm = re.sub(r"[^a-z0-9]", "", name.casefold())
    for label, tokens in FAMILIES:
        if any(token in norm for token in tokens):
            return label
    return "other"


def _type(value: Any) -> str:
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "number"
    if type(value) is str:
        return "string"
    return "other"


def analyze_json_shape(document: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bounded deterministic *sampled* structure analysis. No source values leak.

    Only the first MAX_ARRAY_SAMPLES elements of each array are descended into.
    These are observed syntax counts, not exhaustive record statistics.
    """
    families: Counter[str] = Counter()
    types: Counter[str] = Counter()
    possible_paths: dict[str, str] = {}
    array_count = 0
    truncated_array_count = 0
    nodes = 0
    stack = [(document, "$", 0)]
    while stack:
        value, path, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise ValueError("metadata JSON traversal exceeds node budget")
        kind = _type(value)
        types[kind] += 1
        if depth >= MAX_JSON_DEPTH:
            if isinstance(value, (Mapping, list)):
                raise ValueError("metadata JSON exceeds allowed nesting depth")
            continue
        if isinstance(value, Mapping):
            if len(value) > MAX_OBJECT_KEYS:
                raise ValueError("metadata JSON object exceeds key budget")
            if any(type(k) is not str or len(k) > 100 or any(ord(c) < 32 for c in k)
                   for k in value):
                raise ValueError("invalid or unsafe JSON metadata key")
            for key in sorted(value, reverse=True):
                child_path = path + "." + key
                families[_family(key)] += 1
                if len(possible_paths) < MAX_PATHS:
                    possible_paths.setdefault(child_path, _type(value[key]))
                stack.append((value[key], child_path, depth + 1))
        elif isinstance(value, list):
            array_count += 1
            if len(value) > MAX_ARRAY_SAMPLES:
                truncated_array_count += 1
            for child in reversed(value[:MAX_ARRAY_SAMPLES]):
                stack.append((child, path + "[]", depth + 1))
    redacted = {
        "status": "sampled_json_key_shape_not_native_join",
        "value_contents_exported": False,
        "schema_or_roster_join_verified": False,
        "observed_nodes_in_sample": nodes,
        "observed_types": dict(sorted(types.items())),
        "observed_key_family_occurrences_in_sample": dict(sorted(families.items())),
        "arrays_encountered": array_count,
        "arrays_partially_sampled": truncated_array_count,
        "max_array_elements_sampled_per_array": MAX_ARRAY_SAMPLES,
        "key_names_in_report": False,
    }
    private = {"key_paths_sampled": [
        {"path": k, "value_type": v} for k, v in sorted(possible_paths.items())
    ], "path_limit": MAX_PATHS, "path_limit_reached": len(possible_paths) >= MAX_PATHS,
       "values_included": False, "schema_or_roster_join_verified": False}
    return redacted, private


def _regular_file(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("metadata path must be a local regular file, not a symlink")
    st = path.stat()
    if st.st_size <= 0 or st.st_size > maximum or not stat.S_ISREG(st.st_mode):
        raise ValueError("metadata source is empty or oversized")
    data = path.read_bytes()
    if len(data) != st.st_size:
        raise ValueError("metadata file changed during read")
    return data


def examine_cache(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read allowlisted existing .meta files only; never sync a MetadataCache."""
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("metadata cache must be a local directory")
    redacted: dict[str, Any] = {}
    private: dict[str, Any] = {}
    for name in CUSTOMIZATION_BLOCKS:
        path = directory / (name + ".meta")
        if not path.exists() and not path.is_symlink():
            redacted[name] = {"present": False, "schema_or_roster_join_verified": False}
            continue
        raw = _regular_file(path, MAX_BLOCK_BYTES)
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("metadata cache block is not valid JSON: " + name) from None
        if isinstance(data, Mapping) and name in data:
            data = data[name]
        profile, paths = analyze_json_shape(data)
        redacted[name] = {"present": True, "format": "local_metadata_cache_json",
                          "byte_count": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                          "profile": profile, "schema_or_roster_join_verified": False}
        private[name] = paths
    return redacted, private


def _write_new(path: Path, obj: Any) -> None:
    """Never overwrite (including symlinks), and avoid broad POSIX permissions."""
    if not path.parent.is_dir() or path.parent.is_symlink() or path.exists() or path.is_symlink():
        raise ValueError("output must be a new file in an existing directory")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(obj, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _provenance(path: Path) -> dict[str, Any]:
    raw = _regular_file(path, MAX_REPORT_BYTES)
    try:
        obj = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("invalid existing provenance report") from None
    if not isinstance(obj, dict) or obj.get("status") != "dev41_field_to_source_provenance_research":
        raise ValueError("expected a Dev41 field provenance report")
    blocks = obj.get("unparsed_customization_metadata_blocks")
    fields = obj.get("wire_fields")
    if blocks != list(CUSTOMIZATION_BLOCKS) or not isinstance(fields, list) or len(fields) != 14:
        raise ValueError("Dev41 provenance fields or blocks differ from expected baseline")
    names = [v.get("wire_field") for v in fields if isinstance(v, dict)]
    if len(names) != 14 or len(set(names)) != 14 or any(type(n) is not str for n in names):
        raise ValueError("malformed Dev41 provenance fields")
    if any(v.get("same_namespace_demonstrated") is not False for v in fields):
        raise ValueError("Dev41 provenance unexpectedly claims verified field join")
    return {"provenance_sha256": hashlib.sha256(raw).hexdigest(),
            "source_database_version_from_provenance": obj.get("source_database_version"),
            "roster_wire_fields_from_provenance": names,
            "explicit_native_field_joins_found_in_baseline": False}


def make_audit(*, cache_dir: Optional[Path] = None, apk: Optional[Path] = None,
               provenance_report: Optional[Path] = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """No network; independently reports what is and is not inspectable."""
    cached, private = examine_cache(cache_dir) if cache_dir is not None else ({
        k: {"present": False, "schema_or_roster_join_verified": False} for k in CUSTOMIZATION_BLOCKS
    }, {})
    apk_result = inspect_customization_apk(apk) if apk is not None else None
    report = {
        "status": "dev42_customization_schema_shape_research",
        "apk_binary_inventory": apk_result,
        "metadata_cache_blocks": cached,
        "field_provenance_baseline": _provenance(provenance_report) if provenance_report is not None else None,
        "metadata_cache_json_is_not_apk_binary_schema": True,
        "key_name_similarities_are_not_numeric_id_joins": True,
        "native_field_schema_decoded": False,
        "roster_to_native_field_join_verified": False,
        "trusted_mappings_changed": False,
        "network_requests": 0,
        "gameplay_read_count": 0,
        "key_names_or_values_exported": False,
    }
    private_doc = {"status": "dev42_opt_in_private_key_paths_not_verified_schema",
                   "contains_key_paths_not_values": True,
                   "native_field_schema_decoded": False,
                   "metadata_cache_blocks": private}
    return report, private_doc


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Dev42 offline JSON/APK customization schema-shape audit (never syncs)")
    p.add_argument("--metadata-cache-dir", type=Path, help="optional previously saved local .meta JSON cache")
    p.add_argument("--apk", type=Path, help="optional locally saved APK for opaque NMG fingerprint inventory")
    p.add_argument("--provenance-report", type=Path, help="optional Dev41 aggregate provenance report")
    p.add_argument("--output", type=Path, required=True, help="new redacted JSON report")
    p.add_argument("--private-key-paths-output", type=Path, help="separate opt-in PRIVATE JSON key-path export")
    args = p.parse_args(argv)
    if args.private_key_paths_output and not args.metadata_cache_dir:
        p.error("private key paths require a local metadata cache")
    if args.private_key_paths_output and args.private_key_paths_output == args.output:
        p.error("private output must be separate")
    try:
        # Validate all outputs before calculating, avoid partial output on bad input.
        for path in (args.output, args.private_key_paths_output):
            if path and (not path.parent.is_dir() or path.parent.is_symlink() or path.exists() or path.is_symlink()):
                raise ValueError("output file already exists or parent directory is invalid")
        report, private = make_audit(cache_dir=args.metadata_cache_dir, apk=args.apk,
                                     provenance_report=args.provenance_report)
        if args.private_key_paths_output:
            _write_new(args.private_key_paths_output, private)
        _write_new(args.output, report)
    except (ValueError, OSError) as exc:
        p.error(str(exc))
    print("Dev42: offline schema-shape report written; no verified roster/native joins, zero requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
