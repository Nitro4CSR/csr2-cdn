"""Completely offline, synthetic Showdown metadata preflight tests.

These fixtures mimic the *names* of known 6.8.0 metadata blocks. They do
not assert that the actual current production event has the same fields.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from csr2cdn import CSR2Services, ShowdownDiscovery, scan_showdowns
from csr2cdn._service_auth import PortalCredentials, PreparedRequest
from csr2cdn.service_events import EventResolutionError
from csr2cdn.cli import main

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def blocks(board="test_resolved_board"):
    group = {"id": "event_fixture_a", "ScheduleID": "calendar_fixture_a",
             "Leaderboard": {"LeaderboardTemplateID": "TEMPLATE_ONLY"}}
    if board is not None:
        group["Leaderboard"]["LeaderboardUniqueID"] = board
    return {
        "ShowdownEventsContainer": {"RaceEventGroups": [group, {
            "id": "event_fixture_b", "ScheduleID": "calendar_fixture_b",
            "Leaderboard": {"LeaderboardTemplateID": "not_a_board"},
        }]},
        "EventSchedule": {"ScheduleList": [
            {"ScheduleID": "calendar_fixture_a", "_Time_ActiveBetween": {
                "Start": "2026-10-15T10:00:00Z", "End": "2026-10-15T15:00:00+00:00"}},
            {"ScheduleID": "calendar_fixture_b", "_Time_ActiveBetween": {
                "Start": "2026-10-20T10:00:00Z", "End": "2026-10-20T15:00:00Z"}},
        ]},
        "EventLeaderboards": {"EventLeaderboardsDefinitions": []},
    }


def directory(tmp_path, data):
    for name, content in data.items():
        (tmp_path / (name + ".meta")).write_text(json.dumps({name: content}), encoding="utf-8")
    return tmp_path


def test_scan_scheduled_and_requestable():
    rows = scan_showdowns(blocks(), at=NOW)
    assert [(x.event_id, x.time_status) for x in rows] == [
        ("event_fixture_a", "scheduled_now"), ("event_fixture_b", "upcoming")]
    assert rows[0].requestable
    assert rows[0].schedule_gates_unverified
    assert rows[0].leaderboard_template_id == "TEMPLATE_ONLY"
    assert not rows[1].requestable
    assert rows[0].starts_at.tzinfo is not None


def test_showdown_end_to_end_fixture_offline(tmp_path, capsys):
    discovery = ShowdownDiscovery.from_json_directory(directory(tmp_path, blocks()))
    service = CSR2Services("TEST_USER", events=discovery.to_event_catalog())
    contract = service.prepare_current_showdown(discovery, at=NOW)
    assert contract.route == "leaderboard/test_resolved_board/view"
    assert contract.request_type == 5
    assert contract.params["top"] == 10
    assert service.prepare_showdown(event_id="event_fixture_a").route == contract.route
    assert main(["services", "--metadata-dir", str(tmp_path), "--at", NOW.isoformat(), "showdowns",
                 "--scheduled-now"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert len(output) == 1
    assert output[0]["leaderboard_name"] == "test_resolved_board"
    assert main(["services", "--metadata-dir", str(tmp_path), "--at", NOW.isoformat(),
                 "showdown", "--current"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["route"] == "leaderboard/test_resolved_board/view"
    assert preview["status"] == "offline-only; nothing sent"


def test_template_id_is_never_treated_as_resolved_board():
    discovery = ShowdownDiscovery(lambda: blocks(board=None))
    assert discovery.scheduled_now(at=NOW)[0].leaderboard_name is None
    with pytest.raises(EventResolutionError, match="resolved leaderboard ID"):
        discovery.resolve_current_board(at=NOW)


def test_multiple_scheduled_events_ambiguous():
    data = blocks()
    data["EventSchedule"]["ScheduleList"][1]["_Time_ActiveBetween"] = {
        "Start": "2026-10-14T10:00:00Z", "End": "2026-10-17T15:00:00Z"}
    discovery = ShowdownDiscovery(lambda: data)
    with pytest.raises(EventResolutionError, match="ambiguous"):
        discovery.resolve_current_board(at=NOW)


def test_missing_time_window_does_not_assert_current():
    data = blocks()
    data["EventSchedule"]["ScheduleList"] = []
    discovery = ShowdownDiscovery(lambda: data)
    assert all(x.time_status == "unknown" for x in discovery.list_showdowns(at=NOW))
    assert not discovery.scheduled_now(at=NOW)


def test_bad_time_and_empty_metadata_gracefully_rejected(tmp_path):
    with pytest.raises(ValueError, match="timezone"):
        scan_showdowns(blocks(), at=datetime(2026, 10, 15))
    with pytest.raises(EventResolutionError, match="required"):
        ShowdownDiscovery.from_json_directory(tmp_path).list_showdowns(at=NOW)
    assert scan_showdowns({"ShowdownEventsContainer": {"RaceEventGroups": []}}, at=NOW) == ()


def test_metadata_client_adapter_is_lazy_and_uses_current_blocks():
    class StubBlock:
        def __init__(self, value): self.content = value
    class Client:
        calls = 0
        def get(self, names, *, zid, product_version):
            self.calls += 1
            assert zid == "test-id" and product_version == "6.8.0"
            assert tuple(names) == ("ShowdownEventsContainer", "EventSchedule", "EventLeaderboards")
            return {name: StubBlock(content) for name, content in blocks().items()}
    stub = Client()
    provider = ShowdownDiscovery.from_metadata(stub, player_id="test-id", product_version="6.8.0")
    assert stub.calls == 0
    assert provider.resolve_current_board(at=NOW) == "test_resolved_board"
    assert stub.calls == 1
    assert provider.resolve_current_board(at=NOW) == "test_resolved_board"
    assert stub.calls == 1
    provider.resolve_current_board(at=NOW, refresh=True)
    assert stub.calls == 2


def test_metadata_adapter_fails_closed_if_partial():
    class Client:
        def get(self, *args, **kwargs): return {"ShowdownEventsContainer": object()}
    provider = ShowdownDiscovery.from_metadata(Client(), player_id="test", product_version="6.8.0")
    with pytest.raises(EventResolutionError, match="incomplete"):
        provider.list_showdowns(at=NOW)


def test_cache_preserved_on_bad_refresh():
    values = [blocks(), []]
    provider = ShowdownDiscovery(lambda: values.pop(0))
    assert provider.resolve_current_board(at=NOW) == "test_resolved_board"
    with pytest.raises(EventResolutionError): provider.refresh()
    assert provider.resolve_current_board(at=NOW) == "test_resolved_board"


def test_sensitive_request_repr_redacted():
    prepared = PreparedRequest("https://secret.invalid/private/auth", b"opaque", {"Authorization": "private"})
    assert "secret.invalid" not in repr(prepared)
    assert "private" not in repr(prepared)
    creds = PortalCredentials("person123", "secret-access", "pid-private", "key-private", 2147483647)
    assert "person123" not in repr(creds)
    assert "secret-access" not in repr(creds)


def test_cli_generic_session_failure_does_not_log_method(tmp_path, capsys):
    directory(tmp_path, blocks())
    # Invalid input is rejected locally, with no portal or signature diagnostics.
    assert main(["services", "--metadata-dir", str(tmp_path), "--at", NOW.isoformat(),
                 "showdown", "--current", "--top", "-2147483648"]) == 1
    captured = capsys.readouterr()
    assert "portal" not in captured.err.lower()
    assert "sign" not in captured.err.lower()
    assert "token" not in captured.err.lower()


def test_real_metadata_group_name_is_not_dropped_before_schedule_resolution():
    """Matches the field *names* reported by validation, not any private values."""
    sample = {"ShowdownEventsContainer": {"RaceEventGroups": [
        {"EventGroupName": "sample_group", "ScheduleID": "sample_schedule",
         "Leaderboard": {"LeaderboardTemplateID": "not_resolved",
                         "UnlockConditions": []}}
    ]}, "EventSchedule": {"ScheduleList": [
        {"ScheduleID": "sample_schedule", "BasedOn_ScheduleID": "other_schedule",
         "Time_ActiveBetweenAny": []}
    ]}, "EventLeaderboards": {}}
    rows = scan_showdowns(sample, at=NOW)
    assert len(rows) == 1
    assert rows[0].event_id == "sample_group"  # candidate label, not canonical event ID
    assert rows[0].identifier_source == "EventGroupName"
    assert rows[0].schedule_id == "sample_schedule"
    assert rows[0].leaderboard_template_id == "not_resolved"
    assert rows[0].time_status == "unknown"  # unsupported inherited time gates
    assert rows[0].leaderboard_name is None
    assert not rows[0].requestable


def test_group_name_is_not_promoted_to_canonical_event_catalog_key():
    data = blocks()
    del data["ShowdownEventsContainer"]["RaceEventGroups"][0]["id"]
    data["ShowdownEventsContainer"]["RaceEventGroups"][0]["EventGroupName"] = "LABEL_ONLY"
    discovery = ShowdownDiscovery(lambda: data)
    rows = discovery.list_showdowns(at=NOW)
    assert rows[0].identifier_source == "EventGroupName"
    assert rows[0].requestable  # explicit server board name, independent of ID source
    catalog = discovery.to_event_catalog()
    assert all(x.event_id != "LABEL_ONLY" for x in catalog.list_events())
