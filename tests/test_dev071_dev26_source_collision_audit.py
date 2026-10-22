"""Dev26: forensic collision retention only; production matching untouched."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from csr2cdn.game_labels import GameVisualLibrary, VisualCodeName
from csr2cdn.visual_library_bundle import VisualLibrarySourceError
from csr2cdn._research.dev25_visual_forensics import (audit_comparison_source_catalog,
    load_visual_libraries_unityfs as load_forensics,
    diagnose_paint_interior_gaps)
from csr2cdn.tnr_visual_probe import assess_tnr_resolution_comparison
from test_dev071_dev24_tnr_resolution_comparison import sample


STANDARD = 'CarPaintLibrary'
TUNER = 'CarTunerStarsPaintLibrary'


def _fake_bundles(monkeypatch, tmp_path, library_rows):
    from csr2cdn._research import dev25_visual_forensics as investigation
    def native_file(path):
        name = Path(path).name.split('.')[0]
        return GameVisualLibrary(tuple(library_rows[name]))
    monkeypatch.setattr(investigation, 'load_visual_unityfs', native_file)
    return [tmp_path / (name + '.ASTC.123') for name in library_rows]


def test_cross_standard_tnr_id_collision_is_reported_not_auto_resolved(monkeypatch, tmp_path):
    snap, _, base, _, _ = sample()
    # Ordinary Dev24 cross-library collision case, validated per source.
    per_source = {}
    for record in base.records:
        per_source.setdefault(record.source_library, []).append(record)
    per_source[TUNER].append(VisualCodeName('*', 'paint', 9, 'PRIVATE_COLLIDING_LABEL', TUNER))
    paths = _fake_bundles(monkeypatch, tmp_path, per_source)
    joined = load_forensics(paths)
    evidence = audit_comparison_source_catalog(joined)
    assert evidence['standard_tnr_duplicate_ids_by_slot']['paint'] == 1
    assert evidence['source_catalog_has_cross_source_id_collisions'] is True
    assert evidence['general_purpose_resolution_from_merged_catalog_safe'] is False
    comparison = assess_tnr_resolution_comparison(snap, joined)
    assert comparison['totals']['paint']['ambiguous_cross_library_ids'] == 1
    gaps = diagnose_paint_interior_gaps(snap, joined)
    assert gaps['by_slot_and_cohort']['paint']['tnr_model_syntax']['unresolved'] == 1
    assert gaps['by_slot_and_cohort']['paint']['tnr_model_syntax']['reasons'] == {
        'ambiguous_cross_library': 1}
    text = json.dumps(evidence) + json.dumps(gaps)
    assert 'PRIVATE_' not in text and 'PRIVATE_COLLIDING_LABEL' not in text
    assert '"id"' not in text


def test_rejects_duplicate_source_argument(monkeypatch, tmp_path):
    rows = {STANDARD: (VisualCodeName('*', 'paint', 1, 'A', STANDARD),)}
    paths = _fake_bundles(monkeypatch, tmp_path, rows)
    with pytest.raises(VisualLibrarySourceError, match='duplicate original'):
        load_forensics(paths * 2)


def test_rejects_unrelated_sources_sharing_same_id(monkeypatch, tmp_path):
    unrelated = 'CarWrapLibrary'
    rows = {
        STANDARD: (VisualCodeName('*', 'paint', 12, 'A', STANDARD),),
        unrelated: (VisualCodeName('*', 'paint', 12, 'B', unrelated),),
    }
    paths = _fake_bundles(monkeypatch, tmp_path, rows)
    with pytest.raises(VisualLibrarySourceError, match='unsupported duplicate'):
        load_forensics(paths)


def test_no_false_collision_for_disjoint_codes(monkeypatch, tmp_path):
    rows = {
        STANDARD: (VisualCodeName('*', 'paint', 12, 'A', STANDARD),),
        TUNER: (VisualCodeName('*', 'paint', 1000001, 'B', TUNER),),
    }
    result = load_forensics(_fake_bundles(monkeypatch, tmp_path, rows))
    audit = audit_comparison_source_catalog(result)
    assert audit['standard_tnr_duplicate_ids_by_slot'] == {'paint': 0}
    assert audit['source_catalog_has_cross_source_id_collisions'] is False
    assert audit['ui_appearance_verified'] is False


def test_wrong_source_identity_is_rejected(monkeypatch, tmp_path):
    rows = {STANDARD: (VisualCodeName('*', 'paint', 12, 'B', TUNER),)}
    with pytest.raises(VisualLibrarySourceError, match='source name'):
        load_forensics(_fake_bundles(monkeypatch, tmp_path, rows))


def test_offline_source_only_cli_reports_catalog_without_ids(tmp_path, capsys):
    from test_dev071_dev23_tnr_native_libraries import synthetic_tnr_asset
    from csr2cdn._research.dev25_visual_forensics import main
    path = tmp_path / 'CarTunerStarsPaintLibrary.ASTC.fixture'
    path.write_bytes(synthetic_tnr_asset('CarTunerStarsPaintLibrary'))
    assert main(['--visual-asset-bundle', str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'dev25_source_only_no_roster'
    assert report['source_catalog']['records_per_source'] == {
        'CarTunerStarsPaintLibrary': 24}
    assert report['source_catalog']['standard_tnr_duplicate_ids_by_slot'] == {}
    assert report['source_catalog']['collision_ids_disclosed'] is False
    assert report['network_requests'] == report['gameplay_read_count'] == 0
    assert 'Native name' not in json.dumps(report)
