"""0.7.1.dev83 — roster/crew scalars that reached no typed attribute.

Placement note: this category already had a home in ``crew_optional_data``
(``CrewOptionalStats`` for crew-wide, ``CrewMemberOptionalStats`` for
per-member), where nine of these fields were already modelled. The new ones
were added there rather than to ``service_models``, so there is exactly one
typed reader per wire key.

``facebook_id`` is the one roster field deliberately NOT modelled;
``test_identifying_fields_stay_unmodelled`` guards that decision.
``license_plate_text`` and ``last_log_in_time`` were in that set until the
maintainer confirmed on 2026-10-21 that plates, in-game IDs and the login time
are all visible in game and fine to print.
"""
import pytest

from csr2cdn.crew_optional_data import (
    CrewMemberOptionalStats, CrewOptionalSnapshot, CrewOptionalStats)
from csr2cdn.service_models import CrewMembers, OwnCrew, ServiceResponseError


# -- crew-wide -----------------------------------------------------------
def own_crew(**over):
    reply = {"crewUID": "12345", "crew_name": "Test Crew", "playerRole": "LEADER",
             "members": 29, "max_members": 30, "crew_status": "OPEN",
             "total_invites": 2, "total_requests": 7, "app_ver": "1.6.2",
             "debug_season": False, "crew_level": 40}
    reply.update(over)
    return OwnCrew.from_response(reply)


def test_crew_stats_read_the_three_new_scalars():
    stats = CrewOptionalStats.from_own_crew(own_crew())
    assert stats.crew_status == "OPEN"
    assert stats.app_ver == "1.6.2"
    assert stats.debug_season is False


def test_crew_stats_keep_reading_the_existing_four():
    stats = CrewOptionalStats.from_own_crew(own_crew())
    assert (stats.members, stats.max_members) == (29, 30)
    assert (stats.total_invites, stats.total_requests) == (2, 7)
    assert stats.crew_level == 40


def test_seats_free_needs_both_sides():
    assert CrewOptionalStats.from_own_crew(own_crew()).seats_free == 1
    assert CrewOptionalStats.from_own_crew(own_crew(members=30)).seats_free == 0
    # Never negative, even if the service over-reports membership.
    assert CrewOptionalStats.from_own_crew(own_crew(members=31)).seats_free == 0
    assert CrewOptionalStats().seats_free is None
    assert CrewOptionalStats(members=5).seats_free is None


def test_new_crew_scalars_default_to_none():
    stats = CrewOptionalStats.from_own_crew(OwnCrew.from_response({"crewUID": "1"}))
    assert stats.crew_status is None
    assert stats.app_ver is None
    assert stats.debug_season is None


@pytest.mark.parametrize("value", [0, 1, "true", "false", None, [], {}])
def test_debug_season_takes_only_a_real_boolean(value):
    """_flag is strict: 0/1 and "true" are not booleans on this wire."""
    assert CrewOptionalStats.from_own_crew(own_crew(debug_season=value)).debug_season is None


def test_crew_status_is_length_capped_like_other_player_text():
    stats = CrewOptionalStats.from_own_crew(own_crew(crew_status="x" * 181))
    assert stats.crew_status is None
    assert CrewOptionalStats.from_own_crew(
        own_crew(crew_status="x" * 180)).crew_status == "x" * 180


# -- the member_count regression -----------------------------------------
def test_member_count_reads_the_live_members_key():
    """The live reply spells the current size `members`, so this was always None."""
    assert own_crew().member_count == 29


@pytest.mark.parametrize("key", ["memberCount", "membersTotal", "members"])
def test_member_count_accepts_every_spelling(key):
    reply = {"crewUID": "1", key: 17}
    assert OwnCrew.from_response(reply).member_count == 17


def test_crewless_envelope_still_carries_its_counters():
    crew = OwnCrew.from_response(
        {"Error": "Player not in crew", "error_code": 306,
         "total_invites": 0, "app_ver": "1.6.2"})
    assert crew.in_crew is False
    assert CrewOptionalStats.from_own_crew(crew).app_ver == "1.6.2"


def test_a_malformed_reply_is_still_an_error():
    with pytest.raises(ServiceResponseError):
        OwnCrew.from_response({"max_members": 30, "app_ver": "1.6.2"})


# -- per-member ----------------------------------------------------------
def member_wire(**over):
    row = {"garage_value": 98765, "career_earning": 123456789, "cash_donated": 5000,
           "collections_rank": 88, "season_pass_rp_boost": 15,
           "season_pass_premium_plus_pass_holder": True,
           "token_donated": 42, "license_level": 12, "tier": 5, "rarity": 2,
           "is_super_rare": True, "avatar_index": 4, "preferred_avatar_type": 1,
           "license_plate_text": "NITRO", "last_log_in_time": 1761000000}
    row.update(over)
    return row


def test_member_stats_read_the_eight_new_scalars():
    st = CrewMemberOptionalStats.from_wire(member_wire())
    assert st.token_donated == 42
    assert st.license_level == 12
    assert (st.tier, st.rarity) == (5, 2)
    assert st.is_super_rare is True
    assert (st.avatar_index, st.preferred_avatar_type) == (4, 1)
    assert st.license_plate_text == "NITRO"
    assert st.last_log_in_time == 1761000000


def test_member_stats_keep_reading_the_existing_six():
    st = CrewMemberOptionalStats.from_wire(member_wire())
    assert st.garage_value == 98765
    assert st.career_earning == 123456789
    assert st.cash_donated == 5000
    assert st.collections_rank == 88
    assert st.season_pass_rp_boost == 15
    assert st.premium_plus_pass_holder is True


def test_absent_member_scalars_are_none_not_zero():
    st = CrewMemberOptionalStats.from_wire({})
    for name in ("token_donated", "license_level", "tier", "rarity",
                 "is_super_rare", "avatar_index", "preferred_avatar_type",
                 "license_plate_text", "last_log_in_time", "garage_value",
                 "career_earning"):
        assert getattr(st, name) is None, name


def test_zero_is_preserved_as_zero():
    """A real 0 donation or tier must not collapse to None."""
    st = CrewMemberOptionalStats.from_wire(
        member_wire(token_donated=0, tier=0, avatar_index=0, is_super_rare=False))
    assert st.token_donated == 0
    assert st.tier == 0
    assert st.avatar_index == 0
    assert st.is_super_rare is False


@pytest.mark.parametrize("value", [-1, "5", 5.0, True, None, [], {}])
def test_junk_counters_degrade_to_none(value):
    st = CrewMemberOptionalStats.from_wire(member_wire(tier=value))
    assert st.tier is None


def test_identifying_fields_stay_unmodelled():
    """A deliberate project decision, not an oversight. Do not 'fix' this.

    A Facebook ID is a real-world social account rather than game data, and
    nothing here needs it to describe a crew. In-game IDs, plate text and the
    login time are a different category: all are visible in game, and all are
    modelled.
    """
    st = CrewMemberOptionalStats.from_wire(member_wire(facebook_id="fb-opaque"))
    names = set(CrewMemberOptionalStats.__dataclass_fields__)
    assert not hasattr(st, "facebook_id")
    assert "facebook_id" not in names
    assert "fb-opaque" not in repr(st)


def test_withheld_fields_remain_reachable_in_extras():
    """Withholding is about typed output, not about hiding data from callers."""
    roster = CrewMembers.from_response("12345", {
        "crewUID": "12345",
        "members": [dict(member_wire(), player_uid="p1", facebook_id="fb")]})
    extras = roster.members[0].extras
    assert extras["facebook_id"] == "fb"


def test_no_wire_key_gets_two_typed_readers():
    """dev83 regression: these were briefly duplicated into service_models."""
    import csr2cdn.service_models as sm
    text = open(sm.__file__, encoding="utf-8").read()
    for key in ("token_donated", "avatar_index", "is_super_rare",
                "crew_status", "debug_season", "preferred_avatar_type",
                "rarity", "license_plate_text", "last_log_in_time"):
        assert '"%s"' % key not in text, key


# -- end to end through the snapshot -------------------------------------
def test_snapshot_surfaces_the_new_scalars():
    own = own_crew()
    roster = CrewMembers.from_response("12345", {
        "crewUID": "12345",
        "members": [dict(member_wire(), player_uid="p1", name="Alt")]})
    snap = CrewOptionalSnapshot.from_reads(own, roster)
    assert snap.crew.crew_status == "OPEN"
    assert snap.crew.seats_free == 1
    assert snap.crew.app_ver == "1.6.2"
    member = snap.members[0]
    assert member.stats.tier == 5
    assert member.stats.token_donated == 42
    assert member.stats.avatar_index == 4
    assert member.stats.license_plate_text == "NITRO"
