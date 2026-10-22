"""Offline, schema-gated readers for native game label sources.

CSR2 IL2CPP metadata contains FlatBuffers TranslationFile/TranslationEntry
symbols, but it does not establish table field indices. This module cannot
infer the native table schema. It accepts an *explicit*, independently
corroborated table layout and fails closed when a file cannot satisfy it.

Metadata CDN blocks are already JSON-decoded by MetadataCache. We provide a
privacy-preserving shape inventory, never assume a particular visual-record
schema from a block's name, and never perform HTTP requests here.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import struct
from typing import Any, Mapping, Optional

from .game_labels import GameCarTranslations, GameVisualLibrary
from .customization_evidence import CUSTOMIZATION_BLOCKS, SLOT_FIELDS
from .metadata import MetadataCache

_MAX_BUFFER = 20 * 1024 * 1024
_MAX_ROWS = 20000
_MAX_DEPTH = 6
_MAX_KEYS = 40


class SourceSchemaError(ValueError):
    """Unreadable, unsupported or non-matching source layout."""


def _index(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 127:
        raise SourceSchemaError("FlatBuffers field indices must be 0..127 integers")
    return value


def _source_path(path: str | Path, *, maximum: int = _MAX_BUFFER) -> bytes:
    file = Path(path)
    if not file.is_file() or not 4 <= file.stat().st_size <= maximum:
        raise SourceSchemaError("local source missing or exceeds size bounds")
    return file.read_bytes()


class _FlatBuffer:
    """Minimal bounds-checked FlatBuffers table/vector/string traversal.

    Only the standard FlatBuffers table envelope is interpreted; no CSR2 field
    meaning is assigned until an explicit layout is supplied.
    """
    def __init__(self, raw: bytes):
        if type(raw) is not bytes or not 8 <= len(raw) <= _MAX_BUFFER:
            raise SourceSchemaError("invalid or oversized FlatBuffers source")
        self.b = raw

    def _at(self, pos: int, size: int) -> None:
        if type(pos) is not int or pos < 0 or size < 0 or pos + size > len(self.b):
            raise SourceSchemaError("invalid FlatBuffers offset")

    def u16(self, pos: int) -> int:
        self._at(pos, 2)
        return struct.unpack_from("<H", self.b, pos)[0]

    def u32(self, pos: int) -> int:
        self._at(pos, 4)
        return struct.unpack_from("<I", self.b, pos)[0]

    def i32(self, pos: int) -> int:
        self._at(pos, 4)
        return struct.unpack_from("<i", self.b, pos)[0]

    def root(self) -> int:
        root = self.u32(0)
        self.table(root)
        return root

    def table(self, pos: int) -> tuple[int, int, int]:
        self._at(pos, 4)
        back = self.i32(pos)
        vtable = pos - back
        self._at(vtable, 4)
        length = self.u16(vtable)
        obj_len = self.u16(vtable + 2)
        if length < 4 or length % 2 or obj_len < 4 or length > 260 or obj_len > 65535:
            raise SourceSchemaError("invalid FlatBuffers vtable")
        self._at(vtable, length)
        self._at(pos, obj_len)
        return vtable, length, obj_len

    def field(self, table: int, index: int) -> Optional[int]:
        vtable, length, obj_len = self.table(table)
        off = 4 + 2 * _index(index)
        if off >= length:
            return None
        delta = self.u16(vtable + off)
        if delta == 0:
            return None
        if delta < 4 or delta + 4 > obj_len:
            raise SourceSchemaError("invalid FlatBuffers field address")
        return table + delta

    def target(self, pos: int) -> int:
        # FlatBuffers uoffsets are unsigned and relative to their own location.
        at = pos + self.u32(pos)
        self._at(at, 4)
        return at

    def table_vector(self, table: int, index: int) -> tuple[int, ...]:
        off = self.field(table, index)
        if off is None:
            raise SourceSchemaError("required table vector absent")
        vec = self.target(off)
        count = self.u32(vec)
        if count > _MAX_ROWS:
            raise SourceSchemaError("translation vector exceeds record limit")
        start = vec + 4
        self._at(start, count * 4)
        rows = []
        for i in range(count):
            entry = self.target(start + 4 * i)
            self.table(entry)
            rows.append(entry)
        return tuple(rows)

    def string(self, table: int, index: int) -> Optional[str]:
        off = self.field(table, index)
        if off is None:
            return None
        pos = self.target(off)
        length = self.u32(pos)
        if length > 240:
            raise SourceSchemaError("native label string exceeds safety bound")
        self._at(pos + 4, length + 1)
        if self.b[pos + 4 + length] != 0:
            raise SourceSchemaError("native FlatBuffers string missing terminator")
        try:
            return self.b[pos + 4: pos + 4 + length].decode("utf-8")
        except UnicodeDecodeError:
            raise SourceSchemaError("invalid native UTF-8 label") from None


@dataclass(frozen=True)
class TranslationLayout:
    """Explicit FlatBuffers field indices, *not* an assumed CSR2 wire schema."""
    entries: int
    model_key: int
    short: int
    medium: int
    long: int

    @classmethod
    def from_manifest(cls, data: Any) -> "TranslationLayout":
        if not isinstance(data, Mapping) or data.get("format") != "csr2cdn.translation-flatbuffer-layout.v1":
            raise SourceSchemaError("translation layout requires a versioned manifest")
        indexes = [_index(data.get(x)) for x in ("entries", "model_key", "short", "medium", "long")]
        if len(set(indexes[1:])) != 4:
            raise SourceSchemaError("translation entry fields must have distinct indices")
        return cls(*indexes)


def decode_translation_flatbuffer(data: bytes, layout: TranslationLayout, *,
                                  expected_keys: tuple[str, ...] = ()) -> GameCarTranslations:
    """Extract normalized names from a *layout-specified* native FlatBuffer.

    Verification of table indices against game assets is required before these
    normalized rows are described as actual game labels. Optional expected_keys
    are exact identifiers whose presence is required, not inferred heuristically.
    """
    if not isinstance(layout, TranslationLayout):
        raise SourceSchemaError("explicit translation layout required")
    fb = _FlatBuffer(data)
    root = fb.root()
    rows = []
    present = set()
    for item in fb.table_vector(root, layout.entries):
        key = fb.string(item, layout.model_key)
        variants = {"SHORT": fb.string(item, layout.short),
                    "MEDIUM": fb.string(item, layout.medium),
                    "LONG": fb.string(item, layout.long)}
        if key is None or not any(variants.values()):
            raise SourceSchemaError("missing car translation key or variants")
        rows.append({"model_key": key, **variants})
        present.add(key)
    if not rows or any(type(k) is not str or not k for k in expected_keys) or any(k not in present for k in expected_keys):
        raise SourceSchemaError("translation file has no entries or fails expected-key checks")
    try:
        return GameCarTranslations.from_manifest({"format": "csr2cdn.car-translations.v1", "records": rows})
    except ValueError:
        raise SourceSchemaError("translation rows violate normalized data contract") from None


@dataclass(frozen=True)
class VisualJsonLayout:
    """Explicit JSON block traversal, not a discovered CSR2 native schema."""
    block: str
    path: tuple[str, ...]
    model_field: str
    code_field: str
    label_field: str
    slot: str

    @classmethod
    def from_manifest(cls, data: Any) -> "VisualJsonLayout":
        if not isinstance(data, Mapping) or data.get("format") != "csr2cdn.visual-json-layout.v1":
            raise SourceSchemaError("unrecognized visual layout")
        block, path, model, code, label, slot = (data.get("block"), data.get("records_path"),
                  data.get("model_field"), data.get("code_field"), data.get("label_field"), data.get("slot"))
        if type(block) is not str or block not in CUSTOMIZATION_BLOCKS or type(slot) is not str or slot not in SLOT_FIELDS:
            raise SourceSchemaError("unknown visual metadata block or cosmetic slot")
        if (type(path) is not list or len(path) > 6 or any(type(k) is not str or not k.isidentifier() for k in path)):
            raise SourceSchemaError("invalid visual record traversal")
        if any(type(k) is not str or not k.isidentifier() for k in (model, code, label)) or len({model, code, label}) != 3:
            raise SourceSchemaError("invalid visual record field mappings")
        return cls(block, tuple(path), model, code, label, slot)


def _guard_cache_file(cache: MetadataCache, name: str) -> None:
    path = Path(cache.path(name))
    if not path.is_file() or path.stat().st_size > _MAX_BUFFER:
        raise SourceSchemaError("missing or oversized cached metadata block")


def decode_visual_metadata_cache(cache: MetadataCache, layouts: tuple[VisualJsonLayout, ...]) -> GameVisualLibrary:
    """Decode cached JSON with explicitly confirmed field paths, without network I/O.

    Hashes represent cache provenance; they do not verify the semantics of
    a proposed JSON field mapping. Unrecognized shapes are errors, not guesses.
    """
    if not isinstance(cache, MetadataCache) or not layouts or len(layouts) > 24 or any(not isinstance(x, VisualJsonLayout) for x in layouts):
        raise SourceSchemaError("a cache and bounded explicit visual layouts are required")
    hashes = cache.hashes(tuple(x.block for x in layouts))
    rows: list[dict[str, Any]] = []
    for layout in layouts:
        if layout.block not in hashes:
            raise SourceSchemaError("cached visual block and CDN hash required")
        _guard_cache_file(cache, layout.block)
        value = cache.load(layout.block)
        for key in layout.path:
            if not isinstance(value, Mapping) or key not in value:
                raise SourceSchemaError("explicit visual JSON path not found")
            value = value[key]
        if type(value) is not list or not 0 < len(value) <= _MAX_ROWS:
            raise SourceSchemaError("expected a nonempty bounded JSON record array")
        for node in value:
            if not isinstance(node, Mapping):
                raise SourceSchemaError("visual JSON record must be an object")
            rows.append({"model_key": node.get(layout.model_field), "slot": layout.slot,
                         "code": node.get(layout.code_field), "name": node.get(layout.label_field),
                         "source_library": layout.block, "metadata_hash": hashes[layout.block]})
        if len(rows) > _MAX_ROWS:
            raise SourceSchemaError("too many visual records")
    try:
        return GameVisualLibrary.from_manifest({"format": "csr2cdn.visual-code-library.v1", "records": rows})
    except ValueError:
        raise SourceSchemaError("visual JSON rows violate normalized contract") from None


def load_translation_source(binary_path: str | Path, layout_path: str | Path, *,
                            expected_keys: tuple[str, ...] = ()) -> GameCarTranslations:
    """Offline convenience adapter with bounded native bytes and JSON layout."""
    layout = TranslationLayout.from_manifest(json.loads(_source_path(layout_path).decode("utf-8-sig")))
    return decode_translation_flatbuffer(_source_path(binary_path), layout,
                                         expected_keys=expected_keys)


def load_visual_source(cache: MetadataCache, layouts_path: str | Path) -> GameVisualLibrary:
    """Offline convenience adapter with bounded JSON layout manifest."""
    rows = json.loads(_source_path(layouts_path).decode("utf-8-sig"))
    if not isinstance(rows, list) or not rows or len(rows) > 24:
        raise SourceSchemaError("visual layout file requires a nonempty bounded array")
    return decode_visual_metadata_cache(cache, tuple(VisualJsonLayout.from_manifest(row) for row in rows))


def _shape(value: Any, *, depth: int = 0, show_field_names: bool = False) -> dict[str, Any]:
    if depth >= _MAX_DEPTH:
        return {"type": "depth_limit"}
    if isinstance(value, Mapping):
        keys = [key for key in value if type(key) is str]
        # Sort keys for deterministic inspection; never display values.
        safe_keys = sorted(k for k in keys if k.isidentifier() and len(k) <= 63)[:_MAX_KEYS]
        return ({"type": "object", "keys_total": len(value),
                 "properties": {k: _shape(value[k], depth=depth + 1, show_field_names=True)
                                for k in safe_keys}}
                if show_field_names else {"type": "object", "keys_total": len(value),
                                          "key_types": {"string": len(keys), "other": len(value) - len(keys)}})
    if isinstance(value, list):
        return {"type": "array", "length": len(value),
                "sample_shape": _shape(value[0], depth=depth + 1, show_field_names=show_field_names) if value else None}
    if value is None:
        return {"type": "null"}
    if type(value) is bool:
        return {"type": "boolean"}
    if type(value) is int:
        return {"type": "integer"}
    if type(value) is float:
        return {"type": "number"}
    if type(value) is str:
        return {"type": "string"}
    return {"type": "other"}


def inspect_metadata_cache(cache: MetadataCache, names: tuple[str, ...], *,
                           show_field_names: bool = False) -> dict[str, Any]:
    """Offline structure only, without member identifiers, values, or sync."""
    if not isinstance(cache, MetadataCache):
        raise TypeError("expected MetadataCache")
    if len(names) > 32 or any(type(name) is not str or not name or not name.isidentifier() or len(name) > 80 for name in names):
        raise ValueError("invalid or excessive block names")
    available = set(cache.stored())
    hashes = cache.hashes(names)
    blocks = {}
    for name in names:
        if name in available:
            _guard_cache_file(cache, name)
        blocks[name] = {"cached": name in available,
                        "metadata_hash_available": name in hashes,
                        "structure": _shape(cache.load(name), show_field_names=show_field_names)
                                     if name in available else None}
    return {"status": "local_metadata_shape_inventory", "network_requests": 0,
            "blocks": blocks}


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Inspect game label sources, offline only")
    p.add_argument("--metadata-cache-dir", help="existing MetadataCache directory; never sync")
    p.add_argument("--blocks", nargs="*", default=list(("CarAdditionalVisuals", "CarAftermarketCustomisations", "CarLiveriesMatrix")))
    p.add_argument("--show-field-names", action="store_true", help="opt into local JSON field-key names for schema inspection")
    p.add_argument("--visual-layout-json", help="explicit verified JSON field layouts for visual code blocks")
    p.add_argument("--output-visual-json", help="opt-in local normalized visual record export path")
    p.add_argument("--translation-file", help="existing native FlatBuffers translation file")
    p.add_argument("--translation-unityfs", help="local game Localisation_EN UnityFS bundle (observed version 6312 format)")
    p.add_argument("--translation-layout-json", help="operator-verified field layout, never inferred")
    p.add_argument("--expected-model-key", action="append", default=[], help="exact car key required in translation results")
    p.add_argument("--output-translations-json", help="opt-in local normalized translation export path")
    args = p.parse_args(argv)
    if args.visual_layout_json and not args.metadata_cache_dir:
        p.error("visual layouts require an existing metadata cache")
    if args.output_visual_json and not args.visual_layout_json:
        p.error("visual export requires an explicit visual layout")
    if args.output_translations_json and not (args.translation_unityfs or (args.translation_file and args.translation_layout_json)):
        p.error("translation export requires a local native source")
    if args.translation_unityfs and (args.translation_file or args.translation_layout_json):
        p.error("choose either UnityFS source or FlatBuffers source and layout")
    if bool(args.translation_file) != bool(args.translation_layout_json):
        p.error("translation file and layout must be supplied together")
    try:
        result: dict[str, Any] = {"mode": "offline", "network_requests": 0,
                                  "native_translation_schema_verified": False,
                                  "visual_library_schema_verified": False}
        if args.metadata_cache_dir:
            cache = MetadataCache(args.metadata_cache_dir)
            result["metadata"] = inspect_metadata_cache(cache, tuple(args.blocks),
                                                        show_field_names=args.show_field_names)
            if args.visual_layout_json:
                visuals = load_visual_source(cache, args.visual_layout_json)
                result["visuals"] = {"status": "layout_specified_candidate", "entries": len(visuals.records),
                                     "verified_against_game_ui": False}
                if args.output_visual_json:
                    out = Path(args.output_visual_json)
                    if out.exists():
                        raise SourceSchemaError("refusing to overwrite existing visual file")
                    manifest = {"format": "csr2cdn.visual-code-library.v1", "records": [
                        {"model_key": item.model_key, "slot": item.slot, "code": item.code,
                         "name": item.name, "source_library": item.source_library,
                         "metadata_hash": item.source_hash} for item in visuals.records]}
                    with out.open("x", encoding="utf-8") as handle:
                        json.dump(manifest, handle, ensure_ascii=False, indent=2)
                    result["visuals"]["exported_to_local_file"] = True
        if args.translation_file or args.translation_unityfs:
            if args.translation_unityfs:
                from .localisation_bundle import load_localisation_unityfs
                names = load_localisation_unityfs(args.translation_unityfs,
                                                  expected_model_keys=tuple(args.expected_model_key))
                result["native_translation_schema_verified"] = True
                source_status = "observed_unityfs_translation_asset"
            else:
                names = load_translation_source(args.translation_file, args.translation_layout_json,
                                                expected_keys=tuple(args.expected_model_key))
                source_status = "layout_specified_candidate"
            result["translations"] = {"status": source_status, "entries": len(names.records),
                                      "label_variants": {s: sum(getattr(row, s.lower()) is not None for row in names.records)
                                                         for s in ("SHORT", "MEDIUM", "LONG")},
                                      "verified_against_game_ui": False}
            if args.output_translations_json:
                normalized = {"format": "csr2cdn.car-translations.v1", "records": [
                    {"model_key": row.model_key, "SHORT": row.short, "MEDIUM": row.medium, "LONG": row.long}
                    for row in names.records]}
                output = Path(args.output_translations_json)
                if output.exists():
                    raise SourceSchemaError("refusing to overwrite an existing translation file")
                with output.open("x", encoding="utf-8") as handle:
                    json.dump(normalized, handle, ensure_ascii=False, indent=2)
                result["translations"]["exported_to_local_file"] = True
        if not args.metadata_cache_dir and not args.translation_file and not args.translation_unityfs:
            result["status"] = "dry_run"
            result["supported_sources"] = ["cached_metadata_shapes", "layout_specified_translation_flatbuffer",
                                           "observed_unityfs_translation_asset", "layout_specified_visual_json"]
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, UnicodeError, TypeError):
        print(json.dumps({"status": "source_unavailable_or_unverified", "network_requests": 0,
                          "details": "suppressed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
