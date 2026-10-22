"""Dev59: cache fast path, milestone fallback, and fail-closed native checks."""
from __future__ import annotations
import pytest

from conftest import requires_symlinks
from csr2cdn._research import dev59_milestone_unlockables as m


def test_rejects_wrong_apk_fingerprints():
    with pytest.raises(ValueError,match='unrecognized'):
        m.audit_native(b'fake metadata',b'fake native')


def test_default_source_omission_is_not_claimed_to_be_runtime():
    assert m.paint_group_variants([1,2],[{'carPaintIDs':[3,4]},{'carPaintIDs':[5]}],2)['hypothetical_only']


def test_milestone_groups_preserve_source_order():
    p=m.paint_group_variants([10,20],[{'carPaintIDs':[10,30]},{'carPaintIDs':[]},{'carPaintIDs':[40,50]}],3)
    assert p['all_groups_candidate']==40
    assert p['milestone_paint_group_count']==2
    assert p['omitting_one_group_sensitivity'][0]['candidate_at_index']==50
    assert p['omitting_one_group_sensitivity'][1]['candidate_at_index'] is None


def test_omitting_earlier_group_changes_selection():
    p=m.paint_group_variants([1,2],[{'carPaintIDs':[3,4,5]},{'carPaintIDs':[6,7,8]}],3)
    assert p['all_groups_candidate']==4
    assert p['omitting_one_group_sensitivity'][0]['candidate_at_index']==7


def test_all_duplicate_group_does_not_change_index():
    p=m.paint_group_variants([1,2],[{'carPaintIDs':[1,2]},{'carPaintIDs':[3,4]}],2)
    assert p['all_groups_candidate']==3
    assert p['omitting_one_group_sensitivity'][0]['candidate_at_index']==3


def test_cannot_generate_from_missing_bundle(tmp_path):
    with pytest.raises(ValueError):m.inspect(tmp_path/'missing.apk',tmp_path/'missing.astc')


def test_cli_refuses_overwrite(tmp_path):
    out=tmp_path/'report.json';out.write_text('preserve')
    with pytest.raises(SystemExit):m.main(['--apk','missing','--bundle','missing','--output',str(out)])
    assert out.read_text()=='preserve'


@requires_symlinks
def test_invalid_apk_symlink_rejected(tmp_path):
    r=tmp_path/'file';r.write_bytes(b'fake')
    s=tmp_path/'alias';s.symlink_to(r)
    with pytest.raises(ValueError,match='invalid or oversized APK'):m._read_native(s)


def test_fail_closed_wrong_instruction():
    with pytest.raises(ValueError):m._verify_instruction(b'\x00'*4,0x300,0x300,0xb5001380)


def test_real_bundle_if_present():
    from pathlib import Path
    b=Path('/mnt/data/Ford_Mustang302_1970_common.ASTC.14')
    if not b.exists():pytest.skip('operator bundle not part of source distribution')
    visual,unlock=m.parse_asset(m.unpack_unityfs(b.read_bytes()))
    assert visual['CarPaintIDs']==[1156,451,1159,1160]
    assert len(unlock['AllUnlockables']['carPaintIDs'])==39
    groups=m.paint_group_variants(visual['CarPaintIDs'],unlock['UnlockableMilestones'],15)
    assert groups['all_groups_candidate']==1323


def test_real_native_if_present():
    from pathlib import Path
    apk=Path('/mnt/data/CSR2_6.8.0.apk')
    if not apk.exists():pytest.skip('operator APK not part of source distribution')
    report=m.audit_native(*m._read_native(apk))
    assert report['native_cache_branch']['field_offset']=='0x28'
    assert report['milestone_setup']['car_visuals_setup_calls_setup_milestones']
