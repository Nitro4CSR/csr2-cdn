"""CLI for experimental, read-only game services (never handles save games)."""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from dataclasses import asdict
from pathlib import Path
from datetime import datetime
from typing import Any

from csr2cdn._service_reads import StandingRange
from csr2cdn._service_auth import DEFAULT_NMCLIENT_ID, PORTAL_URL, WEB_API_URL, ServiceAuthError
from csr2cdn.errors import Csr2CdnError
from csr2cdn.service_events import EventCatalog
from csr2cdn.service_discovery import ShowdownDiscovery
from csr2cdn.services import CSR2Services


def add_service_parser(sub) -> None:
    parser = sub.add_parser("services", help="experimental crew and leaderboard reads (0.7.0 preview)")
    parser.add_argument("--events-file", help="JSON file of dynamic event-to-board mappings")
    parser.add_argument("--metadata-dir", help="directory with local ShowdownEventsContainer.meta / EventSchedule.meta files (offline)")
    parser.add_argument("--modular-groups-file", help="optional offline JSON list of decoded runtime Showdown groups (not fetched by metadata service)")
    parser.add_argument("--at", help="timezone-aware ISO timestamp for offline schedule preflight (default: now)")
    parser.add_argument("--app-version", default="6.8.0", help="game client version for service calls")
    parser.add_argument("--nm-client-id", default=DEFAULT_NMCLIENT_ID, help="registered NM client ID")
    parser.add_argument("--portal-url", default=PORTAL_URL, help=argparse.SUPPRESS)
    parser.add_argument("--web-api-url", default=WEB_API_URL)
    parser.add_argument("--execute", action="store_true", help="OPT IN to unverified live server requests")
    children = parser.add_subparsers(dest="service_command", required=True)

    crew = children.add_parser("crew", help="crew members and their current cars")
    crew.add_argument("crew_uid", nargs="?", help="optional; defaults to your own crew")
    crew.add_argument("--response-file", help="decode local JSON fixture without contacting server")

    candidates = children.add_parser("showdowns", help="inspect time-window Showdown candidates in offline metadata")
    candidates.add_argument("--scheduled-now", action="store_true", help="show only events within a known time window")
    events = children.add_parser("events", help="list discovered event mappings")
    events.add_argument("--refresh", action="store_true")

    for command in ("showdown", "prestige", "showdown-leagues"):
        p = children.add_parser(command, help=("legacy compatibility standings (discontinued Showdown Leagues)" if command == "showdown-leagues" else f"read {command} standings"))
        p.add_argument("--event-id", help="event ID (requires --events-file)")
        if command == "showdown":
            p.add_argument("--name", dest="showdown_name", help="Showdown name; resolve all board inputs dynamically")
            p.add_argument("--current", action="store_true", help="resolve the sole time-window Showdown from --metadata-dir")
        p.add_argument("--leaderboard-name", help="explicit resolved leaderboard name")
        p.add_argument("--season")
        p.add_argument("--segment")
        p.add_argument("--instance")
        p.add_argument("--crew-id")
        p.add_argument("--refresh", action="store_true", help="refresh event map")
        p.add_argument("--top", type=int, default=10)
        p.add_argument("--after", type=int, default=5)
        p.add_argument("--before", type=int, default=5)
        p.add_argument("--offset", type=int, default=0)
        p.add_argument("--response-file", help="decode local JSON fixture without contacting server")
        if command != "showdown-leagues":
            p.add_argument("--score", type=int, help="optional native event range score")
            p.add_argument("--show-default", action="store_true", help="native show_default event flag")
        else:
            p.add_argument("--preview-score", type=int, help="use leaderboard preview read with this score")
            p.add_argument("--player-score", action="store_true", help="read own score/rank for period")


def _public_result(result: Any) -> Any:
    """Serialize only known typed fields; opaque server extras stay in memory."""
    if hasattr(result, "__dataclass_fields__"):
        return {key: _public_result(value) for key, value in vars(result).items()
                if key not in ("extras", "details")}
    if isinstance(result, (tuple, list)):
        return [_public_result(x) for x in result]
    return result


def dispatch_services(args: argparse.Namespace) -> int:
    try:
        event_map = EventCatalog.from_json_file(args.events_file) if args.events_file else None
        if args.modular_groups_file and not args.metadata_dir:
            raise ValueError("--modular-groups-file requires --metadata-dir")
        discovery = (ShowdownDiscovery.from_json_directory(
            args.metadata_dir, modular_groups_file=args.modular_groups_file)
                     if args.metadata_dir else None)
        selected_time = None
        if args.at:
            selected_time = datetime.fromisoformat(args.at.replace("Z", "+00:00"))
            if selected_time.tzinfo is None:
                raise ValueError("--at requires a timezone-aware timestamp")
        if args.service_command == "showdowns":
            if discovery is None:
                raise ValueError("services showdowns requires --metadata-dir")
            rows = discovery.scheduled_now(at=selected_time) if args.scheduled_now else discovery.list_showdowns(at=selected_time)
            print(json.dumps([_public_result(row) for row in rows], default=lambda d: d.isoformat(),
                             indent=2, ensure_ascii=False))
            return 0
        if event_map is None and discovery is not None:
            event_map = discovery.to_event_catalog()
        if args.service_command == "events":
            if event_map is None:
                raise ValueError("services events requires --events-file")
            print(json.dumps([_public_result(e) for e in event_map.list_events(refresh=args.refresh)], indent=2))
            return 0
        player_id = args.zid
        if args.execute and not player_id:
            if not sys.stdin.isatty():
                raise ValueError("an interactive terminal is required for hidden PlayerID input")
            player_id = getpass.getpass("Your PlayerID (input hidden): ").strip()
            if not player_id:
                raise ValueError("a PlayerID is required")
        with CSR2Services(
            player_id or "DRY_RUN_ONLY", app_version=args.app_version,
            nm_client_id=args.nm_client_id, portal_url=args.portal_url,
            web_api_url=args.web_api_url, events=event_map,
            timeout=args.timeout, allow_network=args.execute,
        ) as services:
            if args.service_command == "crew":
                if args.crew_uid is None:
                    # An offline preview cannot know the crew UID yet. The live
                    # operation discovers it first through the dedicated read.
                    contract = services.prepare_my_crew()
                    decoder = services.decode_my_crew
                    live = lambda: services.get_crew_members()
                else:
                    contract = services.prepare_crew_members(args.crew_uid)
                    decoder = lambda response: services.decode_crew_members(args.crew_uid, response)
                    live = lambda: services.get_crew_members(args.crew_uid)
            else:
                board_name = args.leaderboard_name
                if args.service_command == "showdown" and args.current:
                    if args.event_id or board_name or args.showdown_name:
                        raise ValueError("--current cannot be combined with --event-id or --leaderboard-name")
                    if discovery is None:
                        raise ValueError("--current requires --metadata-dir")
                    board_name = discovery.resolve_current_board(at=selected_time, refresh=args.refresh)
                common = dict(
                    event_id=args.event_id, leaderboard_name=board_name,
                    ranges=StandingRange(args.after, args.before, args.offset, top=args.top),
                    season=args.season, segment=args.segment, instance=args.instance,
                    crew_id=args.crew_id, refresh=args.refresh,
                )
                if args.service_command == "showdown" and args.showdown_name:
                    if args.event_id or board_name:
                        raise ValueError("choose --name or explicit event/board identifiers")
                    contract = services.prepare_showdown(showdown_name=args.showdown_name,
                                                         discovery=discovery, at=selected_time,
                                                         **common)
                    resolved_board = contract.route.split("/")[1]
                    common["leaderboard_name"] = resolved_board
                    common["event_id"] = None
                else:
                    contract = None
                if args.service_command == "showdown-leagues" and args.player_score:
                    if not args.leaderboard_name:
                        raise ValueError("Showdown Leagues score lookup requires --leaderboard-name")
                    if args.preview_score is not None:
                        raise ValueError("choose --player-score or --preview-score, not both")
                    contract = services.prepare_showdown_leagues_score(
                        args.leaderboard_name, period_offset=args.offset)
                    live = lambda: services.get_showdown_leagues_score(
                        args.leaderboard_name, period_offset=args.offset)
                elif args.service_command == "showdown-leagues" and args.preview_score is not None:
                    if not args.leaderboard_name:
                        raise ValueError("Showdown Leagues preview requires --leaderboard-name")
                    contract = services.prepare_showdown_leagues_preview(
                        args.leaderboard_name, score=args.preview_score, ranges=common["ranges"])
                    live = lambda: services.get_showdown_leagues_preview(
                        args.leaderboard_name, score=args.preview_score, ranges=common["ranges"])
                elif args.service_command == "showdown-leagues":
                    contract = services.prepare_showdown_leagues(**common)
                    live = lambda: services.get_showdown_leagues_leaderboard(**common)
                else:
                    common.update(score=args.score, show_default=True if args.show_default else None)
                    if args.service_command == "showdown":
                        if contract is None:
                            contract = services.prepare_showdown(**common)
                        live = lambda: services.get_showdown_leaderboard(**common)
                    else:
                        contract = services.prepare_prestige_cup(**common)
                        live = lambda: services.get_prestige_cup_leaderboard(**common)
                if args.service_command == "showdown-leagues" and args.player_score:
                    from csr2cdn.service_models import LeaderboardScore
                    decoder = lambda response: LeaderboardScore.from_response(
                        contract.route.split("/")[1], response, period_offset=args.offset)
                else:
                    decoder = lambda response: services.decode_leaderboard(contract.route.split("/")[1], response)
            fixture = getattr(args, "response_file", None)
            if fixture:
                result = decoder(json.loads(Path(fixture).read_text(encoding="utf-8")))
                print(json.dumps(_public_result(result), indent=2, ensure_ascii=False))
            elif args.execute:
                print("warning: experimental game-service request; live contract not validated", file=sys.stderr)
                result = live()
                print(json.dumps(_public_result(result), indent=2, ensure_ascii=False))
            else:
                print(json.dumps({"status": "offline-only; nothing sent", "operation": contract.operation,
                                  "request_type": contract.request_type, "route": contract.route,
                                  "params": dict(contract.params)}, indent=2))
        return 0
    except (Csr2CdnError, ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
        # Keep server authentication/transport internals out of CLI logs.
        # Errors from local file operations can contain private paths; avoid
        # echoing them. Domain errors are authored to contain no secret values.
        if isinstance(exc, ServiceAuthError):
            print("error: service session unavailable or invalid input", file=sys.stderr)
        elif isinstance(exc, OSError):
            print("error: unable to read local input file", file=sys.stderr)
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1


__all__ = ["add_service_parser", "dispatch_services"]
