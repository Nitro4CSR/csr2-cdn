"""Offline-first, opt-in GCC range investigation for 0.7.1.dev1.

The known production range (top10, +/-5) is unchanged. This module tests
bounded alternate parameters at the EXISTING authenticated read-only route.
The game serializer accepts the four fields; wider GCC ranges/offset behavior
are NOT yet server-verified. Never auto-crawls, caches, or publishes replies.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

from ._service_reads import StandingRange, ReadContractError, gcc_progress_range_contract
from .service_models import GCCProgressCrewScores, ServiceResponseError
from .services import CSR2Services, ServiceHTTPError


def report(response: Any, *, ranges: StandingRange, own_crew_id: Optional[str] = None,
           print_entries: bool = False) -> dict:
    """Summarize an already-retrieved response without leaking crew IDs."""
    page = GCCProgressCrewScores.from_response(response)
    crews = page.crews
    if len(crews) > 1000:
        raise ServiceResponseError("GCC probe result exceeds bounded row limit")
    matches = [c for c in crews if c.crew_id == own_crew_id] if own_crew_id else []
    result = {
        "status": "decoded_exploratory_gcc_range_unverified",
        "request_range": dict(ranges.as_wire_params()),
        "rows": len(crews),
        "distinct_crew_ids": len(set(c.crew_id for c in crews)),
        "rank_min": min(c.rank for c in crews),
        "rank_max": max(c.rank for c in crews),
        "global_top_range_rows": sum(c.rank <= ranges.top for c in crews),
        "own_crew_exact_id_matches": len(matches),
        "own_crew_rank": matches[0].rank if len(matches) == 1 else None,
        "own_crew_score": matches[0].score if len(matches) == 1 else None,
        "entry_values_printed": bool(print_entries),
        "entries": ([{"rank": c.rank, "name": c.name, "score": c.score,
                      "is_own_crew": bool(own_crew_id and c.crew_id == own_crew_id)}
                     for c in crews] if print_entries else []),
        "active_season_verified": False,
        "expanded_range_verified": False,
        "offset_pagination_verified": False,
        "complete_leaderboard_verified": False,
        "notes": "One read only; no claim that requested range, offset, or leaderboard completeness was honored.",
    }
    return result


def compare_responses(previous: Any, current: Any) -> dict:
    """ID-based consistency check; compare already-captured pages only."""
    a, b = (GCCProgressCrewScores.from_response(x).crews for x in (previous, current))
    old = {row.crew_id: row for row in a}
    shared = [row for row in b if row.crew_id in old]
    return {
        "shared_crew_ids": len(shared),
        "matching_rank_and_score": sum(
            old[r.crew_id].rank == r.rank and old[r.crew_id].score == r.score for r in shared),
        "changed_rank_or_score": sum(
            old[r.crew_id].rank != r.rank or old[r.crew_id].score != r.score for r in shared),
        "previous_rows": len(a),
        "current_rows": len(b),
        "non_atomic": True,
        "arbitrary_pagination_verified": False,
    }


def _load_local_json(path: str) -> Any:
    p = Path(path)
    if p.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("fixture too large")
    return json.loads(p.read_text(encoding="utf-8"))


def main(argv=None, *, services_factory=CSR2Services) -> int:
    parser = argparse.ArgumentParser(description="Bounded GCC progress range probe (offline by default)")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--before", type=int, default=10)
    parser.add_argument("--after", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--execute", action="store_true", help="one live GCC request; interactive PlayerID prompt")
    parser.add_argument("--match-own-crew", action="store_true", help="optional separate own-crew identification read")
    parser.add_argument("--print-entries", action="store_true", help="opt in to printing crew names and scores")
    parser.add_argument("--fixture-json", help="decode an existing local response without any requests")
    parser.add_argument("--compare-json", help="compare fixture against another local GCC response by private ID")
    args = parser.parse_args(argv)
    ranges = StandingRange(top=args.top, before=args.before, after=args.after, offset=args.offset)
    try:
        gcc_progress_range_contract(ranges, exploratory=True)
    except ReadContractError as exc:
        parser.error(str(exc))
    if args.execute and (args.fixture_json or args.compare_json):
        parser.error("--execute cannot be combined with local JSON fixtures")
    if args.compare_json and not args.fixture_json:
        parser.error("--compare-json requires --fixture-json")
    if args.match_own_crew and not args.execute:
        parser.error("--match-own-crew requires --execute")
    if not args.execute and not args.fixture_json:
        print(json.dumps({"status": "dry_run", "network_requests": 0,
                          "range": dict(ranges.as_wire_params()),
                          "endpoint": "leaderboard/crew-champs-v2/viewcrew",
                          "experimental": True,
                          "offset_pagination_verified": False}, indent=2))
        return 0
    if args.execute and not sys.stdin.isatty():
        print(json.dumps({"status": "interactive_terminal_required", "network_requests": 0}))
        return 2
    try:
        own_id = None
        if args.execute:
            player_id = getpass.getpass("Your own PlayerID (hidden): ").strip()
            with services_factory(player_id, allow_network=True) as svc:
                if args.match_own_crew:
                    own = svc.get_my_crew(refresh=True)
                    own_id = own.crew_uid
                response = svc.get_gcc_progress_range_response(ranges, exploratory=True)
        else:
            response = _load_local_json(args.fixture_json)
        result = report(response, ranges=ranges, own_crew_id=own_id,
                        print_entries=args.print_entries)
        if args.compare_json:
            result["offline_response_overlap"] = compare_responses(
                _load_local_json(args.compare_json), response)
    except ServiceHTTPError as exc:
        print(json.dumps({"status": "http_error", "status_code": exc.status_code,
                          "details": "suppressed"}))
        return 1
    except (Exception, KeyboardInterrupt):
        # Never disclose network URLs, credentials, raw response values or file content.
        print(json.dumps({"status": "probe_unavailable", "details": "suppressed"}))
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
