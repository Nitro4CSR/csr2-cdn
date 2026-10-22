"""Dev18: privacy-preserving post-live counts triage and guarded dispositions."""
import json

import pytest

from csr2cdn.bulk_gap_triage import main, triage_bulk_report
from csr2cdn.customization_evidence import SLOT_FIELDS


def _report():
    values = {slot: 0 for slot in SLOT_FIELDS}
    good = dict(values)
    for slot, p, r in (
        ("wheel", 29, 0), ("decal_number_color", 8, 0),
        ("decal_number_shape_color", 8, 0), ("decal_number_zone", 8, 0),
        ("paint", 29, 20), ("interior", 29, 26), ("calliper", 29, 26),
        ("livery", 16, 16), ("livery_zones_set", 16, 16),
        ("decal_flag", 1, 1), ("decal_number", 7, 7),
        ("decal_numberplate_style", 12, 12),
    ):
        values[slot] = p
        good[slot] = r
    return {"optional": {"member_rows": 29, "PRIVATE_ID": "NEVER_PRINT"},
            "game_labels": {"visual_codes_present": values,
                            "visual_codes_resolved": good,
                            "member_labels": [{"secret": "LEAK_BAD"}]},
            "private_id": "UNSAFE_ACCOUNT"}


def test_report_matches_live_summary_without_any_private_values():
    got = triage_bulk_report(_report())
    assert got["cosmetics"]["present"] == 192
    assert got["cosmetics"]["resolved"] == 124
    assert got["cosmetics"]["unresolved"] == 68
    assert got["cosmetics"]["pending_join_investigation"] == 53
    assert got["cosmetics"]["other_source_mapping_gaps"] == 15
    assert got["cosmetics"]["coverage_percent"] == 64.6
    assert got["cosmetics"]["slots"][0]["slot"] == "wheel"
    assert not got["automatic_pruning"]
    assert got["arbitrary_gcc_pagination_verified"] is False
    data = json.dumps(got)
    for marker in ("PRIVATE_ID", "NEVER_PRINT", "LEAK_BAD", "UNSAFE_ACCOUNT"):
        assert marker not in data


def test_missing_slots_are_reported_as_no_observation():
    r = _report()
    r["game_labels"]["visual_codes_present"]["decal_flag"] = 0
    r["game_labels"]["visual_codes_resolved"]["decal_flag"] = 0
    g = triage_bulk_report(r)
    flag = next(x for x in g["cosmetics"]["slots"] if x["slot"] == "decal_flag")
    assert flag["state"] == "not_present"


@pytest.mark.parametrize("mutation", [
    lambda r: r.pop("optional"),
    lambda r: r["optional"].update(member_rows=True),
    lambda r: r["optional"].update(member_rows=31),
    lambda r: r["game_labels"].pop("visual_codes_present"),
    lambda r: r["game_labels"]["visual_codes_resolved"].update(wheel=30),
    lambda r: r["game_labels"]["visual_codes_resolved"].update(paint=-1),
    lambda r: r["game_labels"]["visual_codes_present"].update(wheel="29"),
    lambda r: r["game_labels"]["visual_codes_present"].update(totally_new=1),
    lambda r: r["game_labels"]["visual_codes_resolved"].pop("paint"),
])
def test_invalid_counts_fail_closed(mutation):
    r = _report()
    mutation(r)
    with pytest.raises(ValueError):
        triage_bulk_report(r)


def test_default_dry_run_is_zero_network(capsys):
    assert main([]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["network_requests"] == 0


def test_local_file_review_redacts_any_unrelated_values(tmp_path, capsys):
    p = tmp_path / "report.json"
    p.write_text(json.dumps(_report()))
    assert main([str(p)]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["cosmetics"]["unresolved"] == 68
    assert "UNSAFE_ACCOUNT" not in json.dumps(r)


@pytest.mark.parametrize("bad", ["{invalid", "not JSON", '"PRIVATE_ID"'])
def test_bad_files_do_not_reflect_contents(tmp_path, capsys, bad):
    p = tmp_path / "private.json"
    p.write_text(bad)
    assert main([str(p)]) == 2
    out = capsys.readouterr().out
    assert "PRIVATE_ID" not in out
    assert json.loads(out)["network_requests"] == 0


def test_absent_all_codes_does_not_divide_by_zero():
    r = _report()
    r["game_labels"]["visual_codes_present"] = {k: 0 for k in SLOT_FIELDS}
    r["game_labels"]["visual_codes_resolved"] = {k: 0 for k in SLOT_FIELDS}
    out = triage_bulk_report(r)
    assert out["cosmetics"]["coverage_percent"] is None


def test_other_features_are_not_promoted_from_cosmetics_only():
    decision = triage_bulk_report(_report())["recommended_review"]
    assert decision["gcc"] == "insufficient_gcc_evidence"
    assert decision["crew_rp"] == "requires_comparable_gcc_read"
    assert decision["car_names"] == "check_translation_roster_coverage"


def test_contemporaneous_overlap_and_crew_rp_can_be_retained_as_candidates():
    r = _report()
    r["game_labels"]["car_names_resolved"] = 29
    r["gcc"] = {
        "common": {"status": "decoded_common_gcc", "rows": 21,
                   "roster_gcc_comparable": True, "roster_gcc_delta": 0},
        "experimental": {"status": "decoded_exploratory_gcc_range_unverified", "rows": 41},
        "common_vs_experimental": {"shared_crew_ids": 21, "matching_rank_and_score": 21,
                                   "changed_rank_or_score": 0},
        "range_evidence": {"more_rows_than_common": True},
    }
    decision = triage_bulk_report(r)["recommended_review"]
    assert decision["gcc"] == "keep_bounded_expansion_candidate_verify_offset_separately"
    assert decision["crew_rp"] == "retain_guarded_comparison"
    assert decision["car_names"] == "retain_exact_translations"


def test_mismatching_overlap_must_not_retain_expanded_gcc():
    r = _report()
    r["gcc"] = {
        "common": {"status": "decoded_common_gcc", "rows": 21},
        "experimental": {"status": "decoded_exploratory_gcc_range_unverified", "rows": 41},
        "common_vs_experimental": {"shared_crew_ids": 21, "matching_rank_and_score": 20,
                                   "changed_rank_or_score": 1},
        "range_evidence": {"more_rows_than_common": True},
    }
    assert triage_bulk_report(r)["recommended_review"]["gcc"] == "insufficient_gcc_evidence"
