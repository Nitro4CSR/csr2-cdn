"""Dev70: pinned real APK crew-completion visual setup analysis."""
import json
from pathlib import Path

import pytest
from csr2cdn._research.dev59_milestone_unlockables import _read_native
from csr2cdn._research.dev70_crew_completion_path import (
    _METHODS, _SITES, _branch_target, audit_native, inspect, main,
)

APK = Path('/mnt/data/CSR2_6.8.0.apk')
META = Path('/mnt/data/CarMetadata.ASTC.1594')
VISUAL = Path('/mnt/data/Ford_Mustang302_1970_common.ASTC.14')
CACHE = Path('/mnt/data/endpoint-cache.zip')
CATALOG = Path('/mnt/data/dev36-source-ids.json')

@pytest.fixture(scope='module')
def binary():
    if not APK.is_file():
        pytest.skip('authorized local APK not supplied')
    return _read_native(APK)

@pytest.fixture(scope='module')
def native(binary):
    return audit_native(*binary)

@pytest.fixture(scope='module')
def report():
    if not all(p.is_file() for p in (APK, META, VISUAL, CACHE, CATALOG)):
        pytest.skip('offline inputs missing')
    return inspect(APK, META, VISUAL, CACHE, CATALOG)


def test_method_fingerprints_and_pointer_joins(native):
    assert set(native['methods']) == set(_METHODS)
    assert set(native['managed_pointer_matches']) == set(_METHODS)
    assert len(native['verified_sites']) == 16
    assert native['methods']['SceneManagerGarage.CarLoaded']['rva'] == '0x3612398'

@pytest.mark.parametrize('key,target', [
    ('car_loaded_can_tail_call_asset_completed','0x33bcd80'),
    ('asset_request_can_tail_call_synchronous_completion','0x33bda60'),
    ('garage_visuals_configures_shader_lod','0x3804658'),
    ('garage_visuals_configures_lighting','0x3804928'),
    ('scene_calls_garage_visuals_setup','0x33c13e0'),
    ('scene_calls_car_visuals_setup','0x380275c'),
    ('scene_can_show_car_after_visual_setup','0x36179f4'),
])
def test_compiled_direct_branch_target(native,key,target):
    assert native['verified_sites'][key]['direct_target'] == target


def test_visual_setup_sequencing(native):
    sites = native['verified_sites']
    assert int(sites['scene_calls_garage_visuals_setup']['rva'],16) < int(sites['scene_calls_car_visuals_setup']['rva'],16)
    assert int(sites['scene_calls_car_visuals_setup']['rva'],16) < int(sites['scene_can_show_car_after_visual_setup']['rva'],16)
    assert native['scene_manager_calls_car_visuals_setup_afterwards']
    assert native['post_setup_paint_list_unchanged_verified'] is False
    assert native['selected_paint_rendered_observed'] is False


def test_helper_only_accepts_direct_branches():
    assert _branch_target(0x9407bf61, 0x36129d8) == 0x380275c
    assert _branch_target(0x17fffd0d, 0x33bd94c) == 0x33bcd80
    assert _branch_target(0xf9001275, 0x33c148c) is None


def test_method_tampering_fails_closed(binary, monkeypatch):
    broken = dict(_METHODS)
    at, sz, _ = broken['GarageCarVisuals.Setup']
    broken['GarageCarVisuals.Setup'] = (at, sz, '0'*64)
    monkeypatch.setattr('csr2cdn._research.dev70_crew_completion_path._METHODS', broken)
    with pytest.raises(ValueError, match='fingerprint mismatch'):
        audit_native(*binary)


def test_instruction_tampering_fails_closed(binary, monkeypatch):
    broken = dict(_SITES)
    cls, at, word, to = broken['scene_calls_car_visuals_setup']
    broken['scene_calls_car_visuals_setup'] = cls, at, word^1, to
    monkeypatch.setattr('csr2cdn._research.dev70_crew_completion_path._SITES', broken)
    with pytest.raises(ValueError, match='instruction mismatch'):
        audit_native(*binary)


def test_metadata_tampering_fails_closed(binary):
    with pytest.raises(ValueError, match='metadata'):
        audit_native(b'\0'*128, binary[1])


def test_report_is_private_and_conditional(report):
    assert report['paint_reconstruction']['conditional_candidate_paint_id'] == 1323
    assert report['paint_reconstruction']['production_mapping_verified'] is False
    assert report['paint_reconstruction']['runtime_paint_list_captured'] is False
    assert report['paint_reconstruction']['all_indirect_and_later_mutations_excluded'] is False
    assert report['paint_index_zero'] == 'unresolved'
    assert report['network_requests'] == 0
    assert report['authenticated_gameplay_reads'] == 0
    assert report['player_identifiers_exported'] is False
    assert report['production_paint_mapping_changed'] is False
    lower = json.dumps(report).lower()
    for private_key in ('"crew_id"', '"player_id"', '"auth_token"', 'transparent'):
        assert private_key not in lower


def test_cli_and_safe_overwrite(report, tmp_path):
    output = tmp_path / 'dev70.json'
    args = ['--apk', str(APK), '--car-metadata-bundle', str(META),
            '--visual-bundle', str(VISUAL), '--cache-zip', str(CACHE),
            '--source-catalog', str(CATALOG), '--paint-index','15',
            '--output', str(output)]
    assert main(args) == 0
    assert json.loads(output.read_text()) == report
    with pytest.raises(SystemExit):
        main(args)
