"""Dev25: GCC progress scores are unverified *shape* data, not crew totals."""
import json

import pytest

from csr2cdn.crew_rp_verification import gcc_scores_shape, main, verify, _table
from csr2cdn.service_models import OwnCrew


def _scores_payload():
    return {"scores": [
        {"score": 37463129, "rank": 257, "crew": {"name": "Example Crew", "cc_rp": "37463129", "uid": "PRIVATE_ID"},
         "session_token": "PRIVATE_TOKEN", "name": "Example Crew"},
        {"score": "47110000", "position": 200, "name": "Another Crew", "accessToken": "PRIVATE_TOKEN2"},
        {"score": {"value": "9000", "name": "Nested"}, "id": "PLAYER_IDENTIFIER"},
        {"score": True, "rank": -1, "name": "Bad counter"},
    ]}


def test_gcc_scores_structural_fields_no_data_leak_by_default():
    result = gcc_scores_shape(_scores_payload())
    assert result["status"] == "unverified_gcc_progress_scores_shape"
    assert result["row_count"] == 4 and result["dictionary_rows"] == 4
    assert result["known_row_fields_by_type"]["score"] == {"integer": 1, "string": 1, "object": 1, "bool": 1}
    assert result["known_nested_fields_by_type"]["crew"]["cc_rp"] == {"string": 1}
    assert result["known_nested_fields_by_type"]["score"]["value"] == {"string": 1}
    assert result["candidate_rows"] == []
    output = json.dumps(result)
    for secret in ("PRIVATE_ID", "PRIVATE_TOKEN", "Example Crew", "PLAYER_IDENTIFIER"):
        assert secret not in output
    assert not result["active_season_verified"]


def test_only_whitelisted_score_values_print_with_separate_opt_in():
    result = gcc_scores_shape(_scores_payload(), print_candidates=True)
    assert result["candidate_rows"][0] == {
        "response_row_index": 1, "score_unverified": 37463129, "rank_unverified": 257,
        "name_hint_unverified": "Example Crew", "crew.cc_rp_unverified": 37463129,
    }
    assert result["candidate_rows"][1]["score_unverified"] == 47110000
    assert result["candidate_rows"][2]["score.value_unverified"] == 9000
    assert result["candidate_rows"][3] == {"response_row_index": 4, "name_hint_unverified": "Bad counter"}
    assert "PRIVATE_ID" not in json.dumps(result)
    assert "PRIVATE_TOKEN" not in json.dumps(result)
    assert "PLAYER_IDENTIFIER" not in json.dumps(result)
    assert "seasonal_crew_rp" not in result


def test_sanitized_schema_key_names_explicit_opt_in():
    r = gcc_scores_shape({"scores": [
        {"score": 10, "accessToken": "PRIVATE", "session_token": "PRIVATE2", "bad-key": 55,
         "randomFriendlyField": 4, "private_key": "SECRET", "id": "SECRET_ID"},
    ]}, show_schema_keys=True)
    keys = r["schema_key_type_counts"]
    assert keys["randomFriendlyField"] == {"integer": 1}
    assert keys["id"] == {"string": 1}
    assert "bad-key" not in keys
    assert "session_token" not in keys
    assert "accessToken" not in keys
    assert "private_key" not in keys
    assert "PRIVATE" not in json.dumps(r)
    assert not r["candidate_value_preview_opted_in"]


def test_bounded_sizes_no_unrestricted_rows_or_keys():
    rows = [{f"label{i}": i for i in range(90)} for _ in range(1100)]
    r = gcc_scores_shape({"scores": rows}, show_schema_keys=True)
    assert r["row_count"] == 1100
    assert r["inspected_rows"] == 1000
    assert len(r["schema_key_type_counts"]) == 64
    assert r["candidate_rows"] == []


def test_nonnumeric_str_and_float_not_printed_as_valid_score():
    r = gcc_scores_shape({"scores": [
        {"score": "1e5", "rank": 3.5, "cc_rp": -3},
        {"score": "99999999999999999999", "rank": None},
        {"score": "0", "rank": 0},
    ]}, print_candidates=True)
    assert r["candidate_rows"] == [{"response_row_index": 3, "score_unverified": 0, "rank_unverified": 0}]


def test_scores_envelope_response_data_supported():
    r = gcc_scores_shape({"responseData": {"scores": [{"score": 100}]}})
    assert r["row_count"] == 1


def test_non_scores_response_rejected_for_shape_interpretation():
    with pytest.raises(ValueError):
        gcc_scores_shape({"entries": [{"score": 1}]})


def test_live_score_probe_remains_one_read_no_roster_read():
    calls = []
    class FakeService:
        def __init__(self, *args, **kwargs): calls.append("init")
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get_my_crew(self):
            calls.append("own")
            return OwnCrew("PRIVATE_OWN_ID")
        def get_crew_members(self):
            raise AssertionError("no roster read")
        def get_gcc_progress_response(self):
            calls.append("gcc")
            return _scores_payload()
    result = verify(player_id="PRIVATE_ACCOUNT", execute=True, gcc_live=True, gcc_only=True,
                    gcc_show_schema_keys=True, gcc_print_score_candidates=True,
                    services_factory=FakeService)
    assert calls == ["init", "own", "gcc"]
    assert result["gcc_live_response"]["status"] == "unverified_gcc_progress_scores_shape"
    text = _table(result)
    assert "UNVERIFIED SCORE/RANK" in text
    assert "37463129" in text
    assert "CREW STANDINGS NOT DECODED" in text
    assert "PRIVATE" not in text
    assert "own_crew_cc_rp_minus_ui_total" not in json.dumps(result)


def test_offline_scores_response_json_requires_no_login_and_has_nonzero_status(tmp_path, capsys):
    path = tmp_path / "scores.json"
    path.write_text(json.dumps(_scores_payload()))
    assert main(["--gcc-response-json", str(path), "--gcc-show-schema-keys", "--format", "json"]) == 3
    out = json.loads(capsys.readouterr().out)
    assert out["network_requests_allowed"] is False
    assert out["gcc_supplied_response"]["row_count"] == 4
    assert out["gcc_supplied_response"]["candidate_rows"] == []


def test_cli_optin_requires_gcc_source(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--gcc-print-score-candidates"])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        main(["--gcc-show-schema-keys"])
    assert e.value.code == 2
    assert main([]) == 0
    assert json.loads(capsys.readouterr().out)["network_requests"] == 0
