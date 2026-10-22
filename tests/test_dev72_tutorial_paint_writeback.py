"""Dev72 native ARM64 Tutorial-source control flow and privacy regression."""
import json
from pathlib import Path
import pytest

from csr2cdn._research.dev59_milestone_unlockables import _read_native
from csr2cdn._research.dev72_tutorial_paint_writeback import (
    _PINNED_WORDS,_WRITEBACKS,_IAP_BRANCH,_SPECIAL_BRANCH,_IAP_ENTRY,
    _AFTER_SOURCE_DISPATCH, _START, _LEN,
    _signed,_successors,_reachable,_garage_paint_stores,
    audit_tutorial_cfg,inspect,main,
)
from csr2cdn._research.dev48_native_paint_methods import _ELF,_slice

APK=Path('/mnt/data/CSR2_6.8.0.apk')
CAR=Path('/mnt/data/CarMetadata.ASTC.1594')
VIS=Path('/mnt/data/Ford_Mustang302_1970_common.ASTC.14')
CACHE=Path('/mnt/data/endpoint-cache.zip')
CAT=Path('/mnt/data/dev36-source-ids.json')

@pytest.fixture(scope='module')
def raw():
    if not APK.is_file():pytest.skip('offline APK unavailable')
    return _read_native(APK)

@pytest.fixture(scope='module')
def body(raw):
    e=_ELF(raw[1]);return _slice(raw[1],e.fileoff(_START,_LEN,execute=True),_LEN)

@pytest.fixture(scope='module')
def audit(raw):return audit_tutorial_cfg(*raw)

@pytest.fixture(scope='module')
def report():
    if not all(x.is_file() for x in (APK,CAR,VIS,CACHE,CAT)):
        pytest.skip('offline investigation input missing')
    return inspect(APK,CAR,VIS,CACHE,CAT)


def test_source_guards_verified(audit):
    assert audit['source_enum']=='Tutorial'
    assert audit['source_numeric_value']==1
    assert audit['source_special_mask_matched'] is False
    assert audit['source_iap_matched'] is False


def test_actual_mask_and_iap_branches(audit):
    assert audit['source_mask_failure_goes_to_is_iap']==hex(_IAP_ENTRY)
    assert audit['source_iap_failure_goes_to_common_setup']==hex(_AFTER_SOURCE_DISPATCH)
    assert len(audit['verified_machine_sites'])==len(_PINNED_WORDS)


def test_full_control_flow_reaches_both_writebacks(audit):
    assert audit['all_identified_setup_garage_paint_writebacks']==[hex(v) for v in _WRITEBACKS]
    assert audit['unrestricted_reachable_instruction_count']==1008


def test_tutorial_control_flow_excludes_writebacks(audit):
    assert audit['tutorial_reachable_garage_paint_writebacks']==[]
    assert audit['tutorial_reachable_instruction_count']==759
    assert audit['tutorial_can_reach_paint_refresh'] is True


def test_indirect_and_runtime_state_not_claimed(audit):
    assert audit['indirect_calls_and_later_runtime_mutations_excluded'] is False
    assert audit['assumes_tutorial_source_reaches_garage_instance_unchanged'] is True
    assert audit['exact_runtime_branch_outcomes_observed'] is False


@pytest.mark.parametrize('pc,word,target',[
    (_SPECIAL_BRANCH,0x54000e60,_IAP_ENTRY),
    (_IAP_BRANCH,0x36000ba0,_AFTER_SOURCE_DISPATCH),
    (0x38030a0,0x14000195,0x38036f4),
    (0x380308c,0x54003282,0x38036dc),
])
def test_branch_decoder_native_targets(pc,word,target):
    assert target in _successors(pc,word)


def test_sign_extension_and_return_decoding():
    assert _signed(0x7ffff,19)==-1
    assert _signed(0x3ffffff,26)==-1
    assert _successors(0x1000,0xd65f03c0)==()
    assert _successors(0x1000,0x94000000)==(0x1004,)


def test_bad_cfg_constraint_fails_closed(body):
    with pytest.raises(ValueError,match='not a native CFG edge'):
        _reachable(body,{_SPECIAL_BRANCH:0x380b4f8})


def test_unrestricted_and_tutorial_stores_differ(body):
    x=_reachable(body)
    t=_reachable(body,{_SPECIAL_BRANCH:_IAP_ENTRY,_IAP_BRANCH:_AFTER_SOURCE_DISPATCH})
    assert _garage_paint_stores(body,x)==list(_WRITEBACKS)
    assert _garage_paint_stores(body,t)==[]


def test_native_fingerprint_tamper_fails_closed(raw,monkeypatch):
    import csr2cdn._research.dev72_tutorial_paint_writeback as mod
    monkeypatch.setattr(mod,'_PINNED_WORDS',{**_PINNED_WORDS,_SPECIAL_BRANCH:0})
    with pytest.raises(ValueError,match='native branch-site changed'):
        audit_tutorial_cfg(*raw)


def test_invalid_apk_fails_closed(raw):
    with pytest.raises(ValueError):audit_tutorial_cfg(b'INVALID',raw[1])


def test_real_evidence_preserves_production_mapping(report):
    assert report['status']=='dev72_tutorial_setup_writebacks_not_reachable'
    assert report['roster_source_verified']=='Tutorial'
    p=report['paint_reconstruction']
    assert p['received_index']==15
    assert p['conditional_candidate_paint_id']==1323
    assert p['conditional_candidate_label']=='Ford Dark Highland Green'
    assert p['two_known_setup_index_writebacks_excluded_for_tutorial'] is True
    assert p['production_mapping_verified'] is False
    assert p['post_setup_mutations_excluded'] is False
    assert report['paint_index_zero']=='unresolved'


def test_privacy_no_network(report):
    def keys(obj):
        if isinstance(obj,dict):
            for k,v in obj.items():
                yield k
                yield from keys(v)
        elif isinstance(obj,list):
            for v in obj: yield from keys(v)
    fields=set(keys(report))
    assert report['player_identifiers_exported'] is False
    assert report['authenticated_gameplay_reads']==0
    assert report['network_requests']==0
    for key in ('member_user_id','player_id','session_token','access_token'):
        assert key not in fields


def test_cli_no_overwrite(tmp_path):
    out=tmp_path/'evidence.json';out.write_text('old content')
    with pytest.raises(SystemExit):main([
        '--apk',str(APK),'--car-metadata-bundle',str(CAR),
        '--visual-bundle',str(VIS),'--cache-zip',str(CACHE),
        '--source-catalog',str(CAT),'--output',str(out),
    ])
    assert out.read_text()=='old content'
