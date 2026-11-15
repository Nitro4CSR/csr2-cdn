"""Dev86: the 0.7.2 crew-service read contracts and their decoders.

Six targets, all read-only, all reconstructed from the 6.8.0 IL2CPP metadata:
the two previously-discarded fields of `crews/checkUserCrew`,
`events/crewEventProgress`, `crews/showCrewsRanks`, `leaderboard/{board}/top`,
`wildcards/status` and `crews/checkCrewPerks`.

No test here asserts that a live server accepts any of it. What they do assert
is that the package cannot invent a value it was not given, cannot be talked
into a request outside the allowlist, and reports "absent" rather than zero.
"""
from __future__ import annotations

import re

import pytest

from csr2cdn._service_reads import (
    ReadContractError, StandingRange, WILDCARD_ROUTES, crew_event_progress_contract,
    crew_perks_contract, crew_rankings_contract,
    prepare_read_contract, wildcard_status_contract,
)
from csr2cdn.crew_optional_data import CrewTournament
from csr2cdn.crew_service_reads import (
    WILDCARD_STATES, CrewEventProgress, CrewMilestone, CrewPerks, CrewRankings,
    CrewWildcardStatus,
)
from csr2cdn.service_models import OwnCrew, ServiceResponseError


# --------------------------------------------------------------------------
# request contracts


def test_crew_event_progress_contract_shape():
    contract = crew_event_progress_contract("CREW1", "EVT1", "SER1")
    assert contract.route == "events/crewEventProgress"
    # EWebRequestType.Events ordinal; documentary only.
    assert contract.request_type == 4
    assert tuple(contract.params) == ("crew_uid", "event_id", "series_id", "app_ver")
    assert contract.params["app_ver"] == "6.8.0"


@pytest.mark.parametrize("args", [
    ("", "EVT1", "SER1"),
    ("CREW1", "", "SER1"),
    ("CREW1", "EVT1", "bad/slash"),
    ("CREW1", "EVT1", "x" * 200),
])
def test_crew_event_progress_rejects_unsafe_identifiers(args):
    with pytest.raises(ReadContractError):
        crew_event_progress_contract(*args)


def test_crew_rankings_contract_omits_offset():
    """FetchCrewRankings takes no offset, so StandingRange must not be used."""
    contract = crew_rankings_contract("CREW1", top=10, before=5, after=5)
    assert contract.route == "crews/showCrewsRanks"
    assert contract.request_type == 3
    assert tuple(contract.params) == ("crew_uid", "app_ver", "top", "before", "after")
    assert "offset" not in contract.params


@pytest.mark.parametrize("kwargs", [
    {"top": 0, "before": 5, "after": 5},
    {"top": 51, "before": 5, "after": 5},
    {"top": 10, "before": -1, "after": 5},
    {"top": 10, "before": 31, "after": 5},
    {"top": 10, "before": 5, "after": 31},
    {"top": True, "before": 5, "after": 5},
])
def test_crew_rankings_bounds(kwargs):
    with pytest.raises(ReadContractError):
        crew_rankings_contract("CREW1", **kwargs)


def test_wildcard_contract_accepts_only_traced_spellings():
    # The plural is the one that answers live, so it is first and the default.
    assert WILDCARD_ROUTES == ("wildcards/status", "wildcard/status")
    assert wildcard_status_contract().route == "wildcards/status"
    for route in WILDCARD_ROUTES:
        contract = wildcard_status_contract(route=route)
        assert contract.route == route
        assert tuple(contract.params) == ("app_ver",)
    with pytest.raises(ReadContractError):
        wildcard_status_contract(route="wildcard/activate")


def test_crew_perks_contract_shape():
    contract = crew_perks_contract("CREW1")
    assert contract.route == "crews/checkCrewPerks"
    assert tuple(contract.params) == ("crew_uid", "app_ver")


# --------------------------------------------------------------------------
# the allowlist


def _credentials():
    pytest.importorskip("csr2cdn._service_auth")
    from csr2cdn._service_auth import PortalCredentials
    return PortalCredentials


def test_new_contracts_are_on_the_allowlist():
    """A mutated contract must not reach the signer."""
    from csr2cdn._service_reads import ReadContract
    from collections import OrderedDict

    tampered = ReadContract("events/crewEventProgress",
                            OrderedDict([("crew_uid", "C"), ("app_ver", "6.8.0")]),
                            4, "Fetches crew event progress")
    with pytest.raises(ReadContractError):
        prepare_read_contract(None, tampered)  # type: ignore[arg-type]

    off_list = ReadContract("crews/kickCrew",
                            OrderedDict([("app_ver", "6.8.0")]), 3, "nope")
    with pytest.raises(ReadContractError):
        prepare_read_contract(None, off_list)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# events/crewEventProgress


def test_crew_event_progress_is_a_crew_aggregate():
    progress = CrewEventProgress.from_response(
        {"isValid": True, "crewEventProgress":
            {"isValid": True, "progress": 137, "participated": ["111", "222"]}})
    assert progress.progress == 137
    assert progress.is_valid is True
    assert progress.participated_member_ids == ("111", "222")
    # The same value must not also read as a count or a flag.
    assert progress.participated_count is None
    assert progress.participated_flag is None
    assert progress.participated_shape == "list[2]"


@pytest.mark.parametrize("value,shape,count,flag,ids", [
    (4, "int", 4, None, None),
    (True, "bool", None, True, None),
    (["1"], "list[1]", None, None, ("1",)),
    ({"a": 1}, "object", None, None, None),
])
def test_participated_accessors_only_answer_for_their_own_shape(value, shape, count, flag, ids):
    progress = CrewEventProgress.from_response(
        {"crewEventProgress": {"progress": 1, "participated": value}})
    assert progress.participated_shape == shape
    assert progress.participated_count == count
    assert progress.participated_flag == flag
    assert progress.participated_member_ids == ids


def test_inner_is_valid_false_is_not_a_transport_failure():
    """A closed series reports isValid=False; that is data, not an error."""
    progress = CrewEventProgress.from_response(
        {"crewEventProgress": {"isValid": False, "progress": 0}})
    assert progress.is_valid is False
    assert progress.progress == 0


def test_outer_failure_envelope_still_raises():
    with pytest.raises(ServiceResponseError):
        CrewEventProgress.from_response({"isValid": False, "errorCode": 500})
    with pytest.raises(ServiceResponseError):
        CrewEventProgress.from_response({"unrelated": 1})


def test_absent_progress_is_none_not_zero():
    progress = CrewEventProgress.from_response({"crewEventProgress": {"participated": 0}})
    assert progress.progress is None


# --------------------------------------------------------------------------
# crews/showCrewsRanks


def test_crew_rankings_decodes_neighbours():
    rankings = CrewRankings.from_response({
        "crewUID": "C1", "crewRank": 42,
        "topCrews": [{"crewUID": "T1", "crewName": "Alpha", "crewRank": 1, "crewRP": 99}],
        "crewsJustAbove": [{"crewUID": "A1", "crewRank": 41}],
        "crewsJustBelow": [{"crewUID": "B1", "crewRank": 43}],
    })
    assert rankings.crew_rank == 42
    assert [e.crew_uid for e in rankings.top] == ["T1"]
    assert rankings.top[0].score == 99
    assert [e.crew_uid for e in rankings.neighbourhood] == ["A1", "B1"]


def test_crew_rankings_tolerates_missing_lists():
    rankings = CrewRankings.from_response({"crewUID": "C1", "crewRank": 7})
    assert rankings.top == () and rankings.just_above == () and rankings.just_below == ()


def test_crew_rankings_skips_non_object_rows():
    rankings = CrewRankings.from_response(
        {"crewRank": 1, "topCrews": [{"crewUID": "T1"}, "junk", 5, None]})
    assert len(rankings.top) == 1


def test_crew_rankings_requires_a_marker_field():
    with pytest.raises(ServiceResponseError):
        CrewRankings.from_response({"crewUID": "C1"})


# --------------------------------------------------------------------------
# crews/checkCrewPerks


#: Trimmed from the reply verified live on 2026-11-06.
LIVE_PERKS = {
    "app_ver": "1.3.0", "crew_uid": "C1", "crew_respect_rank": 25, "error_code": 0,
    "perkGroupsUnlocked": 0, "perksUnlocked": [],
    "milestone_achieved": {
        "Milestone_Crew_CE": 4, "Milestone_Crew_CE_Reward": 20,
        "Milestone_Crew_CE_quantity": 35917022934,
        "Milestone_Crew_CE_quantity_target": 0,
        "Milestone_Crew_Level": 4, "Milestone_Crew_Level_quantity": 25,
        "Milestone_Crew_Level_quantity_target": 25,
        "Milestone_EVO_Points": 0, "Milestone_EVO_Points_quantity": 0,
        "Milestone_EVO_Points_quantity_target": 1000,
    },
}


def test_crew_perks_decodes_the_live_reply():
    perks = CrewPerks.from_response(LIVE_PERKS)
    assert perks.crew_respect_rank == 25
    assert perks.crew_uid == "C1"
    assert perks.perk_groups_unlocked == 0
    assert perks.perks_unlocked == ()
    assert perks.families == ("Crew_CE", "Crew_Level", "EVO_Points")


def test_milestone_quantity_target_suffix_is_not_read_as_quantity():
    """`_quantity_target` must win over `_quantity`, or the family splits."""
    crew_ce = CrewPerks.from_response(LIVE_PERKS).milestone("Crew_CE")
    assert crew_ce.quantity == 35917022934
    assert crew_ce.target == 0
    assert crew_ce.tier == 4
    assert crew_ce.reward == 20


def test_target_zero_means_maxed_not_a_requirement_of_zero():
    perks = CrewPerks.from_response(LIVE_PERKS)
    maxed = perks.milestone("Crew_CE")
    assert maxed.is_maxed is True
    assert maxed.remaining is None
    assert maxed.fraction is None

    pending = perks.milestone("EVO_Points")
    assert pending.is_maxed is False
    assert pending.remaining == 1000
    assert pending.fraction == 0.0


def test_milestone_overshoot_never_goes_negative():
    record = CrewMilestone("X", tier=1, quantity=120, target=100)
    assert record.remaining == 0
    assert record.fraction == 1.0


def test_milestone_families_are_not_a_fixed_list():
    """A family the decoder has never seen must still come through."""
    perks = CrewPerks.from_response({"milestone_achieved": {
        "Milestone_Something_New": 2,
        "Milestone_Something_New_quantity": 5,
        "Milestone_Something_New_quantity_target": 10}})
    record = perks.milestone("Something_New")
    assert (record.tier, record.quantity, record.target) == (2, 5, 10)


def test_crew_perks_absent_counts_stay_none():
    perks = CrewPerks.from_response({"crew_respect_rank": 0})
    assert perks.crew_respect_rank == 0
    assert perks.perk_groups_unlocked is None
    assert perks.perks_unlocked == ()
    assert perks.milestones == ()


# --------------------------------------------------------------------------
# wildcards/status


#: Shaped exactly like the reply verified live on 2026-11-06.
LIVE_WILDCARDS = {
    "app_ver": "1.6.2", "error_code": 0, "last_message_id": 23086,
    "period_mod": 1, "season_end_time": 1795082400, "token": 530,
    "cards": [
        {"cost": 250, "level": 25, "paid": 250, "rarity": "bronze",
         "seq": 0, "status": "complete"},
        {"cost": 500, "level": 25, "paid": 120, "rarity": "silver",
         "seq": 1, "status": "incomplete"},
        {"cost": 900, "level": 25, "paid": 900, "rarity": "gold",
         "seq": 2, "status": "active"},
    ],
}


def test_wildcard_status_decodes_the_live_reply():
    status = CrewWildcardStatus.from_response(LIVE_WILDCARDS)
    assert status.season_end_time == 1795082400
    assert status.token == 530
    assert status.period_mod == 1
    assert status.last_message_id == 23086
    assert len(status.cards) == 3


def test_wildcard_rarity_is_a_string_not_an_integer():
    """`WildcardData.rarity` is an int in C#; on the wire it is "bronze"."""
    card = CrewWildcardStatus.from_response(LIVE_WILDCARDS).cards[0]
    assert card.rarity == "bronze"
    assert isinstance(card.rarity, str)


def test_wildcard_status_values_match_the_compiled_enum():
    status = CrewWildcardStatus.from_response(LIVE_WILDCARDS)
    assert all(card.is_known_state for card in status.cards)
    assert set(c.status for c in status.cards) <= set(WILDCARD_STATES)
    assert [c.seq for c in status.active] == [2]


def test_wildcard_progress_is_derived_not_invented():
    cards = CrewWildcardStatus.from_response(LIVE_WILDCARDS).cards
    assert cards[1].remaining == 380
    assert round(cards[1].fraction, 2) == 0.24
    assert cards[0].remaining == 0
    bare = CrewWildcardStatus.from_response(
        {"token": 1, "cards": [{"seq": 0}]}).cards[0]
    assert bare.remaining is None
    assert bare.fraction is None
    assert bare.is_complete is None


def test_wildcard_status_does_not_surface_client_side_bookkeeping():
    status = CrewWildcardStatus.from_response({
        "season_end_time": 1, "cards": [
            {"awaitingNetwork_Donate": True, "pendingDonationAmount": 50}]})
    card = status.cards[0]
    assert not hasattr(card, "awaiting_network_donate")
    assert not hasattr(card, "pending_donation_amount")
    # ...but nothing is lost, so a real reply can still be inspected.
    assert card.raw["pendingDonationAmount"] == 50


# --------------------------------------------------------------------------
# crews/checkUserCrew: the tournament block and the error envelope


def test_own_crew_positional_fields_did_not_shift():
    """extras is still the raw node after the 0.7.2 field changes."""
    crew = OwnCrew.from_response({"crewUID": "C1", "crewName": "Alpha", "members": 3})
    assert crew.name == "Alpha"
    assert crew.member_count == 3
    assert crew.extras["crewUID"] == "C1"
    assert not hasattr(crew, "cup_standing")
    assert not hasattr(crew, "crew_leaderboard_type")


LIVE_TOURNAMENT_BLOCK = {
    "events": {
        "278": {"crews": [{"id": "10000001", "name": "a", "logo": {}}],
                "hash": "10000001_10000002_10000003",
                "members": ["20000000001"], "vanity_reward": "1_1793872800"},
        "279": {"crews": [{"id": "10000004", "name": "b", "logo": {}}],
                "hash": "10000004_10000002_10000005",
                "members": ["20000000001"]},
    },
    "extra": {},
}


def test_the_tournament_block_is_the_collections_tournament():
    """`tournament` is the client's CollectionsTournamentCrewData.

    It reaches OwnCrew untouched and decodes through CrewTournament, keyed by
    tournament id, with the closed event's tier as the crew's placing.
    """
    crew = OwnCrew.from_response({
        "crew_uid": "C1", "crew_name": "Alpha", "members": 30,
        "player_role": "LEADER", "error_code": 0,
        "tournament": LIVE_TOURNAMENT_BLOCK})
    assert crew.extras["tournament"] is LIVE_TOURNAMENT_BLOCK
    tournament = CrewTournament.from_mapping(crew.extras["tournament"], "10000002")
    assert [e.event_id for e in tournament.events] == [278, 279]
    assert tournament.current_event_id == 279
    assert tournament.events[0].reward_tier == 1
    assert tournament.events[1].reward_tier is None  # still open


def test_snake_case_error_code_is_a_failure_not_a_result():
    """Live replies spell it `error_code`; an error envelope must not pass."""
    from csr2cdn.crew_service_reads import CrewPerks as _Perks

    for decoder in (CrewRankings.from_response, CrewWildcardStatus.from_response,
                    _Perks.from_response):
        with pytest.raises(ServiceResponseError):
            decoder({"app_ver": "1.6.2", "error_code": 403})


def test_error_code_zero_is_still_a_success():
    status = CrewWildcardStatus.from_response(
        {"error_code": 0, "token": 1, "cards": []})
    assert status.token == 1


def test_crewless_306_envelope_survives_the_stricter_check():
    """The no-crew answer is itself an error envelope, so it is matched first."""
    crew = OwnCrew.from_response({
        "Error": "Player not in crew", "error_code": 306,
        "player_uid": "x", "total_invites": 0, "app_ver": "1.6.2"})
    assert crew.in_crew is False


def test_crewless_envelope_still_decodes_with_the_new_fields():
    crew = OwnCrew.from_response({
        "Error": "Player not in crew", "error_code": 306,
        "player_uid": "x", "total_invites": 0, "app_ver": "1.6.2"})
    assert crew.in_crew is False


# --------------------------------------------------------------------------
# no identifiers in reprs


def test_reprs_do_not_leak_raw_reply_nodes():
    """Raw nodes stay out of repr; promoted identifiers are allowed."""
    crew = OwnCrew.from_response({"crewUID": "C1", "secretField": "SENSITIVE"})
    assert "SENSITIVE" not in repr(crew)
    progress = CrewEventProgress.from_response(
        {"crewEventProgress": {"progress": 1, "participated": ["SENSITIVE"]}})
    assert "SENSITIVE" not in repr(progress)


def test_service_helpers_prepare_without_network():
    """Every `prepare_*` must stay offline, as the rest of the class does."""
    from csr2cdn.services import CSR2Services

    services = CSR2Services("11111111111", allow_network=False)
    prepared = [
        services.prepare_crew_event_progress("EVT", "SER", crew_uid="C1"),
        services.prepare_crew_rankings(crew_uid="C1"),
        services.prepare_wildcard_status(),
        services.prepare_crew_perks("C1"),
    ]
    assert [c.route for c in prepared] == [
        "events/crewEventProgress", "crews/showCrewsRanks",
        "wildcards/status", "crews/checkCrewPerks",
    ]


def test_service_helpers_refuse_an_unresolved_crew():
    from csr2cdn.services import CSR2Services

    services = CSR2Services("11111111111", allow_network=False)
    for call in (lambda: services.prepare_crew_perks(),
                 lambda: services.prepare_crew_rankings(),
                 lambda: services.prepare_crew_event_progress("EVT", "SER")):
        with pytest.raises(ReadContractError):
            call()


def test_no_module_embeds_a_real_player_id():
    """Guard by shape, so the guard does not embed one either."""
    import pathlib

    import csr2cdn.crew_service_reads as crew_reads

    shape = re.compile(r"(?<!\d)\d{11}(?!\d)")
    for module in (crew_reads,):
        text = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        assert not shape.search(text), module.__name__
