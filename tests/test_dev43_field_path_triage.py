"""Dev43 source-only lexical triage tests; all data below synthetic."""
import json
import os
from pathlib import Path

import pytest

from csr2cdn._research.dev41_field_source_provenance import make_audit as dev41_audit
from csr2cdn._research.dev43_field_path_triage import analyze, main, _degree


def setup_paths(tmp_path):
    provenance = tmp_path / 'dev41.json'
    provenance.write_text(json.dumps(dev41_audit()), encoding='utf-8')
    folder = tmp_path / 'cache'
    folder.mkdir()
    (folder / 'CarCustomizationParameters.meta').write_text(json.dumps({
        'CarCustomizationParameters': {
            'Items': [{'CarPaintID': 15, 'PaintID': 0,
                       'RepaintHint': 'MUST_NOT_MATCH',
                       'car_wheel_name': 'PRIVATE_WHEEL',
                       'Other': {'WheelColour': 'SECRETCOLOR',
                                 'CarPaintID': 'wrong type', 'CalliperID': 16}}]
        }
    }), encoding='utf-8')
    return provenance, folder


def test_no_cache_lexical_is_not_promotion(tmp_path):
    prov, _ = setup_paths(tmp_path)
    result, priv = analyze(provenance_report=prov)
    assert result['analysis_incomplete_without_local_metadata'] is True
    assert len(result['wire_field_candidates']) == 14
    assert all(x['number_of_candidate_paths_in_sample'] == 0 for x in result['wire_field_candidates'].values())
    assert result['network_requests'] == result['gameplay_read_count'] == 0
    assert priv['candidate_paths_by_wire_field']['car_paint_id'] == []


def test_synthetic_exact_alias_related_and_type_agreement(tmp_path):
    prov, cache = setup_paths(tmp_path)
    report, priv = analyze(provenance_report=prov, cache_dir=cache)
    paint = report['wire_field_candidates']['car_paint_id']
    assert paint['candidate_key_path_counts_by_lexical_grade'] == {
        'exact_wire_key_spelling': 2, 'without_car_prefix_spelling': 1,
    }
    assert paint['candidate_path_type_agreement_counts_by_lexical_grade'] == {
        'exact_wire_key_spelling': 1, 'without_car_prefix_spelling': 1,
    }
    assert paint['candidate_source_blocks'] == ['CarCustomizationParameters']
    assert report['verified_roster_to_source_joins'] == 0
    blob = json.dumps(report)
    for private in ('CarPaintID', 'PaintID', 'PRIVATE_WHEEL', 'SECRETCOLOR', 'MUST_NOT_MATCH'):
        assert private not in blob
    private_blob = json.dumps(priv)
    assert 'CarPaintID' in private_blob
    assert 'PRIVATE_WHEEL' not in private_blob
    assert 'SECRETCOLOR' not in private_blob
    assert 'MUST_NOT_MATCH' not in private_blob
    assert priv['contains_source_values'] is False
    assert _degree('car_paint_id', '$.Items[].RepaintHint') is None
    assert _degree('car_paint_id', '$.Items[].CarPaintID') == 'exact_wire_key_spelling'
    assert _degree('car_paint_id', '$.Items[].PaintID') == 'without_car_prefix_spelling'
    assert _degree('car_wheel_name', '$.WheelColour') == 'related_key_token_only'


def test_cli_outputs_and_overwrite_guard(tmp_path):
    prov, cache = setup_paths(tmp_path)
    red = tmp_path / 'redacted.json'
    private = tmp_path / 'private.json'
    assert main(['--provenance-report', str(prov), '--metadata-cache-dir', str(cache),
                 '--output', str(red), '--private-candidate-paths-output', str(private)]) == 0
    assert json.loads(red.read_text())['native_schema_decoded'] is False
    assert 'CarPaintID' in private.read_text()
    if os.name != 'nt':
        assert (private.stat().st_mode & 0o077) == 0
    with pytest.raises(SystemExit):
        main(['--provenance-report', str(prov), '--output', str(red)])
    with pytest.raises(SystemExit):
        main(['--provenance-report', str(prov), '--output', str(tmp_path / 'same.json'),
              '--private-candidate-paths-output', str(tmp_path / 'same.json')])


def test_reject_modified_provenance_type_inventory(tmp_path):
    prov, cache = setup_paths(tmp_path)
    obj = json.loads(prov.read_text())
    obj['wire_fields'][0]['wire_type'] = 'string'
    prov.write_text(json.dumps(obj))
    with pytest.raises(ValueError, match='wire types'):
        analyze(provenance_report=prov, cache_dir=cache)


def test_private_cache_symlink_rejection(tmp_path):
    prov, cache = setup_paths(tmp_path)
    target = cache / 'CarCustomizationParameters.meta'
    content = tmp_path / 'meta'
    target.rename(content)
    try:
        target.symlink_to(content)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks unavailable')
    with pytest.raises(ValueError, match='symlink'):
        analyze(provenance_report=prov, cache_dir=cache)


def test_sample_truncation_is_reported(tmp_path):
    prov, cache = setup_paths(tmp_path)
    (cache / 'CarCustomizationParameters.meta').write_text(json.dumps({
        'Items': [{'CarPaintID': i} for i in range(90)]
    }))
    report, _ = analyze(provenance_report=prov, cache_dir=cache)
    assert 'CarCustomizationParameters' in report['sampled_or_truncated_blocks']
    assert report['wire_field_candidates']['car_paint_id']['number_of_candidate_paths_in_sample'] == 1


def test_invalid_lexical_key_path():
    with pytest.raises(ValueError):
        _degree('car_paint_id', 'CarPaintID')
