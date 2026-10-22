"""Bounded, privacy-safe TNR/Tuner Stars cosmetic hypothesis probe.

The roster's model key and wheel code are used transiently to assess cohort
coverage.  No individual model, wheel string, crew/player identifier, or server
response is retained in the output.  This module does zero I/O on import.

Native semantics NOT asserted: TNR-like model codes do not prove the associated
Tuner Stars library is the game's source for that model's cosmetics.  The
published standard libraries cannot decode the other Tuner Stars libraries yet.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
import getpass
import json
from pathlib import Path
import re
import sys
from typing import Any, Optional

from .cdn import CDN
from .crew_optional_data import CrewOptionalSnapshot
from .database import AssetDatabase
from .game_labels import GameVisualLibrary
from .service_models import CrewMembers, OwnCrew
from .services import CSR2Services, ServiceHTTPError
from .visual_library_bundle import load_visual_libraries_unityfs

# These are *actual* asset codes in the 6.8.0 asset database, not endpoints.
TUNER_ASSETS = (
    "CarTunerStarsPaintLibrary",
    "CarTunerStarsInteriorLibrary",
    "CarTunerStarsCalliperLibrary",
    "CarTunerStarsLiveryLibrary",
    "CarTunerStarsRimLibrary",
    "CarTunerStarsTireLibrary",
    "CarTunerStarsBoostColorLibrary",
    "CarTunerStarsLiverySetLibrary",
    "TunerStarsLiveryZonesSetLibrary",
)
# Match game model tokens, not arbitrary substring "tnr" in another word.
_TNR_MODEL = re.compile(r"TNR(?:[0-9]+)?_(?:19|20)[0-9]{2}(?:_|$)", re.ASCII)
_SAFE_VERSION = re.compile(r"[0-9]{1,12}\Z", re.ASCII)
_STORED_FIELDS = {
    "paint": "paint_id", "interior": "interior_id",
    "calliper": "calliper_id", "livery": "livery_id",
    "livery_zones_set": "livery_zones_set_id",
    "wheel": "wheel_name", "decal_number_color": "decal_number_color_id",
    "decal_number_shape_color": "decal_number_shape_color_id",
    "decal_number_zone": "decal_number_zone_id",
}
_KNOWN_JOINS = frozenset(("paint", "interior", "calliper", "livery", "livery_zones_set"))
_TNR_COMPARISON_LIBRARIES = {
    "paint": ("CarPaintLibrary", "CarTunerStarsPaintLibrary"),
    "interior": ("CarInteriorLibrary", "CarTunerStarsInteriorLibrary"),
    "calliper": ("CarCalliperLibrary", "CarTunerStarsCalliperLibrary"),
}

_MAX_DATABASE = 32 * 1024 * 1024
_MAX_LOCAL_JSON = 8 * 1024 * 1024


@dataclass(frozen=True)
class TNRAssetEntry:
    code: str
    version: Optional[str]
    size_bytes: Optional[int]
    url: Optional[str]

    @property
    def available(self) -> bool:
        return self.url is not None

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "version": self.version,
                "size_bytes": self.size_bytes, "url": self.url,
                "decoder_status": ("primary_ids_decoded_join_candidate"
                                   if self.code in ("CarTunerStarsPaintLibrary", "CarTunerStarsInteriorLibrary", "CarTunerStarsCalliperLibrary")
                                   else ("standalone_rim_decoded_join_unverified"
                                         if self.code == "CarTunerStarsRimLibrary"
                                         else "native_source_schema_pending"))}


@dataclass(frozen=True)
class TNRAssetPlan:
    entries: tuple[TNRAssetEntry, ...]
    database_version: str
    platform: str = "ANDROID"
    quality: str = "ASTC"

    @property
    def found(self) -> int:
        return sum(entry.available for entry in self.entries)

    def as_dict(self) -> dict[str, Any]:
        return {"database_version": self.database_version,
                "platform": self.platform, "quality": self.quality,
                "available": self.found, "expected": len(TUNER_ASSETS),
                "assets": [entry.as_dict() for entry in self.entries]}


def plan_tnr_assets(database: AssetDatabase) -> TNRAssetPlan:
    """Use exact local index entries; never invent URLs for absent versions."""
    if not isinstance(database, AssetDatabase):
        raise TypeError("AssetDatabase required")
    cdn = CDN(platform="ANDROID", quality="ASTC")
    entries = []
    for code in TUNER_ASSETS:
        asset = database.assets.get(code)
        version = str(asset.version) if asset is not None else None
        size = asset.size("ASTC") if asset is not None else None
        if (version is not None and _SAFE_VERSION.fullmatch(version)
                and type(size) is int and 0 < size < 8 * 1024 * 1024):
            entries.append(TNRAssetEntry(code, version, size,
                cdn.asset_url(code, version, platform="ANDROID", quality="ASTC")))
        else:
            entries.append(TNRAssetEntry(code, None, None, None))
    dbv = str(database.version)
    if not _SAFE_VERSION.fullmatch(dbv):
        dbv = "unverified"
    return TNRAssetPlan(tuple(entries), dbv)


def is_tnr_model(model_key: Optional[str]) -> bool:
    return isinstance(model_key, str) and len(model_key) <= 256 and bool(_TNR_MODEL.search(model_key))


def _cohort_counter() -> dict[str, Any]:
    return {"members": 0, "tnr_model_syntax": False,
            "model_wheel_assets_found_members": 0, "model_wheel_assets_missing_members": 0,
            "slot_coverage": {slot: {"present": 0, "resolved_in_standard_library": 0,
                                     "tnr_library_id_candidate": 0, "unresolved": 0, "join_unverified": slot not in _KNOWN_JOINS}
                              for slot in _STORED_FIELDS}}


def assess_tnr_snapshot(snapshot: CrewOptionalSnapshot, database: AssetDatabase,
                        visual_library: Optional[GameVisualLibrary] = None,
                        *, show_unmatched_numeric_ids: bool = False) -> dict[str, Any]:
    """Pure aggregate analysis; never returns roster identifiers or wheel strings.

    For TNR syntax, the model-specific asset evidence checks *only* whether an
    exact model prefix plus `_Wheel` appears in the supplied asset database.
    This does not prove a join to the returned wheel name or to Tuner Stars rims.
    """
    if not isinstance(snapshot, CrewOptionalSnapshot) or not isinstance(database, AssetDatabase):
        raise TypeError("typed snapshot and asset database required")
    if visual_library is not None and not isinstance(visual_library, GameVisualLibrary):
        raise TypeError("visual source must be GameVisualLibrary")
    if type(show_unmatched_numeric_ids) is not bool:
        raise TypeError("show_unmatched_numeric_ids must be boolean")
    if len(snapshot.members) > 30:
        raise ValueError("crew roster exceeds 30 members")
    asset_codes = {asset.code for asset in database.assets}
    # Cohorts use *only* model-key syntax. Any unusual/absent model is counted
    # outside TNR rather than claiming the game doesn't use Tuner Stars parts.
    cohorts = {"tnr_model_syntax": _cohort_counter(), "other_or_unknown_model": _cohort_counter()}
    ids: dict[str, dict[str, Counter[int]]] = {
        key: {slot: Counter() for slot in _STORED_FIELDS} for key in cohorts}
    for member in snapshot.members:
        vehicle = member.vehicle
        model = vehicle.model_key
        cohort_name = "tnr_model_syntax" if is_tnr_model(model) else "other_or_unknown_model"
        counter = cohorts[cohort_name]
        counter["members"] += 1
        counter["tnr_model_syntax"] = cohort_name == "tnr_model_syntax"
        # Exact asset prefix, not a fuzzy name join or a downloaded wheel object.
        has_wheel_asset = (type(model) is str and len(model) <= 256 and
            any(code.startswith(f"{model}_Wheel") for code in asset_codes))
        counter["model_wheel_assets_found_members" if has_wheel_asset else
                "model_wheel_assets_missing_members"] += 1
        appearance = vehicle.appearance
        for slot, field_name in _STORED_FIELDS.items():
            raw = getattr(appearance, field_name) if appearance is not None else None
            if raw is None:
                continue
            slot_counts = counter["slot_coverage"][slot]
            slot_counts["present"] += 1
            match = (visual_library.match(model, slot, raw)
                     if slot in _KNOWN_JOINS and visual_library is not None else None)
            if match is not None and not match.source_library.startswith('CarTunerStars'):
                slot_counts["resolved_in_standard_library"] += 1
            elif (match is not None and match.source_library.startswith('CarTunerStars')
                  and is_tnr_model(model)):
                # Observed high-ID record and model/category candidate, *not*
                # independent proof of the game's cosmetic join semantics.
                slot_counts["tnr_library_id_candidate"] += 1
            else:
                slot_counts["unresolved"] += 1
                if show_unmatched_numeric_ids and type(raw) is int:
                    ids[cohort_name][slot][raw] += 1
    if show_unmatched_numeric_ids:
        for cohort_name, slot_counters in ids.items():
            for slot, missing in slot_counters.items():
                cohorts[cohort_name]["slot_coverage"][slot]["unmatched_numeric_ids"] = [
                    {"id": identifier, "occurrences": count}
                    for identifier, count in sorted(missing.items())]
    return {
        "status": "read_only_tnr_source_hypothesis_unverified",
        "member_count": len(snapshot.members),
        "identities_distinct": snapshot.identity_complete,
        "roster_matches_own_crew": snapshot.roster_count_matches_own_crew,
        "source_database_version": (str(database.version) if _SAFE_VERSION.fullmatch(str(database.version)) else "unverified"),
        "visual_library_supplied": visual_library is not None,
        "privacy": {"player_names": False, "player_ids": False, "crew_id": False,
                    "model_keys": False, "wheel_strings": False,
                    "unmatched_numeric_ids_opt_in": show_unmatched_numeric_ids,
                    "raw_server_replies_saved": False},
        "cohorts": cohorts,
        "claims": {"tnr_model_syntax_is_game_semantics": False,
                   "model_wheel_asset_exists_proves_roster_wheel_join": False,
                   "standalone_tuner_rim_proves_wheel_join": False,
                   "tuner_stars_cosmetic_ids_verified": True if visual_library is not None and any(r.source_library.startswith("CarTunerStars") and r.slot in _KNOWN_JOINS for r in visual_library.records) else False,
                   "tnr_library_matches_prove_game_ui_equivalence": False,
                   "standard_library_misses_may_be_tuner_variants": True},
    }


def assess_tnr_resolution_comparison(
    snapshot: CrewOptionalSnapshot,
    visual_library: GameVisualLibrary,
) -> dict[str, Any]:
    """Compare official standard vs. Tuner Stars ID matches, offline only.

    Requires all six individually decoded source libraries. A TNR match on a
    TNR-looking model is an ID/name **candidate**, not a verified in-game join.
    Neither wheel strings nor other source fields are emitted in the result.
    """
    if not isinstance(snapshot, CrewOptionalSnapshot) or not isinstance(visual_library, GameVisualLibrary):
        raise TypeError("typed snapshot and decoded visual library required")
    if len(snapshot.members) > 30:
        raise ValueError("crew roster exceeds 30 members")
    required = {x for pair in _TNR_COMPARISON_LIBRARIES.values() for x in pair}
    observed = {record.source_library for record in visual_library.records}
    if not required.issubset(observed):
        raise ValueError("six standard and TNR libraries required for fair comparison")
    # Scope each lookup by its *declared source*, never by raw numeric range.
    # Model-specific records take precedence over global records in match().
    source_libraries = {
        name: GameVisualLibrary(tuple(record for record in visual_library.records
                                      if record.source_library == name))
        for name in required
    }
    result = {
        "status": "source_id_matches_only_ui_unverified",
        "comparison_libraries": sorted(required),
        "members": len(snapshot.members),
        "cohorts": {},
        "ui_accuracy_verified": False,
        "tnr_model_classification_verified": False,
        "tnr_auxiliary_eligibility_verified": False,
        "network_requests": 0,
        "privacy": {"player_ids": False, "player_names": False,
                    "model_keys": False, "raw_codes": False, "wheel_strings": False},
    }
    for cohort in ("tnr_model_syntax", "other_or_unknown_model"):
        result["cohorts"][cohort] = {
            "members": 0,
            "slots": {slot: {
                "present": 0, "standard_matches": 0,
                "new_tnr_id_candidates": 0,
                "tnr_id_candidates_outside_tnr_models": 0,
                "ambiguous_cross_library_ids": 0,
                "still_unresolved": 0,
                "candidate_matches_after": 0,
            } for slot in _TNR_COMPARISON_LIBRARIES},
        }
    for member in snapshot.members:
        vehicle = member.vehicle
        cohort = "tnr_model_syntax" if is_tnr_model(vehicle.model_key) else "other_or_unknown_model"
        group = result["cohorts"][cohort]
        group["members"] += 1
        for slot, (standard_name, tnr_name) in _TNR_COMPARISON_LIBRARIES.items():
            field_name = _STORED_FIELDS[slot]
            raw = getattr(vehicle.appearance, field_name) if vehicle.appearance else None
            if raw is None:
                continue
            counts = group["slots"][slot]
            counts["present"] += 1
            original = source_libraries[standard_name].match(vehicle.model_key, slot, raw)
            tnr = source_libraries[tnr_name].match(vehicle.model_key, slot, raw)
            if original is not None and tnr is not None:
                counts["ambiguous_cross_library_ids"] += 1
                # A collision is not a valid success, even if the names agree.
                counts["still_unresolved"] += 1
            elif original is not None:
                counts["standard_matches"] += 1
                counts["candidate_matches_after"] += 1
            elif tnr is not None and cohort == "tnr_model_syntax":
                counts["new_tnr_id_candidates"] += 1
                counts["candidate_matches_after"] += 1
            elif tnr is not None:
                # An All-category TNR row can have the same ID even on a car
                # that is *not* recognized as a TNR model. Never promote it.
                counts["tnr_id_candidates_outside_tnr_models"] += 1
                counts["still_unresolved"] += 1
            else:
                counts["still_unresolved"] += 1
            if counts["present"] != (counts["candidate_matches_after"] +
                                     counts["still_unresolved"]):
                raise AssertionError("visual accounting error")
    totals = {slot: {
        field: sum(result["cohorts"][cohort]["slots"][slot][field]
                   for cohort in result["cohorts"])
        for field in next(iter(result["cohorts"].values()))["slots"][slot]}
        for slot in _TNR_COMPARISON_LIBRARIES}
    result["totals"] = totals
    return result


def _load_local_database(path: str) -> AssetDatabase:
    p = Path(path)
    if not p.is_file() or not 128 <= p.stat().st_size <= _MAX_DATABASE:
        raise ValueError("invalid asset database file size")
    return AssetDatabase.loads(p.read_bytes())


def _load_json(path: str) -> Any:
    p = Path(path)
    if not p.is_file() or not 2 <= p.stat().st_size <= _MAX_LOCAL_JSON:
        raise ValueError("invalid offline fixture")
    return json.loads(p.read_text(encoding="utf-8-sig"))


def main(argv: Optional[list[str]] = None, *, services_factory=CSR2Services) -> int:
    parser = argparse.ArgumentParser(description="Privacy-safe TNR visual investigation (2 reads maximum; dry run by default)")
    parser.add_argument("--asset-database", help="local asset_database_* (6.8.0 or newer)")
    parser.add_argument("--visual-asset-bundle", action="append", default=[],
                        help="previously downloaded ASTC visual library; repeat for each")
    parser.add_argument("--execute", action="store_true", help="opt in to TWO read-only game service calls")
    parser.add_argument("--own-json", help="offline response fixture; requires --members-json")
    parser.add_argument("--members-json", help="offline response fixture; requires --own-json")
    parser.add_argument("--compare-standard-tnr", action="store_true",
                        help="compare all 3 standard and 3 TNR source libraries; require all six inputs")
    parser.add_argument("--show-unmatched-numeric-ids", action="store_true",
                        help="explicitly include distinct raw numeric codes and counts; never names, models, or wheel strings")
    parser.add_argument("--output", help="save sanitized JSON report to this file")
    args = parser.parse_args(argv)
    if args.execute and (args.own_json or args.members_json):
        parser.error("--execute cannot be combined with offline server fixtures")
    if bool(args.own_json) != bool(args.members_json):
        parser.error("both offline response fixtures are required")
    if (args.execute or args.own_json) and not args.asset_database:
        parser.error("--asset-database required for analysis")
    if not args.execute and not args.own_json:
        report = {"status": "dry_run", "network_requests": 0,
                  "planned_live_requests": 2,
                  "contracts": ["crews/checkUserCrew", "crews/viewMembers"],
                  "privacy": "no IDs/names/model keys/wheel strings printed",
                  "purpose": "compare standard misses with source-backed TNR ID candidates; no speculative wheel/color joins",
                  "standard_tnr_comparison_requested": args.compare_standard_tnr}
        print(json.dumps(report, indent=2))
        return 0
    if args.output and (Path(args.output).exists() or not Path(args.output).parent.is_dir()):
        parser.error("output path must not exist and its parent must be a directory")
    if args.execute and not sys.stdin.isatty():
        print(json.dumps({"status": "interactive_terminal_required", "network_requests": 0}))
        return 2
    try:
        # Validate ALL local inputs before an authorized network operation.
        db = _load_local_database(args.asset_database)
        visuals = load_visual_libraries_unityfs(args.visual_asset_bundle) if args.visual_asset_bundle else None
        if args.compare_standard_tnr:
            if visuals is None:
                raise ValueError("six decoded sources required before network reads")
            required = {x for pair in _TNR_COMPARISON_LIBRARIES.values() for x in pair}
            if not required.issubset({r.source_library for r in visuals.records}):
                raise ValueError("required standard or TNR source library missing")
        if args.own_json:
            own_json = _load_json(args.own_json)
            members_json = _load_json(args.members_json)
        if args.execute:
            player_id = getpass.getpass("Own CSR2 PlayerID (hidden): ").strip()
            if not player_id:
                raise ValueError("PlayerID required")
            with services_factory(player_id, allow_network=True) as service:
                own_json = service._read(service.prepare_my_crew())
                own = OwnCrew.from_response(own_json)
                if not own.crew_uid:
                    raise ValueError("own crew unavailable")
                members_json = service._read(service.prepare_crew_members(own.crew_uid))
        own = OwnCrew.from_response(own_json)
        members = CrewMembers.from_response(own.crew_uid, members_json)
        snapshot = CrewOptionalSnapshot.from_reads(own, members)
        report = assess_tnr_snapshot(snapshot, db, visuals,
            show_unmatched_numeric_ids=args.show_unmatched_numeric_ids)
        report["tuner_stars_asset_plan"] = plan_tnr_assets(db).as_dict()
        if args.compare_standard_tnr:
            report["standard_tnr_comparison"] = assess_tnr_resolution_comparison(snapshot, visuals)
        report["mode"] = "authorized_read_only" if args.execute else "offline_replay"
        report["gameplay_read_count"] = 2 if args.execute else 0
        if args.output:
            path = Path(args.output)
            if path.exists():
                raise ValueError("refusing to overwrite an existing report")
            with path.open("x", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except ServiceHTTPError as exc:
        status = exc.status_code if type(exc.status_code) is int else None
        print(json.dumps({"status": "http_error", "status_code": status,
                          "details": "suppressed"}))
        return 1
    except (Exception, KeyboardInterrupt):
        print(json.dumps({"status": "tnr_probe_unavailable", "details": "suppressed"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
