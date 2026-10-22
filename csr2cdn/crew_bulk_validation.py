"""One-round, read-only 0.7.1 investigation of optional data + GCC ranges.

Dry-run by default. A future operator-authorized live invocation performs
exactly four existing authenticated reads (own crew, roster, common GCC and
one bounded exploratory GCC range). Each feature reports its own outcome so
unsupported ideas can be pruned from the next development build.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import json
from pathlib import Path
import sys
from typing import Any, Optional

from ._service_reads import StandingRange, ReadContractError, gcc_progress_range_contract
from .crew_optional_data import CrewOptionalSnapshot, optional_report
from .game_labels import (CarNameStyle, GameCarTranslations, GameVisualLibrary,
                          game_label_report, metadata_library_inventory)
from .crew_rp import CrewRPSnapshot
from .bulk_review import BulkUIReference, review_bulk_evidence
from .gcc_range_probe import report as gcc_range_report, compare_responses
from .service_models import OwnCrew, CrewMembers, GCCProgressCrewScores, ServiceResponseError
from .services import CSR2Services, ServiceHTTPError

_MAX_INPUT_BYTES = 8 * 1024 * 1024


def bulk_report(own_response: Any, roster_response: Any, gcc_default_response: Any,
                gcc_experimental_response: Any, *, ranges: StandingRange,
                show_stat_values: bool = False, show_members: bool = False,
                print_gcc_entries: bool = False,
                member_read_utc: Optional[datetime] = None,
                gcc_read_utc: Optional[datetime] = None,
                read_errors: Optional[dict[str, dict[str, Any]]] = None,
                car_catalog=None, cosmetic_catalog=None, game_names=None,
                game_visuals=None, car_name_style: CarNameStyle | str = CarNameStyle.MEDIUM,
                metadata_inventory=None, visual_source_shapes=None,
                ui_reference: Optional[BulkUIReference] = None,
                show_unmatched_visual_ids: bool = False) -> dict[str, Any]:
    """Offline-only comparison; feature failures are reported separately.

    Personal identifiers are used *only* to join records in memory. Nothing
    writes raw JSON. A single report never claims that the server honored the
    expanded range or that any optional field has verified units.
    """
    read_errors = read_errors or {}
    own = OwnCrew.from_response(own_response)
    if not own.crew_uid:
        raise ServiceResponseError("own crew missing")
    members = CrewMembers.from_response(own.crew_uid, roster_response)
    optional = CrewOptionalSnapshot.from_reads(own, members)
    # Reuse the same typed attribute-first view in all offline projections.
    if game_names is not None:
        optional = optional.with_translations(game_names, style=car_name_style)
    if game_visuals is not None:
        optional = optional.with_visuals(game_visuals)
    result: dict[str, Any] = {
        "status": ("bulk_partial_read" if read_errors else
                   "bulk_candidate_evidence_not_yet_live_verified"),
        "contracts": ["crews/checkUserCrew", "crews/viewMembers",
                      "leaderboard/crew-champs-v2/viewcrew (common)",
                      "leaderboard/crew-champs-v2/viewcrew (experimental range)"],
        "network_requests_for_offline_decoder": 0,
        "raw_replies_saved": False,
        "member_details_printed": bool(show_members),
        "optional": optional_report(optional, show_values=show_stat_values,
                                    show_members=show_members, car_catalog=car_catalog,
                                    cosmetic_catalog=cosmetic_catalog),
        "gcc": {},
        "feature_decisions": {
            "optional_stats": "candidate_only",
            "vehicle_details": "candidate_only",
            "crew_presentation": "candidate_only",
            "vehicle_appearance": "candidate_only",
            "vehicle_catalogue": "offline_source_candidate" if car_catalog is not None else "not_supplied",
            "cosmetic_labels": "unverified_manifest_candidate" if cosmetic_catalog is not None else "not_supplied",
            "tournament_shape": "candidate_only",
            "gcc_expanded_range": "candidate_only",
        },
    }
    if game_names is not None or game_visuals is not None:
        result["game_labels"] = game_label_report(
            optional, names=game_names, visuals=game_visuals,
            style=car_name_style, show_members=show_members)
        result["feature_decisions"]["game_translation_names"] = "offline_decoded_source_candidate"
        result["feature_decisions"]["visual_library_names"] = "offline_decoded_source_candidate"
    if game_visuals is not None:
        from .visual_gap_diagnostics import analyze_visual_gaps
        result["visual_gap_diagnostics"] = analyze_visual_gaps(
            optional, game_visuals,
            show_unmatched_ids=show_unmatched_visual_ids).as_dict()
    if metadata_inventory is not None:
        result["metadata_cdn_inventory"] = metadata_inventory
    if visual_source_shapes is not None:
        result["visual_source_shapes"] = visual_source_shapes
    # The crew-wide `crew_rp` is not equivalent to the season GCC score.
    default: Optional[GCCProgressCrewScores] = None
    try:
        if "common" in read_errors:
            raise ServiceResponseError("common GCC request unavailable")
        default = GCCProgressCrewScores.from_response(gcc_default_response)
        own_rows = [c for c in default.crews if c.crew_id == own.crew_uid]
        gcc_report: dict[str, Any] = {
            "status": "decoded_common_gcc",
            "rows": len(default.crews),
            "own_crew_exact_id_matches": len(own_rows),
            "own_crew_rank": own_rows[0].rank if len(own_rows) == 1 else None,
            "own_crew_score": own_rows[0].score if len(own_rows) == 1 else None,
        }
        if member_read_utc is not None and gcc_read_utc is not None:
            expected = optional.crew.members
            snapshot = CrewRPSnapshot.from_reads(
                members, default, own_crew_id=own.crew_uid,
                member_read_utc=member_read_utc,
                gcc_read_utc=gcc_read_utc,
                now_utc=gcc_read_utc,
                expected_member_count=expected if expected is not None else None)
            gcc_report["roster_gcc_comparable"] = snapshot.comparable
            gcc_report["roster_gcc_delta"] = snapshot.delta
            gcc_report["roster_gcc_warnings"] = list(snapshot.warnings)
        result["gcc"]["common"] = gcc_report
    except (ServiceResponseError, ValueError):
        result["gcc"]["common"] = (read_errors.get("common") or
                                     {"status": "unrecognized_schema", "details": "suppressed"})
        result["feature_decisions"]["gcc_common"] = "investigate"
    try:
        if "experimental" in read_errors:
            raise ServiceResponseError("experimental GCC request unavailable")
        expanded = gcc_range_report(gcc_experimental_response, ranges=ranges,
                                    own_crew_id=own.crew_uid,
                                    print_entries=print_gcc_entries)
        result["gcc"]["experimental"] = expanded
        if default is not None:
            result["gcc"]["common_vs_experimental"] = compare_responses(
                gcc_default_response, gcc_experimental_response)
            # No automatic completeness claim: a server may silently clamp the request.
            result["gcc"]["range_evidence"] = {
                "more_rows_than_common": expanded["rows"] > len(default.crews),
                "common_row_count": len(default.crews),
                "experimental_row_count": expanded["rows"],
                "range_honored_verified": False,
                "offset_pagination_verified": False,
            }
    except (ServiceResponseError, ValueError, KeyError):
        result["gcc"]["experimental"] = (read_errors.get("experimental") or
                                           {"status": "unrecognized_schema", "details": "suppressed"})
        result["feature_decisions"]["gcc_expanded_range"] = "investigate"
    result["review"] = review_bulk_evidence(result, ui_reference=ui_reference)
    return result


def _safe_read_failure(exc: Exception) -> dict[str, Any]:
    """Capture error category, never server messages, payloads, URLs or credentials."""
    if isinstance(exc, ServiceHTTPError):
        code = exc.status_code
        return {"status": "http_error", "status_code": code if type(code) is int else None,
                "details": "suppressed"}
    return {"status": "read_unavailable", "details": "suppressed"}


def _load_json(path: str) -> Any:
    file = Path(path)
    if file.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError("local fixture too large")
    return json.loads(file.read_text(encoding="utf-8-sig"))


def main(argv: Optional[list[str]] = None, *, services_factory=CSR2Services) -> int:
    parser = argparse.ArgumentParser(description="Offline-first 0.7.1 crew feature batch probe")
    parser.add_argument("--execute", action="store_true", help="opt into exactly four read-only requests")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--before", type=int, default=10)
    parser.add_argument("--after", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--show-stat-values", action="store_true", help="print own-crew and aggregate member counter candidates")
    parser.add_argument("--show-members", action="store_true", help="print private per-member stats, names and vehicles (never account IDs)")
    parser.add_argument("--show-unmatched-visual-ids", action="store_true",
                        help="opt in to distinct unresolved numeric codes and occurrence counts; never wheel strings or player IDs")
    parser.add_argument("--car-catalog-json", help="local HUB TextData/CarData.json; no extra HTTP reads")
    parser.add_argument("--car-translations-json", help="local normalized decoded game translation records (SHORT/MEDIUM/LONG)")
    parser.add_argument("--car-name-style", choices=["SHORT", "MEDIUM", "LONG"], default="MEDIUM",
                        help="preferred translated car name length; default MEDIUM")
    parser.add_argument("--visual-library-json", help="local normalized decoded game visual-code library names")
    parser.add_argument("--visual-asset-bundle", action="append", default=[],
                        help="original Android ASTC paint/livery/interior asset; repeat for multiple files")
    parser.add_argument("--translation-flatbuffer", help="local native translation file; requires a verified layout")
    parser.add_argument("--translation-unityfs", help="local English game localisation asset; read offline")
    parser.add_argument("--translation-layout-json", help="explicit FlatBuffers field layout")
    parser.add_argument("--visual-cache-layout-json", help="explicit visual-code JSON layouts for --metadata-cache-dir")
    parser.add_argument("--metadata-cache-dir", help="existing game Metadata CDN cache; offline inventory, no sync")
    parser.add_argument("--show-metadata-field-names", action="store_true",
                        help="opt in to Metadata CDN schema paths/field names, never raw values")
    parser.add_argument("--cosmetic-manifest-json", help="local normalized candidate labels; not a game-data decoder")
    parser.add_argument("--cosmetic-apk", help="optional local APK used to check manifest source SHA256 values")
    parser.add_argument("--print-gcc-entries", action="store_true", help="print experimental GCC crew names, ranks, scores")
    parser.add_argument("--ui-reference-json", help="optional local bounded UI rank/score/count comparison; no IDs or names")
    parser.add_argument("--own-json")
    parser.add_argument("--members-json")
    parser.add_argument("--gcc-common-json")
    parser.add_argument("--gcc-experimental-json")
    args = parser.parse_args(argv)
    ranges = StandingRange(top=args.top, before=args.before,
                           after=args.after, offset=args.offset)
    try:
        gcc_progress_range_contract(ranges, exploratory=True)
    except ReadContractError as exc:
        parser.error(str(exc))
    paths = (args.own_json, args.members_json,
             args.gcc_common_json, args.gcc_experimental_json)
    if bool(args.translation_flatbuffer) != bool(args.translation_layout_json):
        parser.error("native translation file and layout are required together")
    if sum(bool(x) for x in (args.translation_flatbuffer, args.translation_unityfs, args.car_translations_json)) > 1:
        parser.error("choose one game translation input: UnityFS, FlatBuffers, or normalized JSON")
    if args.show_metadata_field_names and not args.metadata_cache_dir:
        parser.error("--show-metadata-field-names requires --metadata-cache-dir")
    if args.visual_cache_layout_json and (not args.metadata_cache_dir or args.visual_library_json or args.visual_asset_bundle):
        parser.error("visual cache layouts require --metadata-cache-dir without other visual inputs")
    if args.show_unmatched_visual_ids and not (args.visual_asset_bundle or args.visual_library_json or args.visual_cache_layout_json):
        parser.error("--show-unmatched-visual-ids requires a visual library input")
    if args.visual_asset_bundle and args.visual_library_json:
        parser.error("choose original visual asset bundles or a normalized JSON manifest")
    if args.ui_reference_json and not (args.execute or all(paths)):
        parser.error("UI reference requires --execute or all four offline response files")
    if args.execute and any(paths):
        parser.error("--execute cannot be combined with offline files")
    if any(paths) and not all(paths):
        parser.error("offline mode requires all four response files")
    if not args.execute and not all(paths):
        print(json.dumps({"mode": "dry_run", "network_requests": 0,
                          "planned_live_requests": 4,
                          "range": dict(ranges.as_wire_params()),
                          "car_name_style": args.car_name_style,
                          "candidate_semantics_verified": False,
                          "report_sections": ["optional", "gcc", "game_labels", "review"],
                          "ui_reference_format": "csr2cdn.crew-bulk-ui-reference.v1"}, indent=2))
        return 0
    if args.execute and not sys.stdin.isatty():
        print(json.dumps({"status": "interactive_terminal_required", "network_requests": 0}))
        return 2
    try:
        # Resolve and validate every local source before an opt-in live read.
        # A corrupt translation/visual/reference file must not waste four
        # authenticated requests or produce a partial server-data output.
        car_catalog = None
        if args.car_catalog_json:
            from .vehicle_catalog import VehicleCatalog
            car_catalog = VehicleCatalog.from_car_data(_load_json(args.car_catalog_json))
        cosmetic_catalog = None
        if args.cosmetic_apk and not args.cosmetic_manifest_json:
            raise ValueError("cosmetic APK verification requires a manifest")
        if args.cosmetic_manifest_json:
            from .customization_evidence import (CosmeticCandidateCatalog,
                                                  inspect_customization_apk)
            apk_inventory = inspect_customization_apk(args.cosmetic_apk) if args.cosmetic_apk else None
            cosmetic_catalog = CosmeticCandidateCatalog.from_manifest(
                _load_json(args.cosmetic_manifest_json), apk_inventory=apk_inventory)
        from .native_game_sources import load_translation_source, load_visual_source
        from .metadata import MetadataCache
        if args.translation_unityfs:
            from .localisation_bundle import load_localisation_unityfs
            game_names = load_localisation_unityfs(args.translation_unityfs)
        elif args.translation_flatbuffer:
            game_names = load_translation_source(args.translation_flatbuffer, args.translation_layout_json)
        elif args.car_translations_json:
            game_names = GameCarTranslations.from_manifest(_load_json(args.car_translations_json))
        else:
            game_names = None
        if args.visual_asset_bundle:
            from .visual_library_bundle import load_visual_libraries_unityfs
            game_visuals = load_visual_libraries_unityfs(args.visual_asset_bundle)
        elif args.visual_cache_layout_json:
            game_visuals = load_visual_source(MetadataCache(args.metadata_cache_dir), args.visual_cache_layout_json)
        elif args.visual_library_json:
            game_visuals = GameVisualLibrary.from_manifest(_load_json(args.visual_library_json))
        else:
            game_visuals = None
        inventory = None
        if args.metadata_cache_dir:
            from .metadata import MetadataCache
            inventory = metadata_library_inventory(MetadataCache(args.metadata_cache_dir))
        visual_shapes = None
        if args.metadata_cache_dir:
            from .visual_source_recon import inspect_visual_cache
            visual_shapes = inspect_visual_cache(MetadataCache(args.metadata_cache_dir)).report(
                show_field_names=args.show_metadata_field_names)
        reference = None
        if args.ui_reference_json:
            reference_path = Path(args.ui_reference_json)
            if reference_path.stat().st_size > 8192:
                raise ValueError("UI reference too large")
            reference = BulkUIReference.from_mapping(_load_json(args.ui_reference_json))
        if args.execute:
            player_id = getpass.getpass("Your own PlayerID (hidden): ").strip()
            if not player_id:
                raise ValueError("PlayerID required")
            with services_factory(player_id, allow_network=True) as service:
                own_response = service._read(service.prepare_my_crew())
                own = service.decode_my_crew(own_response)
                if not own.crew_uid:
                    raise ServiceResponseError("no active crew")
                roster_response = service._read(service.prepare_crew_members(own.crew_uid))
                member_time = datetime.now(timezone.utc)
                read_errors: dict[str, dict[str, Any]] = {}
                try:
                    common_response = service.get_gcc_progress_response()
                except Exception as exc:
                    read_errors["common"] = _safe_read_failure(exc)
                    common_response = None
                gcc_time = datetime.now(timezone.utc)
                try:
                    experiment_response = service.get_gcc_progress_range_response(ranges, exploratory=True)
                except Exception as exc:
                    read_errors["experimental"] = _safe_read_failure(exc)
                    experiment_response = None
        else:
            own_response, roster_response, common_response, experiment_response = (
                _load_json(path) for path in paths)
            member_time = gcc_time = None
            read_errors = {}
        # Runtime evidence is built after all local sources have passed checks.
        result = bulk_report(own_response, roster_response,
                             common_response, experiment_response, ranges=ranges,
                             show_stat_values=args.show_stat_values,
                             show_members=args.show_members,
                             print_gcc_entries=args.print_gcc_entries,
                             member_read_utc=member_time, gcc_read_utc=gcc_time,
                             read_errors=read_errors, car_catalog=car_catalog,
                             cosmetic_catalog=cosmetic_catalog,
                             game_names=game_names, game_visuals=game_visuals,
                             car_name_style=args.car_name_style,
                             metadata_inventory=inventory, visual_source_shapes=visual_shapes,
                             ui_reference=reference,
                             show_unmatched_visual_ids=args.show_unmatched_visual_ids)
    except ServiceHTTPError as exc:
        print(json.dumps({"status": "http_error", "status_code": exc.status_code,
                          "details": "suppressed"}))
        return 1
    except (Exception, KeyboardInterrupt):
        print(json.dumps({"status": "bulk_probe_unavailable", "details": "suppressed"}))
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 4 if result["status"] == "bulk_partial_read" else 0


if __name__ == "__main__":
    raise SystemExit(main())
