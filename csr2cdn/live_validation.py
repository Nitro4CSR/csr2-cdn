"""Opt-in, minimal read-only live smoke checks for an account controlled by caller.

There is no event catalog, save feature, credential persistence, response dump,
or diagnostic HTTP logging. Only sanitized summaries go to stdout. Running this
module without --execute produces no network traffic and asks for no PlayerID.

    python -m csr2cdn.live_validation --execute
    python -m csr2cdn.live_validation --execute --showdown-board RESOLVED_NAME
    python -m csr2cdn.live_validation --execute --crew-uid OWN_CREW_UID

Use an interactive terminal: the PlayerID prompt does not echo input or place
it in shell history/process arguments. No output file is created.
"""
from __future__ import annotations

import argparse
from collections import Counter
import getpass
import json
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

import requests

from csr2cdn._service_auth import ServiceAuthError
from csr2cdn._service_reads import ReadContractError
from csr2cdn.errors import Csr2CdnError
from csr2cdn.metadata import MetadataClient
from csr2cdn.service_discovery import ShowdownDiscovery
from csr2cdn.service_events import EventResolutionError, ShowdownInactiveError
from csr2cdn.service_modular_assets import RuntimeEventSourceError
from csr2cdn.service_models import ServiceResponseError
from csr2cdn.services import CSR2Services, ServiceHTTPError


def _status(exc: Exception) -> dict:
    """Never expose exception text, URLs, account fields or response content."""
    if isinstance(exc, ServiceHTTPError):
        return {"status": "http_rejected", "http_status": exc.status_code}
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return {"status": "transport_unavailable"}
    if isinstance(exc, RuntimeEventSourceError):
        return {"status": "runtime_catalogue_unavailable"}
    if isinstance(exc, ShowdownInactiveError):
        return {"status": "inactive_event"}
    if isinstance(exc, (EventResolutionError, ReadContractError, ValueError)):
        return {"status": "unresolved_input"}
    if isinstance(exc, ServiceAuthError):
        return {"status": "service_unavailable"}
    if isinstance(exc, ServiceResponseError):
        report = {"status": "response_not_recognized"}
        if exc.structure is not None:
            report["response_structure"] = exc.structure
        return report
    if isinstance(exc, (requests.RequestException, Csr2CdnError)):
        return {"status": "service_unavailable"}
    return {"status": "unexpected_failure"}


def _resolve_product_version(player_id: str, app_version: str) -> str:
    """Get the *database* product version, which differs from app version."""
    from csr2cdn.cdn import CDN
    with CDN(zid=player_id, release_version=app_version, probe=False) as client:
        return client.product_version


def _crew_season_probe(roster: Any) -> dict:
    """Per-roster candidate coverage, without exposing IDs or numeric RP.

    These counters establish only *wire presence*. Even perfect coverage does
    not establish active 14-day season scope or equivalence with the UI.
    """
    members = roster.members
    member_ids = [m.player_uid or m.zid for m in members]
    named_ids = [uid for uid in member_ids if uid]
    distinct = len(set(named_ids))
    candidate_rows = sum(m.season_crew_rp_candidate is not None for m in members)
    populated_identity_candidate = sum(
        bool(uid) and m.season_crew_rp_candidate is not None
        for uid, m in zip(member_ids, members))
    return {
        "records": len(members),
        "member_identity_rows": len(named_ids),
        "distinct_preferred_member_identifiers": distinct,
        "duplicate_preferred_member_identifiers": len(named_ids) - distinct,
        "cc_contrib_candidate_rows": sum(
            m.season_crew_rp_candidate is not None and m.season_crew_rp_source == "cc_contrib"
            for m in members),
        "score_fallback_candidate_rows": sum(
            m.season_crew_rp_candidate is not None and m.season_crew_rp_source == "score"
            for m in members),
        "season_candidate_numeric_rows": candidate_rows,
        "season_candidate_zero_rows": sum(
            m.season_crew_rp_candidate == 0 for m in members),
        "identified_season_candidate_rows": populated_identity_candidate,
        "complete_identity_and_candidate_coverage": bool(members) and (
            len(named_ids) == distinct == candidate_rows == len(members)),
        "active_season_scope_verified": False,
        "in_game_member_equivalence_verified": False,
        "seasonal_crew_rp_release_unblocked": False,
    }


def run_live(
    player_id: str,
    *,
    app_version: str = "6.8.0",
    #: Instant to evaluate event schedules against. Defaults to the real
    #: clock. Pass a fixed value to make a run reproducible: without it, a
    #: report depends on when it was taken, and a test that pins its fixture
    #: schedule starts failing once that window elapses.
    at: Optional[datetime] = None,
    metadata_product_version: Optional[str] = None,
    showdown_board: Optional[str] = None,
    showdown_index: Optional[int] = None,
    showdown_name: Optional[str] = None,
    crew_uid: Optional[str] = None,
    auto_crew: bool = True,
    crew_only: bool = False,
    crew_rp_schema: bool = False,
    crew_season_probe: bool = False,
    prestige_board: Optional[str] = None,
    prestige_current: bool = False,
    native_prestige_season: Optional[int] = None,
    native_prestige_car_tier: Optional[int] = None,
    native_prestige_car_key: Optional[str] = None,
    leagues_board: Optional[str] = None,
    skip_metadata: bool = False,
    metadata_factory: Callable[[], Any] = MetadataClient,
    product_version_resolver: Callable[[str, str], str] = _resolve_product_version,
    services_factory: Callable[..., Any] = CSR2Services,
    asset_cdn_factory: Optional[Callable[..., Any]] = None,
) -> dict:
    """Run selected reads at most once; no identifiers or response records in report.

    Session machinery may independently retry one HTTP 401 as normal. Network
    compatibility must be established against an account owned by the operator.
    """
    # Resolved once, so every schedule decision in this run and the reported
    # timestamp all refer to the same instant.
    evaluated_at = at if at is not None else datetime.now(timezone.utc)
    if evaluated_at.tzinfo is None:
        raise ValueError("at must be timezone-aware")
    report = {
        "at_utc": evaluated_at.isoformat(timespec="seconds"),
        "game_version": app_version,
        "mode": "live_read_only",
        "checks": {},
    }
    checks = report["checks"]
    discovered_board = None
    discovered_prestige_board = None

    if crew_only:
        # A roster-coverage check needs only the own-crew and viewMembers reads.
        # Do not query event metadata or unrelated leaderboards.
        skip_metadata = True

    if not skip_metadata:
        client = None
        try:
            product_version = (metadata_product_version or
                               product_version_resolver(player_id, app_version))
            client = metadata_factory()
            # Production defaults to the complete modular runtime event source.
            # Dependency-injected metadata-only tests remain deterministic.
            if asset_cdn_factory is None and metadata_factory is MetadataClient:
                from csr2cdn.cdn import CDN
                asset_cdn_factory = CDN
            if asset_cdn_factory is not None:
                asset_cdn = asset_cdn_factory(zid=player_id, product_version=product_version,
                                              release_version=app_version, probe=False)
                discovery = ShowdownDiscovery.from_metadata(
                    client, player_id=player_id, product_version=product_version,
                    asset_cdn=asset_cdn)
            else:
                discovery = ShowdownDiscovery.from_metadata(
                    client, player_id=player_id, product_version=product_version)
            all_events = discovery.list_showdowns(at=evaluated_at)
            active = [e for e in all_events if e.time_status == "scheduled_now"]
            resolved = [e for e in active if e.requestable]
            missing = Counter(part for row in all_events
                              for part in getattr(row, "unresolved_inputs", ()))
            coverage = getattr(discovery, "source_coverage", "standalone_only")
            checks["metadata"] = {
                "status": "ok",
                "source_coverage": coverage,
                "active_event_absence_is_conclusive": False,
 "showdown_groups_recognized": len(all_events),
                "active_showdown_candidates": len(active),
                "resolved_board_candidates": len(resolved),
                "unresolved_input_categories": dict(sorted(missing.items())),
                "elapsed_candidates": sum(e.time_status == "elapsed" for e in all_events),
            }
            # Native Prestige identification is independent of Showdown names.
            # Load the game's standalone cup series as well as modular events.
            if prestige_current:
                from csr2cdn.service_prestige import (
                    PrestigeCupDiscovery, CUP_METADATA_BLOCK, ADDITIONAL_PRESTIGE_BLOCKS, load_native_prestige_bundle)
                def load_prestige_block(name):
                    data = client.get((name,), zid=player_id,
                                      product_version=product_version)
                    if name not in data:
                        raise EventResolutionError("prestige event source unavailable")
                    return data[name].content
                def make_loader(name):
                    # Capture the name for each separate metadata request.
                    return lambda: load_prestige_block(name)
                prestige = PrestigeCupDiscovery(
                    discovery,
                    cup_source=make_loader(CUP_METADATA_BLOCK),
                    other_sources={name: make_loader(name)
                                   for name in ADDITIONAL_PRESTIGE_BLOCKS},
                    native_binary_source=(lambda: load_native_prestige_bundle(asset_cdn)) if asset_cdn_factory is not None else None,
                    native_season=native_prestige_season,
                    native_car_tier=native_prestige_car_tier,
                    native_car_key=native_prestige_car_key,
                )
                try:
                    resolved_prestige = prestige.resolve_current(at=evaluated_at)
                    discovered_prestige_board = resolved_prestige.leaderboard_name
                    checks["prestige_discovery"] = {"status": "ok", **prestige.source_summary()}
                except Exception as exc:
                    checks["prestige_discovery"] = {"status": _status(exc)["status"],
                                                     **prestige.source_summary()}
            # A named event can be selected among simultaneous Showdowns.
            if showdown_name is not None:
                discovered_board = discovery.resolve_named(
                    showdown_name, at=evaluated_at).leaderboard_name
            elif showdown_index is not None and 0 <= showdown_index < len(resolved):
                # Stable selection across ambiguous current-event schedules.
                choices = sorted(resolved, key=lambda e: getattr(e, "event_id", ""))
                discovered_board = choices[showdown_index].leaderboard_name
            elif not prestige_current and showdown_index is None and len(active) == 1 and len(resolved) == 1:
                discovered_board = resolved[0].leaderboard_name
        except Exception as exc:
            if checks.get("metadata", {}).get("status") == "ok":
                # Metadata itself was valid, but the named board selector
                # could not resolve. Preserve safe input diagnostics.
                checks["showdown_selection"] = _status(exc)
            else:
                checks["metadata"] = _status(exc)
        finally:
            if 'asset_cdn' in locals():
                try:
                    asset_cdn.close()
                except Exception:
                    pass
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
    else:
        checks["metadata"] = {"status": "skipped"}

    board = None if crew_only else showdown_board or discovered_board
    prestige_board = None if crew_only else prestige_board or discovered_prestige_board
    needs_service = bool(board or crew_uid or auto_crew or prestige_board or leagues_board)
    if not needs_service:
        checks["showdown"] = {"status": "not_selected" if prestige_current and not (showdown_name or showdown_board or showdown_index is not None) else "unresolved_board"}
        checks["crew"] = {"status": "not_selected"}
        checks["prestige_cup"] = {"status": "unresolved_board" if prestige_current else "not_selected"}
        checks["showdown_leagues_legacy"] = {"status": "not_selected"}
        return report

    try:
        services = services_factory(player_id, app_version=app_version, allow_network=True)
    except Exception as exc:
        checks["setup"] = _status(exc)
        return report

    with services:
        operations = (
            ("showdown", board, "get_showdown_leaderboard", "leaderboard_name", "entries"),
            ("prestige_cup", prestige_board, "get_prestige_cup_leaderboard", "leaderboard_name", "entries"),
            ("showdown_leagues_legacy", leagues_board, "get_showdown_leagues_leaderboard", "leaderboard_name", "entries"),
        )
        for label, ident, method, keyword, rows_attr in operations:
            if not ident:
                checks[label] = {"status": ("not_selected" if crew_only else
                                            "unresolved_board" if label == "prestige_cup" and prestige_current else
                                            "not_selected" if label == "showdown" and prestige_current and not (showdown_name or showdown_board or showdown_index is not None) else
                                            "unresolved_board" if label == "showdown" else "not_selected")}
                continue
            try:
                result = getattr(services, method)(**{keyword: ident})
                rows = getattr(result, rows_attr)
                if not isinstance(rows, (tuple, list)):
                    raise ServiceResponseError("invalid structured result")
                checks[label] = {"status": "ok", "records": len(rows)}
            except Exception as exc:
                checks[label] = _status(exc)
        if crew_uid or auto_crew:
            try:
                if crew_uid:
                    roster = services.get_crew_members(crew_uid=crew_uid)
                else:
                    own = services.get_my_crew()
                    if not own.in_crew:
                        checks["crew"] = {"status": "not_in_crew"}
                        roster = None
                    else:
                        roster = services.get_crew_members()
                if roster is not None:
                    if not isinstance(roster.members, (tuple, list)):
                        raise ServiceResponseError("invalid crew member list")
                    # Value-free coverage summary: never print player identities,
                    # profile values, raw reply fields or authentication material.
                    checks["crew"] = {
                        "status": "ok",
                        "records": len(roster.members),
                        "nickname_populated": sum(bool(getattr(m, "nickname", None))
                                                  for m in roster.members),
                        "crew_rp_populated": sum(getattr(m, "crew_rp", None) is not None
                                                 for m in roster.members),
                        "player_rank_populated": sum(getattr(m, "player_rank", None) is not None
                                                     for m in roster.members),
                        # No values, keys from a raw reply, or member identities.
                        # Keep native all-time RP distinct from a verified
                        # in-game seasonal Crew RP figure.
                        "rp_all_time_populated": sum(getattr(m, "rp_all_time", None) is not None
                                                     for m in roster.members),
                        # Native UserManager.FillNonSecureBlobDict ->
                        # PlayerProfile.get_RP -> player_rp. This is a distinct
                        # player-profile stat, not verified seasonal crew RP.
                        "player_profile_rp_populated": sum(
                            getattr(m, "player_rp", None) is not None for m in roster.members),
                        "rp_from_native_uppercase": sum(getattr(m, "crew_rp_source", None) == "RP"
                                                        for m in roster.members),
                        "rp_from_explicit_season": sum(getattr(m, "crew_rp_source", None) in
                                                        ("RP_season", "rp_season", "seasonRP", "season_rp")
                                                        for m in roster.members),
                        "rp_from_crew_alias": sum(getattr(m, "crew_rp_source", None) in
                                                   ("crewRP", "crew_rp", "crewRp")
                                                   for m in roster.members),
                        "role_populated": sum(getattr(m, "role", None) is not None
                                              for m in roster.members),
                        "role_recognized": sum(getattr(m, "role_normalized", None) is not None
                                              for m in roster.members),
                    }
                    # Diagnostic counts come from the decoder, never a logged raw
                    # response. Fixed, authored labels only; no player data.
                    wire = getattr(roster, "wire_rp_diagnostics", None)
                    if isinstance(wire, Mapping) and wire:
                        checks["crew"]["wire_rp_diagnostics"] = dict(wire)
                    if crew_rp_schema:
                        from csr2cdn.service_models import _crew_rp_name_families
                        schema = getattr(roster, "wire_rp_schema_keys", {})
                        # Only repeated static schema names, never member values.
                        checks["crew"]["rp_schema_field_counts"] = dict(schema)
                        checks["crew"]["rp_schema_field_families"] = dict(
                            _crew_rp_name_families(schema))
                    if crew_season_probe:
                        checks["crew"]["season_contribution_probe"] = _crew_season_probe(roster)
            except Exception as exc:
                checks["crew"] = _status(exc)
        else:
            checks["crew"] = {"status": "not_selected"}
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="CSR2 experimental read-only live smoke checks")
    parser.add_argument("--execute", action="store_true", help="allow live read requests (requires interactive PlayerID input)")
    parser.add_argument("--showdown-name", help="Showdown name; resolve leaderboard from current game metadata")
    parser.add_argument("--showdown-board", help="advanced: explicitly resolved board name")
    parser.add_argument("--showdown-index", type=int, help="select one resolved active Showdown by zero-based index when multiple are reported")
    parser.add_argument("--crew-uid", help="optional explicit crew; defaults to your own crew")
    parser.add_argument("--crew-only", action="store_true", help="validate own-crew fields without unrelated metadata/leaderboards")
    parser.add_argument("--crew-rp-schema", action="store_true", help="opt in to aggregate, privacy-filtered RP-looking field-name counts; only with --crew-only")
    parser.add_argument("--crew-season-probe", action="store_true", help="opt in to safe cc_contrib / score candidate and member-ID coverage counts; only with --crew-only; does NOT verify season scope")
    parser.add_argument("--skip-crew", action="store_true", help="skip automatic own-crew discovery")
    parser.add_argument("--prestige-board", help="advanced: fully resolved Prestige Cup leaderboard name")
    parser.add_argument("--prestige-current", action="store_true", help="discover active Prestige Cup from event metadata and binary client templates")
    parser.add_argument("--prestige-season", type=int, help="crew season confirmed from active game; required for native binary template resolution")
    parser.add_argument("--prestige-car-tier", type=int, help="game display tier (1..5) from current Prestige car metadata")
    parser.add_argument("--prestige-car-json", help="locally extracted Prestige car JSON; derive tier and cross-check seasonal car identity")
    parser.add_argument("--leagues-board", help="optional discontinued Showdown Leagues compatibility read")
    parser.add_argument("--skip-metadata", action="store_true", help="do not request current metadata")
    parser.add_argument("--app-version", default="6.8.0")
    parser.add_argument("--metadata-product-version", help="optional database product version; if omitted resolve it dynamically")
    args = parser.parse_args(argv)
    if sum(x is not None for x in (args.showdown_board, args.showdown_index, args.showdown_name)) > 1:
        parser.error("choose one Showdown selector")
    if args.showdown_index is not None and args.showdown_index < 0:
        parser.error("--showdown-index must be nonnegative")
    if (args.prestige_season is not None or args.prestige_car_tier is not None or args.prestige_car_json) and not args.prestige_current:
        parser.error("Prestige template inputs require --prestige-current")
    if args.prestige_car_json and args.prestige_car_tier is not None:
        parser.error("choose --prestige-car-json or --prestige-car-tier")
    if args.prestige_season is not None and not 0 <= args.prestige_season <= 999:
        parser.error("--prestige-season must be 0..999")
    if args.prestige_car_tier is not None and not 1 <= args.prestige_car_tier <= 5:
        parser.error("--prestige-car-tier must be 1..5")
    if args.prestige_current and args.prestige_board:
        parser.error("choose --prestige-current or --prestige-board")
    if args.crew_rp_schema and not args.crew_only:
        parser.error("--crew-rp-schema requires --crew-only")
    if args.crew_season_probe and not args.crew_only:
        parser.error("--crew-season-probe requires --crew-only")
    if args.crew_only and (args.skip_crew or args.prestige_current or args.prestige_board or
                          args.showdown_board or args.showdown_index is not None or args.showdown_name or
                          args.leagues_board):
        parser.error("--crew-only cannot be combined with other event checks or --skip-crew")
    if args.prestige_current and args.skip_metadata:
        parser.error("--prestige-current requires metadata")
    if not args.execute:
        print(json.dumps({"mode": "dry_run", "status": "not_executed", "network_requests": 0}, indent=2))
        return 0
    if not sys.stdin.isatty():
        print(json.dumps({"mode": "live_read_only", "checks": {
            "setup": {"status": "interactive_terminal_required"}}}, indent=2))
        return 2
    try:
        native_car_tier = args.prestige_car_tier
        native_car_key = None
        if args.prestige_car_json:
            from pathlib import Path
            car_path = Path(args.prestige_car_json)
            if car_path.stat().st_size > 8_000_000:
                raise ValueError("car record exceeds safety limit")
            car_data = json.loads(car_path.read_text(encoding="utf-8-sig"))
            if not isinstance(car_data, dict):
                raise ValueError("car record must be an object")
            native_car_key = car_data.get("Key")
            base_tier = car_data.get("BaseCarTier")
            if not isinstance(native_car_key, str) or not native_car_key or type(base_tier) is not int or not 0 <= base_tier <= 4:
                raise ValueError("car record lacks validated key/tier")
            native_car_tier = base_tier + 1
        player_id = getpass.getpass("Your PlayerID (input hidden): ").strip()
        if not player_id:
            raise ValueError("empty identifier")
        report = run_live(
            player_id, app_version=args.app_version,
            metadata_product_version=args.metadata_product_version,
            showdown_board=args.showdown_board, showdown_index=args.showdown_index,
            showdown_name=args.showdown_name,
            crew_uid=args.crew_uid, auto_crew=not args.skip_crew,
            crew_only=args.crew_only,
            crew_rp_schema=args.crew_rp_schema,
            crew_season_probe=args.crew_season_probe,
            prestige_board=args.prestige_board, prestige_current=args.prestige_current,
            native_prestige_season=args.prestige_season,
            native_prestige_car_tier=native_car_tier,
            native_prestige_car_key=native_car_key,
            leagues_board=args.leagues_board,
            skip_metadata=args.skip_metadata,
        )
    except (Exception, KeyboardInterrupt):
        # Avoid propagating exceptions that may contain private request context.
        report = {"mode": "live_read_only", "checks": {"setup": {"status": "unavailable"}}}
    print(json.dumps(report, indent=2))
    return 0 if all(item["status"] in ("ok", "not_selected", "skipped", "not_in_crew")
                    for item in report["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
