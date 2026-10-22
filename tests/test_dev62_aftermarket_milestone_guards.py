"""Dev62: concrete native guard sites, synthetic branch cases, optional real fixtures."""
import json
from pathlib import Path
import pytest
from csr2cdn._research import dev62_aftermarket_milestone_guards as m

@pytest.mark.parametrize('has,tuner,outcome',[
    (False,None,'setup_aftermarket_locked_data_skipped_no_milestones'),
    (False,False,'setup_aftermarket_locked_data_skipped_no_milestones'),
    (False,True,'setup_aftermarket_locked_data_skipped_no_milestones'),
    (True,True,'setup_aftermarket_locked_data_skipped_tuner_stars'),
    (True,False,'setup_aftermarket_locked_data_called'),
    (True,None,'not_determined_without_runtime_predicates'),
    (None,None,'not_determined_without_runtime_predicates'),
    (None,False,'not_determined_without_runtime_predicates'),
    (None,True,'not_determined_without_runtime_predicates'),
])
def test_branch_matrix(has,tuner,outcome):
    assert m.branch_outcome(has_milestones=has,is_tuner_stars=tuner)==outcome

@pytest.mark.parametrize('has,tuner',[(1.0,False),('yes',False),(True,[]),({},False)])
def test_bad_guards_rejected(has,tuner):
    with pytest.raises(ValueError):m.branch_outcome(has_milestones=has,is_tuner_stars=tuner)


def test_audit_rejects_fake_native():
    with pytest.raises(ValueError):m.audit_restoration_setup(b'bad',b'bad')


def test_cli_refuses_overwriting_private_file(tmp_path):
    output=tmp_path/'exists.json'; output.write_text('PRIVATE')
    with pytest.raises(SystemExit):
        m.main(['--apk','nonexistent','--bundle','nonexistent','--output',str(output)])
    assert output.read_text()=='PRIVATE'


def test_known_guard_addresses_unique_and_pinned():
    assert len(m._OPCODES)==len(set(m._OPCODES))
    assert m._OPCODES['call_setup_milestones'][1]==0x380dd1c
    assert m._OPCODES['non_null_all_unlockables_fast_path'][1]==0x3828078
    assert m._METHODS[m._PREP][0]==0x3827df8


def test_real_verified_apk_when_available():
    apk=Path('/mnt/data/CSR2_6.8.0.apk')
    if not apk.is_file():pytest.skip('operator APK absent')
    meta,native=m._read_native(apk)
    report=m.audit_restoration_setup(meta,native)
    assert report['setup_path']['calls_locked_data_setup_only_if_has_milestones_and_not_tuner_stars']
    assert report['locked_data_path']['prepared_milestone_list_written_offset']=='0x30'
    assert report['locked_data_path']['serialized_or_cached_all_unlockables_offset']=='0x28'
    assert report['locked_data_path']['runtime_all_unlockables_identity_preserved_verified'] is False


def test_actual_paint_candidate_stays_conditional_when_available():
    root=Path('/mnt/data')
    inp=[root/x for x in ['CSR2_6.8.0.apk','Ford_Mustang302_1970_common.ASTC.14','dev36-source-ids.json','endpoint-cache.zip']]
    if not all(x.is_file() for x in inp):pytest.skip('operator inputs absent')
    report=m.inspect(inp[0],inp[1],inp[2],cache=inp[3])
    assert report['static_bundle_replay_without_early_append']['candidate_paint_id']==1323
    assert report['observed_cached_milestone_level']==50
    assert report['milestone_level_used_as_index_or_list_order_modifier_verified'] is False
    assert report['runtime_has_milestones_predicate_verified'] is False
    assert report['paint_index_15_verified'] is False
    assert 'player_uid' not in json.dumps(report)
    assert 'Transparent' not in json.dumps(report)
