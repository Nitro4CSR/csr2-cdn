"""0.7.1.dev84 — fields the Showdown Leagues endpoints send that were dropped.

Found by auditing every supported endpoint against the live service rather
than only the two crew reads. Shapes are taken from a live leagues board:
21 rows carrying crewId, last_updated, multiplier and sp_boost_data, and a
score response carrying last_updated, sig and sig_timestamp.
"""
import pytest

from csr2cdn.service_models import (
    MONADIC_NOTHING, LeaderboardEntry, LeaderboardPage, LeaderboardScore,
    ServiceResponseError, _optional_str)

BOARD = "evnt-off-202-dur-240-hours-dsc---301141039"


def row(**over):
    r = {"rank": 1, "zid": "10000000001", "name": "Alt", "score": 4200,
         "races": 7, "license_level": 3, "crewId": "", "facebook_id": "fb",
         "last_updated": 1792674789, "multiplier": MONADIC_NOTHING,
         "sp_boost_data": {}}
    r.update(over)
    return r


def page(*rows):
    return LeaderboardPage.from_response(BOARD, {"scores": list(rows) or [row()]})


# -- the Nothing sentinel ------------------------------------------------
def test_the_backend_nothing_sentinel_is_not_a_value():
    """Every live row sends this string instead of omitting the key."""
    assert MONADIC_NOTHING == "Monadic::Nothing"
    assert _optional_str({"k": MONADIC_NOTHING}, "k") is None
    assert _optional_str({"k": "  %s  " % MONADIC_NOTHING}, "k") is None


@pytest.mark.parametrize("value,expected", [
    ("2x", "2x"), ("", None), ("   ", None), (None, None),
    ("Monadic::Just 2", "Monadic::Just 2"),
])
def test_optional_str_keeps_real_values(value, expected):
    assert _optional_str({"k": value}, "k") == expected


def test_a_real_multiplier_survives():
    assert page(row(multiplier="1.5x")).entries[0].multiplier == "1.5x"


def test_the_live_multiplier_reads_as_absent():
    assert page().entries[0].multiplier is None


# -- crewId spelling ----------------------------------------------------
def test_the_leagues_crew_id_spelling_is_read():
    """Regression: the decoder knew crew_uid/crewUID/crew_id but not crewId."""
    assert page(row(crewId="20000001")).entries[0].crew_id == "20000001"


def test_an_empty_crew_id_is_absent_not_an_empty_string():
    """It is "" on all 21 live rows, because leagues ranks players."""
    assert page().entries[0].crew_id is None


@pytest.mark.parametrize("key", ["crew_uid", "crewUID", "crew_id", "crewId"])
def test_every_crew_id_spelling_still_works(key):
    r = row(); del r["crewId"]; r[key] = "20000001"
    assert page(r).entries[0].crew_id == "20000001"


# -- the other two row fields -------------------------------------------
def test_row_last_updated_is_read_as_sent():
    assert page().entries[0].last_updated == 1792674789


def test_sp_boost_data_is_retained_so_a_future_payload_is_visible():
    assert page().entries[0].sp_boost_data == {}
    loaded = page(row(sp_boost_data={"boost": 3})).entries[0]
    assert loaded.sp_boost_data == {"boost": 3}


@pytest.mark.parametrize("junk", [None, 7, "x", [], "Monadic::Nothing"])
def test_a_non_object_sp_boost_data_degrades_to_empty(junk):
    assert page(row(sp_boost_data=junk)).entries[0].sp_boost_data == {}


def test_absent_row_fields_are_none():
    bare = {"rank": 1, "zid": "1", "name": "n", "score": 1}
    entry = LeaderboardPage.from_response(BOARD, {"scores": [bare]}).entries[0]
    assert entry.last_updated is None
    assert entry.multiplier is None
    assert entry.sp_boost_data == {}
    assert entry.crew_id is None


def test_existing_entry_fields_are_untouched():
    e = page().entries[0]
    assert (e.rank, e.score) == (1, 4200)
    assert e.player_id == "10000000001" and e.player_name == "Alt"
    assert e.extras["races"] == 7


def test_appended_fields_keep_positional_construction_working():
    e = LeaderboardEntry(1, "z", "n", 10)
    assert e.last_updated is None and e.multiplier is None
    assert e.sp_boost_data == {}


# -- the score response -------------------------------------------------
def score(**over):
    body = {"score": 4200, "rank": 12, "last_updated": 1792674789,
            "sig": "a" * 64, "sig_timestamp": 1792674790,
            "tier": 3, "bucket": 1, "app_ver": "1.6.2"}
    body.update(over)
    return LeaderboardScore.from_response(BOARD, body)


def test_score_reads_the_response_metadata():
    s = score()
    assert s.last_updated == 1792674789
    assert s.sig_timestamp == 1792674790
    assert (s.score, s.rank) == (4200, 12)


def test_the_signature_is_reported_present_but_not_retained():
    """A 64-hex server integrity value: opaque-token family, like `auth`."""
    s = score()
    assert s.signature_present is True
    assert "a" * 64 not in repr(s)
    for name in ("sig", "signature"):
        assert name not in LeaderboardScore.__dataclass_fields__
    # Still reachable for anyone who needs it.
    assert s.extras["sig"] == "a" * 64


@pytest.mark.parametrize("value,present", [
    ("a" * 64, True), ("", False), ("   ", False), (None, False),
    (12345, False), ([], False),
])
def test_signature_presence_requires_a_non_empty_string(value, present):
    assert score(sig=value).signature_present is present


def test_a_score_response_without_a_signature():
    body = {"score": 1, "rank": 2}
    s = LeaderboardScore.from_response(BOARD, body)
    assert s.signature_present is False
    assert s.last_updated is None and s.sig_timestamp is None


def test_a_score_response_with_neither_score_nor_rank_still_raises():
    with pytest.raises(ServiceResponseError):
        LeaderboardScore.from_response(BOARD, {"tier": 3, "sig": "a" * 64})


def test_nested_score_data_wrapper_is_still_honoured():
    s = LeaderboardScore.from_response(
        BOARD, {"scoreData": {"score": 9, "rank": 1, "last_updated": 5,
                              "sig": "b" * 64, "sig_timestamp": 6}})
    assert (s.score, s.rank) == (9, 1)
    assert s.last_updated == 5 and s.sig_timestamp == 6
    assert s.signature_present is True
