"""Offline regression tests for 6.8.0 native Showdown board-ID reconstruction."""
from datetime import datetime, timedelta, timezone

import pytest

from csr2cdn import ShowdownDiscovery, scan_showdowns
from csr2cdn.service_showdown_resolution import (CLIENT_EPOCH, native_board_name,
    first_race_event_id, ranking_direction, schedule_windows)
from csr2cdn.service_events import EventResolutionError

AT = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
START = datetime(2026, 10, 15, 9, tzinfo=timezone.utc)
END = START + timedelta(days=7)


def payload(*, window=True):
    groups = [{
        "EventGroupName": "SMP_SHOWDOWN_269_W2",
        "ScheduleID": "SHOWDOWN_269",
        "RaceEvents": [{"EventID": 834201, "EventName": "showdown-race-1"}, {"EventID": 834202}],
        "Leaderboard": {"LeaderboardTemplateID": "TROPHIES"},
    }]
    schedules = [{"ScheduleID": "SHOWDOWN_269", "BasedOn_ScheduleID": "BASE_269"},
                 {"ScheduleID": "BASE_269", "Time_ActiveBetweenAny": [
                     {"Start": START.isoformat(), "End": END.isoformat()}
                 ] if window else []}]
    return {"ShowdownEventsContainer": {"RaceEventGroups": groups},
            "EventSchedule": {"ScheduleList": schedules},
            "EventLeaderboards": {"EventLeaderboardsDefinitions": [{
                "nameID": "TROPHIES", "rankingOrder": 1,
            }]}}


def test_native_uid_four_inputs_order_and_epoch():
    name = native_board_name(start=START, duration_seconds=7 * 86400,
                             ranking_order="dsc", first_event_id=834201)
    offset = (int(START.timestamp()) - CLIENT_EPOCH) % (7*86400) // 3600
    assert name == f"evnt-off-{offset}-dur-168-hours-dsc---834201"
    assert ranking_direction(0) == "asc"
    assert ranking_direction(1) == "dsc"
    assert ranking_direction("descending") == "dsc"
    assert ranking_direction(7) is None


def test_metadata_auto_board_id_and_name_selection():
    discovery = ShowdownDiscovery(lambda: payload())
    c = discovery.resolve_named("championship-showdown", at=AT)
    assert c.time_status == "scheduled_now"
    assert c.resolution_source == "native_6_8_0"
    assert c.leaderboard_group_identifier == "834201"
    assert c.leaderboard_name == native_board_name(
        start=START, duration_seconds=604800, ranking_order="dsc", first_event_id=834201)
    assert discovery.resolve_named("CHAMPIONSHIP SHOWDOWN", at=AT) == c
    assert discovery.resolve_current_board(at=AT) == c.leaderboard_name


def test_multiple_names_select_exact_and_no_substring_ambiguity():
    p = payload()
    # Evaluate against the fixed AT fixture; do not mix wall-clock schedule
    # boundaries with the test's fixed observation time.
    p["EventSchedule"]["ScheduleList"][1]["Time_ActiveBetweenAny"] = [{
        "Start": (AT - timedelta(days=1)).isoformat(),
        "End": (AT + timedelta(days=6)).isoformat()}]
    rival = dict(p["ShowdownEventsContainer"]["RaceEventGroups"][0])
    rival["EventGroupName"] = "SMP_SHOWDOWN_269_W1"
    p["ShowdownEventsContainer"]["RaceEventGroups"].append(rival)
    d = ShowdownDiscovery(lambda: p)
    assert d.resolve_named("Elite Showdown", at=AT).display_name == "SMP_SHOWDOWN_269_W1"
    with pytest.raises(EventResolutionError, match="not found"):
        d.resolve_named("Showdown", at=AT)
    with pytest.raises(EventResolutionError, match="ambiguous"):
        d.resolve_current_board(at=AT)


def test_missing_first_race_id_cannot_fabricate_board():
    p = payload()
    p["ShowdownEventsContainer"]["RaceEventGroups"][0]["RaceEvents"] = []
    d = ShowdownDiscovery(lambda: p)
    assert d.list_showdowns(at=AT)[0].leaderboard_name is None
    with pytest.raises(EventResolutionError, match="incomplete"):
        d.resolve_named("Championship Showdown", at=AT)


def test_missing_rank_and_unsupported_duration_do_not_fabricate():
    p = payload()
    p["EventLeaderboards"]["EventLeaderboardsDefinitions"][0]["rankingOrder"] = "unknown"
    assert scan_showdowns(p, at=AT)[0].leaderboard_name is None
    p = payload()
    p["EventSchedule"]["ScheduleList"][1]["Time_ActiveBetweenAny"] = [{
        "Start": START.isoformat(), "End": (START + timedelta(minutes=30)).isoformat()
    }]
    assert scan_showdowns(p, at=START)[0].leaderboard_name is None


def test_inherited_schedule_cycles_and_unsupported_windows_fail_closed():
    p = payload()
    p["EventSchedule"]["ScheduleList"][1] = {"ScheduleID": "BASE_269", "BasedOn_ScheduleID": "SHOWDOWN_269"}
    c = scan_showdowns(p, at=AT)[0]
    assert c.time_status == "unknown" and not c.requestable
    p = payload()
    p["EventSchedule"]["ScheduleList"][1]["Time_ActiveBetweenAny"] = [{"unsupported": True}]
    assert scan_showdowns(p, at=AT)[0].time_status == "unknown"


def test_explicit_server_name_takes_precedence():
    p = payload()
    p["ShowdownEventsContainer"]["RaceEventGroups"][0]["Leaderboard"]["LeaderboardUniqueID"] = "explicit_board"
    c = scan_showdowns(p, at=AT)[0]
    assert c.leaderboard_name == "explicit_board" and c.resolution_source == "explicit"


def test_duplicate_definitions_ambiguous_and_first_race_mapping_order():
    p = payload()
    definitions = p["EventLeaderboards"]["EventLeaderboardsDefinitions"]
    definitions.append({"nameID": "TROPHIES", "rankingOrder": 0})
    assert scan_showdowns(p, at=AT)[0].leaderboard_name is None
    assert first_race_event_id({"RaceEvents": {"race-b": {"EventID": 2}}}) is None


def test_unknown_event_time_and_ranking_rejected():
    with pytest.raises(ValueError):
        native_board_name(start=START.replace(tzinfo=None), duration_seconds=3600,
                          ranking_order="asc", first_event_id=12)
    with pytest.raises(ValueError):
        native_board_name(start=START, duration_seconds=0,
                          ranking_order="asc", first_event_id=12)


def test_offline_public_api_accepts_only_player_id_showdown_name_and_snapshot():
    from csr2cdn import CSR2Services
    with CSR2Services("SYNTHETIC_PLAYER") as service:
        c = service.prepare_showdown(showdown_name="championship showdown",
                                     discovery=ShowdownDiscovery(lambda: payload()), at=AT)
    assert c.route.startswith("leaderboard/evnt-off-")
    assert c.route.endswith("---834201/view")
    with CSR2Services("SYNTHETIC_PLAYER") as service:
        with pytest.raises(Exception, match="automatic Showdown discovery"):
            service.prepare_showdown(showdown_name="Championship Showdown")


def test_dynamic_metadata_is_fetched_with_no_other_user_parameters(monkeypatch):
    from csr2cdn import CSR2Services
    from csr2cdn import cdn as cdnmodule, metadata as metamodule
    calls = []
    class CDNStub:
        def __init__(self, **kw):
            calls.append(("cdn", kw["zid"], kw["release_version"]))
            self.product_version = "6.8.11"
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Block:
        def __init__(self, data): self.content = data
    class MetadataStub:
        def __init__(self, timeout=20): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, names, *, zid, product_version):
            calls.append(("metadata", zid, product_version))
            assert set(names) == {"ShowdownEventsContainer", "EventSchedule", "EventLeaderboards"}
            return {k: Block(v) for k,v in payload().items()}
    monkeypatch.setattr(cdnmodule,"CDN", CDNStub)
    monkeypatch.setattr(metamodule,"MetadataClient", MetadataStub)
    with CSR2Services("SYNTHETIC_PLAYER", allow_network=True) as service:
        contract = service.prepare_showdown(showdown_name="Championship Showdown", at=AT)
    assert contract.route.startswith("leaderboard/evnt-off-")
    assert calls == [("cdn", "SYNTHETIC_PLAYER", "6.8.0"),
                     ("metadata", "SYNTHETIC_PLAYER", "6.8.11")]


def test_cli_named_showdown_with_local_fixture(tmp_path, capsys):
    from csr2cdn.cli import main
    import json
    for k,v in payload().items():
        (tmp_path / f"{k}.meta").write_text(json.dumps({k:v}), encoding="utf-8")
    status = main(["services", "--metadata-dir", str(tmp_path), "--at", AT.isoformat(),
                   "showdown", "--name", "Championship Showdown"])
    assert status == 0
    data = json.loads(capsys.readouterr().out)
    assert data["route"].endswith("---834201/view")


def test_live_runner_can_use_a_name_with_multiples_from_local_test_provider():
    from csr2cdn.live_validation import run_live
    p = payload()
    # Live runner evaluates today's clock instead of the fixed fixture time.
    current = datetime.now(timezone.utc)
    p["EventSchedule"]["ScheduleList"][1]["Time_ActiveBetweenAny"] = [{
        "Start": (current - timedelta(days=1)).isoformat(),
        "End": (current + timedelta(days=6)).isoformat()}]
    rival = dict(p["ShowdownEventsContainer"]["RaceEventGroups"][0])
    rival["EventGroupName"] = "SMP_SHOWDOWN_269_W1"
    p["ShowdownEventsContainer"]["RaceEventGroups"].append(rival)
    class MockMetadata:
        def close(self): pass
        def get(self, names, *, zid, product_version):
            class B:
                def __init__(self, content): self.content=content
            return {k:B(v) for k,v in p.items()}
    class MockServices:
        def __init__(self, player_id, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get_showdown_leaderboard(self, **opts):
            assert opts["leaderboard_name"].startswith("evnt-off-")
            class Page:
                entries = []
            return Page()
        def get_my_crew(self):
            class Crew:
                in_crew=False
            return Crew()
    from unittest.mock import patch
    with patch('csr2cdn.live_validation.ShowdownDiscovery') as factory:
        discovery = ShowdownDiscovery(lambda:p)
        factory.from_metadata.return_value = discovery
        report = run_live("SYNTHETIC_PLAYER",showdown_name="Elite Showdown",
                          metadata_product_version="6.8.11",metadata_factory=MockMetadata,
                          services_factory=MockServices)
    assert report["checks"]["showdown"]["status"] == "ok"
    assert report["checks"]["metadata"]["active_showdown_candidates"] == 2


def test_missing_fields_report_categories_without_exposing_values():
    p = payload()
    group = p["ShowdownEventsContainer"]["RaceEventGroups"][0]
    del group["RaceEvents"]
    del p["EventSchedule"]["ScheduleList"][1]["Time_ActiveBetweenAny"]
    del p["EventLeaderboards"]["EventLeaderboardsDefinitions"][0]["rankingOrder"]
    row = scan_showdowns(p, at=AT)[0]
    assert set(row.unresolved_inputs) == {"first_race_event_id", "ranking_order", "schedule_window", "duration"}
    assert row.leaderboard_name is None
    assert "Championship" not in str(row.unresolved_inputs)


def test_packaged_native_fixture_has_named_showdown_preview(capsys):
    from pathlib import Path
    from csr2cdn.cli import main
    import json
    fixture = Path(__file__).parent / "fixtures" / "showdown_native_synthetic"
    assert main(["services", "--metadata-dir", str(fixture),
                 "--at", AT.isoformat(), "showdown", "--name", "Championship Showdown"]) == 0
    request = json.loads(capsys.readouterr().out)
    assert request["route"].startswith("leaderboard/evnt-off-")
    assert request["request_type"] == 5


def test_sanitized_live_metadata_report_has_only_unresolved_categories(monkeypatch):
    from csr2cdn import live_validation as probe
    from types import SimpleNamespace
    p = payload()
    del p["ShowdownEventsContainer"]["RaceEventGroups"][0]["RaceEvents"]
    class Source:
        def close(self): pass
    monkeypatch.setattr(probe.ShowdownDiscovery, "from_metadata", lambda *a, **kw:
                        ShowdownDiscovery(lambda: p))
    r=probe.run_live("PRIVATE_PLAYER_ID",metadata_product_version="6.8.11",
                     metadata_factory=Source, auto_crew=False, services_factory=lambda *a,**k: None)
    assert r["checks"]["metadata"]["unresolved_input_categories"] == {"first_race_event_id":1}
    import json
    assert "PRIVATE_PLAYER_ID" not in json.dumps(r)


def test_named_live_unresolved_retains_sanitized_metadata_diagnostics(monkeypatch):
    from csr2cdn import live_validation as probe
    p=payload()
    del p["ShowdownEventsContainer"]["RaceEventGroups"][0]["RaceEvents"]
    class Source:
        def close(self): pass
    monkeypatch.setattr(probe.ShowdownDiscovery,"from_metadata",lambda *a, **kw:
                        ShowdownDiscovery(lambda:p))
    r=probe.run_live("PRIVATE_PLAYER_ID",metadata_product_version="6.8.11",
                     showdown_name="Championship Showdown",metadata_factory=Source,
                     auto_crew=False,
                     # Pinned to the fixture window; see AT at the top of this
                     # module. Reading the real clock expires the test.
                     at=AT)
    assert r["checks"]["metadata"]["status"]=="ok"
    assert r["checks"]["metadata"]["unresolved_input_categories"]=={"first_race_event_id":1}
    assert r["checks"]["showdown_selection"]["status"]=="unresolved_input"
    assert r["checks"]["showdown"]["status"]=="unresolved_board"
