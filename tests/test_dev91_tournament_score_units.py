"""Dev91: the Collections Tournament board ``score`` is ten-thousandths of a
second, not milliseconds.

0.7.2 read the board ``score`` as milliseconds and divided by 1000, which made
every time 10x too large (a 1.7237 s run showed as 17.237 s). The real format,
confirmed against tournament 279's live rows and the known competitive race
times, is ET seconds x 10000 -- a fixed-point integer -- so seconds are
``score / 10000``.

Each case below pairs a real rank-1 raw ``score`` from tournament 279 with the
competitive (fastest-known) time for that race. A real crew's best member runs
at or just above that floor, so ``score / 10000`` must land inside a generous
+20% band -- and the old ``/ 1000`` value (10x) must fall far outside it.
"""
from __future__ import annotations

import pytest

from csr2cdn.collections_tournament import MemberRaceTime

# (day, race, raw score of a real rank-1 row, competitive floor in seconds)
# Raw scores are the tournament-279 board values; floors are the fastest-known
# times for each race. Day 3 floors (7.770, 8.545) are known but no raw row was
# captured, so they are not asserted here.
LIVE = [
    ("Day1", "Race1", 17237, 1.690),
    ("Day1", "Race2", 99182, 9.800),
    ("Day2", "Race1", 112352, 11.190),
    ("Day2", "Race2", 110904, 11.000),
]

GENEROUS_BAND = 1.20  # casual players up to 20% slower than the competitive floor


@pytest.mark.parametrize("day, race, raw, floor", LIVE)
def test_score_is_ten_thousandths_of_a_second(day, race, raw, floor):
    t = MemberRaceTime(day, race, raw)
    # the format: seconds = score / 10000, ms = score / 10
    assert t.best_time_seconds == raw / 10000.0
    assert t.best_time_ms == raw / 10.0
    # real time lands at or just above the competitive floor, inside +20%
    assert floor <= t.best_time_seconds <= floor * GENEROUS_BAND
    # the old 0.7.2 behaviour (score / 1000) is 10x too large -- far outside
    assert raw / 1000.0 > floor * GENEROUS_BAND


def test_absent_score_stays_none():
    t = MemberRaceTime("Day1", "Race1", None)
    assert t.best_time_raw is None
    assert t.best_time_seconds is None
    assert t.best_time_ms is None
