"""Dev25 source audits and bounded gap diagnostics require no original game data."""
from __future__ import annotations

import json

import pytest

from csr2cdn import AssetDatabase, GameVisualLibrary, VisualCodeName
from csr2cdn.crew_optional_data import CrewOptionalSnapshot
from csr2cdn.service_models import OwnCrew, CrewMembers
from csr2cdn._research.dev25_visual_forensics import (
    audit_tnr_eligibility_source, assess_color_evidence, assess_wheel_evidence,
    diagnose_paint_interior_gaps, main)
from test_dev071_dev23_tnr_native_libraries import synthetic_tnr_asset, SPECS

CREW_SECRET = 'SENSITIVE_CREW_IDENTIFIER'


def inputs():
    own = {'crew_uid': CREW_SECRET, 'members': 3}
    members = {'crew_uid': CREW_SECRET, 'scores': [
        {'player_uid': 'PRIVATE_A', 'name': 'SECRET_FIRST',
         'current_car': 'Mazda_RX8TNR0_2008', 'car_paint_id': 1000001,
         'car_interior_id': 3001111, 'car_calliper_id': 1000001,
         'car_wheel_name': 'SECRET_STRING_1', 'car_decal_number_color_id': 9},
        {'player_uid': 'PRIVATE_B', 'name': 'SECRET_SECOND',
         'current_car': 'Normal_Car_2024', 'car_paint_id': 88,
         'car_interior_id': 3002222, 'car_calliper_id': 8,
         'car_wheel_name': 'Secret*Wheel', 'car_decal_number_color_id': 9},
        {'player_uid': 'PRIVATE_C', 'name': 'SECRET_THIRD',
         'current_car': 'Honda_CivicEGTNR2_1995', 'car_paint_id': 777,
         'car_interior_id': 7, 'car_calliper_id': 1000001,
         'car_wheel_name': 'SECRET_STRING_2'},
    ]}
    snapshot = CrewOptionalSnapshot.from_reads(
        OwnCrew.from_response(own), CrewMembers.from_response(CREW_SECRET, members))
    specs = [('paint', 42, 1000001), ('interior', 7, 1000001), ('calliper', 8, 1000001)]
    rows = []
    for slot, normal, tuner in specs:
        name = {'paint': 'CarPaintLibrary', 'interior': 'CarInteriorLibrary',
                'calliper': 'CarCalliperLibrary'}[slot]
        tname = {'paint': 'CarTunerStarsPaintLibrary', 'interior': 'CarTunerStarsInteriorLibrary',
                 'calliper': 'CarTunerStarsCalliperLibrary'}[slot]
        rows.extend([VisualCodeName('*', slot, normal, 'SECRET_LABEL', name),
                     VisualCodeName('*', slot, tuner, 'SECRET_TNR_LABEL', tname)])
    rows.append(VisualCodeName('*', 'color', 9, 'SECRET_COLOR', 'CarColorLibrary'))
    rows.append(VisualCodeName('*', 'tuner_rim', 5, 'SECRET_STRING_1', 'CarTunerStarsRimLibrary'))
    library = GameVisualLibrary(tuple(rows))
    db = AssetDatabase.from_json([{'version': '33695'}, [
        {'code': 'Mazda_RX8TNR0_2008_Wheel_Secret', 'version': '1'},
        {'code': 'Normal_Car_2024_Wheel_01', 'version': '1'},
        {'code': 'unrelated_Wheel_01', 'version': '1'},
    ]])
    return snapshot, db, library, own, members


@pytest.mark.parametrize('library', list(SPECS))
def test_include_to_car_source_audit_retains_decoder_verification_and_has_hard_gate(library):
    raw = synthetic_tnr_asset(library)
    report = audit_tnr_eligibility_source(raw, library=library)
    assert report['primary_records'] == 24
    assert report['category_all_records'] == 23
    assert report['category_model_specific_records'] == 1
    assert report['include_to_car_integer_histogram'] == {'0': 24}
    assert report['trusted_car_specific_eligibility'] is False
    assert report['supplementary_compatibility_rules_verified'] is False
    assert 'Mazda' not in json.dumps(report)


def test_bad_source_rejected_without_falling_back_to_guessed_eligibility():
    with pytest.raises(ValueError):
        audit_tnr_eligibility_source(synthetic_tnr_asset('CarTunerStarsPaintLibrary'),
                                    library='CarPaintLibrary')
    with pytest.raises(ValueError):
        audit_tnr_eligibility_source(synthetic_tnr_asset('CarTunerStarsPaintLibrary', duplicate=True),
                                    library='CarTunerStarsPaintLibrary')


def test_source_id_diagnostics_default_private_opt_in_exact_and_no_cross_field_disclosure():
    snapshot, db, library, _, _ = inputs()
    hidden = diagnose_paint_interior_gaps(snapshot, library)
    tnr_paint = hidden['by_slot_and_cohort']['paint']['tnr_model_syntax']
    assert tnr_paint['unresolved'] == 1
    assert tnr_paint['distinct_numeric_ids'] == 1
    assert 'numeric_ids' not in tnr_paint
    revealed = diagnose_paint_interior_gaps(snapshot, library, show_numeric_ids=True)
    assert revealed['by_slot_and_cohort']['paint']['tnr_model_syntax']['numeric_ids'] == [
        {'id': 777, 'reason': 'not_matched_in_six_sources', 'occurrences': 1}]
    assert revealed['by_slot_and_cohort']['interior']['tnr_model_syntax']['numeric_ids'] == [
        {'id': 3001111, 'reason': 'not_matched_in_six_sources', 'occurrences': 1}]
    assert revealed['by_slot_and_cohort']['paint']['other_or_unknown_model']['numeric_ids'] == [
        {'id': 88, 'reason': 'not_matched_in_six_sources', 'occurrences': 1}]
    assert revealed['by_slot_and_cohort']['interior']['other_or_unknown_model']['numeric_ids'] == [
        {'id': 3002222, 'reason': 'not_matched_in_six_sources', 'occurrences': 1}]
    for report in (hidden, revealed):
        text = json.dumps(report)
        for secret in ('PRIVATE_', CREW_SECRET, 'SECRET_', 'Mazda_RX8', 'Honda_Civic', 'Normal_Car',
                       'SECRET_COLOR', 'SECRET_TNR_LABEL'):
            assert secret not in text
    assert '9' not in json.dumps(revealed)  # decal color code is excluded entirely


def test_no_wheel_or_color_promotion_and_only_aggregate_encoding():
    snapshot, db, library, _, _ = inputs()
    wheels = assess_wheel_evidence(snapshot, db, library)
    assert wheels['cohorts']['tnr_model_syntax']['members'] == 2
    assert wheels['cohorts']['tnr_model_syntax']['model_wheel_asset_found'] == 1
    assert wheels['cohorts']['other_or_unknown_model']['model_wheel_asset_found'] == 1
    assert wheels['cohorts']['tnr_model_syntax']['tuner_rim_name_overlap_candidate_only'] == 1
    assert wheels['model_wheel_asset_is_roster_mapping'] is False
    assert wheels['tuner_stars_rim_is_universal_dictionary'] is False
    assert 'SECRET_' not in json.dumps(wheels)
    colors = assess_color_evidence(snapshot, library)
    assert colors['slots']['decal_number_color']['palette_id_overlap_candidate_only'] == 2
    assert colors['slots']['decal_number_color']['trusted_name_mappings'] == 0
    assert colors['roster_palette_relationship_verified'] is False
    assert 'SECRET_' not in json.dumps(colors)


def test_empty_cli_dry_run_and_offline_source_only(tmp_path, capsys):
    assert main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['network_requests'] == 0
    assert report['status'] == 'dev25_dry_run_no_inputs'
    file = tmp_path / 'CarTunerStarsPaintLibrary.ASTC.412'
    file.write_bytes(synthetic_tnr_asset('CarTunerStarsPaintLibrary'))
    assert main(['--visual-asset-bundle', str(file)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'dev25_source_only_no_roster'
    assert len(result['tnr_eligibility_source_audits']) == 1
    assert result['candidate_names_trusted'] is False


def test_replay_refuses_missing_six_original_libraries_without_echoing_secrets(tmp_path, capsys):
    snapshot, db, library, own, members = inputs()
    dbp = tmp_path / 'asset_database'; dbp.write_text(db.dumps())
    ownp = tmp_path / 'own.json'; ownp.write_text(json.dumps(own))
    memp = tmp_path / 'members.json'; memp.write_text(json.dumps(members))
    bad = tmp_path / 'BAD_LIBRARY.ASTC.123'; bad.write_text('sensitive')
    reportp = tmp_path / 'report.json'
    assert main(['--visual-asset-bundle', str(bad), '--asset-database', str(dbp),
                 '--own-json', str(ownp), '--members-json', str(memp),
                 '--output', str(reportp)]) == 3
    assert not reportp.exists()
    assert json.loads(capsys.readouterr().out)['status'] == 'offline_source_investigation_unavailable'


def test_complete_offline_replay_zero_network_opt_in_and_refuse_overwrite(tmp_path, monkeypatch, capsys):
    snapshot, db, library, own, members = inputs()
    dbp = tmp_path / 'asset_database'; dbp.write_text(db.dumps())
    ownp = tmp_path / 'own.json'; ownp.write_text(json.dumps(own))
    memp = tmp_path / 'members.json'; memp.write_text(json.dumps(members))
    monkeypatch.setattr('csr2cdn._research.dev25_visual_forensics.load_visual_libraries_unityfs', lambda _: library)
    reportp = tmp_path / 'report.json'
    args = ['--visual-asset-bundle', 'mock-sources-not-shared', '--asset-database', str(dbp),
            '--own-json', str(ownp), '--members-json', str(memp),
            '--show-unmatched-paint-interior-ids', '--output', str(reportp)]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['gameplay_read_count'] == 0
    assert result['comparison']['totals']['paint']['new_tnr_id_candidates'] == 1
    assert result['paint_interior_gaps']['numeric_id_disclosure_opt_in'] is True
    assert json.loads(reportp.read_text()) == result
    with pytest.raises(SystemExit) as refused:
        main(args)
    assert refused.value.code == 2
    assert json.loads(reportp.read_text()) == result  # preserved, not overwritten
    capsys.readouterr()
