"""Dev31: demonstrate the expected 14-day Crew RP reset without network calls.

Only synthetic fixtures are used. A successful simulation does not imply any
live reset occurred and does not establish the server's season identifier.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from typing import Optional

from .crew_rp import CrewRPSnapshot
from .crew_season import CrewSeasonTransition
from .service_models import CrewMembers, GCCProgressCrewScores


def simulated_transition() -> CrewSeasonTransition:
    """Rehearse 29-member reset on the operator-expected 14-day boundary."""
    end_before = datetime(2026, 10, 22, 10, 0, 0, tzinfo=timezone.utc)
    end_after = end_before + timedelta(days=14)
    before_read = end_before - timedelta(seconds=2)
    after_read = end_before + timedelta(seconds=2)

    def snapshot(read_time: datetime, *, end: datetime, contribution: int,
                 score: int, own_rp: int, garage: int, previous=None) -> CrewRPSnapshot:
        roster = CrewMembers.from_response("synthetic-crew", {"scores": [
            {"player_uid": f"synthetic-{i}", "cc_contrib": contribution}
            for i in range(29)
        ]})
        board = GCCProgressCrewScores.from_response({
            "end_time": int(end.timestamp()),
            "time_left": int((end - read_time).total_seconds()),
            "scores": [{"crew_id": "synthetic-crew", "name": "SYNTHETIC CREW",
                        "rank": 1, "score": score}],
        })
        return CrewRPSnapshot.from_reads(
            roster, board, own_crew_id="synthetic-crew",
            member_read_utc=read_time - timedelta(milliseconds=100),
            gcc_read_utc=read_time, now_utc=read_time,
            expected_member_count=29, previous=previous,
            own_crew_rp_unverified=own_rp,
            own_crew_garage_value_unverified=garage,
        )

    first = snapshot(before_read, end=end_before, contribution=100, score=2900,
                     own_rp=9999999, garage=80000000)
    second = snapshot(after_read, end=end_after, contribution=0, score=0,
                      own_rp=9999999, garage=80000000, previous=first)
    return CrewSeasonTransition.between(first, second)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Offline-only Crew RP reset lifecycle rehearsal")
    parser.add_argument("--simulate", action="store_true", help="run synthetic 14-day before/after reset")
    args = parser.parse_args(argv)
    if not args.simulate:
        print(json.dumps({"mode": "dry_run", "network_requests": 0,
                          "simulator_available": True, "server_reset_observed": False}, indent=2))
        return 0
    report = simulated_transition().public_summary(show_own_crew_stats=True)
    print(json.dumps({"mode": "synthetic_test_only", "network_requests": 0,
                      "server_reset_observed": False,
                      "expected_reset_scenario_passed": bool(report["zero_reset_observed_in_supplied_snapshots"]),
                      "synthetic_transition": report}, indent=2))
    return 0 if report["zero_reset_observed_in_supplied_snapshots"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
