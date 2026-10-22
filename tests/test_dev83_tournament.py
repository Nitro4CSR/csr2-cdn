"""0.7.1.dev83 — the own-crew tournament tree.

Offline and synthetic, built to the shapes confirmed live on 2026-10-21:
six consecutive events 272..277, each with a 3-crew match-up, a ~30-entry
member roster, a `hash` that is the crew IDs joined by "_", and a
`vanity_reward` of "<tier>_<unix seconds>" landing on Thursdays 10:00 UTC
exactly 14 days apart.

Privacy, as the maintainer set it on 2026-10-21: in-game player IDs, crew IDs
and plate text are fine to print, so event member rosters and rival crew
identities are retained in full. What must never be retained is a different
category -- opaque auth/token fields and anything unrecognised on the wire.
"""
import pytest

from csr2cdn.crew_optional_data import (
    TOURNAMENT_CADENCE_DAYS, CrewOptionalSnapshot, CrewTournament,
    CrewTournamentEvent, CrewTournamentRival, CrewTournamentShape,
    _split_vanity_reward)
from csr2cdn.service_models import CrewMembers, OwnCrew

OWN = "20000001"
RIVAL_A, RIVAL_B = "20000002", "20000003"
# 2026-08-13 10:00 UTC, then fortnightly.
BASE = 1786615200
FORTNIGHT = 14 * 86400


def event(n, *, crews=(OWN, RIVAL_A, RIVAL_B), members=30, tier=1,
          wire_hash=None, reward=None):
    ids = list(crews)
    return {
        "hash": wire_hash if wire_hash is not None else "_".join(ids),
        "members": ["7%010d" % (i + 1) for i in range(members)],
        "crews": [{"id": c, "name": "crew-%s" % c,
                   "logo": {"id": 2000 + i, "colour": "1Tone"}}
                  for i, c in enumerate(ids)],
        "vanity_reward": reward if reward is not None
        else "%d_%d" % (tier, BASE + (n - 272) * FORTNIGHT),
    }


def tree(ids=range(272, 278), **meta_over):
    ids = list(ids)
    meta = {"scores": [1], "prev_match": [[OWN, RIVAL_A, RIVAL_B]],
            "vanity_reward": "1_%d" % (BASE + (ids[-1] - 272) * FORTNIGHT)}
    meta.update(meta_over)
    return {"events": {str(n): event(n) for n in ids}, "extra": {}, "meta": meta}


def built(**kw):
    return CrewTournament.from_mapping(tree(**kw), OWN)


# -- vanity_reward -------------------------------------------------------
def test_vanity_reward_splits_into_tier_and_timestamp():
    assert _split_vanity_reward("1_1792663200") == (1, 1792663200)
    assert _split_vanity_reward("3_%d" % BASE) == (3, BASE)


@pytest.mark.parametrize("value", [
    None, 42, "", "1", "1_2_3", "a_1792663200", "1_notanumber", "1_", "_1",
])
def test_vanity_reward_refuses_anything_else(value):
    assert _split_vanity_reward(value) == (None, None)


def test_vanity_reward_rejects_an_absurd_timestamp():
    """A tier survives; a stamp outside a sane range does not."""
    assert _split_vanity_reward("1_5") == (1, None)
    assert _split_vanity_reward("1_99999999999") == (1, None)


# -- the hash is a match-up key -----------------------------------------
def test_hash_is_the_crew_ids_joined():
    ev = CrewTournamentEvent.from_wire("272", event(272), OWN)
    assert ev.matchup_key_consistent is True
    assert ev.crew_count == 3


def test_an_inconsistent_hash_is_reported_not_hidden():
    ev = CrewTournamentEvent.from_wire(
        "272", event(272, wire_hash="11111111_22222222_33333333"), OWN)
    assert ev.matchup_key_consistent is False


def test_hash_verdict_is_none_when_there_is_nothing_to_compare():
    raw = event(272); raw["crews"] = []
    assert CrewTournamentEvent.from_wire("272", raw, OWN).matchup_key_consistent is None


# -- events --------------------------------------------------------------
def test_events_are_decoded_and_ordered():
    t = built()
    assert t.present is True
    assert t.event_count == 6
    assert [e.event_id for e in t.events] == [272, 273, 274, 275, 276, 277]
    assert t.current_event_id == 277


def test_event_ids_arrive_as_ints_from_string_keys():
    assert all(isinstance(e.event_id, int) for e in built().events)


def test_cadence_is_derived_from_the_reward_stamps():
    t = built()
    assert t.cadence_days == TOURNAMENT_CADENCE_DAYS == 14


def test_cadence_is_none_when_spacing_is_irregular():
    raw = tree()
    raw["events"]["275"]["vanity_reward"] = "1_%d" % (BASE + 99 * 86400)
    assert CrewTournament.from_mapping(raw, OWN).cadence_days is None


def test_cadence_needs_two_events():
    assert built(ids=[277]).cadence_days is None


def test_own_crew_participation_is_tracked():
    t = built()
    assert all(e.own_crew_participated for e in t.events)
    assert t.own_crew_event_count == 6


def test_own_crew_absence_is_recorded():
    raw = tree()
    raw["events"]["274"] = event(274, crews=(RIVAL_A, RIVAL_B, "99999999"))
    t = CrewTournament.from_mapping(raw, OWN)
    assert t.own_crew_event_count == 5
    assert [e.own_crew_participated for e in t.events].count(False) == 1


def test_participation_is_unknown_without_an_own_crew_id():
    t = CrewTournament.from_mapping(tree())
    assert all(e.own_crew_participated is None for e in t.events)
    assert t.own_crew_event_count is None


# -- member rosters are retained, with summaries -------------------------
def test_member_identifiers_are_retained_with_counts():
    ev = CrewTournamentEvent.from_wire("272", event(272, members=30), OWN)
    assert ev.member_count == 30
    assert ev.distinct_member_count == 30
    assert len(ev.members) == 30
    assert ev.members[0] == "70000000001"
    # Wire order is preserved, not sorted or deduplicated.
    assert list(ev.members) == ["7%010d" % (i + 1) for i in range(30)]


def test_member_roster_is_out_of_repr_for_readability_only():
    """Thirty strings make a repr unreadable; this is not a privacy measure."""
    ev = CrewTournamentEvent.from_wire("272", event(272), OWN)
    assert "70000000001" not in repr(ev)
    assert ev.members[0] == "70000000001"


def test_member_roster_skips_non_identifier_entries():
    raw = event(272)
    raw["members"] = ["70000000001", 70000000002, None, True, {"a": 1}, []]
    ev = CrewTournamentEvent.from_wire("272", raw, OWN)
    assert ev.members == ("70000000001", "70000000002")
    # The count still reflects what the wire actually sent.
    assert ev.member_count == 6


def test_duplicate_members_are_visible_as_a_gap():
    raw = event(272)
    raw["members"] = ["70000000001"] * 29
    ev = CrewTournamentEvent.from_wire("272", raw, OWN)
    assert ev.member_count == 29
    assert ev.distinct_member_count == 1


# -- rivals are modelled but never printed -------------------------------
def test_rivals_are_decoded():
    ev = CrewTournamentEvent.from_wire("272", event(272), OWN)
    assert len(ev.rivals) == 3
    mine = [r for r in ev.rivals if r.is_own_crew]
    assert len(mine) == 1 and mine[0].crew_id == OWN
    other = [r for r in ev.rivals if not r.is_own_crew]
    assert {r.crew_id for r in other} == {RIVAL_A, RIVAL_B}
    assert all(r.logo_colour == "1Tone" for r in ev.rivals)
    assert ev.rivals[0].logo_id == 2000


def test_rival_identity_is_printed_normally():
    r = CrewTournamentRival.from_wire(
        {"id": RIVAL_A, "name": "crew-%s" % RIVAL_A,
         "logo": {"id": 2001, "colour": "1Tone"}}, OWN)
    assert RIVAL_A in repr(r)
    assert ("crew-%s" % RIVAL_A) in repr(r)
    assert r.is_own_crew is False


def test_large_tuples_stay_out_of_repr_for_readability():
    """Six events x (3 rivals + 30 members) is unreadable, not secret."""
    t = built()
    assert "rivals" not in repr(t.events[0])
    assert "events" not in repr(t)
    # Still fully reachable.
    assert sum(len(e.rivals) for e in t.events) == 18
    assert sum(len(e.members) for e in t.events) == 180


def test_opaque_and_unknown_wire_keys_are_never_retained():
    """The one thing still withheld unconditionally."""
    raw = tree()
    raw["events"]["272"]["auth"] = "SECRET_EVENT"
    raw["events"]["272"]["hidden_token"] = "LOGO_SECRET"
    raw["events"]["272"]["crews"][0]["auth_secret"] = "TOP_SECRET_SETUP"
    raw["meta"]["TOKEN_PRIVATE"] = "TOKEN_SECRET"
    t = CrewTournament.from_mapping(raw, OWN)
    rendered = repr(t) + repr(t.events) + repr([e.rivals for e in t.events])
    for secret in ("SECRET_EVENT", "LOGO_SECRET", "TOP_SECRET_SETUP",
                   "TOKEN_SECRET", "TOKEN_PRIVATE"):
        assert secret not in rendered, secret
    # Not merely hidden from repr: not held anywhere on the model.
    for e in t.events:
        assert not hasattr(e, "auth") and not hasattr(e, "hidden_token")
        for r in e.rivals:
            assert not hasattr(r, "auth_secret")


def test_rival_from_junk_is_empty_not_an_error():
    for junk in (None, 7, "x", [], {}):
        r = CrewTournamentRival.from_wire(junk, OWN)
        assert r.crew_id is None and r.logo_id is None


def test_rival_without_a_logo_object():
    r = CrewTournamentRival.from_wire({"id": "123", "name": "n"}, OWN)
    assert r.logo_id is None and r.logo_colour is None


# -- meta ----------------------------------------------------------------
def test_meta_describes_the_current_event():
    t = built()
    assert t.current_reward_tier == 1
    assert t.current_reward_at == BASE + 5 * FORTNIGHT
    assert t.current_reward_at == t.events[-1].reward_at


def test_prev_match_actually_names_the_current_matchup():
    """The wire name is misleading; this is the observed behaviour."""
    t = built()
    assert t.prev_match_crew_count == 3
    assert t.prev_match_is_current_event is True


def test_prev_match_pointing_elsewhere_is_reported_as_false():
    t = CrewTournament.from_mapping(
        tree(prev_match=[["11111111", "22222222", "33333333"]]), OWN)
    assert t.prev_match_is_current_event is False


def test_scores_only_when_it_is_the_single_int_observed():
    assert built().current_score == 1
    for bad in ([], [1, 2], ["1"], [True], 1, None, {}):
        assert CrewTournament.from_mapping(tree(scores=bad), OWN).current_score is None


def test_empty_extra_is_not_reported_as_populated():
    assert built().extra_populated is False


def test_a_future_extra_payload_is_noticed():
    raw = tree(); raw["extra"] = {"something_new": 1}
    assert CrewTournament.from_mapping(raw, OWN).extra_populated is True


# -- degradation ---------------------------------------------------------
@pytest.mark.parametrize("raw", [None, 7, "x", [], ()])
def test_junk_tree_is_absent_not_an_error(raw):
    t = CrewTournament.from_mapping(raw, OWN)
    assert t.present is False and t.events == () and t.event_count is None


def test_an_empty_tree_is_present_but_bare():
    t = CrewTournament.from_mapping({}, OWN)
    assert t.present is True
    assert t.event_count == 0
    assert t.current_event_id is None
    assert t.cadence_days is None


def test_malformed_events_do_not_sink_the_tree():
    raw = tree()
    raw["events"]["999"] = "not-an-object"
    t = CrewTournament.from_mapping(raw, OWN)
    assert t.event_count == 7
    assert t.current_event_id == 999
    assert t.events[-1].crew_count is None


# -- the presence-only view is untouched ---------------------------------
def test_shape_model_still_works_alongside():
    shape = CrewTournamentShape.from_mapping(tree())
    assert shape.present and shape.events_present and shape.meta_present
    assert shape.events_keys == 6
    assert shape.meta_keys == 3


def test_snapshot_exposes_the_tournament():
    own = OwnCrew.from_response(
        {"crewUID": OWN, "members": 1, "tournament": tree()})
    roster = CrewMembers.from_response(
        OWN, {"crewUID": OWN, "members": [{"player_uid": "p1", "name": "a"}]})
    snap = CrewOptionalSnapshot.from_reads(own, roster)
    assert snap.tournament.current_event_id == 277
    assert snap.tournament.cadence_days == 14
    assert snap.tournament.own_crew_event_count == 6
    assert len(snap.tournament.events[0].members) == 30


def test_snapshot_without_a_tournament_is_fine():
    own = OwnCrew.from_response({"crewUID": OWN, "members": 1})
    roster = CrewMembers.from_response(
        OWN, {"crewUID": OWN, "members": [{"player_uid": "p1", "name": "a"}]})
    snap = CrewOptionalSnapshot.from_reads(own, roster)
    assert snap.tournament.present is False
