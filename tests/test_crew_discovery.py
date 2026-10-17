"""Synthetic/offline validation of native own-crew lookup and crew ID resolution.

No live service calls, private account data, or save-game paths are involved.
"""
from __future__ import annotations

import json

import pytest

from csr2cdn import CSR2Services, OwnCrew, ServiceNetworkDisabled, ServiceResponseError
from csr2cdn._service_reads import (
    ReadContract, ReadContractError, own_crew_contract, prepare_read_contract,
)
from test_services_v07 import Session, Response, creds
from csr2cdn.cli import main


def test_check_user_crew_native_request_is_app_version_only():
    contract = own_crew_contract()
    assert contract.route == "crews/checkUserCrew"
    assert contract.request_type == 3
    assert list(contract.params.items()) == [("app_ver", "6.8.0")]
    signed = prepare_read_contract(creds(), contract, unix_time=1700000000, nonce=4)
    assert signed.body == b'{"app_ver":"6.8.0"}'
    assert signed.url.endswith("/crews/checkUserCrew")
    assert "PRIVATE" not in repr(signed)


def test_only_canonical_own_crew_request_is_allowed():
    for bad in [
        ReadContract("crews/checkUserCrew", {"app_ver": "6.8.0", "crew_uid": "unknown"}, 3, "Check User Crew"),
        ReadContract("crews/checkUserCrew", {"app_ver": "6.8.0"}, 5, "Check User Crew"),
        ReadContract("crews/checkUserCrew", {"app_ver": "bad"}, 3, "Check User Crew"),
    ]:
        with pytest.raises(ReadContractError):
            prepare_read_contract(creds(), bad, unix_time=1700000000)


def test_own_crew_decoder_handles_membership_and_no_membership():
    own = OwnCrew.from_response({"responseData": {
        "crewUID": "AUTH_CREW", "crewName": "Example Crew", "memberCount": 18,
        "playerRole": "member", "playerUID": "SENSITIVE_PLAYER",
    }})
    assert own.in_crew
    assert own.crew_uid == "AUTH_CREW"
    assert own.name == "Example Crew"
    assert own.member_count == 18
    assert "SENSITIVE_PLAYER" not in repr(own)
    absent = OwnCrew.from_response({"responseData": {"playerUID": "user", "crewUID": ""}})
    assert not absent.in_crew
    assert absent.crew_uid is None
    for bad in ({}, {"responseData": {}}, {"crewUID": "../cross-path"},
                {"responseData": {"error": "private failure", "crewUID": "c"}}):
        with pytest.raises(ServiceResponseError):
            OwnCrew.from_response(bad)


def test_own_crew_then_members_are_queried_without_input_uid():
    s = Session(
        Response({"responseData": {"crewUID": "server_crew", "crewName": "Test"}}),
        Response({"responseData": {"crewUID": "server_crew", "crewMembers": [{"zid": "test1"}]}}),
        Response({"responseData": {"crewUID": "server_crew", "crewMembers": []}}),
    )
    service = CSR2Services("12345678901", allow_network=True, credentials=creds(), session=s)
    crew = service.get_crew_members()
    assert crew.crew_uid == "server_crew"
    assert len(crew.members) == 1
    assert [call[0].rsplit("/", 1)[-1] for call in s.calls] == ["checkUserCrew", "viewMembers"]
    assert json.loads(s.calls[0][1]["data"]) == {"app_ver": "6.8.0"}
    assert json.loads(s.calls[1][1]["data"])["crew_uid"] == "server_crew"
    assert service.get_crew_members().members == ()
    assert len(s.calls) == 3  # cached own-crew resolution
    service.close()


def test_no_crew_blocks_second_request():
    session = Session(Response({"responseData": {"playerUID": "test", "crewUID": ""}}))
    service = CSR2Services("12345678901", allow_network=True, credentials=creds(), session=session)
    with pytest.raises(ReadContractError, match="no resolved crew"):
        service.get_crew_members()
    assert len(session.calls) == 1


def test_offline_preview_without_uid_does_not_infer_identity(tmp_path, capsys):
    service = CSR2Services("12345678901")
    assert service.prepare_my_crew().route == "crews/checkUserCrew"
    with pytest.raises(ReadContractError, match="not resolved"):
        service.prepare_crew_members()
    with pytest.raises(ServiceNetworkDisabled):
        service.get_crew_members()
    assert main(["services", "crew"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["route"] == "crews/checkUserCrew"
    assert preview["params"] == {"app_ver": "6.8.0"}
    fixture = tmp_path / "own-crew.json"
    fixture.write_text('{"responseData": {"crewUID":"fixture_crew", "crewName":"Fixture"}}')
    assert main(["services", "crew", "--response-file", str(fixture)]) == 0
    assert json.loads(capsys.readouterr().out)["crew_uid"] == "fixture_crew"


def test_refresh_membership_and_explicit_override():
    session = Session(
        Response({"crewUID": "crewA"}),
        Response({"crewUID": "crewB"}),
        Response({"crewMembers": []}),
    )
    service = CSR2Services("12345678901", allow_network=True, credentials=creds(), session=session)
    assert service.get_my_crew().crew_uid == "crewA"
    assert service.get_my_crew().crew_uid == "crewA"
    assert len(session.calls) == 1
    assert service.get_my_crew(refresh=True).crew_uid == "crewB"
    assert service.get_crew_members("override").members == ()
    assert json.loads(session.calls[-1][1]["data"])["crew_uid"] == "override"
    service.close()
    assert service._own_crew is None


def test_public_services_cli_prompts_hidden_player_id(monkeypatch, capsys):
    import csr2cdn.service_cli as cli
    from types import SimpleNamespace
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "PRIVATE_USER")
    seen = {}
    class Client:
        def __init__(self, player_id, **kwargs):
            seen["player_id"] = player_id
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def prepare_my_crew(self): return own_crew_contract()
        def decode_my_crew(self, response): return OwnCrew.from_response(response)
        def get_crew_members(self):
            return OwnCrew("private", "dont-print-credentials")
    monkeypatch.setattr(cli, "CSR2Services", Client)
    # Use globally routed CLI, but inject no private id into CLI argv.
    assert main(["services", "--execute", "crew"]) == 0
    assert seen["player_id"] == "PRIVATE_USER"
    stdout = capsys.readouterr().out
    assert "PRIVATE_USER" not in stdout
