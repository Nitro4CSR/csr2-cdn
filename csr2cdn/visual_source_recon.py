"""Offline schema reconnaissance of cached Metadata CDN cosmetic blocks.

This is deliberately *not* a visual-code decoder: without real CDN JSON
samples, candidate arrays and field-name/type signatures cannot establish
which game identifiers map to human-readable names. No network access, raw
metadata export, member data, or unverified automatic labels.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Optional, Tuple

from .customization_evidence import CUSTOMIZATION_BLOCKS
from .metadata import MetadataCache
from .native_game_sources import SourceSchemaError, load_visual_source

# AftermarketCollections is listed in the bundled metadata block catalogue,
# but is not yet allowlisted for label decoding (only structure inspection).
VISUAL_SOURCE_BLOCKS: Tuple[str, ...] = CUSTOMIZATION_BLOCKS + ("AftermarketCollections",)
_MAX_BYTES = 8 * 1024 * 1024
_MAX_DEPTH = 9
_MAX_ARRAYS = 250
_MAX_ROWS = 20000
_MAX_KEYS = 75
_FIELD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,47}\Z")


@dataclass(frozen=True)
class VisualArrayShape:
    """One bounded object-array candidate; `path` is source-schema only."""
    path: Optional[str] = None
    rows: int = 0
    fields: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    object_rows: int = 0
    source_semantics_verified: bool = False

    def report(self, show_field_names: bool = False) -> dict[str, Any]:
        result = {"rows": self.rows, "object_rows_sampled": self.object_rows,
                  "field_count": len(self.fields), "mapping_verified": False}
        if show_field_names:
            result["path"] = self.path
            result["field_types"] = dict(self.fields)
        return result


@dataclass(frozen=True)
class VisualBlockShape:
    """Source-file evidence only; CDN hash is cache bookkeeping, not a digest verification."""
    block: str
    status: str
    size_bytes: Optional[int] = None
    cached_cdn_hash: Optional[str] = None
    local_sha256: Optional[str] = None
    root_type: Optional[str] = None
    candidate_arrays: Tuple[VisualArrayShape, ...] = field(default_factory=tuple)
    truncated: bool = False

    def report(self, show_field_names: bool = False) -> dict[str, Any]:
        return {"status": self.status,
                "size_bytes": self.size_bytes,
                "cached_cdn_hash": self.cached_cdn_hash,
                "local_sha256": self.local_sha256,
                "root_type": self.root_type,
                "candidate_array_count": len(self.candidate_arrays),
                "candidate_arrays": [x.report(show_field_names) for x in self.candidate_arrays],
                "truncated": self.truncated,
                "visual_code_meanings_verified": False}


@dataclass(frozen=True)
class VisualSourceInventory:
    blocks: Tuple[VisualBlockShape, ...] = field(default_factory=tuple)
    status: str = "metadata_cache_schema_only"
    network_requests: int = 0
    cosmetic_labels_verified: bool = False

    def report(self, *, show_field_names: bool = False) -> dict[str, Any]:
        return {"status": self.status, "network_requests": 0,
                "cosmetic_labels_verified": False,
                "blocks": {x.block: x.report(show_field_names) for x in self.blocks}}


def _typename(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "number"
    if type(value) is str:
        return "string"
    return "other"


def _arrays(node: Any) -> tuple[Tuple[VisualArrayShape, ...], bool]:
    arrays: list[VisualArrayShape] = []
    stack: list[tuple[Any, str, int]] = [(node, "$", 0)]
    truncated = False
    while stack:
        value, path, depth = stack.pop()
        if depth >= _MAX_DEPTH:
            truncated = True
            continue
        if isinstance(value, list):
            if len(value) > _MAX_ROWS:
                truncated = True
                continue
            sample = [x for x in value[:3] if isinstance(x, Mapping)]
            if sample:
                keys = [k for k in sample[0] if type(k) is str and _FIELD_RE.fullmatch(k)]
                keys = sorted(keys)[:_MAX_KEYS]
                fields = []
                for k in keys:
                    types = {_typename(x[k]) for x in sample if k in x}
                    fields.append((k, next(iter(types)) if len(types) == 1 else "mixed"))
                arrays.append(VisualArrayShape(path, len(value), tuple(fields), len(sample)))
                if len(arrays) >= _MAX_ARRAYS:
                    truncated = True
                    break
            # Inspection of representative shapes, not enumeration of all values.
            if value:
                stack.append((value[0], path + "[]", depth + 1))
        elif isinstance(value, Mapping):
            # Only keys that look like schema properties. Dynamic ID maps are
            # not exposed as record paths, even in opt-in field-name mode.
            for k in sorted((k for k in value if type(k) is str and _FIELD_RE.fullmatch(k)), reverse=True)[:_MAX_KEYS]:
                child = value[k]
                if isinstance(child, (list, Mapping)):
                    stack.append((child, path + "." + k, depth + 1))
    return tuple(arrays), truncated


def inspect_visual_cache(cache: MetadataCache, *, blocks: Tuple[str, ...] = VISUAL_SOURCE_BLOCKS) -> VisualSourceInventory:
    """Inspect only allowlisted existing cache files. Never calls sync/get/HTTP.

    Untrusted files are size-bounded, JSON-decoded and reduced to shape and
    checksums. No raw values are returned by either the function or CLI.
    """
    if not isinstance(cache, MetadataCache):
        raise TypeError("expected MetadataCache")
    if not blocks or len(blocks) > len(VISUAL_SOURCE_BLOCKS) or any(
            type(name) is not str or name not in VISUAL_SOURCE_BLOCKS for name in blocks):
        raise ValueError("unknown metadata block")
    if len(set(blocks)) != len(blocks):
        raise ValueError("duplicate metadata block")
    untrusted_hashes = cache.hashes(blocks)
    # Never echo malformed/unbounded hash bookkeeping values from a local file.
    hashes = {k: v for k, v in untrusted_hashes.items()
              if type(v) is str and re.fullmatch(r"[0-9a-f]{32}", v)}
    results: list[VisualBlockShape] = []
    for name in blocks:
        path = Path(cache.path(name))
        if not path.is_file():
            results.append(VisualBlockShape(name, "not_cached"))
            continue
        size = path.stat().st_size
        if not 0 < size <= _MAX_BYTES:
            results.append(VisualBlockShape(name, "size_rejected", size_bytes=size))
            continue
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        try:
            parsed = json.loads(data.decode("utf-8-sig"))
        except (UnicodeError, ValueError):
            results.append(VisualBlockShape(name, "not_json", size, hashes.get(name), digest))
            continue
        if isinstance(parsed, Mapping) and name in parsed:
            parsed = parsed[name]
        shapes, truncation = _arrays(parsed)
        results.append(VisualBlockShape(name, "inspected", size, hashes.get(name),
                                        digest, _typename(parsed), shapes, truncation))
    return VisualSourceInventory(tuple(results))


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Offline visual-library Metadata CDN cache schema inspection")
    p.add_argument("--metadata-cache-dir", help="existing cache from MetadataCache.sync; never synced here")
    p.add_argument("--block", action="append", choices=VISUAL_SOURCE_BLOCKS,
                   help="only inspect a named visual block (repeatable)")
    p.add_argument("--show-field-names", action="store_true",
                   help="opt in to schema paths/field names (never field values)")
    p.add_argument("--layout-json", help="explicit previously confirmed visual JSON layout(s)")
    args = p.parse_args(argv)
    if not args.metadata_cache_dir:
        print(json.dumps({"mode": "dry_run", "network_requests": 0,
                          "target_blocks": list(VISUAL_SOURCE_BLOCKS), "names_verified": False}, indent=2))
        return 0
    if args.block and len(set(args.block)) != len(args.block):
        p.error("duplicate block")
    cache = MetadataCache(args.metadata_cache_dir)
    try:
        inventory = inspect_visual_cache(cache, blocks=tuple(args.block) if args.block else VISUAL_SOURCE_BLOCKS)
        report = inventory.report(show_field_names=args.show_field_names)
        if args.layout_json:
            # This is an explicit layout, not schema autodetection. Only report
            # coverage and slot counts; never print labels or model identifiers.
            decoded = load_visual_source(cache, args.layout_json)
            report["explicit_layout"] = {"status": "normalized_rows_decoded_unverified_ui",
                                         "records": len(decoded.records),
                                         "slots": {s: sum(x.slot == s for x in decoded.records)
                                                   for s in sorted({x.slot for x in decoded.records})}}
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, SourceSchemaError, TypeError):
        print(json.dumps({"status": "offline_schema_unavailable", "details": "suppressed",
                          "network_requests": 0}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
