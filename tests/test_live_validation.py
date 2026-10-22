"""No network I/O is allowed in these tests."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import csr2cdn.live_validation as probe
from csr2cdn.services import ServiceHTTPError


class FakeMetadata:
    closed = False

    def close(self):
        self.closed = True


class FakeServices:
    calls = []

    def __init__(self, player_id, **kwargs):
        assert player_id == "PRIVATE_PLAYER_ID"
        assert kwargs["allow_network"] is True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def get_showdown_leaderboard(self, *, leaderboard_name):
        self.calls.append("showdown")
        return SimpleNamespace(entries=(object(), object()))

    def get_my_crew(self):
        self.calls.append("own_crew")
        return SimpleNamespace(crew_uid="PRIVATE_CREW", in_crew=True)

    def get_crew_members(self, crew_uid=None):
        self.calls.append("crew")
        return SimpleNamespace(members=(object(),))

    def get_prestige_cup_leaderboard(self, *, leaderboard_name):
        self.calls.append("prestige_cup")
        return SimpleNamespace(entries=())

    def get_showdown_leagues_leaderboard(self, *, leaderboard_name):
        self.calls.append("leagues")
        return SimpleNamespace(entries=())


@pytest.fixture(autouse=True)
def _reset_calls():
    FakeServices.calls = []


def test_read_only_checks_summarize_counts_without_identifiers():
    result = probe.run_live(
        "PRIVATE_PLAYER_ID", skip_metadata=True, showdown_board="PRIVATE_BOARD",
        crew_uid="PRIVATE_CREW", prestige_board="PRIVATE_PRESTIGE",
        leagues_board="PRIVATE_LEGACY", services_factory=FakeServices,
    )
    result_text = json.dumps(result)
    assert FakeServices.calls == ["showdown", "prestige_cup", "leagues", "crew"]
    assert result["checks"]["showdown"] == {"status": "ok", "records": 2}
    assert result["checks"]["crew"] == {"status": "ok", "records": 1, "nickname_populated": 0, "crew_rp_populated": 0, "player_rank_populated": 0, "rp_all_time_populated": 0, "player_profile_rp_populated": 0, "rp_from_native_uppercase": 0, "rp_from_explicit_season": 0, "rp_from_crew_alias": 0, "role_populated": 0, "role_recognized": 0}
    for private in ("PRIVATE_PLAYER_ID", "PRIVATE_BOARD", "PRIVATE_CREW", "PRIVATE_PRESTIGE", "PRIVATE_LEGACY"):
        assert private not in result_text


def test_metadata_discovery_selects_exactly_one(monkeypatch):
    seen = {}
    def fake_discovery(client, *, player_id, product_version):
        seen["product_version"] = product_version
        return SimpleNamespace(list_showdowns=lambda **_kw: [SimpleNamespace(time_status="scheduled_now", requestable=True, leaderboard_name="PRIVATE_BOARD")])
    monkeypatch.setattr(probe.ShowdownDiscovery, "from_metadata", fake_discovery)
    result = probe.run_live(
        "PRIVATE_PLAYER_ID", metadata_factory=FakeMetadata,
        product_version_resolver=lambda player, app: "6.8.91",
        services_factory=FakeServices,
    )
    assert seen["product_version"] == "6.8.91"
    assert result["checks"]["metadata"]["active_showdown_candidates"] == 1
    assert result["checks"]["showdown"]["records"] == 2


def test_metadata_override_does_not_resolve_version(monkeypatch):
    seen = {}
    def fake_discovery(client, *, player_id, product_version):
        seen["product_version"] = product_version
        return SimpleNamespace(list_showdowns=lambda **_kw: [])
    monkeypatch.setattr(probe.ShowdownDiscovery, "from_metadata", fake_discovery)
    r = probe.run_live("PRIVATE_PLAYER_ID", metadata_product_version="6.8.42",
                       product_version_resolver=lambda *args: (_ for _ in ()).throw(AssertionError("unexpected")),
                       metadata_factory=FakeMetadata, services_factory=FakeServices)
    assert seen["product_version"] == "6.8.42"
    assert r["checks"]["showdown"] == {"status": "unresolved_board"}
    assert FakeServices.calls == ["own_crew", "crew"]


def test_metadata_ambiguity_does_not_auto_select(monkeypatch):
    monkeypatch.setattr(probe.ShowdownDiscovery, "from_metadata", lambda *a, **k:
                        SimpleNamespace(list_showdowns=lambda **_kw: [
                            SimpleNamespace(time_status="scheduled_now", requestable=True, leaderboard_name="ONE"),
                            SimpleNamespace(time_status="scheduled_now", requestable=True, leaderboard_name="TWO")]))
    r = probe.run_live("PRIVATE_PLAYER_ID", metadata_factory=FakeMetadata,
                       metadata_product_version="6.8.4", services_factory=FakeServices)
    assert r["checks"]["metadata"]["active_showdown_candidates"] == 2
    assert r["checks"]["showdown"] == {"status": "unresolved_board"}
    assert FakeServices.calls == ["own_crew", "crew"]


def test_http_error_never_includes_urls_or_headers():
    class FailedServices(FakeServices):
        def get_showdown_leaderboard(self, *, leaderboard_name):
            raise ServiceHTTPError(403)
    r = probe.run_live("PRIVATE_PLAYER_ID", skip_metadata=True,
                       showdown_board="SECRET_BOARD", services_factory=FailedServices)
    assert r["checks"]["showdown"] == {"status": "http_rejected", "http_status": 403}
    assert "SECRET_BOARD" not in json.dumps(r)


def test_error_message_and_unexpected_failure_suppressed():
    assert probe._status(RuntimeError("token=SECRET; url=https://sensitive.example")) == {
        "status": "unexpected_failure"}


def test_dry_run_never_reads_player_id(monkeypatch, capsys):
    monkeypatch.setattr(probe.getpass, "getpass", lambda *a, **k: (_ for _ in ()).throw(AssertionError("prompted")))
    assert probe.main([]) == 0
    assert json.loads(capsys.readouterr().out)["network_requests"] == 0


def test_cli_secure_prompt_and_redacted_report(monkeypatch, capsys):
    monkeypatch.setattr(probe.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(probe.getpass, "getpass", lambda *args: "PRIVATE_PLAYER_ID")
    monkeypatch.setattr(probe, "run_live", lambda *args, **kwargs: {
        "mode": "live_read_only", "checks": {"showdown": {"status": "ok", "records": 2}}})
    assert probe.main(["--execute"]) == 0
    assert "PRIVATE_PLAYER_ID" not in capsys.readouterr().out


def test_live_runner_rejects_noninteractive_terminal(monkeypatch, capsys):
    monkeypatch.setattr(probe.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(probe.getpass, "getpass", lambda *args: (_ for _ in ()).throw(AssertionError("unsafe fallback")))
    assert probe.main(["--execute"]) == 2
    assert json.loads(capsys.readouterr().out)["checks"]["setup"]["status"] == "interactive_terminal_required"


def test_select_one_live_discovered_board_by_index(monkeypatch):
    monkeypatch.setattr(probe.ShowdownDiscovery, "from_metadata", lambda *a, **k:
                        SimpleNamespace(list_showdowns=lambda **_kw: [
                            SimpleNamespace(event_id="B", time_status="scheduled_now", requestable=True, leaderboard_name="SECOND"),
                            SimpleNamespace(event_id="A", time_status="scheduled_now", requestable=True, leaderboard_name="FIRST")]))
    class SelectedServices(FakeServices):
        def get_showdown_leaderboard(self, *, leaderboard_name):
            assert leaderboard_name == "FIRST"
            self.calls.append("showdown")
            return SimpleNamespace(entries=(object(),))
    r = probe.run_live("PRIVATE_PLAYER_ID", metadata_factory=FakeMetadata,
                       metadata_product_version="6.8.4", showdown_index=0,
                       services_factory=SelectedServices)
    assert r["checks"]["metadata"]["resolved_board_candidates"] == 2
    assert r["checks"]["showdown"] == {"status": "ok", "records": 1}


def test_default_live_probe_attempts_own_crew_without_uid():
    result = probe.run_live("PRIVATE_PLAYER_ID", skip_metadata=True,
                            services_factory=FakeServices)
    assert FakeServices.calls == ["own_crew", "crew"]
    assert result["checks"]["crew"] == {"status": "ok", "records": 1, "nickname_populated": 0, "crew_rp_populated": 0, "player_rank_populated": 0, "rp_all_time_populated": 0, "player_profile_rp_populated": 0, "rp_from_native_uppercase": 0, "rp_from_explicit_season": 0, "rp_from_crew_alias": 0, "role_populated": 0, "role_recognized": 0}
    assert result["checks"]["showdown"] == {"status": "unresolved_board"}
    assert "PRIVATE_CREW" not in json.dumps(result)


def test_probe_no_crew_and_skip_crew():
    class NoCrew(FakeServices):
        def get_my_crew(self):
            return SimpleNamespace(in_crew=False, crew_uid=None)
        def get_crew_members(self, crew_uid=None):
            raise AssertionError("must not query members without a crew")
    report = probe.run_live("PRIVATE_PLAYER_ID", skip_metadata=True,
                            services_factory=NoCrew)
    assert report["checks"]["crew"] == {"status": "not_in_crew"}
    FakeServices.calls = []
    other = probe.run_live("PRIVATE_PLAYER_ID", skip_metadata=True,
                           services_factory=FakeServices, auto_crew=False)
    assert other["checks"]["crew"]["status"] == "not_selected"
    assert FakeServices.calls == []


def test_unresolved_board_is_not_success_exit(monkeypatch, capsys):
    monkeypatch.setattr(probe.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(probe.getpass, "getpass", lambda *a: "PRIVATE_PLAYER_ID")
    monkeypatch.setattr(probe, "run_live", lambda *a, **k: {
        "checks": {"showdown": {"status": "unresolved_board"}}})
    assert probe.main(["--execute"]) == 1
    assert "PRIVATE_PLAYER_ID" not in capsys.readouterr().out
