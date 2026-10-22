"""Dev17: deterministic evidence triage without network or implicit acceptance."""
import json
from datetime import datetime, timezone

import pytest

from csr2cdn._service_reads import StandingRange
from csr2cdn.bulk_review import BulkUIReference, review_bulk_evidence
from csr2cdn.crew_bulk_validation import bulk_report, main
from csr2cdn.game_labels import GameCarTranslations, GameVisualLibrary

RANGE = StandingRange(top=20, before=10, after=10, offset=0)


def fixture():
    own = {"crew_uid": "HIDE_CREW_UID", "members": 2, "crew_level": 5,
           "crew_garage_value": 900, "crew_logo": {"id": 1, "colour": "HIDE_COLOR"}}
    roster = {"crew_uid": "HIDE_CREW_UID", "scores": [
        {"player_uid": "HIDE_MEMBER_A", "name": "HIDE_PLAYER_NAME", "cc_contrib": 6,
         "garage_value": 400, "cash_donated": 7, "current_car": "TESTCAR_A",
         "car_pp": 800, "car_paint_id": 3, "car_decal_flag_id": 0,
         "facebook_id": "PRIVATE_FB"},
        {"player_uid": "HIDE_MEMBER_B", "name": "HIDE_PLAYER_NAME_2", "cc_contrib": 7,
         "garage_value": 500, "cash_donated": 0, "current_car": "TESTCAR_B",
         "car_pp": 799, "car_paint_id": 5, "car_decal_flag_id": 0},
    ]}
    common = {"scores": [
        {"crew_id": "HIDE_CREW_UID", "name": "HIDE_CREW_NAME", "rank": 101, "score": 13},
        {"crew_id": "OTHER_ID", "name": "HIDE_OTHER", "rank": 1, "score": 999},
    ]}
    expanded = {"scores": common["scores"] + [
        {"crew_id": "THIRD_ID", "name": "HIDE_THIRD", "rank": 2, "score": 950},
    ]}
    return own, roster, common, expanded


def labels():
    names = GameCarTranslations.from_manifest({"format": "csr2cdn.car-translations.v1", "records": [
        {"model_key": "TESTCAR_A", "SHORT": "A", "MEDIUM": "Car A", "LONG": "Test Car A"}
    ]})
    visuals = GameVisualLibrary.from_manifest({"format": "csr2cdn.visual-code-library.v1", "records": [
        {"model_key": "*", "slot": "paint", "code": 3, "name": "HIDE_PAINT_NAME",
         "source_library": "CarPaintLibrary"}
    ]})
    return names, visuals


def report(**kw):
    t = datetime(2026, 10, 17, 15, tzinfo=timezone.utc)
    return bulk_report(*fixture(), ranges=RANGE, member_read_utc=t, gcc_read_utc=t, **kw)


def test_review_is_included_but_does_not_automatically_accept_candidates():
    result = report()
    review = result["review"]
    assert review["status"] == "operator_review_required"
    assert review["automatic_feature_acceptance"] is False
    assert review["features"]["roster"]["status"] == "complete_against_server_count"
    assert review["features"]["crew_rp_vs_gcc"]["status"] == "consistent_candidate"
    assert review["features"]["gcc_expanded_range"]["status"] == "more_rows_observed_not_pagination_proof"
    assert review["features"]["gcc_expanded_range"]["full_pagination_verified"] is False
    assert review["features"]["crew_stats"]["fields_present"] > 0
    assert review["features"]["member_stats"]["fields_with_rows"] > 0
    assert review["features"]["vehicle_details"]["fields_with_rows"] > 0
    assert review["features"]["vehicle_appearance"]["fields_with_rows"] > 0
    assert review["features"]["translated_car_names"]["status"] == "not_supplied"
    assert review["features"]["visual_names"]["status"] == "not_supplied"


def test_game_labels_mark_only_exact_matches_and_keep_private_names_hidden():
    names, visuals = labels()
    result = report(game_names=names, game_visuals=visuals)
    review = result["review"]
    assert review["features"]["translated_car_names"]["status"] == "resolved_on_roster"
    assert review["features"]["translated_car_names"]["roster_rows_with_name"] == 1
    assert review["features"]["visual_names"]["status"] == "exact_matches_present"
    assert review["features"]["visual_names"]["codes_present"] == 4
    assert review["features"]["visual_names"]["codes_named"] == 1
    text = json.dumps(result)
    for hidden in ("HIDE_MEMBER", "HIDE_PLAYER", "PRIVATE_FB", "HIDE_CREW_UID",
                   "HIDE_CREW_NAME", "HIDE_PAINT_NAME", "TESTCAR_A"):
        assert hidden not in text


def test_ui_reference_agreement_is_operator_supplied_not_certified():
    ref = BulkUIReference.from_mapping({"format": "csr2cdn.crew-bulk-ui-reference.v1",
                                        "own_crew_rank": 101, "own_crew_score": 13,
                                        "crew_member_count": 2})
    review = report(ui_reference=ref)["review"]
    assert review["ui_reference_supplied"] is True
    assert review["ui_comparison"] == {"rank": "agrees", "score": "agrees", "member_count": "agrees"}
    assert review["ui_reference_temporal_comparability_verified"] is False
    assert review["automatic_feature_acceptance"] is False
    assert "HIDE" not in json.dumps(review)


def test_ui_mismatch_calls_for_review_without_failing_all_features():
    ref = BulkUIReference(own_crew_rank=102, own_crew_score=14, crew_member_count=3)
    result = report(ui_reference=ref)
    assert set(result["review"]["ui_comparison"].values()) == {"differs_review_snapshot_timing"}
    assert result["review"]["features"]["roster"]["status"] == "complete_against_server_count"


@pytest.mark.parametrize("bad", [
    {}, {"format": "wrong", "own_crew_rank": 5},
    {"format": "csr2cdn.crew-bulk-ui-reference.v1"},
    {"format": "csr2cdn.crew-bulk-ui-reference.v1", "own_crew_rank": True},
    {"format": "csr2cdn.crew-bulk-ui-reference.v1", "own_crew_score": -1},
    {"format": "csr2cdn.crew-bulk-ui-reference.v1", "crew_member_count": 31},
    {"format": "csr2cdn.crew-bulk-ui-reference.v1", "own_crew_rank": 0},
    {"format": "csr2cdn.crew-bulk-ui-reference.v1", "own_crew_rank": 5, "private": "HIDE"},
    ["HIDE"],
])
def test_invalid_ui_reference_rejected(bad):
    with pytest.raises(ValueError):
        BulkUIReference.from_mapping(bad)


def test_common_schema_failure_keeps_typed_report_and_marks_ui_unobserved():
    own, roster, _, expanded = fixture()
    result = bulk_report(own, roster, None, expanded, ranges=RANGE,
                         read_errors={"common": {"status": "http_error", "status_code": 502, "details": "suppressed"}},
                         ui_reference=BulkUIReference(own_crew_rank=101))
    review = result["review"]
    assert review["features"]["gcc_expanded_range"]["status"] == "decoded_no_common_comparison"
    assert review["features"]["crew_stats"]["fields_present"] > 0
    assert review["ui_comparison"]["rank"] == "not_observed"
    assert review["features"]["crew_rp_vs_gcc"]["status"] == "not_comparable"


def test_one_expanded_failure_does_not_drop_good_evidence():
    own, roster, common, _ = fixture()
    result = bulk_report(own, roster, common, None, ranges=RANGE,
                         read_errors={"experimental": {"status": "http_error", "status_code": 429, "details": "suppressed"}})
    assert result["status"] == "bulk_partial_read"
    assert result["review"]["features"]["gcc_expanded_range"]["status"] == "investigate_or_retry"
    assert result["review"]["features"]["member_stats"]["fields_with_rows"] > 0


def test_unchanged_window_does_not_claim_expansion():
    own, roster, common, _ = fixture()
    result = bulk_report(own, roster, common, common, ranges=RANGE)
    assert result["review"]["features"]["gcc_expanded_range"]["status"] == "no_extra_rows_observed"


def test_shared_rank_shift_is_non_atomic_not_false_failure():
    own, roster, common, expanded = fixture()
    expanded["scores"][0] = dict(expanded["scores"][0], rank=102)
    result = bulk_report(own, roster, common, expanded, ranges=RANGE)
    assert result["review"]["features"]["gcc_expanded_range"]["status"] == "shared_rows_changed_non_atomic"


def test_cli_reference_is_accepted_for_offline_fixtures(tmp_path, capsys):
    args = []
    for flag, content in zip(("--own-json", "--members-json", "--gcc-common-json", "--gcc-experimental-json"), fixture()):
        p = tmp_path / (flag[2:] + ".json")
        p.write_text(json.dumps(content))
        args.extend((flag, str(p)))
    p = tmp_path / "reference.json"
    p.write_text(json.dumps({"format": "csr2cdn.crew-bulk-ui-reference.v1", "own_crew_rank": 101}))
    assert main(args + ["--ui-reference-json", str(p)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["review"]["ui_comparison"]["rank"] == "agrees"
    assert printed["review"]["ui_comparison"]["score"] == "not_supplied"
    assert "HIDE_CREW_UID" not in json.dumps(printed)


def test_dry_run_has_review_sections_and_zero_requests(capsys):
    assert main([]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["network_requests"] == 0
    assert printed["planned_live_requests"] == 4
    assert "review" in printed["report_sections"]


def test_ui_reference_in_dry_run_rejected_without_reading(capsys):
    with pytest.raises(SystemExit):
        main(["--ui-reference-json", "not_a_real_path"])


def test_oversized_ui_reference_rejected_privately(tmp_path, capsys):
    data = fixture()
    args = []
    for flag, content in zip(("--own-json", "--members-json", "--gcc-common-json", "--gcc-experimental-json"), data):
        p = tmp_path / (flag[2:] + ".json")
        p.write_text(json.dumps(content))
        args += [flag, str(p)]
    p = tmp_path / "reference.json"
    p.write_text('Z' * 8200)
    assert main(args + ["--ui-reference-json", str(p)]) == 3
    printed = json.loads(capsys.readouterr().out)
    assert printed == {"status": "bulk_probe_unavailable", "details": "suppressed"}


def test_bad_reference_preflight_blocks_live_requests(tmp_path, monkeypatch, capsys):
    """The operator must not spend four reads on invalid local evidence."""
    bad = tmp_path / "invalid_reference.json"
    bad.write_text(json.dumps({"format": "csr2cdn.crew-bulk-ui-reference.v1",
                               "own_crew_rank": True}))
    def unexpected(*args, **kwargs):
        raise AssertionError("live service or prompt called before preflight")
    monkeypatch.setattr("csr2cdn.crew_bulk_validation.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("csr2cdn.crew_bulk_validation.getpass.getpass", unexpected)
    assert main(["--execute", "--ui-reference-json", str(bad)], services_factory=unexpected) == 3
    assert json.loads(capsys.readouterr().out) == {"status": "bulk_probe_unavailable", "details": "suppressed"}


def test_bad_visual_source_preflight_blocks_live_requests(monkeypatch, capsys):
    def unexpected(*args, **kwargs):
        raise AssertionError("auth read started")
    monkeypatch.setattr("csr2cdn.crew_bulk_validation.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("csr2cdn.crew_bulk_validation.getpass.getpass", unexpected)
    assert main(["--execute", "--visual-asset-bundle", "/file/not/present.ASTC.000"],
                services_factory=unexpected) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "bulk_probe_unavailable"
