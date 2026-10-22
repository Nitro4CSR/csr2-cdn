"""Offline, field-aware inspection of Unity-extracted CarVisualConfigs text.

This module never downloads assets or reads crew responses.  A file must be
supplied by its operator. Matches are observations, not a trusted mapping from
crew indices to paint IDs: the archive can be older than the live game, and
native code may append options to runtime lists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

MAX_BYTES = 4 * 1024 * 1024
VECTOR_TYPES = {
    "CarPaintIDs": int,
    "CarInteriorIDs": int,
    "CarCalliperIDs": int,
    "CarLiveryIDs": int,
    "CarLiveryZonesSetIDs": int,
    "WheelBundleNames": str,
}
PRESET_KEYS = {
    "PaintID", "InteriorID", "CalliperID", "LiveryID", "LiveryZonesSetID",
    "WrapPaintID", "WheelBundleName", "gachaLetter", "duplicate",
}


def _read_local_text(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("config must be a regular, non-symlinked local file")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("config exceeds the 4 MiB inspection limit")
    return path.read_text(encoding="utf-8-sig")


def _parse_value(text: str, target: type) -> Any:
    if target is int:
        if not re.fullmatch(r"-?\d+", text):
            raise ValueError("invalid integer in extracted CarVisualConfigs text")
        return int(text)
    if not (text.startswith('"') and text.endswith('"')):
        raise ValueError("invalid string in extracted CarVisualConfigs text")
    return json.loads(text)


def parse_car_visual_config(text: str) -> dict[str, Any]:
    """Parse known arrays without guessing Unity field semantics or ordering."""
    arrays: dict[str, list[Any]] = {k: [] for k in VECTOR_TYPES}
    expected: dict[str, int] = {}
    presets: list[dict[str, Any]] = []
    section: str | None = None
    preset: dict[str, Any] | None = None
    current_index = -1
    lock_paints: int | None = None
    for line in text.splitlines():
        top = re.fullmatch(r"\tvector (\w+)", line)
        if top:
            section = top.group(1) if top.group(1) in arrays else None
            preset = None
            current_index = -1
            continue
        if line == "\tCarVisualsGachaConfig GachaConfigs":
            section, preset, current_index = "GachaConfigs", None, -1
            continue
        if line.startswith("\t") and not line.startswith("\t\t"):
            m = re.fullmatch(r"\tint lockPaintsToIndex = (-?\d+)", line)
            if m:
                lock_paints = int(m.group(1))
            section = None
            continue
        if section is None:
            continue
        size = re.fullmatch(r"\t\tint size = (\d+)", line)
        if size:
            n = int(size.group(1))
            if n > 100_000:
                raise ValueError("array length unreasonable")
            expected[section] = n
            continue
        entry = re.fullmatch(r"\t\t\t\[(\d+)\]", line)
        if entry:
            ix = int(entry.group(1))
            if ix != current_index + 1:
                raise ValueError("noncontiguous array indices")
            current_index = ix
            if section == "GachaConfigs":
                preset = {}
                presets.append(preset)
            continue
        if section in arrays:
            value = re.fullmatch(r"\t\t\t(?:int|string) data = (.+)", line)
            if value:
                if current_index != len(arrays[section]):
                    raise ValueError("unexpected visual array value")
                arrays[section].append(_parse_value(value.group(1), VECTOR_TYPES[section]))
        elif section == "GachaConfigs" and preset is not None:
            field = re.fullmatch(r"\t\t\t\t(?:int|string) ([A-Za-z]+) = (.+)", line)
            if field and field.group(1) in PRESET_KEYS:
                key = field.group(1)
                preset[key] = _parse_value(field.group(2), str if key in {"gachaLetter", "WheelBundleName"} else int)
    for key, values in {**arrays, "GachaConfigs": presets}.items():
        if key not in expected or expected[key] != len(values):
            raise ValueError(f"missing or inconsistent {key} array")
    if lock_paints is None:
        raise ValueError("missing lockPaintsToIndex")
    return {"arrays": arrays, "gacha_configs": presets, "lock_paints_to_index": lock_paints}


def _wheel_suffix(wheel_name: str) -> str | None:
    """Strip only the car prefix; never compare arbitrary substrings."""
    m = re.search(r"(?:^|_)(Wheel[0-9][A-Za-z0-9]*_3D)$", wheel_name)
    return m.group(1) if m else None


def inspect_car_visual_config(
    content: bytes, *, paint_index: int | None = None,
    interior_id: int | None = None, calliper_id: int | None = None,
    wheel_name: str | None = None,
    livery_id: int | None = None, livery_zone_set_id: int | None = None,
    source_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if len(content) > MAX_BYTES:
        raise ValueError("config exceeds the 4 MiB inspection limit")
    source = parse_car_visual_config(content.decode("utf-8-sig"))
    arrays, presets = source["arrays"], source["gacha_configs"]
    unique_gacha_paints = {p["PaintID"] for p in presets if "PaintID" in p}
    base_paints = arrays["CarPaintIDs"]
    known_paints = set(base_paints) | unique_gacha_paints
    res: dict[str, Any] = {
        "status": "archived_car_visual_config_inspected_not_runtime_mapping",
        "config_sha256": hashlib.sha256(content).hexdigest(),
        "network_requests": 0,
        "gameplay_reads": 0,
        "base_array_lengths": {k: len(v) for k, v in arrays.items()},
        "gacha_config_count": len(presets),
        "distinct_gacha_paint_id_count": len(unique_gacha_paints),
        "distinct_base_plus_gacha_paint_id_count": len(known_paints),
        "lock_paints_to_index_raw": source["lock_paints_to_index"],
        "historical_archive_may_differ_from_live_game": True,
        "runtime_aftermarket_append_order_verified": False,
        "crew_paint_index_to_paint_id_verified": False,
        "other_fields_are_not_assumed_index_encoded": True,
        "mapping_promoted": False,
    }
    if paint_index is not None:
        if paint_index < 0:
            raise ValueError("paint index must be nonnegative")
        res["paint_index_observation"] = {
            "received_index": paint_index,
            "within_archived_base_array": paint_index < len(base_paints),
            "archived_base_candidate_id": base_paints[paint_index] if paint_index < len(base_paints) else None,
            "candidate_is_verified_runtime_selection": False,
        }
    observed: dict[str, Any] = {}
    for label, field, value, preset_key in (
        ("interior", "CarInteriorIDs", interior_id, "InteriorID"),
        ("calliper", "CarCalliperIDs", calliper_id, "CalliperID"),
        ("livery", "CarLiveryIDs", livery_id, "LiveryID"),
        ("livery_zones_set", "CarLiveryZonesSetIDs", livery_zone_set_id, "LiveryZonesSetID"),
    ):
        if value is not None:
            observed[label] = {
                "received_id": value,
                "present_in_archived_base_array": value in arrays[field],
                "gacha_config_occurrences": sum(p.get(preset_key) == value for p in presets),
                "roster_to_runtime_join_verified": False,
            }
    if wheel_name is not None:
        suffix = _wheel_suffix(wheel_name)
        observed["wheel"] = {
            "recognized_wheel_bundle_suffix": suffix is not None,
            "base_wheel_match": suffix in arrays["WheelBundleNames"] if suffix else False,
            "gacha_wheel_occurrences": sum(p.get("WheelBundleName") == suffix for p in presets) if suffix else 0,
            "car_specific_asset_verified_current": False,
        }
    if observed:
        res["observed_field_comparisons"] = observed
    if source_catalog is not None:
        rows = source_catalog.get("individual_source_ids")
        if not isinstance(rows, list):
            raise ValueError("source catalogue lacks individual_source_ids")
        present: dict[str, set[int]] = {"paint": set(), "interior": set(), "calliper": set()}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("invalid catalogue source record")
            slot, num = row.get("slot"), row.get("numeric_id")
            if slot in present and type(num) is int:
                present[slot].add(num)
        for slot, array_field, preset_field in (
            ("paint", "CarPaintIDs", "PaintID"),
            ("interior", "CarInteriorIDs", "InteriorID"),
            ("calliper", "CarCalliperIDs", "CalliperID"),
        ):
            candidates = set(arrays[array_field]) | {
                r[preset_field] for r in presets if type(r.get(preset_field)) is int
            }
            res.setdefault("catalogue_source_presence", {})[slot] = {
                "distinct_config_ids": len(candidates),
                "present_in_source_catalogue": len(candidates & present[slot]),
                "absent_from_source_catalogue": len(candidates - present[slot]),
                "presence_is_not_roster_index_mapping": True,
            }
        res["catalogue_database_version"] = source_catalog.get("database_version")
    return res


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline, non-promoting analysis of a Unity-extracted per-car visual config")
    parser.add_argument("--config-file", type=Path, required=True)
    parser.add_argument("--paint-index", type=int)
    parser.add_argument("--interior-id", type=int)
    parser.add_argument("--calliper-id", type=int)
    parser.add_argument("--wheel-name")
    parser.add_argument("--livery-id", type=int)
    parser.add_argument("--livery-zone-set-id", type=int)
    parser.add_argument("--source-catalog", type=Path, help="Optional saved public Dev36 catalogue")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        parser.error("refusing to overwrite an existing report")
    catalog = None
    if args.source_catalog is not None:
        if args.source_catalog.is_symlink() or not args.source_catalog.is_file():
            parser.error("source catalogue must be a regular, non-symlinked file")
        if args.source_catalog.stat().st_size > 16 * 1024 * 1024:
            parser.error("source catalogue exceeds 16 MiB")
        catalog = json.loads(args.source_catalog.read_text(encoding="utf-8"))
    output = inspect_car_visual_config(
        _read_local_text(args.config_file).encode("utf-8"),
        paint_index=args.paint_index,
        interior_id=args.interior_id,
        calliper_id=args.calliper_id,
        wheel_name=args.wheel_name,
        livery_id=args.livery_id,
        livery_zone_set_id=args.livery_zone_set_id,
        source_catalog=catalog,
    )
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("CarVisualConfigs analysis complete; no mapping promoted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
