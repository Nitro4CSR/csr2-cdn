"""Offline CSR2 customization metadata inventory and explicitly sourced candidate lookups.

The APK's bundled ``*.metadata`` files are binary NMG blocks, not JSON lookup
rows. We inspect their presence and SHA256 but do NOT pretend to decode them.
Any optional named cosmetic candidate must be independently supplied with an
exact model/slot/ID and a provenance digest. A matching digest demonstrates
that the cited *file* is present in an APK; it cannot validate the proposed
semantic mapping or user-interface label. No HTTP, account state, or writes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple
from zipfile import BadZipFile, ZipFile

# Actual names in the local CSR2 6.8.0 APK, not guessed server endpoints.
CUSTOMIZATION_BLOCKS = (
    "CarCustomizationParameters", "CarAftermarketCustomisations",
    "CarLiveriesMatrix", "CarPresets", "CarAdditionalVisuals",
    "AftermarketConfig", "HypermodMaterialsConfig",
)
SLOT_FIELDS = {
    "calliper": "calliper_id", "interior": "interior_id",
    "livery": "livery_id", "livery_zones_set": "livery_zones_set_id",
    "paint": "paint_id", "wheel": "wheel_name",
    "decal_flag": "decal_flag_id", "decal_number": "decal_number_id",
    "decal_number_color": "decal_number_color_id",
    "decal_number_shape_color": "decal_number_shape_color_id",
    "decal_number_zone": "decal_number_zone_id",
    "decal_numberplate_style": "decal_numberplate_style_id",
}
MAX_BLOCK_BYTES = 8 * 1024 * 1024
MAX_APK_FILE_BYTES = 800 * 1024 * 1024
MAX_MAP_ROWS = 20000


def inspect_customization_apk(apk_path: str | Path) -> dict[str, Any]:
    """Inspect the seven allowlisted 6.8.0 metadata block files only.

    This is a binary *inventory*, not a decoder, nor a claim that the APK
    version is 6.8.0. Fails closed on ZIP corruption and oversized blocks.
    """
    path = Path(apk_path)
    if not path.is_file() or path.stat().st_size > MAX_APK_FILE_BYTES:
        raise ValueError("APK must be a local bounded regular file")
    results = {}
    try:
        with ZipFile(path) as apk:
            for name in CUSTOMIZATION_BLOCKS:
                target = "assets/Media/Metadata/" + name + ".metadata"
                try:
                    info = apk.getinfo(target)
                except KeyError:
                    results[name] = {"present": False}
                    continue
                if info.file_size > MAX_BLOCK_BYTES or info.file_size < 5:
                    raise ValueError("customization metadata block exceeds bounds")
                with apk.open(info) as handle:
                    data = handle.read(MAX_BLOCK_BYTES + 1)
                if len(data) != info.file_size:
                    raise ValueError("customization metadata length mismatch")
                results[name] = {
                    "present": True,
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "format": "binary_nmg_unparsed" if data.startswith(b"\x00$Nmg") else "unknown_unparsed",
                }
    except (BadZipFile, OSError, RuntimeError, EOFError) as exc:
        raise ValueError("local APK archive cannot be inspected") from None
    return {"status": "apk_binary_inventory_only", "network_requests": 0,
            "semantic_mappings_verified": False, "blocks": results}


def _short(value: Any, length: int = 180) -> bool:
    return (type(value) is str and bool(value) and len(value) <= length and
            value == value.strip() and not any(ord(c) < 32 or ord(c) == 127 for c in value))


@dataclass(frozen=True)
class CosmeticCandidate:
    """One exact mapping hypothesis supplied with explicit provenance.

    The label is deliberately never verified simply by loading an APK digest.
    """
    car_db_name: str = field(repr=False)
    slot: str = ""
    value: int | str = 0
    label_candidate: str = field(default="", repr=False)
    source_block: str = ""
    source_sha256: str = ""
    source_record_path: str = field(default="", repr=False)


@dataclass(frozen=True)
class CosmeticCandidateCatalog:
    """Operator-supplied normalized candidates, NOT an NMG block decoder."""
    records: Tuple[CosmeticCandidate, ...] = field(default_factory=tuple, repr=False)
    apk_block_digests_confirmed: bool = False

    @classmethod
    def from_manifest(cls, data: Any, *, apk_inventory: Optional[Mapping[str, Any]] = None) -> "CosmeticCandidateCatalog":
        if not isinstance(data, Mapping) or data.get("format") != "csr2cdn.cosmetic-candidates.v1":
            raise ValueError("unrecognized cosmetic candidate manifest format")
        rows = data.get("records")
        if not isinstance(rows, list) or len(rows) > MAX_MAP_ROWS:
            raise ValueError("cosmetic candidates must be a bounded records list")
        sources = None
        if apk_inventory is not None:
            if not isinstance(apk_inventory, Mapping) or apk_inventory.get("status") != "apk_binary_inventory_only":
                raise ValueError("invalid APK customization inventory")
            sources = apk_inventory.get("blocks")
            if not isinstance(sources, Mapping):
                raise ValueError("APK customization inventory missing blocks")
        parsed = []
        seen = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("invalid candidate row")
            name, slot, value = row.get("car_db_name"), row.get("slot"), row.get("id")
            label, source, sha, source_path = (row.get("label"), row.get("source_block"),
                                                row.get("source_sha256"), row.get("source_record_path"))
            if not _short(name) or type(slot) is not str or slot not in SLOT_FIELDS:
                raise ValueError("invalid cosmetic car or slot")
            if slot == "wheel":
                if not _short(value):
                    raise ValueError("wheel key must be a nonempty string")
            elif type(value) is not int or not 0 <= value < 2**31:
                raise ValueError("numeric cosmetic ID must be a nonnegative integer")
            if not _short(label, 120) or type(source) is not str or source not in CUSTOMIZATION_BLOCKS or not _short(source_path, 220):
                raise ValueError("invalid label or source provenance")
            if not (type(sha) is str and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)):
                raise ValueError("source SHA256 required as 64 lowercase hex chars")
            key = (name, slot, value)
            if key in seen:
                raise ValueError("ambiguous duplicate cosmetic candidate")
            seen.add(key)
            if sources is not None:
                block = sources.get(source)
                if not isinstance(block, Mapping) or block.get("present") is not True or block.get("sha256") != sha:
                    raise ValueError("candidate source block SHA256 does not match local APK")
            parsed.append(CosmeticCandidate(name, slot, value, label, source, sha, source_path))
        return cls(tuple(parsed), sources is not None)

    def match(self, model_key: Optional[str], slot: str, value: Any) -> Optional[CosmeticCandidate]:
        if not _short(model_key) or type(slot) is not str or slot not in SLOT_FIELDS:
            return None
        return next((x for x in self.records if x.car_db_name == model_key and
                     x.slot == slot and type(x.value) is type(value) and x.value == value), None)


def cosmetic_coverage_report(snapshot: Any, catalog: CosmeticCandidateCatalog, *,
                             show_members: bool = False) -> dict[str, Any]:
    """Coverage for observed roster appearance IDs; opt-in to expose labels.

    Missing source rows remain unresolved. A checksum match is not a semantic
    verification. No names, IDs or labels in the default report.
    """
    if not isinstance(catalog, CosmeticCandidateCatalog):
        raise TypeError("expected CosmeticCandidateCatalog")
    slot_present = {s: 0 for s in SLOT_FIELDS}
    slot_matched = {s: 0 for s in SLOT_FIELDS}
    per_member = []
    for member in snapshot.members:
        app = member.vehicle.appearance
        found = {}
        for slot, attr in SLOT_FIELDS.items():
            value = getattr(app, attr) if app is not None else None
            if value is None:
                continue
            slot_present[slot] += 1
            match = catalog.match(member.vehicle.model_key, slot, value)
            if match is not None:
                slot_matched[slot] += 1
                if show_members:
                    found[slot] = {"label_candidate": match.label_candidate,
                                   "source_block": match.source_block,
                                   "verified_in_game": False}
        if show_members:
            per_member.append(found)
    report = {
        "status": "operator_supplied_cosmetic_candidates_unverified",
        "manifest_records": len(catalog.records),
        "roster_rows": len(snapshot.members),
        "apk_block_digests_confirmed": catalog.apk_block_digests_confirmed,
        "labels_verified_in_game": False,
        "source_record_semantics_verified": False,
        "slot_present": slot_present,
        "slot_exact_candidate_matches": slot_matched,
        "network_requests": 0,
    }
    if show_members:
        report["member_label_candidates"] = per_member
    return report


def main(argv: Optional[list[str]] = None) -> int:
    """Offline inspection of APK metadata fingerprints, no decoding or I/O to servers."""
    import argparse
    import json
    p = argparse.ArgumentParser(description="Inspect local APK customization metadata fingerprints offline")
    p.add_argument("--apk", help="path to locally held CSR2 APK (not uploaded or modified)")
    args = p.parse_args(argv)
    if not args.apk:
        print(json.dumps({"mode": "dry_run", "network_requests": 0,
                          "target_blocks": list(CUSTOMIZATION_BLOCKS), "labels_decoded": False}))
        return 0
    try:
        print(json.dumps(inspect_customization_apk(args.apk), indent=2))
        return 0
    except (ValueError, OSError):
        print(json.dumps({"status": "apk_inspection_unavailable", "details": "suppressed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
