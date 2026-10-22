"""Dev79 separate-file stage alignment & provenance consistency regressions."""
import copy
import hashlib
import json
from pathlib import Path
import os
import subprocess
import sys

import pytest

from conftest import requires_symlinks

from csr2cdn._research.dev79_capture_provenance import (
    _STAGE_ANCHORS, assess, canonical_hash, main, read_bounded_json,
    sha256_file, validate_manifest,
)

ROOT = Path(__file__).resolve().parent.parent
APK = Path('/mnt/data/CSR2_6.8.0.apk')
S_PATH = ROOT / 'docs/examples/dev78-synthetic-snapshot.json'
M_PATH = ROOT / 'docs/examples/dev79-synthetic-stage-manifest.json'


@pytest.fixture
def evidence():
    return json.loads(S_PATH.read_text()), S_PATH.read_bytes(), json.loads(M_PATH.read_text())


def check(snapshot, raw, manifest):
    return validate_manifest(snapshot, raw, manifest, json.loads(M_PATH.read_text())['apk_sha256'])


def test_synthetic_is_explicit(evidence):
    s, raw, m = evidence
    assert s['capture']['kind'] == m['capture']['kind'] == 'synthetic'
    assert m['capture']['method'] == 'synthetic_fixture'
    assert check(s, raw, m)['status'] == 'synthetic_stage_manifest_consistent_not_runtime_evidence'


def test_no_production_promotion_even_when_1323(evidence):
    s, raw, m = evidence
    result = check(s, raw, m)
    assert result['snapshot_assessment']['paint_index_15_equals_conditional_1323_at_lookup'] is True
    assert result['production_paint_mapping_verified'] is False
    assert result['external_capture_origin_independently_authenticated'] is False
    assert result['game_execution_stage_alignment_independently_verified'] is False
    assert result['snapshot_assessment']['production_paint_mapping_verified'] is False


def test_stage_order_and_native_pins(evidence):
    s, raw, m = evidence
    a = check(s, raw, m)
    assert a['stages_claimed'] == ['gacha_gate', 'paint_lookup', 'profile_update', 'paint_post_refresh']
    assert a['native_rva_stage_anchors_match_pinned_locations']
    assert a['all_stage_payload_sha256_match']


def test_manifest_hash_deterministic(evidence):
    s, raw, m = evidence
    assert check(s, raw, m)['manifest_sha256'] == canonical_hash(m)
    assert len(canonical_hash(m)) == 64


def test_apk_hash_matches_real_file(evidence):
    _, _, m = evidence
    if APK.exists():
        assert sha256_file(APK) == m['apk_sha256']


def test_raw_snapshot_whitespace_digest_fails(evidence):
    s, raw, m = evidence
    with pytest.raises(ValueError, match='raw snapshot'):
        check(s, raw + b' ', m)


def test_parsed_snapshot_change_payload_fails(evidence):
    s, raw, m = evidence
    s['paint']['lookup']['ordered_paint_ids'][0] = 999
    with pytest.raises(ValueError, match='stage payload'):
        check(s, raw, m)


def test_profile_update_marker_has_no_payload(evidence):
    s, raw, m = evidence
    assert 'section_sha256' not in m['events'][2]


@pytest.mark.parametrize('key,bad', [
    ('schema', 'csr2cdn.dev79.stage-manifest.v2'),
    ('snapshot_sha256', '0'*64),
    ('snapshot_sha256', 'A'*64),
    ('snapshot_sha256', 0),
    ('snapshot_sha256', None),
    ('apk_sha256', '0'*64),
    ('apk_sha256', 'ABC'),
    ('apk_sha256', True),
    ('events', []),
    ('events', None),
    ('events', 'fake'),
    ('capture', []),
    ('capture', None),
])
def test_manifest_bad_top_level(evidence, key, bad):
    s, raw, m = evidence
    m[key] = bad
    with pytest.raises(ValueError):
        check(s, raw, m)


@pytest.mark.parametrize('key,bad', [
    ('capture_id', ''),
    ('capture_id', 'a'*65),
    ('capture_id', '../private-id'),
    ('capture_id', 'contains spaces'),
    ('capture_id', 1),
    ('capture_id', None),
    ('kind', 'passive_runtime'),
    ('kind', 'unknown'),
    ('method', 'read_only_observation'),
    ('method', 'online_api'),
    ('method', None),
    ('no_replayed_gameplay_calls', False),
    ('no_replayed_gameplay_calls', 1),
    ('session_continuity_claimed', False),
    ('session_continuity_claimed', 1),
])
def test_capture_claims_fail_closed(evidence, key, bad):
    s, raw, m = evidence
    m['capture'][key] = bad
    with pytest.raises(ValueError):
        check(s, raw, m)


@pytest.mark.parametrize('stage_index,key,bad', [
    (0, 'stage', 'unknown'),
    (0, 'stage', 0),
    (0, 'native_rva', '0x36126F0'),
    (0, 'native_rva', 0x36126F4),
    (1, 'native_rva', '0x380B61C'),
    (2, 'native_rva', '0x380B648'),
    (3, 'native_rva', '0x3805C0C'),
    (0, 'sequence', True),
    (0, 'sequence', -1),
    (0, 'sequence', 1.0),
    (0, 'monotonic_tick', None),
    (0, 'monotonic_tick', -1),
    (0, 'monotonic_tick', 1.5),
    (0, 'section_sha256', '0'*64),
    (1, 'section_sha256', 'A'*64),
    (3, 'section_sha256', False),
])
def test_event_guard(evidence, stage_index, key, bad):
    s, raw, m = evidence
    m['events'][stage_index][key] = bad
    with pytest.raises(ValueError):
        check(s, raw, m)


def test_profile_marker_cannot_supply_payload(evidence):
    s, raw, m = evidence
    m['events'][2]['section_sha256'] = '0'*64
    with pytest.raises(ValueError, match='unbound'):
        check(s, raw, m)


@pytest.mark.parametrize('index', [0,1,2,3])
def test_missing_stage_fails(evidence, index):
    s, raw, m = evidence
    m['events'].pop(index)
    with pytest.raises(ValueError):
        check(s, raw, m)


def test_repeated_stage_fails(evidence):
    s, raw, m = evidence
    m['events'][1] = copy.deepcopy(m['events'][0])
    with pytest.raises(ValueError):
        check(s, raw, m)


def test_nonmonotonic_sequence_fails(evidence):
    s, raw, m = evidence
    m['events'][1]['sequence'] = m['events'][0]['sequence']
    with pytest.raises(ValueError, match='increase'):
        check(s, raw, m)


def test_nonmonotonic_tick_fails(evidence):
    s, raw, m = evidence
    m['events'][2]['monotonic_tick'] = m['events'][1]['monotonic_tick']
    with pytest.raises(ValueError, match='increase'):
        check(s, raw, m)


def test_no_extra_stage_fails(evidence):
    s, raw, m = evidence
    m['events'].append(copy.deepcopy(m['events'][-1]))
    with pytest.raises(ValueError):
        check(s, raw, m)


def test_missing_section_digest_fails(evidence):
    s, raw, m = evidence
    del m['events'][1]['section_sha256']
    with pytest.raises(ValueError, match='section_sha256'):
        check(s, raw, m)


def test_manifest_with_no_snapshot_stage_fails(evidence):
    s, raw, m = evidence
    del s['gacha']
    del s['paint']
    with pytest.raises(ValueError):
        check(s, raw, m)


def test_missing_paint_section_with_exact_subset_stage_valid(evidence):
    s, raw, m = evidence
    del s['paint']
    m['events'] = m['events'][:1]
    assert check(s, raw, m)['stages_claimed'] == ['gacha_gate']


def test_lookup_only_manifest_valid(evidence):
    s, raw, m = evidence
    del s['gacha']
    del s['paint']['post_refresh']
    m['events'] = m['events'][1:2]
    assert check(s, raw, m)['stages_claimed'] == ['paint_lookup']


def test_passive_claim_still_not_authenticated(evidence):
    s, raw, m = evidence
    s['capture']['kind'] = 'passive_runtime'
    m['capture']['kind'] = 'passive_runtime'
    m['capture']['method'] = 'read_only_observation'
    assert check(s, raw, m)['status'] == 'self_reported_stage_manifest_consistent_not_authenticated'
    assert not check(s, raw, m)['production_paint_mapping_verified']


def test_passive_nonmutating_false_rejected(evidence):
    s, raw, m = evidence
    s['capture']['kind'] = 'passive_runtime'
    s['capture']['non_mutating'] = False
    m['capture']['kind'] = 'passive_runtime'
    m['capture']['method'] = 'read_only_observation'
    with pytest.raises(ValueError, match='non-mutating'):
        check(s, raw, m)


def test_synthetic_nonmutating_false_rejected(evidence):
    s, raw, m = evidence
    s['capture']['non_mutating'] = False
    with pytest.raises(ValueError):
        check(s, raw, m)


def test_unknown_top_field_rejected(evidence):
    s, raw, m = evidence
    m['token'] = 'SECRET'
    with pytest.raises(ValueError, match='unrecognized') as exc:
        check(s, raw, m)
    assert 'SECRET' not in str(exc.value)


def test_unknown_nested_field_rejected(evidence):
    s, raw, m = evidence
    m['capture']['private_user_id'] = 'SECRET'
    with pytest.raises(ValueError, match='unrecognized'):
        check(s, raw, m)


def test_unknown_event_field_rejected(evidence):
    s, raw, m = evidence
    m['events'][0]['secret'] = 'SECRET'
    with pytest.raises(ValueError, match='unrecognized'):
        check(s, raw, m)


@requires_symlinks
def test_bounded_read_rejects_symlink(tmp_path):
    target = tmp_path / 'target.json'
    target.write_text('{}')
    link = tmp_path / 'link.json'
    link.symlink_to(target)
    with pytest.raises(ValueError):
        read_bounded_json(link)


@pytest.mark.parametrize('data', [b'{"a":1,"a":2}', b'NaN', b'Infinity', b'\xff', b'[]', b'false'])
def test_bounded_read_rejects_bad_json(tmp_path, data):
    file = tmp_path / 'bad.json'
    file.write_bytes(data)
    with pytest.raises(ValueError):
        read_bounded_json(file)


def test_bounded_read_rejects_oversized(tmp_path):
    file = tmp_path / 'too-large.json'
    file.write_bytes(b' ' * 131073)
    with pytest.raises(ValueError, match='128 KiB'):
        read_bounded_json(file)


def test_missing_manifest_requires_snapshot(tmp_path):
    with pytest.raises(ValueError, match='requires'):
        assess(APK, None, M_PATH)


def test_native_apk_only_assessment():
    if not APK.exists():
        pytest.skip('local APK unavailable')
    r = assess(APK)
    assert not r['snapshot_supplied']
    assert not r['stage_manifest_supplied']
    assert not r['production_paint_mapping_verified']
    assert r['missing_capture_artifacts'] == ['runtime_snapshot', 'stage_manifest']


def test_native_apk_with_synthetic_manifest():
    if not APK.exists():
        pytest.skip('local APK unavailable')
    r = assess(APK, S_PATH, M_PATH)
    assert r['snapshot_supplied']
    assert r['stage_manifest_assessment']['all_stage_payload_sha256_match']
    assert not r['production_mappings_changed']
    assert r['network_requests'] == r['gameplay_state_writes'] == 0


def test_cli_refuses_overwrite(tmp_path):
    out = tmp_path / 'existing.json'
    out.write_text('NO_OVERWRITE')
    with pytest.raises(SystemExit):
        main(['--apk',str(APK),'--output',str(out)])
    assert out.read_text() == 'NO_OVERWRITE'


def test_cli_missing_snapshot_for_manifest(tmp_path):
    with pytest.raises(SystemExit):
        main(['--apk',str(APK),'--manifest',str(M_PATH),
              '--output',str(tmp_path / 'out.json')])


def test_no_runtime_dependency_in_module():
    body = (ROOT / 'csr2cdn/_research/dev79_capture_provenance.py').read_text()
    assert 'import requests' not in body
    assert 'urllib' not in body
    assert 'PopCarIfInDeliveryWaitingList(' not in body


def test_documented_anchor_set():
    assert _STAGE_ANCHORS == {
        'gacha_gate': '0x36126F4',
        'paint_lookup': '0x380B648',
        'profile_update': '0x34E8988',
        'paint_post_refresh': '0x380B648',
    }
