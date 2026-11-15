"""Dev90: the Collections Tournament — board ids, config, standings.

Verified live 2026-11-15: all six race boards of tournament 279 answered with
per-member best times and attempts. Fixtures are shaped like the live config
and board replies, with invented ids.
"""
from __future__ import annotations

import pathlib
import re
from collections import OrderedDict

import pytest

from csr2cdn._service_reads import (
    ReadContract, ReadContractError, StandingRange, prepare_read_contract,
    tournament_race_contract,
)
from csr2cdn.collections_tournament import (
    BOARD_PREFIX, CollectionsTournamentStandings, TournamentConfig, TournamentError,
    board_id, current_tournament, parse_board_id, standard_board_ids,
)
from csr2cdn.service_models import ServiceResponseError

GROUP = "10000001_10000002_10000003"


# --------------------------------------------------------------------------
# board ids

def test_board_id_matches_the_live_format():
    b = board_id(279, GROUP, "Day1", "Race1")
    assert b == BOARD_PREFIX + "279-" + GROUP + "-Day1_Race1"
    assert parse_board_id(b) == ("279", GROUP, "Day1", "Race1", False)


def test_debug_prefix_is_never_implied():
    live = board_id(279, GROUP, "Day1", "Race1")
    debug = board_id(279, GROUP, "Day1", "Race1", debug=True)
    assert live != debug
    assert parse_board_id(debug)[4] is True


@pytest.mark.parametrize("args", [
    ("", GROUP, "Day1", "Race1"),
    (279, "not-a-group", "Day1", "Race1"),
    (279, GROUP, "Day", "Race1"),
    (279, GROUP, "Day1", "Lap1"),
])
def test_board_id_rejects_bad_parts(args):
    with pytest.raises(TournamentError):
        board_id(*args)


@pytest.mark.parametrize("board", [
    "csr2-collections-tournament---279-10000001-Day1_Race1",  # group has one id
    "leaderboard/x/top", None, "crew-champs-v2-279",
    BOARD_PREFIX + "279-" + GROUP + "-Day1",                  # no race
])
def test_parse_board_id_refuses_bad(board):
    assert parse_board_id(board) is None


def test_standard_board_ids_is_the_six_race_grid():
    boards = standard_board_ids(279, GROUP)
    assert len(boards) == 6
    assert [(d, r) for d, r, _ in boards] == [
        ("Day1", "Race1"), ("Day1", "Race2"), ("Day2", "Race1"),
        ("Day2", "Race2"), ("Day3", "Race1"), ("Day3", "Race2")]
    assert all(parse_board_id(b) for _, _, b in boards)


# --------------------------------------------------------------------------
# config

LIVE_CONFIG = {
    "TemplateConfigs": {
        "3Days": {"PeriodDuration": 86400, "ResultCalculationTime": 300,
                  "ScheduleId": "TOURNAMENT_SEASONAL", "BaseSeasonId": "220"},
    },
    "TournamentEvents": {
        "300": {
            "TemplateId": "3Days",
            "LeaderboardRewardId": "TournamentCrew",
            "MilestoneRewardId": "TournamentMilestoneRewards",
            "PeriodDetails": {
                "Day1": {
                    "Race1": {"JournalId": "coll_r_blackseries", "SlotId": "coll_r_blackseries_Slot_1",
                              "Multiplier": 2, "ParticipationMultiplier": 10,
                              "Restrictions": [{"RestrictionType": "NoNitrousAllowed"}],
                              "RaceEvent": {"EventID": 300364017, "IsHalfMile": True},
                              "RetriesPerCooldown": 3, "CooldownTime": 180},
                    "Race2": {"JournalId": "coll_r_blackseries", "SlotId": "x",
                              "Restrictions": [], "RaceEvent": {"EventID": 300364018}},
                },
                "Day2": {"Race1": {"RaceEvent": {"EventID": 1}}, "Race2": {"RaceEvent": {"EventID": 2}}},
                "Day3": {"Race1": {"RaceEvent": {"EventID": 3}}, "Race2": {"RaceEvent": {"EventID": 4}}},
            },
        },
    },
}


def test_config_decodes_the_race_grid():
    cfg = TournamentConfig.from_block(LIVE_CONFIG, 300)
    assert cfg.template_id == "3Days"
    assert cfg.period_seconds == 86400
    assert cfg.schedule_id == "TOURNAMENT_SEASONAL"
    assert cfg.leaderboard_reward_id == "TournamentCrew"
    assert cfg.day_ids == ("Day1", "Day2", "Day3")
    assert len(cfg.races) == 6
    r = cfg.race("Day1", "Race1")
    assert r.restrictions == ("NoNitrousAllowed",)
    assert r.event_id == 300364017
    assert r.cooldown_time == 180
    assert r.retries_per_cooldown == 3
    assert r.participation_multiplier == 10


def test_config_board_ids_use_the_group():
    cfg = TournamentConfig.from_block(LIVE_CONFIG, 300)
    boards = cfg.board_ids(GROUP)
    assert len(boards) == 6
    assert all(b.startswith(BOARD_PREFIX + "300-" + GROUP) for _, _, b in boards)


def test_config_can_be_read_from_a_nested_bundle():
    bundle = {"anything": {"wrapper": LIVE_CONFIG}}
    cfg = TournamentConfig.from_block(bundle, 300)
    assert len(cfg.races) == 6


def test_config_missing_event_raises():
    with pytest.raises(TournamentError):
        TournamentConfig.from_block(LIVE_CONFIG, 999)


# --------------------------------------------------------------------------
# standings

def _board_reply(rows):
    return {"error_code": 0, "cardinality": len(rows), "scores": [
        {"zid": zid, "name": name, "crewId": crew, "score": score, "races": races,
         "rank": rank, "facebook_id": "", "sp_boost_data": {}}
        for (zid, name, crew, score, races, rank) in rows]}


def _six_boards():
    # two members of crew A, one of crew B, across the six races
    boards = []
    for i, (day, race) in enumerate([("Day1", "Race1"), ("Day1", "Race2"),
                                     ("Day2", "Race1"), ("Day2", "Race2"),
                                     ("Day3", "Race1"), ("Day3", "Race2")]):
        boards.append((day, race, _board_reply([
            ("111", "Alice", "A", 10000 + i, 2 + i, 1),
            ("222", "Bob", "A", 12000 + i, 1, 2),
            ("333", "Cara", "B", 9000 + i, 5, 3),
        ])))
    return boards


def test_standings_fold_members_and_crews():
    st = CollectionsTournamentStandings.from_boards(279, GROUP, _six_boards())
    assert len(st.boards_read) == 6
    assert len(st.members) == 3
    assert {c.crew_id for c in st.crews} == {"A", "B"}
    alice = st.member("111")
    assert alice.crew_id == "A"
    assert alice.races_entered == 6
    assert alice.total_attempts == sum(2 + i for i in range(6))
    assert alice.sum_best_time_ms == sum(10000 + i for i in range(6))
    rt = alice.race_time("Day1", "Race1")
    assert rt.best_time_ms == 10000
    assert rt.best_time_seconds == 10.0
    assert rt.rank == 1


def test_standings_crew_aggregate():
    st = CollectionsTournamentStandings.from_boards(279, GROUP, _six_boards())
    crew_a = st.crew("A")
    assert crew_a.member_count == 2
    assert crew_a.participating_member_count == 2
    assert crew_a.sum_best_time_ms == (sum(10000 + i for i in range(6))
                                       + sum(12000 + i for i in range(6)))


def test_standings_skip_a_closed_board():
    boards = _six_boards()
    boards[0] = ("Day1", "Race1", {"error_code": 403})  # closed race
    st = CollectionsTournamentStandings.from_boards(279, GROUP, boards)
    assert ("Day1", "Race1") not in st.boards_read
    assert len(st.boards_read) == 5
    assert st.member("111").race_time("Day1", "Race1") is None
    assert st.member("111").races_entered == 5


def test_standings_require_valid_ids():
    with pytest.raises(TournamentError):
        CollectionsTournamentStandings.from_boards(279, "bad", _six_boards())


# --------------------------------------------------------------------------
# current-tournament resolver

def test_current_tournament_picks_the_latest_event():
    block = {"events": {"274": {"hash": "1_2_3"},
                        "279": {"hash": GROUP},
                        "278": {"hash": "4_5_6"}}, "meta": {}}
    assert current_tournament(block) == ("279", GROUP)


def test_current_tournament_none_without_a_group():
    assert current_tournament({"meta": {}}) is None
    assert current_tournament({"events": {"279": {}}}) is None
    assert current_tournament(None) is None


# --------------------------------------------------------------------------
# contract and allowlist

def test_tournament_race_contract():
    b = board_id(279, GROUP, "Day1", "Race1")
    c = tournament_race_contract(b, StandingRange.common())
    assert c.route == "leaderboard/%s/top" % b
    assert c.request_type == 5
    assert c.params["extra"] is True


def test_contract_rejects_a_non_tournament_board():
    with pytest.raises(ReadContractError):
        tournament_race_contract("evnt-off-160-dur-170-hours-dsc---301176007", StandingRange.common())


def test_allowlist_requires_the_extra_flag():
    b = board_id(279, GROUP, "Day1", "Race1")
    bad = ReadContract("leaderboard/%s/top" % b,
                       OrderedDict([("app_ver", "6.8.0"), ("top", 20), ("after", 10),
                                    ("before", 10), ("offset", 0)]), 5, "x")
    with pytest.raises(ReadContractError):
        prepare_read_contract(None, bad)


def test_service_helpers_stay_offline():
    from csr2cdn.services import CSR2Services
    services = CSR2Services("11111111111", allow_network=False)
    b = board_id(279, GROUP, "Day1", "Race1")
    c = services.prepare_tournament_race(b)
    assert c.route == "leaderboard/%s/top" % b
    with pytest.raises(ReadContractError):
        services.prepare_tournament_race("not-a-board")


def test_no_real_player_id_in_module():
    import csr2cdn.collections_tournament as ct
    text = pathlib.Path(ct.__file__).read_text(encoding="utf-8")
    assert not re.search(r"(?<!\d)\d{11}(?!\d)", text)
