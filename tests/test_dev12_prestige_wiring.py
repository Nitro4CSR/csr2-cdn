"""Integration regressions for the actual opt-in Prestige runner (no network)."""
from types import SimpleNamespace
import json

import csr2cdn.live_validation as runner
from csr2cdn.service_discovery import ShowdownDiscovery


def _base():
    return {"ShowdownEventsContainer": {"RaceEventGroups": []},
            "EventSchedule": {"ScheduleList": []},
            "EventLeaderboards": {"EventLeaderboardsDefinitions": []}}


def test_live_prestige_cli_configures_and_fetches_both_native_sources(monkeypatch):
    names_seen = []
    class Client:
        def get(self, names, *, zid, product_version):
            assert zid == "PRIVATE_TEST_PLAYER" and product_version == "6.8.0"
            names_seen.extend(names)
            payload = {
                "CupInvitationalRaceSeries": {"RaceSeries": []},
                "CareerRaceEvents": {"SMPRaceEvents": {"RaceEventGroups": []}},
                "InvitationalRaceSeries": {"RaceSeries": []},
                "SpecialLadderEvents": {"LadderEvents": {"RaceEventGroups": []}},
            }
            return {n: SimpleNamespace(content=payload[n]) for n in names}
        def close(self): pass

    monkeypatch.setattr(runner.ShowdownDiscovery, "from_metadata", lambda *a, **k:
                        ShowdownDiscovery(lambda: _base()))
    report = runner.run_live(
        "PRIVATE_TEST_PLAYER", metadata_product_version="6.8.0",
        metadata_factory=Client, prestige_current=True, auto_crew=False,
    )
    summary = report["checks"]["prestige_discovery"]
    assert sorted(names_seen) == ["CareerRaceEvents", "CupInvitationalRaceSeries", "InvitationalRaceSeries", "SpecialLadderEvents"]
    assert summary["additional_sources_configured"] == 3
    assert summary["additional_sources_attempted"] == 3
    assert summary["additional_sources_loaded"] == 3
    assert summary["additional_sources_unavailable"] == 0
    assert summary["status"] == "unresolved_input"
    assert report["checks"]["prestige_cup"]["status"] == "unresolved_board"
    assert "PRIVATE_TEST_PLAYER" not in json.dumps(report)


def test_failed_additional_fetch_is_accurately_counted(monkeypatch):
    calls = []
    class Client:
        def get(self, names, *, zid, product_version):
            calls.extend(names)
            n = names[0]
            if n == "InvitationalRaceSeries":
                raise RuntimeError("private server context must not escape")
            return {n: SimpleNamespace(content={"RaceSeries": []})}
        def close(self): pass
    monkeypatch.setattr(runner.ShowdownDiscovery, "from_metadata", lambda *a, **k:
                        ShowdownDiscovery(lambda: _base()))
    report = runner.run_live(
        "PRIVATE_TEST_PLAYER", metadata_product_version="6.8.0",
        metadata_factory=Client, prestige_current=True, auto_crew=False,
    )
    summary = report["checks"]["prestige_discovery"]
    assert summary["additional_sources_configured"] == 3
    assert summary["additional_sources_attempted"] == 3
    assert summary["additional_sources_loaded"] == 2
    assert summary["additional_sources_unavailable"] == 1
    assert "private server context" not in json.dumps(report)


def test_native_prestige_telemetry_literal_is_exact():
    from csr2cdn.service_prestige import _is_prestige
    native = {"EventGroupName": "UNRELATED_EVENT_NAME", "TelemGroupName": "Silver_Prestige"}
    assert _is_prestige(native)
    for other in ("PRESTIGE", "PRESTIGE_CUP", "Silver_Prestige_Fake", "SHOWDOWN"):
        assert not _is_prestige({**native, "TelemGroupName": other})
    # A misleading display name must not override explicit non-Prestige telemetry.
    assert not _is_prestige({"EventGroupName": "PRESTIGE_CUP_2026", "TelemGroupName": "SHOWDOWN"})


def test_native_telemetry_career_event_flows_through_real_runner(monkeypatch):
    """Complete metadata-to-service path, including both configured extra sources."""
    from datetime import datetime, timedelta, timezone
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    end = start + timedelta(days=7)
    blocks = {
        "ShowdownEventsContainer": {"RaceEventGroups": []},
        "EventSchedule": {"ScheduleList": [{"ScheduleID": "pc",
            "Time_ActiveBetweenAny": [{"Start": start.isoformat(), "End": end.isoformat()}]}]},
        "EventLeaderboards": {"EventLeaderboardsDefinitions": [
            {"nameID": "board", "rankingOrder": 0}]},
    }
    group = {"EventGroupName": "EVENT_WITH_NON_PRESTIGE_DISPLAY_NAME",
             "TelemGroupName": "Silver_Prestige", "ScheduleID": "pc",
             "RaceEvents": [{"EventID": 99231}],
             "Leaderboard": {"LeaderboardTemplateID": "board"}}
    fetched = []
    class Client:
        def get(self, names, *, zid, product_version):
            fetched.extend(names)
            data = {
                "CupInvitationalRaceSeries": {"RaceSeries": []},
                "CareerRaceEvents": {"SMPRaceEvents": {"RaceEventGroups": [group]}},
                "InvitationalRaceSeries": {"RaceSeries": []},
                "SpecialLadderEvents": {"LadderEvents": {"RaceEventGroups": []}},
            }
            return {n: SimpleNamespace(content=data[n]) for n in names}
        def close(self): pass
    class Services:
        def __init__(self, player_id, **kwargs):
            assert kwargs["allow_network"] is True
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get_prestige_cup_leaderboard(self, *, leaderboard_name):
            assert leaderboard_name.endswith("-asc---99231")
            return SimpleNamespace(entries=(object(), object(), object()))
    monkeypatch.setattr(runner.ShowdownDiscovery, "from_metadata", lambda *a, **k:
                        ShowdownDiscovery(lambda: blocks))
    result = runner.run_live(
        "PRIVATE_TEST_PLAYER", metadata_product_version="6.8.0",
        metadata_factory=Client, prestige_current=True, auto_crew=False,
        services_factory=Services,
    )
    assert result["checks"]["prestige_discovery"]["native_telemetry_prestige_groups"] == 1
    assert result["checks"]["prestige_discovery"]["additional_sources_loaded"] == 3
    assert result["checks"]["prestige_discovery"]["status"] == "ok"
    assert result["checks"]["prestige_cup"] == {"status": "ok", "records": 3}
    assert sorted(fetched) == ["CareerRaceEvents", "CupInvitationalRaceSeries", "InvitationalRaceSeries", "SpecialLadderEvents"]
    assert "PRIVATE_TEST_PLAYER" not in json.dumps(result)


def test_cli_prestige_option_reaches_runner(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(runner.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(runner.getpass, "getpass", lambda *_: "PRIVATE_TEST_PLAYER")
    def fake_run(player_id, **options):
        assert player_id == "PRIVATE_TEST_PLAYER"
        seen.update(options)
        return {"checks": {"prestige_cup": {"status": "ok", "records": 1}}}
    monkeypatch.setattr(runner, "run_live", fake_run)
    assert runner.main(["--execute", "--skip-crew", "--prestige-current"]) == 0
    assert seen["prestige_current"] is True
    assert seen["auto_crew"] is False
    assert "PRIVATE_TEST_PLAYER" not in capsys.readouterr().out
