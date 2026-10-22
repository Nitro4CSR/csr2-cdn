"""Offline Dev58 safety, ordering and index semantics regressions."""
from __future__ import annotations
import pytest

from conftest import requires_symlinks
from csr2cdn._research import dev58_runtime_paint_replay as m


def test_native_append_order_excludes_negative_separators_and_duplicates():
    combined,added=m.conditional_list([11,44,33], [33, -1, 7, -1, 7, 8, 11, 9])
    assert combined==[11,44,33,7,8,9]
    assert added==[7,8,9]


def test_base_array_keeps_original_order_not_global_sort():
    combined,_=m.conditional_list([1156,451,1159,1160], [1160,451,1156,-1,1164,1163])
    assert combined[:4]==[1156,451,1159,1160]
    assert combined[4:]==[1164,1163]


def test_empty_unlockables_means_no_automatic_index15_mapping():
    combined,added=m.conditional_list([1,2,3],[])
    assert len(combined)==3 and added==[]
    assert (combined[15] if len(combined)>15 else None) is None


@pytest.mark.parametrize('base,unlocks',[
    ([1,1],[2]), ([1],['2']),([True],[]),([1],[-(1<<32)]),([1],[1<<31]),
    ([-1],[3]),('a',[1]),([1],None),([1]*2001,[]),([1],[7]*3001)
])
def test_fail_closed_invalid_source_values(base,unlocks):
    with pytest.raises(ValueError):m.conditional_list(base,unlocks)


def test_verify_instruction_exact_and_mutated():
    m._verify_instruction((0x12345678).to_bytes(4,'little'),0x1000,0x1000,0x12345678)
    with pytest.raises(ValueError):m._verify_instruction(b'\0'*4,0x1000,0x1000,0x12345678)
    with pytest.raises(ValueError):m._verify_instruction(b'\0'*4,0x1000,0x1004,0)


def test_rejects_native_build_not_pinned():
    with pytest.raises(ValueError,match='does not match'):
        m.native_audit(b'metadata',b'native binary')


def test_missing_bundle_rejected(tmp_path):
    with pytest.raises(ValueError,match='invalid UnityFS bundle'):
        m.inspect(tmp_path/'app.apk',tmp_path/'not-exists')


def test_mismatching_bundle_digest_rejected(tmp_path):
    p=tmp_path/'x.astc';p.write_bytes(b'fake-bundle')
    with pytest.raises(ValueError,match='SHA-verified'):
        m.inspect(tmp_path/'app.apk',p)


@requires_symlinks
def test_rejects_symlink_bundle(tmp_path):
    p=tmp_path/'real';p.write_bytes(b'whatever')
    s=tmp_path/'alias';s.symlink_to(p)
    with pytest.raises(ValueError,match='invalid UnityFS bundle'):
        m.inspect(tmp_path/'app.apk',s)


def test_cli_does_not_overwrite(tmp_path):
    out=tmp_path/'report.json';out.write_text('keep')
    with pytest.raises(SystemExit):m.main(['--apk','missing','--bundle','missing','--output',str(out)])
    assert out.read_text()=='keep'


def test_index_bounded_early(tmp_path):
    with pytest.raises(ValueError,match='index outside'):
        m.inspect(tmp_path/'x',tmp_path/'y',paint_index=-1)
    with pytest.raises(ValueError,match='index outside'):
        m.inspect(tmp_path/'x',tmp_path/'y',paint_index=100001)
