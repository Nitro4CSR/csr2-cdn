"""No-network Prestige Cup discovery regressions for the separate cup-series path."""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from csr2cdn import CSR2Services
from csr2cdn.service_discovery import ShowdownDiscovery, merge_modular_event_metadata
from csr2cdn.service_modular_assets import extract_modular_event_metadata
from csr2cdn.service_events import EventResolutionError
from csr2cdn.service_prestige import PrestigeCupDiscovery, scan_prestige_cups

START = datetime(2026, 10, 15, 10, tzinfo=timezone.utc)
NOW = START + timedelta(hours=1)
END = START + timedelta(days=7)


def blocks():
    return {
        "ShowdownEventsContainer": {"RaceEventGroups": [{
            "EventGroupName": "SMP_SHOWDOWN_277_W2", "TelemGroupName": "SHOWDOWN",
            "RaceEvents": [{"EventID": 7654}],
            "Leaderboard": {"LeaderboardTemplateID": "PRESTIGE_TIMES"},
            "ScheduleID": "PC2026",
        }]},
        "EventSchedule": {"ScheduleList": [{"ScheduleID": "PC2026",
             "Time_ActiveBetweenAny": [{"Start": START.isoformat(), "End": END.isoformat()}]}]},
        "EventLeaderboards": {"EventLeaderboardsDefinitions": [{"nameID": "PRESTIGE_TIMES", "rankingOrder": 0}]},
    }


def prestige():
    # The client classifies by TelemGroupName; display names are arbitrary.
    return {"EventGroupName": "SEASON_277_MAIN_5", "TelemGroupName": "Silver_Prestige",
            "ScheduleID": "PC2026", "RaceEvents": [{"EventID": 98765}],
            "Leaderboard": {"LeaderboardTemplateID": "PRESTIGE_TIMES"}}


def test_cup_series_metadata_outside_showdown_candidates_resolves_native_board():
    source = lambda: {"RaceSeries": [{"RaceEventGroups": [prestige()]}]}
    discovery = PrestigeCupDiscovery(ShowdownDiscovery(blocks), cup_source=source)
    candidate = discovery.resolve_current(at=NOW)
    assert candidate.event_name == "SEASON_277_MAIN_5"
    assert candidate.offset == 0
    assert candidate.leaderboard_name.endswith("-asc---98765")
    summary = discovery.source_summary()
    assert summary["cup_series_loaded"] is True
    assert summary["cup_nested_groups"] == 1
    assert summary["prestige_candidates"] == 1
    with CSR2Services("SYNTHETIC_TEST_PLAYER") as services:
        contract = services.prepare_current_prestige_cup(discovery, at=NOW)
        assert contract.request_type == 5
        assert contract.route.endswith("-asc---98765/view")
        assert dict(contract.params) == {"app_ver": "6.8.0", "top": 10, "after": 5,
                                         "before": 5, "offset": 0, "show_default": True}


def test_not_every_cup_series_is_prestige_and_missing_leaderboard_stays_unresolved():
    ordinary = prestige() | {"TelemGroupName": "CUP", "EventGroupName": "ORDINARY_CUP"}
    discovery = PrestigeCupDiscovery(ShowdownDiscovery(blocks), cup_source=lambda: {
        "RaceSeries": [{"RaceEventGroups": [ordinary]}]})
    assert discovery.list_cups(at=NOW) == ()
    with pytest.raises(EventResolutionError):
        discovery.resolve_current(at=NOW)
    incomplete = prestige() | {"Leaderboard": None}
    discovery = PrestigeCupDiscovery(ShowdownDiscovery(blocks), cup_source=lambda: {
        "RaceSeries": [{"RaceEventGroups": [incomplete]}]})
    entries = discovery.list_cups(at=NOW)
    assert len(entries) == 1
    assert not entries[0].requestable
    with pytest.raises(EventResolutionError, match="incomplete"):
        discovery.resolve_current(at=NOW)


def test_modular_race_series_is_preserved_without_pretending_showdown_groups():
    runtime = {"RaceSeries": [{"RaceEventGroups": [prestige()]}],
               "RaceEventGroups": [], "ScheduleList": [], "EventLeaderboardsDefinitions": []}
    fake = SimpleNamespace(type=SimpleNamespace(name="MonoBehaviour"), read_typetree=lambda: runtime)
    decoded = extract_modular_event_metadata(b"UnityFS fixture", loader=lambda _: SimpleNamespace(objects=[fake]))
    assert decoded["RaceSeries"]
    merged = merge_modular_event_metadata(blocks(), decoded)
    assert merged["_RuntimeCupSeries"]["RaceSeries"]
    assert len(scan_prestige_cups(merged, at=NOW)) == 1
    assert len(ShowdownDiscovery(lambda: merged).list_showdowns(at=NOW)) == 1


def test_cup_metadata_fetch_is_separate_from_showdown_and_failures_are_not_absence():
    seen = []
    class Metadata:
        def get(self, names, *, zid, product_version):
            seen.append(tuple(names))
            assert zid == "SYNTHETIC_TEST_PLAYER"
            assert product_version == "6.8.0"
            available = {**blocks(), "CupInvitationalRaceSeries": {"RaceSeries": [
                {"RaceEventGroups": [prestige()]}]}}
            return {name: SimpleNamespace(content=available[name]) for name in names}
    discovery = PrestigeCupDiscovery.from_metadata(
        Metadata(), player_id="SYNTHETIC_TEST_PLAYER", product_version="6.8.0")
    assert discovery.resolve_current(at=NOW).event_name == "SEASON_277_MAIN_5"
    assert ("CupInvitationalRaceSeries",) in seen
    assert tuple(sorted(("ShowdownEventsContainer", "EventSchedule", "EventLeaderboards"))) == tuple(sorted(seen[0]))


def test_bad_cup_source_does_not_replace_good_snapshot():
    calls = [True]
    def source():
        if calls[0]:
            return {"RaceSeries": [{"RaceEventGroups": [prestige()]}]}
        raise EventResolutionError("cup source unavailable")
    d = PrestigeCupDiscovery(ShowdownDiscovery(blocks), cup_source=source)
    assert d.resolve_current(at=NOW).leaderboard_name
    calls[0] = False
    with pytest.raises(EventResolutionError):
        d.list_cups(at=NOW, refresh=True)
    assert d.source_summary()["prestige_candidates"] == 1


def test_prestige_probe_cli_defaults_offline(capsys):
    from csr2cdn.live_validation import main
    assert main(["--prestige-current"]) == 0
    assert '"network_requests": 0' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--prestige-current", "--skip-metadata"])


def test_playerid_only_api_uses_discovered_board_without_any_live_io(monkeypatch):
    from csr2cdn.service_prestige import PrestigeCupSelection
    player = "SYNTHETIC_TEST_PLAYER"
    chosen = PrestigeCupSelection("SEASON_277_MAIN_5", "evnt-off-82-dur-168-hours-asc---98765",
                                  START, END, 0)
    with CSR2Services(player, allow_network=True) as api:
        observed = []
        monkeypatch.setattr(api, "_resolve_current_prestige", lambda **kwargs: chosen)
        def read(contract):
            observed.append(contract)
            return {"scores": [{"rank": 1, "score": 12345}]}
        monkeypatch.setattr(api, "_read", read)
        board = api.get_prestige_cup_leaderboard()
        assert len(board.entries) == 1
        assert board.entries[0].rank == 1
        assert observed[0].route == "leaderboard/" + chosen.leaderboard_name + "/view"
        assert observed[0].params["show_default"] is True
        assert observed[0].params["offset"] == 0


def test_playerid_only_discovery_refuses_network_without_opt_in():
    from csr2cdn.services import ServiceNetworkDisabled
    with CSR2Services("SYNTHETIC_TEST_PLAYER") as api:
        with pytest.raises(ServiceNetworkDisabled):
            api.get_prestige_cup_leaderboard()


def test_prestige_series_only_reference_is_not_a_guessed_leaderboard():
    """Native SeriesEvent.EventFile can reference more data; no fabricated board."""
    d = PrestigeCupDiscovery(ShowdownDiscovery(blocks), cup_source=lambda: {
        "RaceSeries": [{"SeriesName": "PRESTIGE", "EventFile": "SOME_DYNAMIC_EVENT"}]})
    assert d.list_cups(at=NOW) == ()
    diagnostic = d.source_summary()
    assert diagnostic["cup_series_entries"] == 1
    assert diagnostic["prestige_candidates"] == 0
    with pytest.raises(EventResolutionError):
        d.resolve_current(at=NOW)


def test_combined_live_harness_routes_prestige_via_distinct_cup_source(monkeypatch):
    """Fully injected fake network: source selection and request dispatch only."""
    from csr2cdn import live_validation as probe
    from csr2cdn import service_modular_assets
    class Metadata:
        def get(self, names, *, zid, product_version):
            available = {**blocks(), "CupInvitationalRaceSeries": {"RaceSeries": [
                {"RaceEventGroups": [prestige()]}]}}
            return {name: SimpleNamespace(content=available[name]) for name in names}
        def close(self):
            pass
    class AssetCDN:
        def __init__(self, **kwargs): pass
        def close(self): pass
    class Services:
        def __init__(self, player_id, **kwargs):
            assert kwargs["allow_network"]
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get_prestige_cup_leaderboard(self, *, leaderboard_name):
            assert leaderboard_name.endswith("-asc---98765")
            return SimpleNamespace(entries=(object(), object()))
    monkeypatch.setattr(service_modular_assets, "load_modular_event_metadata", lambda _: {
        "RaceEventGroups": [], "RaceSeries": [], "ScheduleList": [],
        "EventLeaderboardsDefinitions": []})
    report = probe.run_live(
        "SYNTHETIC_TEST_PLAYER", metadata_product_version="6.8.0",
        metadata_factory=Metadata, asset_cdn_factory=AssetCDN, services_factory=Services,
        prestige_current=True, auto_crew=False,
        # Pinned to the fixture's own window. Without this the run reads the
        # real clock and the test expires when that window elapses.
        at=NOW)
    assert report["checks"]["prestige_discovery"]["status"] == "ok"
    assert report["checks"]["prestige_discovery"]["cup_series_entries"] == 1
    assert report["checks"]["prestige_cup"] == {"status": "ok", "records": 2}
    assert report["checks"]["showdown"]["status"] == "not_selected"


def test_numeric_eventfile_does_not_classify_a_group_as_prestige():
    # The 6.8.0 native fields are int32; no string-to-asset path exists here.
    item = prestige() | {"EventGroupName": "AUTO_GENERATED_CUP_GROUP",
                         "TelemGroupName": None, "EventFile": 214}
    data = blocks()
    data["ShowdownEventsContainer"]["RaceEventGroups"].append(item)
    cup_series = {"RaceSeries": [{"SeriesName": "CREW_CUP", "EventFile": 214}]}
    d = PrestigeCupDiscovery(ShowdownDiscovery(lambda: data), cup_source=lambda: cup_series)
    assert d.list_cups(at=NOW) == ()
    assert d.source_summary()["numeric_eventfile_records"] == 1
    with pytest.raises(EventResolutionError):
        d.resolve_current(at=NOW)
