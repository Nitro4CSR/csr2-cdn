"""Dev88: the 0.7.2 account-state reads.

Three read-only routes verified live on 2026-11-15:
`season_pass/season_pass_info`, `collections/get_collections_blob_data`, and
the weekly `leaderboard/rp-earned/view` board. The fixtures below are shaped
exactly like the live replies, with invented ids.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from csr2cdn._service_reads import (
    ReadContract, ReadContractError, StandingRange, WEEKLY_LEADERBOARDS,
    collections_blob_contract, prepare_read_contract,
    season_pass_contract, weekly_leaderboard_contract,
)
from csr2cdn.season_pass import SeasonPass, TASK_STATES
from csr2cdn.collections_blob import CollectionsBlob
from csr2cdn.service_models import LeaderboardPage, ServiceResponseError


# --------------------------------------------------------------------------
# fixtures (shaped like the live replies)

LIVE_SEASON_PASS = {
    "data": {
        "rewards": {"eligible": ["50f", "900f", "1420f"],
                    "claimed": ["5f", "25f", "50b_1"]},
        "current_season": "Season57", "season_pass_points": 3315,
        "task_progress": {
            "FitFusionAnyWeekly647": {"Progress": 30, "Status": "Complete",
                                      "DurationType": 2, "Index": 3},
            "DonateCrewTokensWeekly636": {"Progress": 20, "Status": "Unlocked",
                                          "DurationType": 2, "Index": 3},
            "LockedTask999": {"Progress": 0, "Status": "Locked",
                              "DurationType": 1, "Index": 0},
        },
        "delta_time_to_refetch": 60595, "bonus_reward_unlocked": False,
        "is_premium_pass": False, "is_premium_pass_plus": False,
        "rp_boost_percent": 0, "new_payer": False, "lapsed_payer": True,
        "rookie_data": None,
    },
}

LIVE_COLLECTIONS = {
    "data": {
        "CarCredits": 106436,
        "CarsPurchasedViaCarCredits": {
            "Mini_CooperJCWGP_2020": [1726480596793],
            "McLaren_GTRewardRecycled_2020": [1, 2, 3, 4],
        },
        "EventsIDPlayed": [300559336, 300559341, 300559347],
    },
}

LIVE_RP_BOARD = {
    "cardinality": 200, "end_time": 1794978000, "time_left": 215395,
    "tier": "tier12", "bucket": "50", "app_ver": "1.6.2", "error_code": 0,
    "scores": [
        {"name": "Blck P", "zid": "95165314524", "facebook_id": "", "score": 2375000,
         "rank": 1, "license_level": 3, "last_updated": 1794730563,
         "sp_boost_data": {}, "crewId": "", "races": "Monadic::Nothing",
         "multiplier": "Monadic::Nothing"},
    ],
}


# --------------------------------------------------------------------------
# account blob

# --------------------------------------------------------------------------
# season pass

def test_season_pass_decodes():
    sp = SeasonPass.from_response(LIVE_SEASON_PASS)
    assert sp.current_season == "Season57"
    assert sp.season_pass_points == 3315
    assert sp.lapsed_payer is True
    assert sp.is_premium_pass is False
    assert sp.rewards_eligible == ("50f", "900f", "1420f")
    assert sp.rewards_claimed == ("5f", "25f", "50b_1")
    assert len(sp.tasks) == 3


def test_season_pass_task_states():
    sp = SeasonPass.from_response(LIVE_SEASON_PASS)
    assert {t.status for t in sp.tasks} <= set(TASK_STATES)
    assert [t.name for t in sp.completed_tasks] == ["FitFusionAnyWeekly647"]
    task = sp.task("DonateCrewTokensWeekly636")
    assert task.progress == 20
    assert task.is_complete is False
    assert task.is_known_state is True


def test_season_pass_missing_raises():
    with pytest.raises(ServiceResponseError):
        SeasonPass.from_response({"data": {"unrelated": 1}})


# --------------------------------------------------------------------------
# collections blob

def test_collections_blob_decodes():
    cb = CollectionsBlob.from_response(LIVE_COLLECTIONS)
    assert cb.car_credits == 106436
    assert cb.cars_purchased_count == 2
    assert cb.purchase("McLaren_GTRewardRecycled_2020").count == 4
    assert cb.purchase("Mini_CooperJCWGP_2020").timestamps == (1726480596793,)
    assert cb.events_played == (300559336, 300559341, 300559347)


def test_collections_blob_missing_raises():
    with pytest.raises(ServiceResponseError):
        CollectionsBlob.from_response({"data": {"unrelated": 1}})


# --------------------------------------------------------------------------
# weekly leaderboard (reuses LeaderboardPage)

def test_rp_board_decodes_as_leaderboard_page():
    page = LeaderboardPage.from_response("rp-earned", LIVE_RP_BOARD)
    assert len(page.entries) == 1
    row = page.entries[0]
    assert row.rank == 1
    assert row.score == 2375000
    assert row.license_level == 3
    assert row.races is None  # Monadic::Nothing sentinel
    assert row.player_id == "95165314524"


# --------------------------------------------------------------------------
# contracts and the allowlist

def test_contracts_are_read_only_and_minimal():
    assert season_pass_contract().route == "season_pass/season_pass_info"
    assert collections_blob_contract().route == "collections/get_collections_blob_data"
    for c in (season_pass_contract(), collections_blob_contract()):
        assert tuple(c.params) == ("app_ver",)
        assert c.request_type == 1


def test_weekly_leaderboard_contract():
    c = weekly_leaderboard_contract("rp-earned", StandingRange.common())
    assert c.route == "leaderboard/rp-earned/view"
    assert c.request_type == 5
    assert tuple(c.params)[0] == "app_ver"
    assert WEEKLY_LEADERBOARDS == ("rp-earned",)
    with pytest.raises(ReadContractError):
        weekly_leaderboard_contract("made-up-board", StandingRange.common())


@pytest.mark.parametrize("route", [
    "season_pass/season_pass_info", "collections/get_collections_blob_data",
])
def test_account_reads_on_allowlist_reject_tampering(route):
    from collections import OrderedDict
    tampered = ReadContract(route, OrderedDict([("app_ver", "6.8.0"), ("extra", 1)]), 1, "x")
    with pytest.raises(ReadContractError):
        prepare_read_contract(None, tampered)


def test_write_routes_are_not_on_the_allowlist():
    from collections import OrderedDict
    for route in ("users/updateProfileSecure", "collections/add_car_credits",
                  "season_pass/process_level_reward"):
        bad = ReadContract(route, OrderedDict([("app_ver", "6.8.0")]), 1, "x")
        with pytest.raises(ReadContractError):
            prepare_read_contract(None, bad)


# --------------------------------------------------------------------------
# service helpers stay offline

def test_service_helpers_prepare_without_network():
    from csr2cdn.services import CSR2Services
    services = CSR2Services("11111111111", allow_network=False)
    prepared = [
        services.prepare_season_pass(),
        services.prepare_collections_blob(),
        services.prepare_weekly_leaderboard(),
    ]
    assert [c.route for c in prepared] == [
        "season_pass/season_pass_info",
        "collections/get_collections_blob_data", "leaderboard/rp-earned/view",
    ]


def test_no_module_embeds_a_real_player_id():
    import csr2cdn.season_pass as season_pass
    import csr2cdn.collections_blob as collections_blob

    shape = re.compile(r"(?<!\d)\d{11}(?!\d)")
    for module in (season_pass, collections_blob):
        text = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        assert not shape.search(text), module.__name__
