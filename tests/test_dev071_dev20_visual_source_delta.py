"""Dev20 offline source-version comparison and opt-in missing-code recheck."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from csr2cdn import (GameVisualLibrary, VisualCodeName, compare_visual_sources,
                     recheck_visual_missing_ids, VisualSourceDelta, VisualMissingIDRecheck)
from csr2cdn.visual_source_delta import main

SECRET = "private-user-model-001"


def lib(*items):
    return GameVisualLibrary(tuple(VisualCodeName(model_key=model, slot=slot, code=code,
              name=name, source_library="fixture", names=names)
              for model, slot, code, name, names in items))


def old_lib():
    return lib(("*", "paint", 1, "red", ()),
               ("*", "paint", 2, "blue", ()),
               ("*", "interior", 4, "zone one", ("zone one", "zone two")),
               ("*", "color", 3, "color three", ()),
               ("*", "tuner_rim", 1000001, "AA", ()))


def new_lib():
    return lib(("*", "paint", 1, "deep red", ()),
               ("*", "paint", 3, "green", ()),
               ("*", "interior", 4, "zone one", ("zone one", "renamed zone two")),
               ("*", "interior", 9, "new", ("new", "other")),
               ("*", "color", 3, "color three", ()),
               ("*", "color", 6, "palette candidate", ()),
               ("*", "tuner_rim", 1000001, "AB", ()))


def unmatched():
    return {
        "status": "offline_visual_gap_diagnostics_candidate_only",
        "numeric_id_disclosure_opt_in": True,
        "member_names_or_ids_included": False,
        "slots": {
            "paint": {"unresolved_numeric_ids": [
                {"id": 3, "occurrences": 4}, {"id": 9, "occurrences": 2},
                {"id": 2, "occurrences": 1}]},
            "interior": {"unresolved_numeric_ids": [{"id": 9, "occurrences": 2}]},
            "wheel": {"unresolved_numeric_ids": []},
            "decal_number_color": {"unresolved_numeric_ids": [{"id": 6, "occurrences": 2}]},
        },
    }


def test_version_deltas_all_classes():
    d = compare_visual_sources(old_lib(), new_lib())
    assert isinstance(d, VisualSourceDelta)
    assert d.paint.before == 2 and d.paint.after == 2
    assert d.paint.added == d.paint.removed == d.paint.label_changed == 1
    assert d.interior.zone_names_changed == 1 and d.interior.label_changed == 0
    assert d.interior.added == 1 and d.interior.unchanged == 0
    assert d.color.added == 1 and d.color.unchanged == 1
    assert d.tuner_rim.label_changed == 1
    assert d.added_total == 3 and d.removed_total == 1
    assert d.as_dict()["join_evidence_added"] is False


def test_identical_and_reordered_sources_count_equal():
    old = old_lib()
    diff = compare_visual_sources(old, GameVisualLibrary(tuple(reversed(old.records))))
    assert diff.added_total == diff.removed_total == 0
    assert all(s.label_changed == s.zone_names_changed == 0 for s in diff.slots.values())
    assert all(s.unchanged == s.before for s in diff.slots.values())


def test_provenance_hash_not_name_delta():
    original = old_lib()
    changed = GameVisualLibrary(tuple(replace(r, source_hash="0" * 32,
               source_sha256="a" * 64) for r in original.records))
    assert compare_visual_sources(original, changed).paint.unchanged == 2


def test_change_exact_model_scope_not_merged():
    before = lib((SECRET, "paint", 1, "named", ()))
    after = lib(("*", "paint", 1, "named", ()))
    d = compare_visual_sources(before, after)
    assert d.paint.added == 1 and d.paint.removed == 1


def test_explicit_numeric_recheck_only_proven_global_ids():
    r = recheck_visual_missing_ids(unmatched(), old_lib(), new_lib())
    assert isinstance(r, VisualMissingIDRecheck)
    assert r.paint.distinct_ids == 3 and r.paint.occurrences == 7
    assert r.paint.newly_available_ids == 1 and r.paint.newly_available_occurrences == 4
    assert r.paint.still_missing_ids == 2 and r.paint.still_missing_occurrences == 3
    assert r.paint.already_available_ids == 1
    assert r.interior.newly_available_ids == 1
    assert "wheel" not in r.as_dict()["slots"]
    assert "decal_number_color" not in r.as_dict()["slots"]
    assert r.as_dict()["new_source_matches_are_candidates_not_ui_verification"]


def test_model_specific_candidate_is_not_global_lookup():
    after = lib((SECRET, "paint", 3, "matching only for model", ()))
    r = recheck_visual_missing_ids(unmatched(), old_lib(), after)
    assert r.paint.newly_available_ids == 0
    assert r.paint.still_missing_ids == 3
    assert r.as_dict()["model_specific_joins_not_checked"]


def test_zero_numeric_id_supported():
    report = unmatched()
    report["slots"]["paint"]["unresolved_numeric_ids"] = [{"id": 0, "occurrences": 2}]
    r = recheck_visual_missing_ids(report, lib(), lib(("*", "paint", 0, "zero", ())))
    assert r.paint.newly_available_occurrences == 2


def test_no_opt_in_no_recheck_even_when_rows_present():
    report = unmatched()
    report["numeric_id_disclosure_opt_in"] = False
    with pytest.raises(ValueError):
        recheck_visual_missing_ids(report, old_lib(), new_lib())


@pytest.mark.parametrize("edit", [
    lambda x: x.update(status="other"),
    lambda x: x.update(member_names_or_ids_included=True),
    lambda x: x.update(numeric_id_disclosure_opt_in="yes"),
    lambda x: x.update(slots=None),
    lambda x: x["slots"].update(paint={"unresolved_numeric_ids": None}),
    lambda x: x["slots"]["paint"].update(unresolved_numeric_ids=[{"id": True, "occurrences": 1}]),
    lambda x: x["slots"]["paint"].update(unresolved_numeric_ids=[{"id": 1, "occurrences": 0}]),
    lambda x: x["slots"]["paint"].update(unresolved_numeric_ids=[{"id": 1, "occurrences": 31}]),
    lambda x: x["slots"]["paint"].update(unresolved_numeric_ids=[{"id": -1, "occurrences": 1}]),
    lambda x: x["slots"].update(secret_slot={"unresolved_numeric_ids": []}),
    lambda x: x["slots"]["paint"].update(unresolved_numeric_ids=[{"id": 1, "occurrences": 1}] * 2),
])
def test_bad_diagnostic_inputs_rejected(edit):
    data = unmatched()
    edit(data)
    with pytest.raises(ValueError):
        recheck_visual_missing_ids(data, old_lib(), new_lib())


def test_nested_bulk_diagnostic_supported():
    doc = {"user_name": SECRET, "visual_gap_diagnostics": unmatched()}
    r = recheck_visual_missing_ids(doc, old_lib(), new_lib())
    assert r.paint.newly_available_ids == 1
    assert SECRET not in json.dumps(r.as_dict())


def test_privacy_default_and_opt_in_output():
    report = unmatched()
    report["private_account"] = SECRET
    output = json.dumps({"diff":compare_visual_sources(old_lib(), new_lib()).as_dict(),
                         "recheck":recheck_visual_missing_ids(report,old_lib(),new_lib()).as_dict()})
    for forbidden in (SECRET, "deep red", '"name": "red"', '"name": "new"', '"id":', "AA", '"model_key":'):
        assert forbidden not in output


def test_duplicate_records_rejected_even_if_direct_constructed():
    old = old_lib()
    with pytest.raises(ValueError):
        compare_visual_sources(GameVisualLibrary(old.records + old.records[:1]), new_lib())


def test_wrong_types_and_invalid_record_rejected():
    with pytest.raises(TypeError): compare_visual_sources(None, new_lib())
    with pytest.raises(ValueError): compare_visual_sources(GameVisualLibrary(("invalid",)), new_lib())
    with pytest.raises(ValueError): compare_visual_sources(GameVisualLibrary((replace(old_lib().records[0],code=True),)),new_lib())


def test_cli_dry_run_and_no_network(capsys):
    assert main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["network_requests"] == 0 and result["mode"] == "dry_run"


def test_cli_requires_both_generations_before_reading(capsys):
    with pytest.raises(SystemExit) as ex:
        main(["--after-bundle", "private_file.asset"])
    assert ex.value.code == 2


def test_cli_rejects_bad_paths_without_disclosing(capsys):
    assert main(["--before-bundle", SECRET, "--after-bundle", SECRET]) == 2
    output = capsys.readouterr().out
    assert SECRET not in output and "suppressed" in output


def test_no_network_or_file_writes_for_typed_apis():
    with patch.object(Path, "write_text", side_effect=AssertionError("disk write forbidden")):
        assert compare_visual_sources(old_lib(), new_lib()).added_total == 3
        assert recheck_visual_missing_ids(unmatched(), old_lib(), new_lib()).paint.distinct_ids == 3


def test_unknown_slot_does_not_leak_through_report():
    unsafe = lib(("*", SECRET, 1, "public", ()))
    with pytest.raises(ValueError):
        compare_visual_sources(unsafe, new_lib())
