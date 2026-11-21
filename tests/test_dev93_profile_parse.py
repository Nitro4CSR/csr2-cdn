"""Dev93: pure non-secure-blob parsers (WEC attempts + car ownership).

All fixtures here are synthetic; no real account data is committed. The blob
shapes mirror what was confirmed on-device: ``evca`` is a flat
``[eventId, count, ...]`` int list, ``cert`` is ``MM/DD/YYYY HH:MM:SS`` (UTC),
and ``caow`` is a list of car dicts each carrying a ``crdb`` name.
"""
from __future__ import annotations

import datetime as dt

import pytest

from csr2cdn.weekly_elite_cup import WeeklyEliteCup
from csr2cdn.profile_parse import (
    WeeklyEliteCupAttempts, parse_weekly_elite_cup_attempts,
    owned_car_db_names, owns_car, owns_any_car, owns_prestige_cup_car,
)

UTC = dt.timezone.utc


def _blob(**over):
    base = {
        "evca": [800309999, 5, 301141034, 3],
        "evcl": [800302999, 536870911],
        "cert": "11/20/2026 10:00:00",
        "caow": [
            {"crdb": "mclaren_senna", "rcat": 5},
            {"crdb": "koenigsegg_jesko"},
            {"crdb": "bugatti_chiron"},
            {"nocrdb": True},        # ignored: no crdb
            "not-a-dict",            # ignored
        ],
    }
    base.update(over)
    return base


def test_wec_attempts_scoped_to_cup_event_id():
    cup = WeeklyEliteCup.for_iteration(309)   # event 800309999
    a = parse_weekly_elite_cup_attempts(_blob(), cup)
    assert isinstance(a, WeeklyEliteCupAttempts)
    assert a.attempts == 5
    assert a.cap == 8
    assert a.remaining == 3
    assert a.exhausted is False
    assert a.reset_at == dt.datetime(2026, 11, 20, 10, 0, tzinfo=UTC)


def test_wec_attempts_absent_event_is_zero():
    cup = WeeklyEliteCup.for_iteration(310)   # event 800310999, not in evca
    a = parse_weekly_elite_cup_attempts(_blob(), cup)
    assert a.attempts == 0
    assert a.remaining == 8
    assert a.exhausted is False


def test_wec_attempts_exhausted_and_over_cap():
    cup = WeeklyEliteCup.for_iteration(309)
    a = parse_weekly_elite_cup_attempts(_blob(evca=[800309999, 8]), cup)
    assert a.exhausted is True
    assert a.remaining == 0


def test_wec_attempts_tolerates_empty_odd_and_bad_cert():
    cup = WeeklyEliteCup.for_iteration(309)
    assert parse_weekly_elite_cup_attempts({"evca": []}, cup).attempts == 0
    # odd-length list: trailing id without a count is dropped, no raise
    odd = parse_weekly_elite_cup_attempts({"evca": [800309999, 2, 301141034]}, cup)
    assert odd.attempts == 2
    assert parse_weekly_elite_cup_attempts({"cert": "garbage"}, cup).reset_at is None
    assert parse_weekly_elite_cup_attempts({}, cup).reset_at is None


def test_car_ownership():
    blob = _blob()
    assert owned_car_db_names(blob) == frozenset(
        {"mclaren_senna", "koenigsegg_jesko", "bugatti_chiron"})
    assert owns_car(blob, "bugatti_chiron") is True
    assert owns_car(blob, "toyota_ae86") is False
    assert owns_any_car(blob, ["toyota_ae86", "koenigsegg_jesko"]) is True
    assert owns_any_car(blob, ["toyota_ae86"]) is False


def test_owns_prestige_cup_car_accepts_str_or_iterable():
    blob = _blob()
    assert owns_prestige_cup_car(blob, "mclaren_senna") is True
    assert owns_prestige_cup_car(blob, "nissan_gtr") is False
    assert owns_prestige_cup_car(blob, ["nissan_gtr", "bugatti_chiron"]) is True
    assert owns_prestige_cup_car(blob, ["nissan_gtr"]) is False


def test_accepts_wrapped_nonsecure_blob():
    cup = WeeklyEliteCup.for_iteration(309)
    wrapped = {"nonSecureBlob": _blob()}
    assert parse_weekly_elite_cup_attempts(wrapped, cup).attempts == 5
    assert owns_car(wrapped, "bugatti_chiron") is True


def test_parser_returns_only_narrow_result_not_the_blob():
    # the result object carries no reference to the source blob's bulk
    cup = WeeklyEliteCup.for_iteration(309)
    a = parse_weekly_elite_cup_attempts(_blob(), cup)
    assert not hasattr(a, "caow") and not hasattr(a, "evcl")
    assert set(vars(a)) == {"cup", "attempts", "cap", "reset_at"}
