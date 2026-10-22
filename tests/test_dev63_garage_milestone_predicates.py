"""Dev63 zero-network static predicates: synthetic fail-closed + real fixtures."""
import json
from pathlib import Path
import pytest
from csr2cdn._research import dev63_garage_milestone_predicates as m


@pytest.mark.parametrize('opcode,at,dest',[
 (0x17e6b462,0x3476a64,0x2e23bec),
 (0x97efbbd3,0x3476444,0x3065390),
 (0x941d93fe,0x2e23c5c,0x3588c54),
 (0x945df382,0x2e23c88,0x45a0a90),
])
def test_native_branch_targets(opcode,at,dest):
    assert m._branch(opcode,at)==dest


@pytest.mark.parametrize('opcode', [0,0xd65f03c0,0xf9401261])
def test_reject_non_branches(opcode):
    with pytest.raises(ValueError):m._branch(opcode,0)


def test_garage_native_rejects_invalid_data():
    with pytest.raises((ValueError,KeyError)):
        m.audit_predicates(b'fake',b'fake')


def test_cli_refuses_existing_file(tmp_path):
    output=tmp_path/'keep.json';output.write_text('PRIVATE')
    with pytest.raises(SystemExit):
        m.main(['--apk','a','--bundle','b','--private-cache-zip','c','--output',str(output)])
    assert output.read_text()=='PRIVATE'


def test_cached_public_scheme_if_available():
    path=Path('/mnt/data/endpoint-cache.zip')
    if not path.is_file():pytest.skip('operator endpoint cache absent')
    r=m.inspect_public_schemes(path)
    assert r['pricing_scheme_id']=='EliteCustoms_FTUECar'
    assert r['defined_milestone_count']==50
    assert (r['first_level'],r['last_level'])==(1,50)
    assert r['configured_ftue_car_matches'] is True
    assert r['three_public_metadata_blocks_match_capture_manifest'] is True
    assert r['runtime_loaded_scheme_collection_verified'] is False


def test_bad_vehicle_identifier_rejected(tmp_path):
    with pytest.raises(ValueError):m.inspect_public_schemes(tmp_path/'none','../secret')


def test_full_actual_apk_bundle_cache_if_available():
    root=Path('/mnt/data')
    inputs=[root/n for n in ('CSR2_6.8.0.apk','Ford_Mustang302_1970_common.ASTC.14','endpoint-cache.zip','dev36-source-ids.json')]
    if not all(x.is_file() for x in inputs):pytest.skip('operator files unavailable')
    r=m.inspect(inputs[0],inputs[1],inputs[2],catalogue=inputs[3])
    assert r['native']['milestones_are_checked_by_car_key_and_pricing_scheme_collection']
    assert r['native']['tuner_stars_reads_byte_at_offset_0x21_from_looked_up_car_record']
    assert r['conditional_replay']['paint_id']==1323
    assert r['conditional_replay']['conditional_paint_library_label']=='Ford Dark Highland Green'
    assert r['redacted_roster']['aftermarket_milestone_level']==50
    assert r['static_evidence_proves_runtime_has_milestones_return'] is False
    assert r['source_tutorial_proves_not_tuner_stars'] is False
    assert r['production_mapping_modified'] is False
    assert r['http_requests']==r['gameplay_reads']==0
    assert 'player_uid' not in json.dumps(r)
    assert 'Transparent' not in json.dumps(r)


def test_method_fingerprints_expected():
    assert len(m._METHODS)==3
    assert m._METHODS['CarMilestoneDataManager.HasMilestonesForCar'][0]==0x2e23bec
    assert len(m._SITES)>=10
