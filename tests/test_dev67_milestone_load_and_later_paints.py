"""Dev67 native milestone-loader and scene-specific paint insertion regressions."""
import copy
import json
from pathlib import Path
import struct
import pytest

from csr2cdn._research.dev48_native_paint_methods import _ELF
from csr2cdn._research.dev59_milestone_unlockables import _read_native
from csr2cdn._research.dev67_milestone_load_and_later_paints import (
    _NATIVE_METHODS, _INSTRUCTIONS, audit_native, inspect, main)

APK=Path('/mnt/data/CSR2_6.8.0.apk')
META=Path('/mnt/data/CarMetadata.ASTC.1594')
VISUAL=Path('/mnt/data/Ford_Mustang302_1970_common.ASTC.14')
CACHE=Path('/mnt/data/endpoint-cache.zip')
CATALOG=Path('/mnt/data/dev36-source-ids.json')

@pytest.fixture(scope='module')
def compiled():
    if not APK.is_file():pytest.skip('operator APK absent')
    return _read_native(APK)

@pytest.fixture(scope='module')
def audited(compiled):
    return audit_native(*compiled)


def test_all_six_native_method_fingerprints(audited):
    assert len(audited['methods'])==6
    assert audited['methods']['CarLoader.SetupCarVisuals']['rva']=='0x2eb7df4'
    assert len(audited['verified_sites'])==len(_INSTRUCTIONS)==15


def test_manager_json_and_binary_routes(audited):
    routes=audited['verified_milestone_manager_load_routes']
    assert routes['json_callback_delegates_to_json_parser']
    assert routes['binary_callback_calls_binary_parser']
    assert routes['json_dictionary_parser_calls_LoadSchemeFromDict_twice']
    assert routes['loaded_EliteCustoms_FTUECar_membership_observed'] is False
    assert audited['verified_sites']['json_scheme_parse_call_first']['target']=='0x2e28ac0'


def test_car_loader_non_sentinel_guard(audited):
    sites=audited['verified_sites']
    assert sites['car_loader_insert_paint_id']['target']=='0x3813de4'
    assert sites['car_loader_copy_selected_index_to_garage']['address']=='0x2eb8158'
    assert sites['car_loader_sentinel_constant']['opcode']=='0x12b00008'


def test_race_human_ai_paint_mutations(audited):
    paths=audited['verified_later_paint_mutation_paths']
    assert paths['HumanRaceSetup_calls_paint_insertion_twice']
    assert paths['AIRaceSetup_calls_paint_insertion']
    assert paths['HumanRaceSetup_has_literal_zero_as_one_paint_insertion_argument']
    assert paths['these_paths_shown_to_run_for_cached_crew_car'] is False
    assert audited['verified_sites']['human_race_paint_zero_argument']['opcode']=='0x2a1f03e1'


def test_mutated_method_body_rejected(compiled):
    metadata,native=compiled
    elf=_ELF(native)
    corrupted=bytearray(native)
    rva,length,_=_NATIVE_METHODS['CarLoader.SetupCarVisuals']
    corrupted[elf.fileoff(rva,1,execute=True)]^=1
    with pytest.raises(ValueError,match='fingerprint mismatch'):
        audit_native(metadata,bytes(corrupted))


def test_mutated_load_callback_rejected(compiled):
    metadata,native=compiled
    elf=_ELF(native)
    corrupted=bytearray(native)
    addr=_INSTRUCTIONS['on_json_loaded_calls_json_parser'][1]
    corrupted[elf.fileoff(addr,1,execute=True)]^=1
    with pytest.raises(ValueError,match='fingerprint mismatch'):
        audit_native(metadata,bytes(corrupted))


def test_empty_metadata_rejected(compiled):
    _,native=compiled
    with pytest.raises(ValueError,match='metadata'):
        audit_native(b'',native)


def test_invalid_method_span(monkeypatch,compiled):
    metadata,native=compiled
    modified=dict(_NATIVE_METHODS)
    modified['CarLoader.SetupCarVisuals']=(0x2eb7df4, 0, modified['CarLoader.SetupCarVisuals'][2])
    monkeypatch.setattr('csr2cdn._research.dev67_milestone_load_and_later_paints._NATIVE_METHODS',modified)
    with pytest.raises(ValueError,match='span'):
        audit_native(metadata,native)


def test_mutated_expected_direct_target_rejected(monkeypatch,compiled):
    metadata,native=compiled
    modified=dict(_INSTRUCTIONS)
    name='car_loader_insert_paint_id'
    method,addr,word,target=modified[name]
    modified[name]=(method,addr,word,target+4)
    monkeypatch.setattr('csr2cdn._research.dev67_milestone_load_and_later_paints._INSTRUCTIONS',modified)
    with pytest.raises(ValueError,match='target'):
        audit_native(metadata,native)


@pytest.fixture(scope='module')
def real_sources():
    if not all(p.is_file() for p in (APK,META,VISUAL,CACHE,CATALOG)):
        pytest.skip('offline operator assets unavailable')
    return True

@pytest.fixture(scope='module')
def report(real_sources):
    return inspect(APK,META,VISUAL,CACHE,CATALOG)


def test_real_current_assets(report):
    assert report['current_carinfo']['is_tuner_stars_car'] is False
    assert report['public_milestone_scheme']['scheme_id']=='EliteCustoms_FTUECar'
    assert report['public_milestone_scheme']['defined_milestone_count']==50
    assert report['public_milestone_scheme']['scheme_present_in_live_loaded_manager'] is False
    assert report['paint_reconstruction']['candidate_paint_id']==1323
    assert report['paint_reconstruction']['candidate_label']=='Ford Dark Highland Green'
    assert report['paint_reconstruction']['reconstructed_list_count']==30
    assert report['paint_reconstruction']['candidate_only'] is True


def test_report_private_and_production_safety(report):
    assert report['player_identifiers_exported'] is False
    assert report['authenticated_gameplay_reads']==0
    assert report['network_requests']==0
    assert report['production_paint_mapping_changed'] is False
    assert report['paint_index_zero_meaning']=='unresolved'
    assert not report['paint_reconstruction']['rendered_paint_id_observed']
    raw=json.dumps(report).lower()
    for term in ['"crew_id":','"player_id":','"member_id":','"auth_token":','transparent']:
        assert term not in raw


def test_cli_output_matches_source_report(tmp_path,report):
    output=tmp_path/'report.json'
    args=['--apk',str(APK),'--car-metadata-bundle',str(META),
          '--visual-bundle',str(VISUAL),'--cache-zip',str(CACHE),
          '--source-catalog',str(CATALOG),'--output',str(output)]
    assert main(args)==0
    assert json.loads(output.read_text())==report
    with pytest.raises(SystemExit):main(args)


def test_cli_missing_inputs(tmp_path):
    with pytest.raises((FileNotFoundError,ValueError)):
        inspect(tmp_path/'unknown.apk',META,VISUAL,CACHE,CATALOG)
