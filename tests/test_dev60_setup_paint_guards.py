"""Dev60: conditional preappend is pinned to real code and never promoted to roster label."""
from pathlib import Path
import pytest
from csr2cdn._research import dev60_setup_paint_guards as m


def test_no_preappend_uses_original_order():
    result=m.replay_single_preappend([1,2,3],[3,4,5,6],3,None)
    assert result['selected_paint_id']==4
    assert result['initial_early_append_happened'] is False
    assert result['combined_count']==6


def test_existing_paint_does_not_insert_duplicate():
    result=m.replay_single_preappend([1,2],[3,4,5],3,1)
    assert result['selected_paint_id']==4
    assert result['initial_early_append_happened'] is False


def test_distinct_early_paint_can_shift_index():
    base=[1,2]; unlock=[3,4,5,6]
    before=m.replay_single_preappend(base,unlock,3,None)
    after=m.replay_single_preappend(base,unlock,3,999)
    assert before['selected_paint_id']==4
    assert after['selected_paint_id']==3
    assert after['initial_early_append_happened']
    assert base==[1,2] and unlock==[3,4,5,6]


def test_early_paint_from_later_unlockable_changes_order_without_adding_count():
    result=m.replay_single_preappend([1,2],[3,4,5,6],3,6)
    assert result['selected_paint_id']==3
    assert result['combined_count']==6


def test_negatives_skipped_and_duplicates_deduped():
    result=m.replay_single_preappend([11,12],[-1,12,13,13,14,-1],3,222)
    assert result['selected_paint_id']==13
    assert result['combined_count']==5


@pytest.mark.parametrize('index,preappend', [(-1,None),(2048,None),(True,None),(0,-1),(0,2**31),(0,False)])
def test_bad_parameters_fail_closed(index,preappend):
    with pytest.raises(ValueError):
        m.replay_single_preappend([1],[],index,preappend)


def test_apk_digest_rejected():
    with pytest.raises(ValueError):m.audit_setup(b'other metadata',b'other native')


def test_cli_refuses_overwrite(tmp_path):
    p=tmp_path/'occupied.json';p.write_text('unchanged')
    with pytest.raises(SystemExit):
        m.main(['--apk','unused','--bundle','unused','--output',str(p)])
    assert p.read_text()=='unchanged'


def test_missing_apk_fails_closed(tmp_path):
    with pytest.raises(ValueError):
        m.inspect(tmp_path/'none.apk',tmp_path/'none.astc')


def test_real_native_branch_if_available():
    apk=Path('/mnt/data/CSR2_6.8.0.apk')
    if not apk.is_file():pytest.skip('operator APK is not part of the distribution')
    report=m.audit_setup(*m._read_native(apk))
    assert report['first_preappend_site']=='0x3802aa8'
    assert report['fallback_preappend_site']=='0x380309c'
    assert report['force_update_called_after_preappend']=='0x38036a0'
    assert report['source_branch_raw_enum_values']==[2,9,10]
    assert not report['branch_taken_for_roster_car_verified']


def test_real_apk_bundle_sensitivity_if_available():
    root=Path('/mnt/data')
    apk=root/'CSR2_6.8.0.apk'
    bundle=root/'Ford_Mustang302_1970_common.ASTC.14'
    catalog=root/'dev36-source-ids.json'
    if not all(x.is_file() for x in (apk,bundle,catalog)):
        pytest.skip('operator inputs are not part of distribution')
    result=m.inspect(apk,bundle,catalog,15)
    assert result['baseline_without_preappend']['selected_paint_id']==1323
    ids={x['paint_id'] for x in result['possible_labels_under_tested_one_preappend_scenarios']}
    assert ids=={129,1323}
    assert result['runtime_crew_paint_label_confirmed'] is False
    assert result['production_mapping_changed'] is False
    assert not result['reads_private_roster']
