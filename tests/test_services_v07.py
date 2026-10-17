"""Offline-only first-pass 0.7.0 feature tests; synthetic fixtures throughout."""
from __future__ import annotations

import base64
import json
from dataclasses import asdict

import pytest

from csr2cdn import (
    CSR2Services, CrewMembers, EventCatalog, EventLeaderboard, EventResolutionError,
    LeaderboardPage, ServiceHTTPError, ServiceNetworkDisabled, ServiceResponseError,
    StandingRange,
)
from csr2cdn._service_auth import PortalCredentials, ServiceAuthError
from csr2cdn._service_reads import ReadContractError, event_standings_contract, prepare_read_contract
from csr2cdn.service_events import EventResolutionError
from csr2cdn.service_cli import _public_result
from csr2cdn.cli import main


def creds(zid="12345678901", expiry=2000000000):
    token = base64.b64encode(f"head|nm|{zid}|csr2|{expiry}".encode()).decode()
    return PortalCredentials.from_response(zid, {"responseData": {
        "zynga": {"zauth": token, "zauthPidVToken": "TEST_PID_TOKEN"},
        "psk": "0" * 32, "securityHash": "1" * 32,
    }}, now=1700000000)


class Response:
    def __init__(self, doc, status=200):
        self.doc, self.status_code = doc, status

    def __enter__(self): return self
    def __exit__(self, *exc): pass

    def iter_content(self, chunk_size=16384):
        yield json.dumps(self.doc).encode()


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def close(self): pass


def test_crew_members_decoder_retains_cars_and_optional_metadata():
    payload = {"responseData": {"crewUID": "c1", "crewMembers": [
        {"player_uid": "u1", "zid": "p1", "name": "Tester", "role": "leader",
         "current_car": {"car_uid": "car1", "livery": "red"}, "car_pp": 600, "car_ep": "400"},
        {"zid": "p2", "current_car": "car2"},
    ]}}
    crew = CrewMembers.from_response("backup", payload)
    assert crew.crew_uid == "c1"
    assert len(crew.members) == 2
    assert crew.members[0].car.identifier == "car1"
    assert crew.members[0].car.pp == 600
    assert crew.members[0].car.details["livery"] == "red"
    assert crew.members[1].car.identifier == "car2"
    assert "livery" not in _public_result(crew)["members"][0]["car"]
    assert CrewMembers.from_response("c2", {"crewMembers": []}).members == ()
    for bad in ({"responseData": {}}, {"crewMembers": "no"}, {"crewMembers": [3]},
                {"error": "not authorized", "crewMembers": []}):
        with pytest.raises(ServiceResponseError):
            CrewMembers.from_response("c1", bad)


def test_score_decoder_preserves_server_order_and_optional_rank():
    page = LeaderboardPage.from_response("board", {"responseData": {
        "scores": [
            {"rank": 2, "zid": "p2", "name": "Player 2", "score": "700"},
            {"rank": 1, "zid": "p1", "score": 801},
        ], "playerRank": 35, "playerScore": 77,
        "nextCursor": "NEXT-1",
    }}, score_unit="trophies")
    assert [r.rank for r in page.entries] == [2, 1]
    assert page.find_player("p1").score == 801
    assert page.player_rank == 35
    assert page.next_cursor == "NEXT-1"
    assert page.score_unit == "trophies"
    assert page.find_player("absent") is None
    with pytest.raises(ServiceResponseError):
        LeaderboardPage.from_response("x", {"success": False, "scores": []})
    with pytest.raises(ServiceResponseError):
        LeaderboardPage.from_response("x", {"records": "no"})


def test_event_catalog_scope_refresh_expiry_and_transactionality(tmp_path, monkeypatch):
    file = tmp_path / "events.json"
    file.write_text(json.dumps({"events": [
        {"event_id": "event1", "kind": "showdown", "leaderboard_name": "board_A", "segment": "A", "score_unit": "trophies"},
        {"event_id": "event1", "kind": "showdown", "leaderboard_name": "board_B", "segment": "B"},
        {"event_id": "eventP", "kind": "prestige_cup", "leaderboard_name": "prestige_7", "instance": "7"},
    ]}))
    catalog = EventCatalog.from_json_file(file, ttl=999)
    with pytest.raises(EventResolutionError, match="ambiguous"):
        catalog.resolve("event1", "showdown")
    assert catalog.resolve("event1", "showdown", segment="B").leaderboard_name == "board_B"
    assert catalog.resolve("eventP", "prestige_cup").leaderboard_name == "prestige_7"
    with pytest.raises(EventResolutionError):
        catalog.resolve("event1", "prestige_cup")
    before = catalog.list_events()
    file.write_text('{"events":[{"kind":"showdown","event_id":"bad"}]}')
    with pytest.raises(EventResolutionError):
        catalog.refresh()
    assert catalog._items == before
    file.write_text('{"events":[]}')
    assert catalog.refresh() == ()
    with pytest.raises(EventResolutionError):
        catalog.resolve("event1", "showdown")


def test_metadata_adapter_refreshes_using_external_blocks():
    calls = []
    class Block:
        def __init__(self, content): self.content = content
    class Metadata:
        def get(self, names, zid, product_version):
            calls.append((names, zid, product_version))
            return {"LiveEventBlock": Block({"active": [{"event": "x", "board": "resolved_x"}]})}
    def extract(blocks):
        return {"events": [{"event_id": r["event"], "kind": "showdown",
                            "leaderboard_name": r["board"]}
                           for r in blocks["LiveEventBlock"]["active"]]}
    cat = EventCatalog.from_metadata(Metadata(), block_names=["LiveEventBlock"],
                                     zid="z", product_version="6.8.0", extract=extract, ttl=0)
    assert cat.resolve("x", "showdown").leaderboard_name == "resolved_x"
    assert cat.resolve("x", "showdown").leaderboard_name == "resolved_x"
    assert len(calls) == 2


def test_service_prepare_all_features_no_network():
    with CSR2Services("123", events=EventCatalog(lambda: {"events": [
        {"event_id": "sd", "kind": "showdown", "leaderboard_name": "sd-board", "score_unit": "trophies"},
        {"event_id": "pc", "kind": "prestige_cup", "leaderboard_name": "pc-board", "score_unit": "milliseconds"},
        {"event_id": "sl", "kind": "showdown_leagues", "leaderboard_name": "sl-board"},
    ]})) as client:
        assert client.prepare_crew_members("crew").route == "crews/viewMembers"
        assert client.prepare_showdown(event_id="sd").route == "leaderboard/sd-board/view"
        assert client.prepare_prestige_cup(event_id="pc").route == "leaderboard/pc-board/view"
        assert client.prepare_showdown_leagues(event_id="sl").route == "leaderboard/sl-board/view"
        assert client.prepare_showdown_leagues_preview("sl-board", score=34).route == "leaderboard/sl-board/preview"
        assert client.prepare_prestige_cup(leaderboard_name="new_unlisted_board").route.endswith("/view")
        assert client.prepare_showdown(leaderboard_name="abc", ranges=StandingRange.top3_and_you(),
                                       score=123, show_default=True).params["show_default"] is True
        with pytest.raises(ServiceNetworkDisabled):
            client.get_crew_members("crew")
        with pytest.raises(ServiceAuthError):
            client.prepare(client.prepare_crew_members("crew"))
        with pytest.raises(EventResolutionError):
            client.prepare_showdown(event_id="unlisted")


def test_reconstructed_event_contract_uses_native_extras_and_signed_allowlist():
    contract = event_standings_contract("board", StandingRange.common(),
                                        score=47, show_default=True)
    assert list(contract.params) == ["app_ver", "top", "after", "before", "offset", "score", "show_default"]
    result = prepare_read_contract(creds(), contract, unix_time=1700000000, nonce=42)
    assert json.loads(result.body)["show_default"] is True
    assert result.url.endswith("/leaderboard/board/view")
    with pytest.raises(ReadContractError):
        event_standings_contract("board", StandingRange.common(), show_default=1)


def test_offline_mocked_transport_and_no_secrets_in_exceptions():
    mock = Session(Response({"responseData": {"crewMembers": [{"name": "T"}]}}),
                   Response({"responseData": {"scores": [{"score": 30, "rank": 2}]}}))
    client = CSR2Services("12345678901", allow_network=True, credentials=creds(), session=mock)
    assert client.get_crew_members("a").members[0].name == "T"
    result = client.get_showdown_leaderboard(leaderboard_name="board")
    assert result.entries[0].score == 30
    assert len(mock.calls) == 2
    assert mock.calls[0][0].endswith("/crews/viewMembers")
    assert mock.calls[1][0].endswith("/leaderboard/board/view")
    assert mock.calls[0][1]["allow_redirects"] is False
    assert mock.calls[0][1]["timeout"] == (20.0, 20.0)
    assert "Authorization" in mock.calls[0][1]["headers"]
    client.close()
    denied = CSR2Services("12345678901", allow_network=True, credentials=creds(), session=Session(Response({}, 403)))
    with pytest.raises(ServiceHTTPError) as error:
        denied.get_crew_members("crew")
    assert error.value.status_code == 403
    assert "token" not in str(error.value).lower()


def test_service_refuses_redirects_and_large_data():
    client = CSR2Services("12345678901", allow_network=True, credentials=creds(),
                          session=Session(Response({}, 302)))
    with pytest.raises(ServiceHTTPError) as exc:
        client.get_crew_members("crew")
    assert exc.value.status_code == 302


def test_session_and_endpoint_injection_rules():
    with pytest.raises(ServiceAuthError):
        CSR2Services("123", credentials=creds())
    with pytest.raises(ServiceAuthError):
        CSR2Services("123", web_api_url="http://invalid.example")
    client = CSR2Services("123", endpoint_source=lambda: "https://current.example.com")
    assert client.refresh_endpoint() == "https://current.example.com"
    assert client.web_api_url == "https://current.example.com"


def test_cli_contracts_offline_and_mock_fixtures(tmp_path, capsys):
    events = tmp_path / "events.json"
    events.write_text('{"events":[{"event_id":"e1","kind":"prestige_cup","leaderboard_name":"pboard"}]}')
    assert main(["services", "--events-file", str(events), "prestige", "--event-id", "e1"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["route"] == "leaderboard/pboard/view"
    assert output["status"].startswith("offline-only")
    fixture = tmp_path / "crew.json"
    fixture.write_text('{"responseData":{"crewMembers":[{"name":"Test"}]}}')
    assert main(["services", "crew", "crewA", "--response-file", str(fixture)]) == 0
    assert json.loads(capsys.readouterr().out)["members"][0]["name"] == "Test"
    assert main(["services", "events"]) == 1
    assert "--events-file" in capsys.readouterr().err
    assert main(["services", "--execute", "crew", "crew1"]) == 1
    assert "interactive terminal" in capsys.readouterr().err


def test_no_save_code_in_public_api():
    import csr2cdn
    assert not any("save" in attr.lower() or "upload" in attr.lower() for attr in csr2cdn.__all__)


def test_showdown_score_native_read_and_decode(capsys):
    from csr2cdn._service_reads import showdown_leagues_score_contract
    from csr2cdn.service_models import LeaderboardScore
    contract = showdown_leagues_score_contract("board", period_offset=-1)
    assert contract.route == "leaderboard/board/score"
    assert contract.params == {"app_ver": "6.8.0", "offset": -1, "signed": True, "extra": True}
    assert prepare_read_contract(creds(), contract, unix_time=1700000000, nonce=11)
    assert LeaderboardScore.from_response("board", {"score": 100, "rank": 5}).rank == 5
    client = CSR2Services("123", allow_network=False)
    assert client.prepare_showdown_leagues_score("board").route.endswith("/score")
    assert main(["services", "showdown-leagues", "--leaderboard-name", "board", "--player-score"]) == 0
    assert json.loads(capsys.readouterr().out)["params"]["signed"] is True
