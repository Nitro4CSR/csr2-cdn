"""Read-only CSR2 UnityFS 5.6/serialized-v17 CarVisuals extraction.

This is a narrow offline decoder for the 6.8.0 Ford_Mustang302_1970_common
bundle. It does not claim runtime selections or perform network requests. The
LZMA variant uses the five-byte Unity properties header and raw LZMA1 payload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import struct
from pathlib import Path
from typing import Any

MAX_BUNDLE = 64 * 1024 * 1024
MAX_DATA = 96 * 1024 * 1024
EXPECTED_FIELDS = {"CarPaintIDs", "CarInteriorIDs", "CarCalliperIDs", "WheelBundleNames", "GachaConfigs"}


class UnityReadError(ValueError):
    """Malformed or unsupported serialized Unity data."""


def _cstring(data: bytes, pos: int) -> tuple[str, int]:
    end = data.find(b"\x00", pos)
    if end < 0:
        raise UnityReadError("Unterminated UnityFS string")
    return data[pos:end].decode("utf-8", "replace"), end + 1


def _decompress(payload: bytes, expected: int, compression: int) -> bytes:
    if expected > MAX_DATA:
        raise UnityReadError("Decompressed block exceeds safety limit")
    if compression == 0:
        result = payload
    elif compression == 1:
        if len(payload) < 6:
            raise UnityReadError("Truncated Unity LZMA block")
        prop = payload[0]
        lc, lp, pb = prop % 9, (prop // 9) % 5, prop // 45
        if lc + lp > 4 or pb > 4:
            raise UnityReadError("Unsupported LZMA properties")
        dictionary = int.from_bytes(payload[1:5], "little")
        if not 4096 <= dictionary <= MAX_DATA:
            raise UnityReadError("Invalid LZMA dictionary")
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW,
            filters=[{"id": lzma.FILTER_LZMA1, "dict_size": dictionary,
                      "lc": lc, "lp": lp, "pb": pb}])
        result = decoder.decompress(payload[5:], max_length=expected + 1)
    elif compression in (2, 3):
        try:
            from lz4.block import decompress  # optional; not needed for supplied LZMA bundle
        except ImportError as e:
            raise UnityReadError("lz4 is required for this bundle") from e
        result = decompress(payload, uncompressed_size=expected)
    else:
        raise UnityReadError(f"Unsupported Unity compression: {compression}")
    if len(result) != expected:
        raise UnityReadError("Uncompressed size does not match UnityFS header")
    return result


def unpack_unityfs(bundle: bytes) -> bytes:
    """Return the single serialized asset file from a 5.x UnityFS v6 bundle."""
    if len(bundle) > MAX_BUNDLE:
        raise UnityReadError("Bundle exceeds safety limit")
    magic, pos = _cstring(bundle, 0)
    if magic != "UnityFS" or pos + 4 > len(bundle):
        raise UnityReadError("Not a UnityFS asset bundle")
    version = struct.unpack_from(">I", bundle, pos)[0]; pos += 4
    if version != 6:
        raise UnityReadError("Only UnityFS format 6 is supported")
    _, pos = _cstring(bundle, pos)
    _, pos = _cstring(bundle, pos)
    file_size, info_compressed, info_raw, flags = struct.unpack_from(">QIII", bundle, pos)
    pos += 20
    if file_size != len(bundle) or info_compressed > len(bundle) or info_raw > MAX_DATA:
        raise UnityReadError("UnityFS header size mismatch")
    if flags & 0x80:
        info_bytes = bundle[-info_compressed:]
    else:
        info_bytes = bundle[pos:pos + info_compressed]; pos += info_compressed
    info = _decompress(info_bytes, info_raw, flags & 0x3F)
    off = 16  # uncompressed block-info hash
    if len(info) < off + 4:
        raise UnityReadError("Short UnityFS block info")
    count = struct.unpack_from(">I", info, off)[0]; off += 4
    if count > 2000:
        raise UnityReadError("Too many UnityFS blocks")
    blocks = []
    for _ in range(count):
        raw, compressed, opts = struct.unpack_from(">IIH", info, off); off += 10
        blocks.append((raw, compressed, opts))
    count = struct.unpack_from(">I", info, off)[0]; off += 4
    if count != 1:
        raise UnityReadError("Expected one serialized asset node")
    start, size, _node_flags = struct.unpack_from(">QQI", info, off); off += 20
    _, off = _cstring(info, off)
    # UnityFS-v6 5.6 bundles need no 16-byte alignment after blocks info.
    contents = bytearray()
    for raw, compressed, opts in blocks:
        contents.extend(_decompress(bundle[pos:pos + compressed], raw, opts & 0x3F))
        pos += compressed
        if len(contents) > MAX_DATA:
            raise UnityReadError("Total decompressed content too large")
    if start + size > len(contents):
        raise UnityReadError("Asset node exceeds decompressed data")
    return bytes(contents[start:start + size])


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
    def read(self, spec: str) -> Any:
        length = struct.calcsize("<" + spec)
        if self.pos + length > len(self.data):
            raise UnityReadError("Unexpected end of serialized data")
        result = struct.unpack_from("<" + spec, self.data, self.pos)[0]
        self.pos += length
        return result
    def align(self) -> None:
        self.pos = (self.pos + 3) & ~3


def _string_name(buffer: bytes, value: int) -> str:
    if value & 0x80000000:
        return f"COMMON_{value & 0x7FFFFFFF:08X}"
    if value >= len(buffer):
        raise UnityReadError("Out-of-bounds type-tree string")
    return _cstring(buffer, value)[0]


def parse_asset(asset: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract CarVisuals and restoration unlockables using embedded type trees."""
    if len(asset) < 48 or len(asset) > MAX_DATA:
        raise UnityReadError("Invalid Unity serialized asset size")
    meta_size, file_size, version, data_offset = struct.unpack_from(">4I", asset)
    if version != 17 or file_size != len(asset) or meta_size > data_offset:
        raise UnityReadError("Only Unity serialized file v17 is supported")
    meta = _Reader(asset)
    meta.pos = 20
    _, meta.pos = _cstring(asset, meta.pos)
    meta.read("i")  # build target
    type_tree_enabled = meta.read("B")
    if not type_tree_enabled:
        raise UnityReadError("Bundle is missing embedded type trees")
    type_count = meta.read("i")
    if not 0 < type_count < 1000:
        raise UnityReadError("Invalid serialized type count")
    types = []
    for _ in range(type_count):
        class_id = meta.read("i")
        meta.read("B")  # stripped flag
        meta.read("h")  # script type index
        if class_id == 114:
            meta.pos += 16  # MonoBehaviour script GUID hash
        meta.pos += 16  # type hash
        node_count, string_len = meta.read("i"), meta.read("i")
        if not 0 <= node_count <= 5000 or not 0 <= string_len <= 250000:
            raise UnityReadError("Unreasonable serialized type-tree sizes")
        nodes = []
        for _ in range(node_count):
            typ_ver = meta.read("H")
            lvl = meta.read("B")
            typ_flags = meta.read("B")
            typ = meta.read("I"); name = meta.read("I")
            size = meta.read("i"); index = meta.read("i"); flags = meta.read("I")
            nodes.append((typ_ver, lvl, typ_flags, typ, name, size, index, flags))
        if meta.pos + string_len > len(asset):
            raise UnityReadError("Truncated type-tree string table")
        strings = asset[meta.pos:meta.pos + string_len]; meta.pos += string_len
        types.append({"class_id": class_id, "nodes": [
            {"level": n[1], "type": _string_name(strings, n[3]),
             "name": _string_name(strings, n[4]), "size": n[5], "flags": n[7]}
            for n in nodes]})
    object_count = meta.read("i")
    if not 0 < object_count < 100000:
        raise UnityReadError("Invalid object count")
    car_obj = unlock_obj = None
    for _ in range(object_count):
        meta.align()
        _path_id = meta.read("q")
        offset, size, type_index = meta.read("I"), meta.read("I"), meta.read("i")
        if not 0 <= type_index < len(types) or offset + size > len(asset) - data_offset:
            raise UnityReadError("Object table references invalid data")
        tp = types[type_index]
        if tp["class_id"] != 114:
            continue
        names = {n["name"] for n in tp["nodes"]}
        if EXPECTED_FIELDS.issubset(names):
            if car_obj is not None:
                raise UnityReadError("Ambiguous CarVisuals objects")
            car_obj = (tp["nodes"], asset[data_offset + offset:data_offset + offset + size])
        if {"UnlockableMilestones", "AllUnlockables"}.issubset(names):
            if unlock_obj is not None:
                raise UnityReadError("Ambiguous Unlockables objects")
            unlock_obj = (tp["nodes"], asset[data_offset + offset:data_offset + offset + size])
    if car_obj is None or unlock_obj is None:
        raise UnityReadError("Required CarVisuals/Unlockables object not found")
    return _read_typetree(*car_obj), _read_typetree(*unlock_obj)


def _read_typetree(nodes: list[dict[str, Any]], data: bytes) -> dict[str, Any]:
    reader = _Reader(data)
    def end_of(index: int) -> int:
        lvl = nodes[index]["level"]
        end = index + 1
        while end < len(nodes) and nodes[end]["level"] > lvl:
            end += 1
        return end
    def parse(index: int) -> Any:
        node = nodes[index]
        last = end_of(index)
        children = []
        child = index + 1
        while child < last:
            children.append(child)
            child = end_of(child)
        field_type, size = node["type"], node["size"]
        if field_type == "COMMON_00000348":  # serialized string
            count = reader.read("i")
            if not 0 <= count <= 100000 or count > len(data) - reader.pos:
                raise UnityReadError("Invalid serialized string length")
            value = data[reader.pos:reader.pos + count].decode("utf-8", "replace")
            reader.pos += count
            reader.align()
        elif field_type == "COMMON_000003D5" or (len(children) == 1 and nodes[children[0]]["type"] == "COMMON_00000031"):  # vector of elements
            if not children:
                raise UnityReadError("Missing vector array")
            count = reader.read("i")
            if not 0 <= count <= 30000:
                raise UnityReadError("Invalid serialized vector length")
            array = children[0]
            entry = end_of(array + 1)
            value = [parse(entry) for _ in range(count)]
        elif children:
            value = {nodes[child]["name"]: parse(child) for child in children}
        elif size == 1:
            value = reader.read("B")
        elif size == 2:
            value = reader.read("h")
        elif size == 4:
            value = reader.read("f" if field_type == "COMMON_000000A1" else "i")
        elif size == 8:
            value = reader.read("q")
        else:
            raise UnityReadError("Unsupported primitive in target type tree")
        if node["flags"] & 0x4000:
            reader.align()
        return value
    decoded = parse(0)
    if reader.pos != len(data):
        raise UnityReadError("Target object was not completely decoded")
    return decoded


ARCHIVED_BASE = {
    "CarPaintIDs": [1156, 451, 1159, 1160], "CarLiveryZonesSetIDs": [0],
    "CarLiveryIDs": [422], "CarInteriorIDs": [66], "CarCalliperIDs": [4],
    "WheelBundleNames": ["Wheel1A_3D"],
}
ARCHIVED_PRESETS = [
    (1138, 66, 4, "Wheel2A_3D"),
    (1156, 66, 4, "Wheel2A_3D"),
    (1159, 887, 4, "Wheel2A_3D"),
    (1161, 66, 4, "Wheel2A_3D"),
    (451, 885, 4, "Wheel1A_3D"),
    (1158, 886, 4, "Wheel2A_3D"),
    (1157, 884, 4, "Wheel1A_3D"),
    (1162, 66, 4, "Wheel3A_3D"),
    (1160, 888, 4, "Wheel3A_3D"),
    (1163, 884, 4, "Wheel2A_3D"),
    (1164, 66, 4, "Wheel2A_3D"),
]


def inspect_bundle(content: bytes, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    car, unlocks = parse_asset(unpack_unityfs(content))
    base_match = {key: car[key] == expected for key, expected in ARCHIVED_BASE.items()}
    presets = car["GachaConfigs"]
    compact_presets = [(p["PaintID"], p["InteriorID"], p["CalliperID"], p["WheelBundleName"]) for p in presets]
    group = unlocks["AllUnlockables"]["carPaintIDs"]
    filtered = [v for v in group if v != -1]
    catalogue_paints = {v["numeric_id"] for v in (catalog or {}).get("individual_source_ids", []) if v["slot"] == "paint"}
    result = {
        "status": "current_bundle_extracted_runtime_index_unresolved",
        "bundle_sha256": hashlib.sha256(content).hexdigest(), "bundle_bytes": len(content),
        "unityfs_version": 6, "serialized_file_version": 17,
        "network_requests": 0, "gameplay_reads": 0, "production_mapping_changed": False,
        "current_visual": {
            "base_arrays": {key: car[key] for key in ARCHIVED_BASE},
            "gacha_configs": presets, "lock_paints_to_index": car["lockPaintsToIndex"],
            "has_own_livery": bool(car["HasOwnLivery"]),
        },
        "archive_comparison": {
            "source": "Nitro4CSR/CSR2-DataBase Everything/x.CarVisualConfigs/ConfigFiles/Ford_Mustang302_1970.txt",
            "source_blob_sha1": "e9bb0570d3770e009615920238cedb5f1a736f5e",
            "all_base_arrays_equal": all(base_match.values()),
            "base_field_matches": base_match,
            "gacha_count_current": len(presets),
            "gacha_count_archive": len(ARCHIVED_PRESETS),
            "gacha_paint_interior_calliper_wheel_order_equal": compact_presets == ARCHIVED_PRESETS,
            "lock_paints_to_index_equal": car["lockPaintsToIndex"] == 0,
        },
        "other_current_visual_configuration": {
            "unlockable_milestone_count": len(unlocks["UnlockableMilestones"]),
            "all_unlockables_paint_raw": group,
            "all_unlockables_paint_without_separators": filtered,
            "all_unlockables_paint_distinct_count": len(set(filtered)),
            "all_unlockables_interior_ids": unlocks["AllUnlockables"]["carInteriorIDs"],
            "all_unlockables_calliper_ids": unlocks["AllUnlockables"]["carCalliperIDs"],
            "all_unlockables_wheel_names": unlocks["AllUnlockables"]["wheelBundleNames"],
        },
        "received_paint_index_15": {
            "within_current_base_paint_array": 15 < len(car["CarPaintIDs"]),
            "base_array_candidate": None,
            "raw_unlockables_array_at_15": group[15] if len(group) > 15 else None,
            "hypothetical_filtered_unlockables_at_15": filtered[15] if len(filtered) > 15 else None,
            "hypothetical_lookup_verified": False,
            "runtime_paint_list_order_verified": False,
            "crew_value_to_paint_id_verified": False,
        },
    }
    if catalog is not None:
        result["source_catalogue"] = {"database_version": catalog.get("database_version"),
            "all_unlockable_paint_ids_present": all(p in catalogue_paints for p in filtered),
            "matched_paint_ids": sum(p in catalogue_paints for p in filtered),
            "total_unlockable_paint_ids": len(filtered)}
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Inspect a local CSR2 5.x UnityFS CarVisuals bundle (offline)")
    p.add_argument("--bundle", required=True, type=Path)
    p.add_argument("--source-catalog", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    if args.bundle.is_symlink() or not args.bundle.is_file() or args.bundle.stat().st_size > MAX_BUNDLE:
        p.error("--bundle must be a bounded, regular, non-symlinked file")
    if args.output.exists():
        p.error("--output already exists; refusing overwrite")
    catalog = None
    if args.source_catalog:
        if args.source_catalog.is_symlink() or args.source_catalog.stat().st_size > MAX_BUNDLE:
            p.error("--source-catalog invalid")
        catalog = json.loads(args.source_catalog.read_text())
    report = inspect_bundle(args.bundle.read_bytes(), catalog)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"Verified Unity asset report: {args.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
