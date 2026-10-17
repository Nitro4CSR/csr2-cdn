"""Synthetic-only coverage for runtime modular event merging and source scope."""
import json
from datetime import datetime, timezone

import pytest

from csr2cdn import ShowdownDiscovery, merge_modular_showdown_groups
from csr2cdn.service_events import EventResolutionError
from csr2cdn.live_validation import run_live

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def base():
    return {
        "ShowdownEventsContainer": {"RaceEventGroups": [
            {"EventGroupName": "OLD_FIXTURE", "ScheduleID": "OLD"},
        ]},
        "EventSchedule": {"ScheduleList": [
            {"ScheduleID": "OLD", "Time_ActiveBetweenAny": [
                {"Start": "2025-01-01T00:00:00Z", "End": "2025-01-02T00:00:00Z"}]},
            {"ScheduleID": "CURRENT", "Time_ActiveBetweenAny": [
                {"Start": "2026-10-15T00:00:00Z", "End": "2026-10-16T00:00:00Z"}]},
        ]},
        "EventLeaderboards": {"EventLeaderboardsDefinitions": [
            {"nameID": "T", "rankingOrder": 1},
        ]},
    }


def modular():
    return [{"EventGroupName": "CURRENT_FIXTURE", "ScheduleID": "CURRENT",
             "RaceEvents": [{"EventID": 12345}],
             "Leaderboard": {"LeaderboardTemplateID": "T"}}]


def test_old_standalone_metadata_not_a_complete_current_event_catalogue():
    discovery = ShowdownDiscovery(base)
    assert discovery.source_coverage == "standalone_only"
    assert len(discovery.list_showdowns(at=NOW)) == 1
    assert not discovery.scheduled_now(at=NOW)


def test_supplied_modular_groups_enable_name_to_board_without_guessing():
    discovery = ShowdownDiscovery(base, modular_source=modular)
    rows = discovery.list_showdowns(at=NOW)
    assert discovery.source_coverage == "runtime_groups_supplied"
    assert len(rows) == 2
    row = discovery.resolve_named("Current fixture", at=NOW)
    assert row.leaderboard_name is not None
    assert row.resolution_source == "native_6_8_0"
    assert row.identity_inputs.first_event_id == 12345
    assert row.identity_inputs.ranking_order == "dsc"


def test_runtime_duplicate_name_is_not_added_or_overwritten():
    source = base()
    incoming = [{"EventGroupName": "OLD_FIXTURE", "ScheduleID": "CURRENT"}]
    merged = merge_modular_showdown_groups(source, incoming)
    assert len(merged["ShowdownEventsContainer"]["RaceEventGroups"]) == 1
    assert merged["ShowdownEventsContainer"]["RaceEventGroups"][0]["ScheduleID"] == "OLD"
    assert source["ShowdownEventsContainer"]["RaceEventGroups"][0]["ScheduleID"] == "OLD"


def test_bad_runtime_source_does_not_replace_good_refresh():
    values = [modular(), [{"not_an_event": 1}]]
    discovery = ShowdownDiscovery(base, modular_source=lambda: values.pop(0))
    assert len(discovery.list_showdowns(at=NOW)) == 2
    with pytest.raises(EventResolutionError):
        discovery.refresh()
    assert len(discovery.list_showdowns(at=NOW)) == 2


def test_malformed_runtime_group_rejected():
    for value in ([{}], ["not-an-object"], {"RaceEventGroups": []}):
        with pytest.raises(EventResolutionError):
            merge_modular_showdown_groups(base(), value)


def test_local_runtime_fixture_is_explicit_not_a_hardcoded_catalogue(tmp_path):
    for name, value in base().items():
        (tmp_path / (name + ".meta")).write_text(json.dumps({name: value}), encoding="utf-8")
    runtime = tmp_path / "runtime-groups.json"
    runtime.write_text(json.dumps(modular()), encoding="utf-8")
    d = ShowdownDiscovery.from_json_directory(tmp_path, modular_groups_file=runtime)
    assert d.resolve_named("current_fixture", at=NOW).identity_inputs.first_event_id == 12345


def test_limited_metadata_scope_report_without_event_or_account_data(monkeypatch):
    import csr2cdn.live_validation as probe

    class Stub:
        def close(self): pass

    monkeypatch.setattr(probe.ShowdownDiscovery, "from_metadata", lambda *a, **k:
                        ShowdownDiscovery(base))
    class Services:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get_my_crew(self): return type("C", (), {"in_crew": False})()
    report = run_live("PRIVATE_PLAYER", metadata_factory=Stub,
                      metadata_product_version="TEST", services_factory=Services)
    row = report["checks"]["metadata"]
    assert row["status"] == "ok"
    assert row["source_coverage"] == "standalone_only"
    assert row["active_event_absence_is_conclusive"] is False
    assert row["elapsed_candidates"] == 1
    assert "PRIVATE_PLAYER" not in json.dumps(report)
    assert "OLD_FIXTURE" not in json.dumps(report)


def test_event_metadata_assets_use_native_type_47_not_name_matching():
    from csr2cdn import modular_event_assets
    from csr2cdn.database import AssetDatabase
    db = AssetDatabase(assets=[
        {"code": "SYNTHETIC_EVENT_BUNDLE", "type": "47"},
        {"code": "SHOWDOWN_NAMED_BUT_OTHER_TYPE", "type": "1"},
        {"code": "OTHER_EVENT", "type": "0"},
    ])
    found = modular_event_assets(db)
    assert [asset.code for asset in found] == ["SYNTHETIC_EVENT_BUNDLE"]
    with pytest.raises(TypeError):
        modular_event_assets({"assets": []})
