"""0.7.2 groundwork: season numbering, reward cars, ladders, collections cups.

Synthetic, built to the shapes read live on 2026-11-06. Anchors:

* ``Season0StartTime`` 1456394400 with ``Duration`` 20160 minutes gives season
  279 for that date, a window ending 1795082400, which the live
  ``gccProgress`` ``end_time`` matched exactly.
* season 279's Prestige Cup car is ``Chevrolet_LBCamaroIROCZRewardRecycled_1987``.
* the two weekly cups hold 44 and 68 races, matching where their win ladders
  top out.
"""
from datetime import datetime, timedelta, timezone

import pytest

from csr2cdn.collections_cups import (CUP_ID, RESTRICTION_KINDS, CollectionsCup,
                                      CollectionsCupCalendar, CupRace, Restriction)
from csr2cdn.crew_season_schedule import GrandCrewChampionshipSchedule
from csr2cdn.event_milestones import (COLLECTIONS_CUP_CONTAINERS, TUNER_CUP,
                                      EventMilestoneCatalogue, threshold_ladder)
from csr2cdn.reward_types import (SUSPECT_TITLE_BAND, SUSPECT_TITLE_ID,
                                  RewardTypeVocabulary)
from csr2cdn.seasonal_reward_cars import (SeasonalRewardCarIndex,
                                          from_season_bundle,
                                          resolve_seasonal_reward_car,
                                          season_bundle_code)

SEASON_ZERO = 1456394400          # 2016-02-25 10:00 UTC
PERIOD_MINUTES = 20160            # 14 days
AT = datetime(2026, 11, 6, 18, 49, tzinfo=timezone.utc)
LIVE_GCC_END = 1795082400         # 2026-11-19 10:00 UTC


def config(**over):
    cfg = {"Season0StartTime": SEASON_ZERO, "Duration": PERIOD_MINUTES,
           "EndpointURL": "leaderboard/crew-champs-v2/",
           "DEBUG_Season0StartTime": 1461924000, "DEBUG_Duration": 15}
    cfg.update(over)
    return {"GrandCrewChampionshipManagerConfig": cfg}


# -- season numbering ----------------------------------------------------
def test_the_formula_reproduces_the_live_season():
    s = GrandCrewChampionshipSchedule.from_block(config())
    assert s.active_season(now=AT) == 279
    assert s.period_days == 14.0
    assert s.endpoint_url == "leaderboard/crew-champs-v2/"


def test_the_window_end_matches_the_live_gcc_envelope():
    """The strongest corroboration: an exact integer match to a server value."""
    s = GrandCrewChampionshipSchedule.from_block(config())
    assert s.window_epochs(279)[1] == LIVE_GCC_END
    assert s.agrees_with_gcc_end_time(LIVE_GCC_END, now=AT) is True
    assert s.agrees_with_gcc_end_time(LIVE_GCC_END + 1, now=AT) is False


def test_the_tournament_event_id_cross_check():
    s = GrandCrewChampionshipSchedule.from_block(config())
    assert s.agrees_with_tournament_event(279, now=AT) is True
    assert s.agrees_with_tournament_event(282, now=AT) is False


@pytest.mark.parametrize("bad", [None, True, "279", 279.0, []])
def test_a_non_integer_cross_check_is_unknown_not_false(bad):
    """None means "nothing to compare", which a caller must tell from False."""
    s = GrandCrewChampionshipSchedule.from_block(config())
    assert s.agrees_with_tournament_event(bad, now=AT) is None
    assert s.agrees_with_gcc_end_time(bad, now=AT) is None


def test_windows_are_contiguous_and_period_long():
    s = GrandCrewChampionshipSchedule.from_block(config())
    start, end = s.window(279)
    assert (end - start) == timedelta(days=14)
    assert s.window(280)[0] == end
    assert s.season_at(start) == 279
    assert s.season_at(end) == 280          # the boundary belongs to the next
    assert s.season_at(end - timedelta(seconds=1)) == 279


def test_season_zero_starts_where_the_block_says():
    s = GrandCrewChampionshipSchedule.from_block(config())
    assert s.window_epochs(0)[0] == SEASON_ZERO
    assert s.season_at(datetime.fromtimestamp(SEASON_ZERO, timezone.utc)) == 0


def test_a_cadence_change_is_followed_not_assumed():
    """Duration is read, so a server change needs no code change."""
    weekly = GrandCrewChampionshipSchedule.from_block(config(Duration=10080))
    assert weekly.period_days == 7.0
    # Season 279 was 1.37 days into its fortnight, so halving the period lands
    # on 558 whole weeks, not 559.
    assert weekly.active_season(now=AT) == 558


def test_the_debug_twins_are_ignored():
    s = GrandCrewChampionshipSchedule.from_block(config())
    assert s.season_zero_start == SEASON_ZERO
    assert s.period_seconds == PERIOD_MINUTES * 60


@pytest.mark.parametrize("over", [
    {"Season0StartTime": 0}, {"Season0StartTime": -1}, {"Duration": 0},
    {"Season0StartTime": "1456394400"}, {"Duration": None},
    {"Season0StartTime": 10}, {"Season0StartTime": 99999999999},
])
def test_a_malformed_config_raises_rather_than_computing_nonsense(over):
    with pytest.raises(ValueError):
        GrandCrewChampionshipSchedule.from_block(config(**over))


def test_a_naive_datetime_is_refused():
    s = GrandCrewChampionshipSchedule.from_block(config())
    with pytest.raises(ValueError):
        s.season_at(datetime(2026, 11, 6, 18, 49))


# -- reward type vocabulary ---------------------------------------------
def vocab():
    return RewardTypeVocabulary.from_block({"Types": {
        "1": {"RewardType": "Cash", "TitleStringId": "TEXT_CASH"},
        "2": {"RewardType": "Gold", "TitleStringId": "TEXT_GOLD"},
        "13": {"RewardType": "FusionUpgrade", "TitleStringId": "TEXT_FUSION"},
        "18": {"RewardType": "CrewRP", "TitleStringId": "TEXT_CREW_RP"},
        "24": {"RewardType": "AftermarketParts", "TitleStringId": "TEXT_AMP"},
        "47": {"RewardType": "CarCredits", "TitleStringId": SUSPECT_TITLE_ID},
        "53": {"RewardType": "TournamentTrophies", "TitleStringId": SUSPECT_TITLE_ID},
    }})


def test_reward_names_resolve():
    v = vocab()
    assert v.name(1) == "Cash"
    assert v.name(47) == "CarCredits"
    assert v.describe(24, {"partGrade": 2}) == "AftermarketParts [grade 2]"
    assert "matches locked-in car" in v.describe(13, {"matchLockedInCar": True})


def test_the_mispasted_title_band_is_withheld_but_the_name_is_kept():
    """Upstream data bug: 46..59 share the profile-banner title string."""
    v = vocab()
    assert v.title_id(1) == "TEXT_CASH"
    assert v.title_id(47) is None          # suspect, so not offered
    assert v.name(47) == "CarCredits"      # the name is still right
    assert set(v.suspect_titles) == {47, 53}
    assert 47 in SUSPECT_TITLE_BAND


def test_an_undefined_type_with_its_own_name_is_a_flexible_currency():
    """rewardType 35 is used live by tuner_cup but absent from the block."""
    v = vocab()
    assert v.name(35) is None
    assert v.name(35, {"name": "EliteTuners_Credits"}) == "EliteTuners_Credits"
    assert v.describe(35, {"name": "EliteTuners_Credits"}) == "EliteTuners_Credits"


def test_an_unknown_type_with_no_name_is_reported_as_unknown():
    v = vocab()
    assert v.name(999) is None
    assert v.describe(999, {}) == "rewardType=999"


def test_the_vocabulary_reports_its_own_gaps():
    v = vocab()
    assert 3 in v.gaps and 1 not in v.gaps


@pytest.mark.parametrize("bad", [None, 7, "x", [], {}, {"Types": {}}])
def test_a_useless_vocabulary_block_raises(bad):
    with pytest.raises(ValueError):
        RewardTypeVocabulary.from_block(bad)


# -- seasonal reward cars ------------------------------------------------
def bundle(season=279):
    return {str(season): {"CrewLeaderboardRewardDefinitions": {"SeasonalRewardCars": {
        str(season): {
            "PrestigeCupCar": "Chevrolet_LBCamaroIROCZRewardRecycled_1987",
            "primaryPrizeCarDBid": "Hennessey_VenomF5RevRReward_2025",
            "secondaryPrizeCarDBid": "Hennessey_VenomF5RevRRewardRecycled_2025",
            "allowPrimaryPrizeCarTestRun": True}}}}}


def historical():
    return {"SeasonalRewardCars": {
        "200": {"PrestigeCupCar": "Acura_NSXTypeSRewardRecycled_2022",
                "primaryPrizeCarDBid": "Ferrari_296GTSReward_2023"},
        "201": {"PrestigeCupCar": "Some_Other_Car_2020"}}}


def test_the_bundle_code_is_the_season_numbered_asset():
    assert season_bundle_code(279) == "assets_client_metadata_279"


@pytest.mark.parametrize("bad", [-1, True, "279", None])
def test_the_bundle_code_refuses_nonsense(bad):
    with pytest.raises(ValueError):
        season_bundle_code(bad)


def test_the_live_season_resolves_from_its_own_bundle():
    car = from_season_bundle(bundle(), 279)
    assert car.prestige_cup_car == "Chevrolet_LBCamaroIROCZRewardRecycled_1987"
    assert car.primary_prize_car == "Hennessey_VenomF5RevRReward_2025"
    assert car.secondary_prize_car == "Hennessey_VenomF5RevRRewardRecycled_2025"
    assert car.allow_primary_prize_car_test_run is True
    assert car.source == "season_bundle" and car.resolved


def test_the_season_id_nests_both_outside_and_inside():
    """The bundle repeats its own id; an unwrapped document works too."""
    inner = bundle()["279"]
    assert from_season_bundle(inner, 279).resolved


def test_a_historical_season_falls_back_to_the_block():
    index = SeasonalRewardCarIndex.from_block(historical())
    car = resolve_seasonal_reward_car(200, bundle_document=bundle(), index=index)
    assert car.prestige_cup_car == "Acura_NSXTypeSRewardRecycled_2022"
    assert car.source == "crew_leaderboard_block"


def test_the_bundle_wins_when_both_hold_the_season():
    index = SeasonalRewardCarIndex.from_block(historical())
    car = resolve_seasonal_reward_car(279, bundle_document=bundle(), index=index)
    assert car.source == "season_bundle"


def test_an_unknown_season_resolves_to_nothing_rather_than_raising():
    index = SeasonalRewardCarIndex.from_block(historical())
    car = resolve_seasonal_reward_car(9999, index=index)
    assert car.resolved is False and car.source is None


def test_the_index_reports_its_gaps():
    """The live block is missing season 217 inside 5..227."""
    index = SeasonalRewardCarIndex.from_block({"SeasonalRewardCars": {
        "5": {"PrestigeCupCar": "A"}, "6": {"PrestigeCupCar": "B"},
        "8": {"PrestigeCupCar": "C"}}})
    assert index.seasons == (5, 6, 8)
    assert index.gaps == (7,)


# -- milestone ladders ---------------------------------------------------
def milestones():
    def rung(wins, qty, rt, **extra):
        return {"WinsRequired": wins, "Quantity": qty,
                "RewardInfo": dict({"rewardType": rt}, **extra)}
    w1_low = [rung(3, 20, 47), rung(8, 40, 47), rung(14, 50, 47),
              rung(22, 3, 13, partGrade=1, matchLockedInCar=True),
              rung(32, 3, 13, partGrade=2, matchLockedInCar=True), rung(44, 60, 47)]
    w1_high = [rung(3, 60, 47), rung(8, 100, 47), rung(14, 100, 47),
               rung(22, 3, 13, partGrade=1, matchLockedInCar=True),
               rung(32, 3, 13, partGrade=2, matchLockedInCar=True), rung(44, 120, 47)]
    return {
        TUNER_CUP: {"RewardLevels": [{"rewards": [
            rung(1, 20000, 1), rung(5, 20, 24, partGrade=2),
            rung(100, 75000, 1), rung(900, 10, 24, partGrade=4)]}]},
        "COLLECTIONS_CUP_V2_W1": {"RewardLevels": [{"rewards": w1_low},
                                                   {"rewards": w1_high}]},
        "crewcups_keys": {"RewardLevels": [{"rewards": [rung(15, 15, 19)]}] * 6},
        "not_a_ladder": {"somethingElse": 1},
    }


def test_the_tuner_cup_ladder_tops_at_900():
    cat = EventMilestoneCatalogue.from_block(milestones(), vocab())
    tc = cat.tuner_cup
    assert tc.level_count == 1
    assert tc.top == 900
    assert tc.requirements == (1, 5, 100, 900)


def test_levels_are_parallel_not_merged():
    """Merging the two W1 levels would invent twelve rungs where six exist."""
    cat = EventMilestoneCatalogue.from_block(milestones(), vocab())
    w1 = cat.get("COLLECTIONS_CUP_V2_W1")
    assert w1.level_count == 2
    assert len(w1.level(0).rungs) == 6
    assert w1.requirements == (3, 8, 14, 22, 32, 44)
    assert w1.levels_share_requirements is True
    assert w1.levels_are_identical is False
    assert w1.level(0).rungs[0].quantity == 20
    assert w1.level(1).rungs[0].quantity == 60


def test_identical_levels_are_recognised():
    cat = EventMilestoneCatalogue.from_block(milestones(), vocab())
    crew = cat.get("crewcups_keys")
    assert crew.level_count == 6
    assert crew.levels_are_identical is True


def test_a_container_without_reward_levels_is_skipped():
    cat = EventMilestoneCatalogue.from_block(milestones(), vocab())
    assert cat.get("not_a_ladder") is None
    assert "not_a_ladder" not in cat.containers


def test_rewards_are_labelled_through_the_vocabulary():
    cat = EventMilestoneCatalogue.from_block(milestones(), vocab())
    rungs = cat.get("COLLECTIONS_CUP_V2_W1").level(0).rungs
    assert rungs[0].reward_name == "CarCredits"
    assert "matches locked-in car" in rungs[3].label


def test_a_ladder_without_a_vocabulary_still_decodes():
    cat = EventMilestoneCatalogue.from_block(milestones())
    assert cat.tuner_cup.top == 900
    assert cat.tuner_cup.level(0).rungs[0].reward_name is None


# -- progress against a supplied count ----------------------------------
def test_progress_reports_earned_and_next():
    cat = EventMilestoneCatalogue.from_block(milestones(), vocab())
    out = cat.get("COLLECTIONS_CUP_V2_W1").progress(20)
    assert out["earned"] == 3 and out["of"] == 6
    assert out["next_rung"] == 22 and out["remaining"] == 2
    assert out["complete"] is False
    assert out["level"] == 0 and out["of_levels"] == 2


def test_progress_on_the_premium_level_differs_only_in_payout():
    cat = EventMilestoneCatalogue.from_block(milestones(), vocab())
    w1 = cat.get("COLLECTIONS_CUP_V2_W1")
    assert w1.progress(20)["next_rung"] == w1.progress(20, level=1)["next_rung"]


def test_a_complete_ladder_says_so():
    cat = EventMilestoneCatalogue.from_block(milestones(), vocab())
    out = cat.get("COLLECTIONS_CUP_V2_W1").progress(44)
    assert out["complete"] is True and out["next_rung"] is None
    assert out["remaining"] is None


@pytest.mark.parametrize("bad", [None, -1, True, "20", 20.5, []])
def test_progress_refuses_to_guess_from_a_bad_count(bad):
    cat = EventMilestoneCatalogue.from_block(milestones(), vocab())
    out = cat.get("COLLECTIONS_CUP_V2_W1").progress(bad)
    assert out["earned"] is None and out["complete"] is None


def test_progress_on_a_missing_level_is_unknown():
    cat = EventMilestoneCatalogue.from_block(milestones(), vocab())
    assert cat.tuner_cup.progress(10, level=5)["earned"] is None


# -- the threshold ladder ------------------------------------------------
def test_the_threshold_ladder_is_keyed_on_a_total_not_wins():
    block = {"TournamentMilestoneRewards": {"brackets": [
        {"threshold": 50, "rewards": [{"reward": {"rewardType": 47}, "rewardAmount": 50}]},
        {"threshold": 300000, "rewards": [{"reward": {"rewardType": 18},
                                           "rewardAmount": 100000}]}]}}
    ladder = threshold_ladder(block, vocabulary=vocab())
    assert ladder.keyed_on == "threshold"
    assert ladder.requirements == (50, 300000)
    assert ladder.rungs[0].wins_required is None
    assert ladder.rungs[1].reward_name == "CrewRP"


@pytest.mark.parametrize("bad,err", [
    (None, ValueError), ({}, ValueError),
    ({"TournamentMilestoneRewards": {}}, ValueError),
])
def test_a_malformed_threshold_block_raises(bad, err):
    with pytest.raises(err):
        threshold_ladder(bad)


# -- collections cups ----------------------------------------------------
W1_START, W1_END = 1794556800, 1794816000     # Nov 8 .. Nov 11 2026, 10:00 UTC


def cup_blocks(season=279):
    schedule = {"ScheduleList": [
        {"id": "COLLECTIONS_CUP_V2_%d_W1" % season,
         "ScheduleID": "COLLECTIONS_CUP_V2_%d_W1" % season,
         "BasedOn_ScheduleID": "COLLECTIONS", "DurationForeshadow": 259200,
         "Time_ActiveBetweenAny": [[W1_START, W1_END]]},
        {"id": "COLLECTIONS_CUP_V2_%d_W2" % season,
         "ScheduleID": "COLLECTIONS_CUP_V2_%d_W2" % season,
         "BasedOn_ScheduleID": "COLLECTIONS", "DurationForeshadow": 259200,
         "Time_ActiveBetweenAny": [[W1_START + 604800, W1_END + 604800]]},
        {"id": "SOMETHING_ELSE", "ScheduleID": "SOMETHING_ELSE"}]}
    def race(event_id, **over):
        row = {"EventID": event_id, "RewardGroupID": "COLLECTIONS_CUP_V2_W1",
               "ECBRaceType": "NormalRace", "IsHalfMile": False,
               "RaceReward": {"CashPrize": 10000},
               "EventDescription": "TEXT_EVENT_DESCRIPTION_DRAG_2",
               "LockinRequirements": ["{Slot 1}"]}
        row.update(over)
        return row
    ladder = {"LadderEvents": {"RaceEventGroups": [
        {"EventGroupName": "COLLECTIONS_CUP_V2_%d_W1" % season,
         "ScheduleID": "COLLECTIONS_CUP_V2_%d_W1" % season,
         "SpecialLadderType": "CollectionsCup", "Leaderboard": None,
         "LockinNamespace": "COLLECTIONS_CUP_V2_%d_W1" % season,
         "EventPanelOverride": "CollectionsCupV2_EventPanel_Silver",
         "RaceEvents": [race(301176136 + i) for i in range(44)]},
        {"EventGroupName": "COLLECTIONS_CUP_V2_%d_W2" % season,
         "SpecialLadderType": "CollectionsCup", "Leaderboard": None,
         "LockinNamespace": "COLLECTIONS_CUP_V2_%d_W2" % season,
         "EventPanelOverride": "CollectionsCupV2_EventPanel_Gold",
         "RaceEvents": [race(301176180 + i,
                             Restrictions=[{"RestrictionType": "PPRange",
                                            "MinPP": 300, "MaxPP": 920}])
                        for i in range(68)]},
        {"EventGroupName": "COLLECTIONS_BOSS_CAR_Something", "Leaderboard": None}]}}
    return schedule, ladder


def calendar(season=279):
    return CollectionsCupCalendar.from_blocks(*cup_blocks(season))


def test_the_cup_id_pattern():
    assert CUP_ID.match("COLLECTIONS_CUP_V2_279_W1")
    assert not CUP_ID.match("COLLECTIONS_CUP_V2_279_W3")
    assert not CUP_ID.match("COLLECTIONS_BOSS_CAR_Something")


def test_the_two_weekly_cups_join_across_both_blocks():
    cal = calendar()
    assert len(cal) == 2
    w1, w2 = cal.for_season(279)
    assert (w1.week, w2.week) == (1, 2)
    assert w1.tier == "Silver" and w2.tier == "Gold"
    assert w1.lockin_namespace == "COLLECTIONS_CUP_V2_279_W1"


def test_the_race_counts_match_where_the_ladders_top_out():
    """44 and 68 come from two blocks independently; that is the check."""
    w1, w2 = calendar().for_season(279)
    assert w1.race_count == 44
    assert w2.race_count == 68
    assert w1.reward_container == "COLLECTIONS_CUP_V2_W1"
    assert w2.reward_container == "COLLECTIONS_CUP_V2_W2"


def test_a_cup_knows_its_window():
    w1 = calendar().get(279, 1)
    assert w1.starts_at == datetime.fromtimestamp(W1_START, timezone.utc)
    assert (w1.ends_at - w1.starts_at) == timedelta(days=3)
    assert w1.foreshadow_seconds == 259200


def test_active_and_next_depend_on_the_clock():
    cal = calendar()
    before = datetime.fromtimestamp(W1_START - 3600, timezone.utc)
    during = datetime.fromtimestamp(W1_START + 3600, timezone.utc)
    assert cal.active(now=before) is None
    assert cal.next_after(now=before).week == 1
    assert cal.active(now=during).week == 1
    assert cal.get(279, 1).is_active(now=during) is True
    assert cal.get(279, 1).is_active(now=before) is False


def test_no_cup_publishes_a_leaderboard():
    """Leaderboard is null on every observed group, so there is no board to read."""
    for cup in calendar().for_season(279):
        assert cup.has_leaderboard is False


def test_a_race_carries_its_lockin_slot_and_restrictions():
    w1, w2 = calendar().for_season(279)
    race = w1.races[0]
    assert race.lockin_requirements == ("{Slot 1}",)
    assert race.cash_prize == 10000
    assert race.restrictions == ()
    rule = w2.races[0].restrictions[0]
    assert rule.kind == "PPRange" and rule.known_kind
    assert rule.details["MinPP"] == 300


def test_an_unknown_restriction_kind_is_kept_but_flagged():
    rule = Restriction.from_wire({"RestrictionType": "SomethingNew", "X": 1})
    assert rule.kind == "SomethingNew"
    assert rule.known_kind is False
    assert rule.details == {"X": 1}
    assert "PPRange" in RESTRICTION_KINDS


@pytest.mark.parametrize("bad", [None, 7, "x", [], {}])
def test_junk_rows_degrade_quietly(bad):
    assert CupRace.from_wire(bad).event_id is None
    assert Restriction.from_wire(bad).kind is None


def test_a_schedule_without_a_group_still_yields_a_cup():
    """The blocks are joined, so one side alone must not drop the cup."""
    schedule, _ = cup_blocks()
    cal = CollectionsCupCalendar.from_blocks(schedule, {})
    assert len(cal) == 2
    assert cal.get(279, 1).race_count == 0
    assert cal.get(279, 1).starts_at is not None


def test_a_group_without_a_schedule_still_yields_a_cup():
    _, ladder = cup_blocks()
    cal = CollectionsCupCalendar.from_blocks({}, ladder)
    assert len(cal) == 2
    assert cal.get(279, 1).race_count == 44
    assert cal.get(279, 1).starts_at is None
    assert cal.get(279, 1).is_active(now=AT) is None


def test_a_naive_now_is_refused():
    with pytest.raises(ValueError):
        calendar().get(279, 1).is_active(now=datetime(2026, 11, 8, 12))


# -- the server's clock, not ours ---------------------------------------
def test_server_time_comes_out_of_the_gcc_envelope():
    """end_time - time_left is the service's own now; measured 3.9s off local."""
    from csr2cdn.crew_season_schedule import server_now_from_gcc
    envelope = {"end_time": LIVE_GCC_END, "time_left": 1088289}
    server = server_now_from_gcc(envelope)
    assert server == datetime.fromtimestamp(LIVE_GCC_END - 1088289, timezone.utc)
    assert server.tzinfo is not None


@pytest.mark.parametrize("envelope", [
    None, {}, {"end_time": LIVE_GCC_END}, {"time_left": 100},
    {"end_time": 0, "time_left": 1}, {"end_time": LIVE_GCC_END, "time_left": -1},
    {"end_time": LIVE_GCC_END, "time_left": True},
    {"end_time": "x", "time_left": 1}, {"end_time": 99999999999, "time_left": 1},
])
def test_no_server_clock_is_none_not_a_guess(envelope):
    from csr2cdn.crew_season_schedule import server_now_from_gcc
    assert server_now_from_gcc(envelope) is None


def test_the_season_prefers_the_server_clock_and_says_so():
    s = GrandCrewChampionshipSchedule.from_block(config())
    envelope = {"end_time": LIVE_GCC_END, "time_left": 1088289}
    season, used_server = s.active_season_from_gcc(envelope)
    assert (season, used_server) == (279, True)


def test_without_an_envelope_it_falls_back_and_says_so():
    s = GrandCrewChampionshipSchedule.from_block(config())
    season, used_server = s.active_season_from_gcc(None, now=AT)
    assert (season, used_server) == (279, False)


def test_a_wrong_local_clock_near_a_rollover_is_exactly_the_risk():
    """The case this exists for: a skewed local clock picks the wrong season."""
    s = GrandCrewChampionshipSchedule.from_block(config())
    boundary = s.window(279)[1]                      # 2026-11-19 10:00 UTC
    local_is_early = boundary - timedelta(minutes=5)
    assert s.season_at(local_is_early) == 279
    # The server says the window has already closed.
    envelope = {"end_time": LIVE_GCC_END, "time_left": 0}
    assert s.active_season_from_gcc(envelope, now=local_is_early) == (280, True)


def test_clock_skew_is_reported():
    s = GrandCrewChampionshipSchedule.from_block(config())
    envelope = {"end_time": LIVE_GCC_END, "time_left": 1088289}
    server = datetime.fromtimestamp(LIVE_GCC_END - 1088289, timezone.utc)
    assert s.clock_skew_seconds(envelope, now=server) == 0
    assert s.clock_skew_seconds(envelope, now=server + timedelta(seconds=4)) == -4
    assert s.clock_skew_seconds(None, now=server) is None


def test_near_rollover_flags_the_edges_only():
    s = GrandCrewChampionshipSchedule.from_block(config())
    start, end = s.window(279)
    assert s.near_rollover(now=start + timedelta(seconds=60)) is True
    assert s.near_rollover(now=end - timedelta(seconds=60)) is True
    assert s.near_rollover(now=start + timedelta(days=5)) is False
