"""Opt-in Prestige Cup standings release gate; read-only and privacy-conscious.

The native-backed Prestige board selector lives in service_prestige. This CLI
intentionally does not guess a board or active season. Prestige
FastestHalfMileTime scores are displayed as microseconds / 1,000,000
(exactly six decimal places), based on operator-provided in-game UI validation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import json
import sys
from typing import Any, Callable, Optional

from csr2cdn._service_reads import StandingRange
from csr2cdn.service_models import LeaderboardPage
from csr2cdn.prestige_time import (format_prestige_time, format_prestige_time_optional,
                                  format_prestige_time_delta, parse_prestige_ui_time)
from csr2cdn.services import CSR2Services, PrestigeCrewSchemaError


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _score_int(value: Any) -> bool:
    return type(value) is int and -(2**63) <= value <= 2**63 - 1


def _entry_preview(page: LeaderboardPage, *, show_names: bool) -> list:
    """Never print player IDs, crew IDs, arbitrary extras, or raw response JSON."""
    result = []
    for item in page.entries[:200]:
        row = {"rank": item.rank, "score_microseconds": item.score,
               "time_seconds": format_prestige_time_optional(item.score)}
        if show_names:
            row["name"] = (item.player_name or "")[:96]
        result.append(row)
    return result


def compare_prestige_pages(primary: LeaderboardPage, *, player_id: Optional[str] = None,
                           alternate: Optional[LeaderboardPage] = None,
                           show_names: bool = False,
                           ui_rank: Optional[int] = None,
                           ui_score: Optional[int] = None,
                           ui_time: Optional[str] = None) -> dict:
    """Pure bounded summary of live or fixture-backed Prestige pages.

    Matches entries with an explicit server identity; never match on rank/name
    alone. Range cross-checks require the same board and at least one stable
    identity occurring in both pages. Optional UI numbers are operator-provided
    snapshots, not authoritative automatic verification.
    """
    if not isinstance(primary, LeaderboardPage):
        raise TypeError("primary must be LeaderboardPage")
    if alternate is not None and not isinstance(alternate, LeaderboardPage):
        raise TypeError("alternate must be LeaderboardPage")
    if len(primary.entries) > 1000 or (alternate is not None and len(alternate.entries) > 1000):
        raise ValueError("standings exceeds diagnostic safety limit")
    if ui_rank is not None and not _positive_int(ui_rank):
        raise ValueError("UI rank must be positive")
    if ui_score is not None and (not _score_int(ui_score) or ui_score < 0):
        raise ValueError("UI score must be a nonnegative raw microsecond integer")
    if ui_time is not None and ui_score is not None:
        raise ValueError("supply either raw --ui-score or seconds --ui-time, not both")
    ui_time_us = parse_prestige_ui_time(ui_time) if ui_time is not None else None
    if alternate is not None and alternate.leaderboard_name != primary.leaderboard_name:
        raise ValueError("different leaderboard identities cannot be compared")
    rank_known = sum(_positive_int(x.rank) for x in primary.entries)
    score_known = sum(_score_int(x.score) for x in primary.entries)
    pairs = [(row.rank, row.score) for row in primary.entries if _positive_int(row.rank) and _score_int(row.score)]
    ranks = [row.rank for row in primary.entries if _positive_int(row.rank)]
    seen_ids = [str(row.player_id) for row in primary.entries if row.player_id]
    result = {
        "status": "standings_decoded_accuracy_pending",
        "board": primary.leaderboard_name,
        "score_semantics": "Prestige FastestHalfMileTime; raw integer microseconds, displayed as seconds to six decimal places (operator UI confirmation)",
        "score_unit": "microseconds",
        "time_unit": "seconds",
        "time_decimal_places": 6,
        "pagination_scope": "native common window only; arbitrary pages not established",
        "rows": len(primary.entries),
        "rank_numeric_rows": rank_known,
        "score_numeric_rows": score_known,
        "rank_score_rows": len(pairs),
        "distinct_positive_ranks": len(set(ranks)),
        "duplicate_positive_ranks": len(ranks) - len(set(ranks)),
        "distinct_player_ids": len(set(seen_ids)),
        "duplicate_player_ids": len(seen_ids) - len(set(seen_ids)),
        "top_ten_rank_coverage": sum(r in set(ranks) for r in range(1, 11)),
        "player_rank_from_envelope": primary.player_rank,
        "player_score_from_envelope": primary.player_score,
        "player_time_from_envelope_seconds": format_prestige_time_optional(primary.player_score),
        "own_player_exact_id_matches": None,
        "own_player_rank": None,
        "own_player_score": None,
        "own_player_time_seconds": None,
        "rank_score_pair_coverage_complete": len(pairs) == len(primary.entries) and len(primary.entries) > 0,
        "verified_against_in_game_ui": False,
    }
    if player_id:
        own = [r for r in primary.entries if r.player_id == str(player_id)]
        result["own_player_exact_id_matches"] = len(own)
        if len(own) == 1:
            result["own_player_rank"] = own[0].rank
            result["own_player_score"] = own[0].score
            result["own_player_time_seconds"] = format_prestige_time_optional(own[0].score)
            result["own_entry_vs_envelope_rank_agrees"] = (
                own[0].rank == primary.player_rank if primary.player_rank is not None else None)
            result["own_entry_vs_envelope_score_agrees"] = (
                own[0].score == primary.player_score if primary.player_score is not None else None)
    # A snapshot can be compared to only an explicitly known own-player rank,
    # never a nearby row of a similar name or an old leaderboard position.
    own_rank = result["own_player_rank"] if result["own_player_exact_id_matches"] == 1 else primary.player_rank
    own_score = result["own_player_score"] if result["own_player_exact_id_matches"] == 1 else primary.player_score
    if ui_rank is not None:
        result["ui_rank_reference"] = ui_rank
        result["ui_rank_delta_candidate"] = (own_rank - ui_rank if _positive_int(own_rank) else None)
    if ui_score is not None:
        result["ui_score_reference_unverified_units"] = ui_score
        result["ui_score_delta_candidate"] = (own_score - ui_score if _score_int(own_score) else None)
    if ui_time_us is not None:
        result["ui_time_reference_seconds"] = format_prestige_time(ui_time_us)
        result["ui_time_reference_microseconds"] = ui_time_us
        # A manual UI reference can drift from a later server read; equality is
        # a comparison result, not independently captured proof of UI accuracy.
        if _score_int(own_score) and own_score >= 0:
            difference = own_score - ui_time_us
            result["ui_time_delta_microseconds"] = difference
            result["ui_time_delta_seconds"] = format_prestige_time_delta(difference)
            result["ui_time_exact_match"] = difference == 0
        else:
            result["ui_time_delta_microseconds"] = None
            result["ui_time_delta_seconds"] = None
            result["ui_time_exact_match"] = None
    if alternate is not None:
        one = {r.player_id: r for r in primary.entries if r.player_id}
        two = {r.player_id: r for r in alternate.entries if r.player_id}
        overlap = set(one) & set(two)
        consistent = sum(one[k].rank == two[k].rank and one[k].score == two[k].score for k in overlap)
        result["range_cross_check"] = {
            "status": "checked" if overlap else "no_stable_identity_overlap",
            "alternate_rows": len(alternate.entries),
            "shared_player_ids": len(overlap),
            "exact_matching_rank_and_score": consistent,
            "mismatches_or_live_changes": len(overlap) - consistent,
            "non_atomic": True,
            "full_pagination_verified": False,
        }
    if show_names:
        result["entries_opt_in"] = _entry_preview(primary, show_names=True)
    return result



def summarize_prestige_crew_page(
        crew_page: LeaderboardPage, *, player_id: str,
        global_page: Optional[LeaderboardPage] = None,
        show_names: bool = False) -> dict:
    """Summarize the separate event crew-member read without assuming ranks.

    The server's selected member population and whether crew-tab ranks are
    global or within-crew are not yet established. An empty response may
    legitimately mean nobody raced. Compare overlapping player scores only;
    neither names nor positions establish shared identities.
    """
    if not isinstance(crew_page, LeaderboardPage):
        raise TypeError("crew_page must be LeaderboardPage")
    if global_page is not None and crew_page.leaderboard_name != global_page.leaderboard_name:
        raise ValueError("global and crew tabs must use the same Prestige board")
    if len(crew_page.entries) > 1000:
        raise ValueError("crew standings exceeds diagnostic safety limit")
    ids = [r.player_id for r in crew_page.entries if r.player_id]
    numeric = [r for r in crew_page.entries if _score_int(r.score) and r.score >= 0]
    own = [r for r in crew_page.entries if r.player_id == player_id]
    result = {
        "status": "decoded_crew_filtered_response_semantics_pending",
        "route_kind": "event_scores_crewmembers_not_gcc",
        "board": crew_page.leaderboard_name,
        "rows": len(crew_page.entries),
        "distinct_player_ids": len(set(ids)),
        "duplicate_player_ids": len(ids) - len(set(ids)),
        "rank_numeric_rows": sum(_positive_int(r.rank) for r in crew_page.entries),
        "score_numeric_rows": len(numeric),
        "own_player_exact_id_matches": len(own),
        "rank_semantics_verified": False,
        "crew_population_completeness_verified": False,
        "race_times_in_seconds": True,
    }
    if len(own) == 1:
        result["own_player_rank_candidate"] = own[0].rank
        result["own_player_time_seconds"] = format_prestige_time_optional(own[0].score)
    if global_page is not None:
        global_by_id = {x.player_id: x for x in global_page.entries if x.player_id}
        overlapping = [r for r in crew_page.entries if r.player_id in global_by_id]
        result["global_window_overlap"] = {
            "shared_player_ids": len(overlapping),
            "same_raw_score": sum(r.score == global_by_id[r.player_id].score for r in overlapping),
            "same_rank": sum(r.rank == global_by_id[r.player_id].rank for r in overlapping),
            "rank_comparability_verified": False,
        }
    if show_names:
        result["entries_opt_in"] = _entry_preview(crew_page, show_names=True)
    return result


def run_prestige_verification(player_id: str, *, board: Optional[str] = None,
                              season: Optional[int] = None, car_tier: Optional[int] = None,
                              car_key: Optional[str] = None, ui_rank: Optional[int] = None,
                              ui_score: Optional[int] = None, ui_time: Optional[str] = None,
                              print_entries: bool = False,
                              cross_check_range: bool = False,
                              ui_window: bool = False,
                              crew_filtered: bool = False,
                              services_factory: Callable[..., Any] = CSR2Services) -> dict:
    """Native event reads, with explicit opt-ins for two more Prestige views.

    Global UI-like top20/+/-10 is an operator-observed display shape, not a
    separately traced UI initializer. Crew standings use the *distinct*
    6.8.0 EventLeaderboard crew route and its native 10/30/30 range. No
    paging loop, game write, or arbitrary player/crew ID lookup occurs.
    """
    if not player_id or not isinstance(player_id, str):
        raise ValueError("player_id is required")
    if bool(board) == (season is not None):
        raise ValueError("choose a resolved board OR season with car tier and key")
    if board is None and (type(season) is not int or not 0 <= season <= 999 or
                          type(car_tier) is not int or not 1 <= car_tier <= 5 or
                          not isinstance(car_key, str) or not car_key.strip()):
        raise ValueError("current board resolution needs confirmed season, car tier and car key")
    started = datetime.now(timezone.utc)
    with services_factory(player_id, allow_network=True) as service:
        if board:
            getter = lambda rng: service.get_prestige_cup_leaderboard(
                leaderboard_name=board, ranges=rng)
        else:
            # Resolve metadata/native board only once. Both readings must use
            # the exact same event identity and native result offset.
            selected = service._resolve_current_prestige(
                season=season, prestige_car_tier=car_tier,
                prestige_car_key=car_key)
            def getter(rng):
                resolved_range = StandingRange(top=rng.top, after=rng.after,
                                               before=rng.before, offset=selected.offset)
                return service.get_prestige_cup_leaderboard(
                    leaderboard_name=selected.leaderboard_name, ranges=resolved_range)
        global_window = (StandingRange.prestige_ui_window(offset=selected.offset if not board else 0)
                         if ui_window else StandingRange(
                             top=10, after=5, before=5,
                             offset=selected.offset if not board else 0))
        primary = getter(global_window)
        primary_finished = datetime.now(timezone.utc)
        alternate = getter(StandingRange.top3_and_you()) if cross_check_range else None
        alternate_finished = datetime.now(timezone.utc) if alternate is not None else None
        crew_page = None
        crew_finished = None
        if crew_filtered:
            # Resolve board and native event offset only once: a crew filtered
            # request is not a global response filtered on client-provided IDs.
            if board:
                crew_board, crew_offset = board, 0
            else:
                crew_board, crew_offset = selected.leaderboard_name, selected.offset
            crew_page = service.get_prestige_cup_crew_leaderboard(
                leaderboard_name=crew_board,
                ranges=StandingRange.native_event_crew(offset=crew_offset))
            crew_finished = datetime.now(timezone.utc)
    result = compare_prestige_pages(primary, player_id=player_id, alternate=alternate,
                                    show_names=print_entries, ui_rank=ui_rank, ui_score=ui_score,
                                    ui_time=ui_time)
    result.update({"mode": "authorized_read_only", "started_utc": started.isoformat(),
                   "primary_completed_utc": primary_finished.isoformat(),
                   "alternate_completed_utc": alternate_finished.isoformat() if alternate_finished else None,
                   "crew_completed_utc": crew_finished.isoformat() if crew_finished else None,
                   "global_range_requested": dict(global_window.as_wire_params()),
                   "global_ui_window_candidate": ui_window,
                   "read_count": 1 + int(cross_check_range) + int(crew_filtered),
                   "live_ui_equivalence_established": False})
    if crew_page is not None:
        result["crew_filtered"] = summarize_prestige_crew_page(
            crew_page, player_id=player_id, global_page=primary,
            show_names=print_entries)
    return result


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Prestige Cup score/rank and bounded range release check")
    parser.add_argument("--execute", action="store_true", help="opt in to authenticated server reads")
    identity = parser.add_mutually_exclusive_group()
    identity.add_argument("--board", help="previously verified complete Prestige leaderboard identifier")
    identity.add_argument("--season", type=int, help="operator-confirmed active crew season for source-backed Prestige resolution")
    parser.add_argument("--car-tier", type=int, help="known Prestige car tier 1..5, with --season")
    parser.add_argument("--car-key", help="known native Prestige car key, with --season")
    parser.add_argument("--ui-rank", type=int, help="optional recent game UI own-player Prestige rank")
    ui_inputs = parser.add_mutually_exclusive_group()
    ui_inputs.add_argument("--ui-score", type=int, help="optional raw Prestige score in microseconds (legacy)")
    ui_inputs.add_argument("--ui-time", help="optional in-game race time in seconds, e.g. 7.102993")
    parser.add_argument("--print-entries", action="store_true", help="opt in to printing leaderboard names, ranks and scores")
    parser.add_argument("--range-cross-check", action="store_true", help="perform one additional native top-3-and-you window read")
    parser.add_argument("--ui-window", action="store_true",
                        help="opt in to top20 and +/-10 Prestige global range; response unverified")
    parser.add_argument("--crew-filtered", action="store_true",
                        help="opt in to native Prestige crew-member standings read; response unverified")
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({"mode": "dry_run", "network_requests": 0, "status": "not_executed"}, indent=2))
        return 0
    if not sys.stdin.isatty():
        print(json.dumps({"status": "interactive_terminal_required", "network_requests": 0}))
        return 2
    if (args.board is None and args.season is None):
        parser.error("--execute requires either --board or --season with --car-tier and --car-key")
    if args.season is None and (args.car_tier is not None or args.car_key is not None):
        parser.error("--car-tier and --car-key require --season")
    try:
        player_id = getpass.getpass("Your PlayerID (input hidden): ").strip()
        result = run_prestige_verification(player_id, board=args.board,
                    season=args.season, car_tier=args.car_tier, car_key=args.car_key,
                    ui_rank=args.ui_rank, ui_score=args.ui_score, ui_time=args.ui_time,
                    print_entries=args.print_entries, cross_check_range=args.range_cross_check,
                    ui_window=args.ui_window, crew_filtered=args.crew_filtered)
    except PrestigeCrewSchemaError as exc:
        print(json.dumps({"status": "prestige_crew_schema_unrecognized",
                          "shape": exc.structure, "no_raw_response_printed": True}, indent=2))
        return 3
    except Exception as exc:
        # Suppress raw transport errors, server bodies, and account identifiers.
        print(json.dumps({"status": "verification_failed", "category": type(exc).__name__,
                          "no_raw_response_printed": True}, indent=2))
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # A successful HTTP request does not imply successful decoding.
    valid_crew = ("crew_filtered" not in result or
                  (result["crew_filtered"]["score_numeric_rows"] ==
                   result["crew_filtered"]["rows"] and
                   result["crew_filtered"]["rank_numeric_rows"] ==
                   result["crew_filtered"]["rows"]))
    return 0 if result["rank_score_pair_coverage_complete"] and valid_crew else 3


if __name__ == "__main__":
    raise SystemExit(main())
