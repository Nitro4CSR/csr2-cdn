"""Offline-only 0.7.1.dev1 GCC range contract/probe regressions."""
import base64
import json
from dataclasses import replace
from pathlib import Path

import pytest

from csr2cdn._service_auth import PortalCredentials
from csr2cdn._service_reads import (
    ReadContractError, StandingRange, gcc_progress_contract,
    gcc_progress_range_contract, prepare_read_contract,
)
from csr2cdn.gcc_range_probe import report, compare_responses, main
from csr2cdn.service_models import GCCProgressCrewScores, OwnCrew
from csr2cdn.services import CSR2Services, ServiceNetworkDisabled


def credentials():
    token = base64.b64encode(b"head|nm|12345678901|csr2|2000000000").decode()
    return PortalCredentials.from_response("12345678901", {"responseData": {
        "zynga": {"zauth": token, "zauthPidVToken": "TEST_ONLY"},
        "psk": "0" * 32, "securityHash": "1" * 32,
    }}, now=1700000000)


def fixture():
    return {"end_time": 1792663200, "scores": [
        {"crew_id": "secret001", "name": "First", "rank": 1, "score": 9000,
         "logo": {"private": "NO_PRINT"}},
        {"crew_id": "secret003", "name": "Third", "rank": 3, "score": 7000},
        {"crew_id": "secret100", "name": "OurCrew", "rank": 100, "score": 5000},
    ]}


def test_default_gcc_contract_unchanged():
    c = gcc_progress_contract()
    assert c.params == {"app_ver": "6.8.0", "top": 10, "after": 5, "before": 5, "offset": 0}
    assert c.operation == "Fetches GCC current progress (experimental)"
    assert c.request_type == 3
    assert prepare_read_contract(credentials(), c, unix_time=1700000000, nonce=14)


def test_exploratory_explicit_opt_in_and_native_parameter_order():
    r = StandingRange(top=20, after=10, before=10, offset=5)
    with pytest.raises(ReadContractError):
        gcc_progress_range_contract(r)
    c = gcc_progress_range_contract(r, exploratory=True)
    assert c.route == "leaderboard/crew-champs-v2/viewcrew"
    assert c.request_type == 3
    assert list(c.params.items()) == [
        ("app_ver", "6.8.0"), ("top", 20), ("after", 10), ("before", 10), ("offset", 5)]
    signed = prepare_read_contract(credentials(), c, unix_time=1700000000, nonce=16)
    assert signed.body == b'{"app_ver":"6.8.0","top":20,"after":10,"before":10,"offset":5}'
    assert signed.url.endswith("/leaderboard/crew-champs-v2/viewcrew")


@pytest.mark.parametrize("kwargs", [
    {"top": 0}, {"top": 51}, {"top": True}, {"top": None},
    {"before": -1}, {"before": 31}, {"before": 1.5},
    {"after": -1}, {"after": 31}, {"after": False},
    {"offset": -1}, {"offset": 1001}, {"offset": 2**31},
    {"top": 50, "after": 30, "before": 30},
])
def test_bounds_reject_bad_values(kwargs):
    vals = dict(top=20, before=10, after=10, offset=0)
    vals.update(kwargs)
    with pytest.raises(ReadContractError):
        gcc_progress_range_contract(StandingRange(**vals), exploratory=True)


def test_tampered_signed_contracts_rejected():
    c = gcc_progress_range_contract(StandingRange(10, 10, 0, top=20), exploratory=True)
    bad = [
        replace(c, params={**c.params, "after": 31}),
        replace(c, params={"top": 20, "app_ver": "6.8.0", "after": 10,
                           "before": 10, "offset": 0}),
        replace(c, params={**c.params, "offset": -1}),
        replace(c, operation="Some unrecognized operation"),
        replace(c, route="leaderboard/alternative/viewcrew"),
        replace(c, request_type=5),
    ]
    for contract in bad:
        with pytest.raises(ReadContractError):
            prepare_read_contract(credentials(), contract, unix_time=1700000000)


def test_service_explicit_opt_in_and_read_boundary():
    svc = CSR2Services("12345678901", allow_network=False)
    r = StandingRange(top=20, after=10, before=10, offset=0)
    with pytest.raises(ReadContractError):
        svc.prepare_gcc_progress_range(r)
    c = svc.prepare_gcc_progress_range(r, exploratory=True)
    assert c == gcc_progress_range_contract(r, exploratory=True)
    with pytest.raises(ReadContractError):
        svc.get_gcc_progress_range_response(r)
    with pytest.raises(ServiceNetworkDisabled):
        svc.get_gcc_progress_range_response(r, exploratory=True)


def test_decoder_private_by_default():
    r = report(fixture(), ranges=StandingRange(top=20, before=10, after=10, offset=0),
               own_crew_id="secret100")
    body = json.dumps(r)
    assert r["rows"] == 3
    assert r["own_crew_exact_id_matches"] == 1
    assert r["own_crew_rank"] == 100
    assert r["own_crew_score"] == 5000
    assert r["entries"] == []
    for needle in ("secret", "OurCrew", "NO_PRINT", "end_time"):
        assert needle not in body
    assert r["offset_pagination_verified"] is False
    assert r["complete_leaderboard_verified"] is False


def test_opt_in_print_names_but_no_ids_or_logo():
    r = report(fixture(), ranges=StandingRange(top=20, before=10, after=10, offset=0),
               own_crew_id="secret100", print_entries=True)
    s = json.dumps(r)
    assert r["entries"][2]["is_own_crew"]
    assert "OurCrew" in s and "First" in s
    assert "secret100" not in s and "NO_PRINT" not in s


def test_overlap_matches_by_id_never_name_or_position():
    old = fixture()
    new = {"scores": [
        {"crew_id": "secret100", "name": "Renamed", "rank": 100, "score": 5000},
        {"crew_id": "secret003", "name": "Third", "rank": 2, "score": 7300},
        {"crew_id": "someoneElse", "name": "First", "rank": 1, "score": 9000},
    ]}
    c = compare_responses(old, new)
    assert c["shared_crew_ids"] == 2
    assert c["matching_rank_and_score"] == 1
    assert c["changed_rank_or_score"] == 1
    assert c["arbitrary_pagination_verified"] is False
    assert "secret" not in json.dumps(c)


def test_safe_cli_dry_run_no_network_and_invalid_input(capsys, monkeypatch):
    import requests
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    assert main([]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["network_requests"] == 0
    assert out["experimental"] is True
    with pytest.raises(SystemExit) as ex:
        main(["--top", "1000"])
    assert ex.value.code == 2


def test_offline_fixture_and_overlap_are_network_free(capsys, tmp_path):
    a = tmp_path / "one.json"
    a.write_text(json.dumps(fixture()), encoding="utf-8")
    b = tmp_path / "two.json"
    b.write_text(json.dumps(fixture()), encoding="utf-8")
    assert main(["--fixture-json", str(a), "--compare-json", str(b)]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["offline_response_overlap"]["shared_crew_ids"] == 3
    assert r["entries"] == []


def test_one_opt_in_live_probe_and_optional_own_crew_lookup(capsys, monkeypatch):
    calls = []
    class FakeSvc:
        def __init__(self, *args, **kwargs):
            calls.append(("init", kwargs["allow_network"]))
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def get_my_crew(self, *, refresh=False):
            calls.append("own")
            return OwnCrew("secret100")
        def get_gcc_progress_range_response(self, ranges, *, exploratory):
            calls.append(("gcc", ranges, exploratory))
            return fixture()
    # Don't print personal input in test output.
    monkeypatch.setattr("csr2cdn.gcc_range_probe.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("csr2cdn.gcc_range_probe.getpass.getpass", lambda prompt: "12345678901")
    assert main(["--execute", "--match-own-crew", "--top", "20"], services_factory=FakeSvc) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["own_crew_rank"] == 100
    assert calls[0] == ("init", True) and calls[1] == "own"
    assert len([x for x in calls if isinstance(x, tuple) and x[0] == "gcc"]) == 1
    assert "secret" not in json.dumps(r)


def test_unknown_schema_reports_suppressed_error_not_payload(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"TOKEN": "dont_print", "scores": [{"key": "SECRET"}]}))
    assert main(["--fixture-json", str(p)]) == 3
    assert "dont_print" not in capsys.readouterr().out


def test_typed_helper_decodes_with_exactly_one_read(monkeypatch):
    svc = CSR2Services("12345678901", allow_network=False)
    calls = []
    def fake_read(contract):
        calls.append(contract)
        return fixture()
    monkeypatch.setattr(svc, "_read", fake_read)
    result = svc.get_gcc_progress_range(StandingRange(top=20, after=10, before=10, offset=0),
                                        exploratory=True)
    assert isinstance(result, GCCProgressCrewScores)
    assert len(result.crews) == 3
    assert len(calls) == 1
    assert calls[0].operation.endswith("(bounded range probe; unverified)")
