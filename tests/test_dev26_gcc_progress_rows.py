"""Dev26: GCC current-progress score rows are a distinct wire type from GCC results."""
import json
import pytest

from csr2cdn.crew_rp_verification import make_gcc_progress_report, verify, _table, main
from csr2cdn.service_models import GCCProgressCrewScores, OwnCrew, ServiceResponseError


def sample():
    return {"scores": [
        {"crew_id": "crew_256", "name": "UNDERDOGZ 2", "rank": 256, "score": 37526591, "logo": {"danger": "SECRET"}},
        {"crew_id": "crew_257", "name": "ASPHALT STINGERS", "rank": 257, "score": 37483425, "logo": {}},
        {"crew_id": "crew_258", "name": "PRO LEAGUES", "rank": 258, "score": 37469814},
    ]}


def test_observed_wire_shape_strictly_decodes_and_keeps_ids_private():
    obj = GCCProgressCrewScores.from_response(sample())
    assert len(obj.crews) == 3
    assert obj.crews[0].score == 37526591
    assert obj.crews[0].rank == 256
    assert "crew_256" not in repr(obj.crews[0])
    result = make_gcc_progress_report(sample(), own_crew_uid="crew_256", reference_total=37448821,
                                      reference_rank=257, print_rows=True)
    assert result["matched_own_crew_records"] == 1
    assert result["own_crew_score_candidate"] == 37526591
    assert result["own_crew_rank_returned"] == 256
    assert result["own_crew_score_minus_ui_snapshot"] == 77770
    assert result["own_crew_rank_change_since_ui_snapshot"] == -1
    assert result["rows"][0]["matches_own_crew_id"]
    assert result["score_is_confirmed_season_crew_rp"] is False
    assert result["active_season_verified"] is False
    assert "crew_256" not in json.dumps(result)
    assert "SECRET" not in json.dumps(result)
    assert "UNDERDOGZ" in _table({"at_utc": "T", "gcc_live_response": result})


def test_without_explicit_print_optin_show_only_aggregate_and_own_candidate():
    report = make_gcc_progress_report(sample(), own_crew_uid="crew_256")
    assert report["rows"] == [] and report["own_crew_name"] is None
    assert report["own_crew_score_candidate"] == 37526591
    assert "UNDERDOGZ" not in json.dumps(report)
    assert "crew_256" not in json.dumps(report)


def test_wrong_crew_id_never_fuzzy_matches_name_or_rank():
    r = make_gcc_progress_report(sample(), own_crew_uid="missing", reference_rank=256, reference_total=37526591, print_rows=True)
    assert r["matched_own_crew_records"] == 0
    assert r["own_crew_rank_returned"] is None
    assert r["own_crew_score_minus_ui_snapshot"] is None
    assert all(not row["matches_own_crew_id"] for row in r["rows"])


@pytest.mark.parametrize("mutation", [
    lambda rows: rows.append(dict(rows[0])),
    lambda rows: rows[0].update(score=True),
    lambda rows: rows[0].update(rank="256"),
    lambda rows: rows[0].update(crew_id=""),
    lambda rows: rows[0].update(score=-1),
    lambda rows: rows[0].update(rank=0),
    lambda rows: rows[0].update(name=None),
])
def test_reject_malformed_and_duplicate_rows(mutation):
    r = sample()
    mutation(r["scores"])
    with pytest.raises(ServiceResponseError):
        GCCProgressCrewScores.from_response(r)


def test_valid_nested_response_data():
    p = GCCProgressCrewScores.from_response({"responseData": sample()})
    assert len(p.crews) == 3


def test_native_results_shape_remains_separate():
    with pytest.raises(ServiceResponseError):
        GCCProgressCrewScores.from_response({"results": [{"uid": "u", "cc_rp": 12, "crew_rank": 1}]})


def test_live_uses_only_own_read_and_gcc_read_for_exact_id_match():
    calls = []
    class FakeService:
        def __init__(self, *args, **kwargs): calls.append("init")
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get_my_crew(self):
            calls.append("own")
            return OwnCrew("crew_256")
        def get_crew_members(self): raise AssertionError("roster not required")
        def get_gcc_progress_response(self):
            calls.append("gcc")
            return sample()
    report = verify(player_id="PRIVATE_PLAYER", execute=True, gcc_live=True, gcc_only=True,
                    gcc_print_score_candidates=True, services_factory=FakeService,
                    reference_total=37448821, reference_rank=257)
    assert calls == ["init", "own", "gcc"]
    gcc = report["gcc_live_response"]
    assert gcc["matched_own_crew_records"] == 1
    assert gcc["own_crew_rank_returned"] == 256
    assert "crew_256" not in json.dumps(report)
    assert "PRIVATE_PLAYER" not in json.dumps(report)
    table = _table(report)
    assert "SERVER GCC PROGRESS" in table
    assert "UNDERDOGZ 2" in table
    assert "SEASON RP NOT VERIFIED" in table


def test_offline_file_decodes_without_network_or_own_identity(tmp_path, capsys):
    p = tmp_path/"capture.json"
    p.write_text(json.dumps(sample()))
    assert main(["--gcc-response-json", str(p), "--gcc-print-score-candidates"]) == 0
    captured = capsys.readouterr().out
    assert "Rows: 3" in captured
    assert "OWN CREW ID MATCH COUNT: 0" in captured
    assert "UNDERDOGZ 2" in captured
    assert "crew_256" not in captured
