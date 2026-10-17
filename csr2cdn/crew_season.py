"""Offline-only GCC championship boundary and reset evaluation.

The operator expects a 14-day reset to zero for member ``cc_contrib`` and
GCC progress ``score``. The before/after evaluator tests that contract without
manufacturing a server reset, season ID, or locally overriding server values.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .crew_rp import CrewRPSnapshot

EXPECTED_PERIOD_SECONDS = 14 * 24 * 60 * 60
# A 14-calendar-day boundary can differ by an hour in Unix seconds across DST.
PERIOD_CLOCK_SHIFT_ALLOWANCE_SECONDS = 3600


def _nonnegative_int(value: object) -> Optional[int]:
    return value if type(value) is int and 0 <= value < 2**63 else None


@dataclass(frozen=True)
class GCCSeasonTiming:
    """Inferred time-window evidence from a *current-progress* GCC envelope.

    A plausible end time isn't an independently confirmed season identity.
    The candidate start assumes successive 14-day windows, as supplied by
    the operator, not a verified server-provided start timestamp.
    """
    end_utc: Optional[datetime]
    time_left_seconds: Optional[int]
    candidate_start_utc: Optional[datetime]
    implied_server_time_utc: Optional[datetime]
    clock_delta_seconds: Optional[float]
    timing_plausible: bool
    expected_period_seconds: int = EXPECTED_PERIOD_SECONDS
    season_id_verified: bool = False

    @classmethod
    def from_gcc(cls, extras: object, read_utc: datetime,
                 *, maximum_clock_delta_seconds: float = 5.0) -> "GCCSeasonTiming":
        from collections.abc import Mapping
        if not isinstance(read_utc, datetime) or read_utc.tzinfo is None or read_utc.utcoffset() is None:
            raise ValueError("read_utc must be timezone-aware")
        if maximum_clock_delta_seconds <= 0:
            raise ValueError("maximum_clock_delta_seconds must be positive")
        envelope = extras if isinstance(extras, Mapping) else {}
        end_epoch = _nonnegative_int(envelope.get("end_time"))
        left = _nonnegative_int(envelope.get("time_left"))
        # A bounded Unix time range and time-left guard; reject ambiguous units.
        if end_epoch is None or not (946684800 <= end_epoch <= 4102444800):
            end_epoch = None
        if left is None or left > EXPECTED_PERIOD_SECONDS + PERIOD_CLOCK_SHIFT_ALLOWANCE_SECONDS:
            left = None
        end = datetime.fromtimestamp(end_epoch, timezone.utc) if end_epoch is not None else None
        implied = (end - timedelta(seconds=left)) if end is not None and left is not None else None
        delta = ((implied - read_utc.astimezone(timezone.utc)).total_seconds()
                 if implied is not None else None)
        plausible = delta is not None and abs(delta) <= maximum_clock_delta_seconds
        return cls(end_utc=end, time_left_seconds=left,
                   candidate_start_utc=(end - timedelta(seconds=EXPECTED_PERIOD_SECONDS)
                                        if plausible else None),
                   implied_server_time_utc=implied, clock_delta_seconds=delta,
                   timing_plausible=plausible)

    def public_summary(self) -> dict:
        return {
            "candidate_end_utc": self.end_utc.isoformat() if self.end_utc else None,
            "time_left_seconds_candidate": self.time_left_seconds,
            "candidate_start_utc_if_14_days": (
                self.candidate_start_utc.isoformat() if self.candidate_start_utc else None),
            "implied_server_time_utc": (
                self.implied_server_time_utc.isoformat() if self.implied_server_time_utc else None),
            "implied_time_minus_read_seconds": self.clock_delta_seconds,
            "timing_plausible": self.timing_plausible,
            "expected_period_seconds_operator_supplied": self.expected_period_seconds,
            "season_id_verified": False,
        }


@dataclass(frozen=True)
class CrewSeasonTransition:
    """Compare previously obtained snapshots. Zero resets are never fabricated.

    A ``True`` zero-reset observation means the *returned* 14-day-advanced
    window and a complete roster/GCC result contain zeros. It does not prove
    independently that the game has a stable 14-day schedule across seasons.
    """
    same_crew: bool
    chronological: bool
    boundary_advanced: bool
    boundary_advanced_by_14_days: bool
    boundary_step_seconds: Optional[float]
    current_roster_complete: bool
    reset_to_zero_observed: bool
    member_and_gcc_agree: bool
    previous_own_crew_rp_unverified: Optional[int]
    current_own_crew_rp_unverified: Optional[int]
    own_crew_rp_difference: Optional[int]
    previous_own_crew_garage_value_unverified: Optional[int] = None
    current_own_crew_garage_value_unverified: Optional[int] = None
    own_crew_garage_value_difference: Optional[int] = None
    warnings: tuple[str, ...] = ()
    season_id_verified: bool = False

    @classmethod
    def between(cls, previous: "CrewRPSnapshot", current: "CrewRPSnapshot") -> "CrewSeasonTransition":
        from .crew_rp import CrewRPSnapshot
        if not isinstance(previous, CrewRPSnapshot) or not isinstance(current, CrewRPSnapshot):
            raise TypeError("two CrewRPSnapshot instances required")
        same = previous.crew_id == current.crew_id
        p_time = previous.gcc_read_utc
        c_time = current.gcc_read_utc
        chronological = bool(p_time is not None and c_time is not None and c_time > p_time)
        old_window = previous.season_timing
        new_window = current.season_timing
        old_end = old_window.end_utc if old_window and old_window.timing_plausible else None
        new_end = new_window.end_utc if new_window and new_window.timing_plausible else None
        advance = bool(same and chronological and old_end and new_end and new_end > old_end)
        boundary_step = (new_end - old_end).total_seconds() if advance else None
        fourteen_calendar_days_plausible = bool(
            boundary_step is not None and
            abs(boundary_step - EXPECTED_PERIOD_SECONDS) <= PERIOD_CLOCK_SHIFT_ALLOWANCE_SECONDS)
        agree = bool(current.comparable and current.delta == 0)
        reset = bool(fourteen_calendar_days_plausible and previous.member_rp_total is not None and
                     previous.member_rp_total > 0 and previous.leaderboard_score is not None and
                     previous.leaderboard_score > 0 and current.member_rp_total == 0 and
                     current.leaderboard_score == 0 and agree and current.member_rp_populated == current.members_returned)
        old_cum = previous.own_crew_rp_unverified if same else None
        new_cum = current.own_crew_rp_unverified if same else None
        diff = new_cum - old_cum if old_cum is not None and new_cum is not None else None
        old_garage = previous.own_crew_garage_value_unverified if same else None
        new_garage = current.own_crew_garage_value_unverified if same else None
        garage_diff = new_garage - old_garage if old_garage is not None and new_garage is not None else None
        notes = []
        if not same:
            notes.append("crew_identity_changed")
        if not chronological:
            notes.append("snapshots_not_chronological")
        if old_end is None or new_end is None:
            notes.append("championship_timing_not_plausible_or_unavailable")
        if advance and not fourteen_calendar_days_plausible:
            notes.append("championship_boundary_advanced_by_unexpected_duration")
        if fourteen_calendar_days_plausible and not reset:
            notes.append("zero_reset_not_observed_may_have_resumed_earning")
        if not agree:
            notes.append("current_roster_gcc_comparison_not_equal_or_incomplete")
        if diff is not None and diff < 0:
            notes.append("own_crew_rp_declined_check_roster_or_corrections")
        return cls(same_crew=same, chronological=chronological,
                   boundary_advanced=advance,
                   boundary_advanced_by_14_days=fourteen_calendar_days_plausible,
                   boundary_step_seconds=boundary_step,
                   current_roster_complete=bool(current.comparable),
                   reset_to_zero_observed=reset,
                   member_and_gcc_agree=agree,
                   previous_own_crew_rp_unverified=old_cum,
                   current_own_crew_rp_unverified=new_cum,
                   own_crew_rp_difference=diff,
                   previous_own_crew_garage_value_unverified=old_garage,
                   current_own_crew_garage_value_unverified=new_garage,
                   own_crew_garage_value_difference=garage_diff,
                   warnings=tuple(notes))

    def public_summary(self, *, show_own_crew_stats: bool = False) -> dict:
        result = {
            "same_crew": self.same_crew,
            "chronological": self.chronological,
            "candidate_boundary_advanced": self.boundary_advanced,
            "advanced_by_operator_expected_14_days_allowing_dst_hour": self.boundary_advanced_by_14_days,
            "boundary_step_seconds": self.boundary_step_seconds,
            "current_roster_complete": self.current_roster_complete,
            "member_and_gcc_agree": self.member_and_gcc_agree,
            "zero_reset_observed_in_supplied_snapshots": self.reset_to_zero_observed,
            "own_crew_rp_comparison_available": self.own_crew_rp_difference is not None,
            "own_crew_garage_comparison_available": self.own_crew_garage_value_difference is not None,
            "season_id_verified": False,
            "warnings": list(self.warnings),
        }
        if show_own_crew_stats:
            result.update({
                "previous_own_crew_rp_unverified": self.previous_own_crew_rp_unverified,
                "current_own_crew_rp_unverified": self.current_own_crew_rp_unverified,
                "own_crew_rp_difference": self.own_crew_rp_difference,
                "previous_own_crew_garage_value_unverified": self.previous_own_crew_garage_value_unverified,
                "current_own_crew_garage_value_unverified": self.current_own_crew_garage_value_unverified,
                "own_crew_garage_value_difference": self.own_crew_garage_value_difference,
            })
        return result
