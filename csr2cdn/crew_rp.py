"""Read-only Crew Championship RP snapshot built from observed CSR2 6.8.0 wire data.

Member ``cc_contrib`` is the native ``RP_season`` source. The GCC progress
``score`` equals the sum of members in the 2026-10-16 test, but the response
has no confirmed active season ID or rollover semantics. This module never
invents a season boundary and never performs I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Tuple

from .service_models import CrewMembers, GCCProgressCrewScores, GCCProgressCrewScore
from .crew_season import GCCSeasonTiming


@dataclass(frozen=True)
class CrewRPSnapshot:
    """One pair of *sequential*, never atomic, roster/GCC progress reads.

    ``leaderboard_score`` is the score of an exact crew-ID matched GCC entry,
    not a field named ``cc_rp``. Both counts and the sum are for the *returned*
    roster: completeness relative to the real crew is only independently
    established when ``expected_member_count`` is supplied by a trusted read.
    The two server responses do not independently identify a 14-day season.

    ``season_marker`` is optional *operator-supplied context*, not a verified
    server ID. Comparing markers can flag a transition, not certify a reset.
    """
    crew_id: str = field(repr=False)
    members_returned: int = 0
    member_ids_distinct: bool = False
    member_rp_populated: int = 0
    member_rp_total: Optional[int] = None
    expected_member_count: Optional[int] = None
    leaderboard_score: Optional[int] = None
    leaderboard_rank: Optional[int] = None
    standings: Tuple[GCCProgressCrewScore, ...] = field(default_factory=tuple, repr=False)
    crew_matches: int = 0
    member_read_utc: Optional[datetime] = None
    gcc_read_utc: Optional[datetime] = None
    age_seconds: Optional[float] = None
    read_gap_seconds: Optional[float] = None
    comparable: bool = False
    delta: Optional[int] = None
    season_marker: Optional[str] = field(default=None, repr=False)
    season_timing: Optional[GCCSeasonTiming] = None
    own_crew_rp_unverified: Optional[int] = None
    own_crew_garage_value_unverified: Optional[int] = None
    possible_rollover: bool = False
    season_marker_changed: bool = False
    warnings: Tuple[str, ...] = ()
    active_season_verified: bool = False
    atomic: bool = False

    @classmethod
    def from_reads(
        cls, roster: CrewMembers, leaderboard: GCCProgressCrewScores,
        *, own_crew_id: str, member_read_utc: datetime, gcc_read_utc: datetime,
        now_utc: Optional[datetime] = None,
        expected_member_count: Optional[int] = None,
        previous: Optional["CrewRPSnapshot"] = None,
        season_marker: Optional[str] = None,
        own_crew_rp_unverified: Optional[int] = None,
        own_crew_garage_value_unverified: Optional[int] = None,
        max_age_seconds: float = 300,
        max_read_gap_seconds: float = 30,
    ) -> "CrewRPSnapshot":
        """Evaluate a pair of already-decoded read-only responses.

        A mismatch does not make either result invalid: non-atomic snapshots,
        active earners, roster changes and resets can all cause differences.
        Stale readings cannot yield a comparison delta. ``now_utc`` may be
        injected for deterministic tests; by default it is the local UTC clock.
        """
        if not isinstance(own_crew_id, str) or not own_crew_id.strip():
            raise ValueError("nonempty own_crew_id required")
        if expected_member_count is not None and (type(expected_member_count) is not int
                                                   or not 0 <= expected_member_count <= 30):
            raise ValueError("expected_member_count must be 0..30 or None")
        for value in (own_crew_rp_unverified, own_crew_garage_value_unverified):
            if value is not None and (type(value) is not int or not 0 <= value < 2**63):
                raise ValueError("cumulative crew statistics must be nonnegative integers or None")
        if max_age_seconds <= 0 or max_read_gap_seconds <= 0:
            raise ValueError("age and read-gap thresholds must be positive")
        now = now_utc or datetime.now(timezone.utc)
        timestamps = (member_read_utc, gcc_read_utc, now)
        if any(not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None
               for t in timestamps):
            raise ValueError("all timestamps must be timezone-aware")
        # No silent correction of future/skewed clocks or reverse completion order.
        gap = (gcc_read_utc - member_read_utc).total_seconds()
        age = (now - max(member_read_utc, gcc_read_utc)).total_seconds()
        ids = [member.player_uid or member.zid for member in roster.members]
        unique_ids = bool(ids) and all(ids) and len(set(ids)) == len(ids)
        member_values = [member.season_crew_rp for member in roster.members]
        all_contrib = bool(ids) and all(type(v) is int and v >= 0 for v in member_values)
        count = len(ids)
        complete = (unique_ids and all_contrib and 1 <= count <= 30
                    and (expected_member_count is None or expected_member_count == count))
        matches = [crew for crew in leaderboard.crews if crew.crew_id == own_crew_id]
        own = matches[0] if len(matches) == 1 else None
        notes = []
        if not 1 <= count <= 30:
            notes.append("roster_count_out_of_range")
        if not unique_ids:
            notes.append("missing_or_duplicate_member_identity")
        if not all_contrib:
            notes.append("missing_or_invalid_cc_contrib")
        if expected_member_count is None:
            notes.append("roster_total_not_independently_confirmed")
        elif expected_member_count != count:
            notes.append("roster_count_mismatch")
        if own is None:
            notes.append("unique_own_crew_match_missing")
        if gap < 0 or gap > max_read_gap_seconds:
            notes.append("read_gap_exceeds_limit_or_clock_order_invalid")
        if age < -5 or age > max_age_seconds:
            notes.append("stale_or_future_dated_response")
        total = sum(member_values) if all_contrib else None
        timing = GCCSeasonTiming.from_gcc(leaderboard.extras, gcc_read_utc)
        # A read pair straddling the candidate new-window start must not be
        # compared even if the individual reads are close in wall-clock time.
        # When a prior snapshot exists, its end is the stronger candidate
        # boundary. A 14-calendar-day season can shift by one UTC hour at DST.
        candidate_boundaries = (
            [timing.candidate_start_utc] if timing.timing_plausible else [])
        if previous is not None and previous.crew_id == own_crew_id:
            old_timing = previous.season_timing
            if old_timing and old_timing.timing_plausible:
                candidate_boundaries.append(old_timing.end_utc)
        crosses_boundary = any(
            boundary is not None and member_read_utc < boundary <= gcc_read_utc
            for boundary in candidate_boundaries)
        if crosses_boundary:
            notes.append("roster_and_gcc_reads_cross_candidate_season_boundary")
        marker_changed = False
        rollover = False
        if previous is not None:
            if previous.crew_id != own_crew_id:
                notes.append("crew_membership_changed_since_previous_snapshot")
            else:
                if previous.members_returned != count:
                    notes.append("roster_size_changed_since_previous_snapshot")
                if (season_marker is not None and previous.season_marker is not None
                        and season_marker != previous.season_marker):
                    marker_changed = True
                    notes.append("operator_season_marker_changed")
                if (previous.leaderboard_score is not None and own is not None
                        and own.score < previous.leaderboard_score):
                    rollover = True
                    notes.append("score_decreased_reset_or_correction_possible")
        good_times = (0 <= gap <= max_read_gap_seconds and -5 <= age <= max_age_seconds
                      and not crosses_boundary)
        comparable = bool(complete and own is not None and good_times)
        return cls(
            crew_id=own_crew_id, members_returned=count, member_ids_distinct=bool(unique_ids),
            member_rp_populated=sum(type(v) is int and v >= 0 for v in member_values),
            member_rp_total=total, expected_member_count=expected_member_count,
            leaderboard_score=own.score if own else None,
            leaderboard_rank=own.rank if own else None,
            standings=leaderboard.crews, crew_matches=len(matches),
            member_read_utc=member_read_utc, gcc_read_utc=gcc_read_utc,
            age_seconds=age, read_gap_seconds=gap,
            comparable=comparable, delta=total - own.score if comparable else None,
            season_marker=season_marker, season_timing=timing,
            own_crew_rp_unverified=own_crew_rp_unverified,
            own_crew_garage_value_unverified=own_crew_garage_value_unverified,
            possible_rollover=rollover,
            season_marker_changed=marker_changed, warnings=tuple(notes),
        )

    def public_summary(self, *, show_own_crew_stats: bool = False) -> dict:
        """Identifier-free summary. Larger own-crew statistics require opt-in."""
        result = {
            "members_returned": self.members_returned,
            "member_rp_populated": self.member_rp_populated,
            "member_ids_distinct": self.member_ids_distinct,
            "expected_member_count": self.expected_member_count,
            "member_rp_total": self.member_rp_total,
            "leaderboard_score": self.leaderboard_score,
            "leaderboard_rank": self.leaderboard_rank,
            "standings_returned": len(self.standings),
            "own_crew_id_matches": self.crew_matches,
            "age_seconds": self.age_seconds,
            "read_gap_seconds": self.read_gap_seconds,
            "comparable": self.comparable,
            "member_sum_minus_leaderboard": self.delta,
            "possible_rollover": self.possible_rollover,
            "operator_season_marker_changed": self.season_marker_changed,
            "championship_timing": self.season_timing.public_summary() if self.season_timing else None,
            "active_season_verified": False,
            "atomic": False,
            "warnings": list(self.warnings),
        }
        if show_own_crew_stats:
            result["own_crew_rp_unverified_separate_from_seasonal"] = self.own_crew_rp_unverified
            result["own_crew_garage_value_unverified"] = self.own_crew_garage_value_unverified
        return result
