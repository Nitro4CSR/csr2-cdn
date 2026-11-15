"""The active Grand Crew Championship season, computed from server constants.

Until now a caller had to supply the season by hand: ``seasonal_prestige_car``
said "the caller must obtain the exact season from authoritative metadata" and
``PrestigeCupDiscovery`` reported ``runtime_season_or_car_tier_not_supplied``.
The constants were published all along, in
``CrewLeaderboardRewardDefinitions.GrandCrewChampionshipManagerConfig``::

    Season0StartTime = 1456394400   # 2016-02-25 10:00 UTC
    Duration         = 20160        # minutes, exactly 14 days

so::

    season = floor((now - Season0StartTime) / (Duration * 60))

Verified three ways on 2026-11-06, which is why this is a computation and not
a guess:

* the formula gave season 279, with a window ending 2026-11-19 10:00 UTC;
* the live ``crews/gccProgress`` envelope reported ``end_time`` 1795082400,
  the *same integer* as the computed window end;
* ``checkUserCrew``'s tournament tree independently reported
  ``current_event_id`` 279.

One thing this is **not**: the highest ``assets_client_metadata_<N>`` bundle on
the CDN. Those are published ahead of time -- on that date the newest was 282,
three seasons out -- the same pre-publishing the asset database does for
``branch_name``. Reading the maximum overshoots; the formula does not.

``Duration`` is read from the block rather than assumed, so a cadence change
follows the server instead of needing a code change. The ``DEBUG_*`` twins in
that block describe an internal test championship and are ignored.

**Prefer the server's clock.** A season is a 14-day window, so a local clock
that is wrong by minutes is harmless mid-season and wrong *about which season
it is* for a few minutes either side of a rollover -- which is exactly when a
caller asking for "the current Prestige Cup car" would get the wrong answer.
The service hands us its own time without an extra request: the
``crews/gccProgress`` envelope carries ``end_time`` and ``time_left``, whose
difference is the server's now. Measured 3.9 s from the local clock on
2026-11-06. :func:`server_now_from_gcc` extracts it and
:meth:`GrandCrewChampionshipSchedule.active_season_from_gcc` uses it, falling
back to the local clock only when the envelope cannot supply one.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

#: Where the constants live inside ``CrewLeaderboardRewardDefinitions``.
CONFIG_SECTION = "GrandCrewChampionshipManagerConfig"
#: Sane bounds for the epoch, so a malformed block cannot yield season 400000.
_MIN_EPOCH, _MAX_EPOCH = 946684800, 4102444800


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _nonnegative_int(value: Any) -> Optional[int]:
    """Zero is admissible: ``time_left`` is 0 the moment a season closes."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def server_now_from_gcc(envelope: Any) -> Optional[datetime]:
    """The service's own clock, from a ``crews/gccProgress`` envelope.

    ``end_time`` is when the season closes and ``time_left`` how long remains,
    so their difference is the server's current time. Returns None rather than
    a guess when either field is missing or out of range, so a caller can tell
    "no server clock" from "server clock says X".
    """
    if not isinstance(envelope, Mapping):
        return None
    end = _positive_int(envelope.get("end_time"))
    left = _nonnegative_int(envelope.get("time_left"))
    if end is None or left is None or not (_MIN_EPOCH <= end <= _MAX_EPOCH):
        return None
    if left > end - _MIN_EPOCH:
        return None
    return datetime.fromtimestamp(end - left, timezone.utc)


@dataclass(frozen=True)
class GrandCrewChampionshipSchedule:
    """Season numbering and windows, as the service publishes them."""
    season_zero_start: int
    period_seconds: int
    #: The service path for the championship leaderboard, published alongside.
    endpoint_url: Optional[str] = None
    source: str = "CrewLeaderboardRewardDefinitions.GrandCrewChampionshipManagerConfig"

    @classmethod
    def from_block(cls, block: Any) -> "GrandCrewChampionshipSchedule":
        """Decode the block, or its ``GrandCrewChampionshipManagerConfig``."""
        node = block
        if isinstance(block, Mapping) and CONFIG_SECTION in block:
            node = block[CONFIG_SECTION]
        if not isinstance(node, Mapping):
            raise ValueError("%s section missing" % CONFIG_SECTION)
        start = _positive_int(node.get("Season0StartTime"))
        minutes = _positive_int(node.get("Duration"))
        if start is None or not (_MIN_EPOCH <= start <= _MAX_EPOCH):
            raise ValueError("Season0StartTime missing or out of range")
        if minutes is None:
            raise ValueError("Duration missing or not a positive integer")
        url = node.get("EndpointURL")
        return cls(start, minutes * 60,
                   url.strip() if isinstance(url, str) and url.strip() else None)

    # -- numbering ------------------------------------------------------
    def season_at(self, when: datetime) -> int:
        """The season number covering ``when`` (timezone-aware)."""
        if not isinstance(when, datetime) or when.tzinfo is None \
                or when.utcoffset() is None:
            raise ValueError("when must be timezone-aware")
        elapsed = when.astimezone(timezone.utc).timestamp() - self.season_zero_start
        return math.floor(elapsed / self.period_seconds)

    def active_season(self, *, now: Optional[datetime] = None) -> int:
        return self.season_at(now if now is not None else datetime.now(timezone.utc))

    def active_season_from_gcc(self, envelope: Any,
                               *, now: Optional[datetime] = None):
        """``(season, used_server_clock)`` -- the season, and whose clock said so.

        Uses the server's time when the envelope supplies it, otherwise the
        local clock, and reports which, because near a rollover the two can
        disagree about the answer.
        """
        server = server_now_from_gcc(envelope)
        if server is not None:
            return (self.season_at(server), True)
        when = now if now is not None else datetime.now(timezone.utc)
        return (self.season_at(when), False)

    def clock_skew_seconds(self, envelope: Any,
                           *, now: Optional[datetime] = None) -> Optional[float]:
        """Server time minus local time, or None when unavailable."""
        server = server_now_from_gcc(envelope)
        if server is None:
            return None
        when = now if now is not None else datetime.now(timezone.utc)
        return (server - when.astimezone(timezone.utc)).total_seconds()

    def near_rollover(self, *, now: Optional[datetime] = None,
                      margin_seconds: int = 600) -> bool:
        """True when ``now`` sits within ``margin_seconds`` of a boundary.

        A caller that is near one should trust the server clock rather than
        its own, or re-read instead of caching the answer.
        """
        when = now if now is not None else datetime.now(timezone.utc)
        start, end = self.window(self.season_at(when))
        return min((when - start).total_seconds(),
                   (end - when).total_seconds()) <= margin_seconds

    def window(self, season: int):
        """``(start, end)`` for a season, as timezone-aware datetimes."""
        if isinstance(season, bool) or not isinstance(season, int):
            raise ValueError("season must be an integer")
        start = self.season_zero_start + season * self.period_seconds
        return (datetime.fromtimestamp(start, timezone.utc),
                datetime.fromtimestamp(start + self.period_seconds, timezone.utc))

    def window_epochs(self, season: int):
        start, end = self.window(season)
        return (int(start.timestamp()), int(end.timestamp()))

    @property
    def period_days(self) -> float:
        return self.period_seconds / 86400

    # -- corroboration --------------------------------------------------
    def agrees_with_gcc_end_time(self, end_time: Any,
                                 *, now: Optional[datetime] = None) -> Optional[bool]:
        """Does a live ``gccProgress`` ``end_time`` equal the computed window end?

        None when ``end_time`` is absent or not a usable integer, so a caller
        can tell "disagrees" from "nothing to compare".
        """
        value = _positive_int(end_time)
        if value is None or not (_MIN_EPOCH <= value <= _MAX_EPOCH):
            return None
        return value == self.window_epochs(self.active_season(now=now))[1]

    def agrees_with_tournament_event(self, event_id: Any,
                                     *, now: Optional[datetime] = None) -> Optional[bool]:
        """Does ``checkUserCrew``'s newest tournament event id match the season?"""
        if isinstance(event_id, bool) or not isinstance(event_id, int):
            return None
        return event_id == self.active_season(now=now)

    def public_summary(self, *, now: Optional[datetime] = None) -> dict:
        when = now if now is not None else datetime.now(timezone.utc)
        season = self.active_season(now=when)
        start, end = self.window(season)
        return {
            "active_season": season,
            "window_start_utc": start.isoformat(),
            "window_end_utc": end.isoformat(),
            "period_days": self.period_days,
            "season_zero_start_utc": datetime.fromtimestamp(
                self.season_zero_start, timezone.utc).isoformat(),
            "endpoint_url": self.endpoint_url,
            "source": self.source,
        }
