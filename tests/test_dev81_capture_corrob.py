"""Dev81: signed-bundle correlation tests use fabricated captures and ephemeral keys."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from conftest import requires_symlinks

from csr2cdn._research.dev79_capture_provenance import canonical_hash
from csr2cdn._research.dev80_capture_attestation import signature_message
from csr2cdn._research.dev81_capture_corrob import CaptureBundle, compare_signed_bundles, assess, main

ROOT = Path(__file__).resolve().parent.parent
APK = Path('/mnt/data/CSR2_6.8.0.apk')
ORIGINAL_SNAPSHOT = json.loads((ROOT/'docs/examples/dev78-synthetic-snapshot.json').read_text())
ORIGINAL_MANIFEST = json.loads((ROOT/'docs/examples/dev79-synthetic-stage-manifest.json').read_text())
APK_DIGEST = ORIGINAL_MANIFEST['apk_sha256']


def make_bundle(base, ordinal, *, change=None, kind='synthetic', same_snapshot=False,
                signing_key=None, challenge_override=None):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    base.mkdir(parents=True, exist_ok=True)
    snap = copy.deepcopy(ORIGINAL_SNAPSHOT)
    snap['capture']['kind'] = kind
    if change:
        change(snap)
    # Distinct snapshot files despite the same parsed values; never evidence of distinct game runs.
    rendered = json.dumps(snap, indent=None if same_snapshot else ordinal + 2,
                          sort_keys=True, ensure_ascii=True).encode() + b'\n'
    sp = base/'snapshot.json'; sp.write_bytes(rendered)
    manifest = copy.deepcopy(ORIGINAL_MANIFEST)
    manifest['capture']['capture_id'] = f'fixture-{ordinal:03}'
    manifest['capture']['kind'] = kind
    manifest['capture']['method'] = 'synthetic_fixture' if kind == 'synthetic' else 'read_only_observation'
    manifest['snapshot_sha256'] = hashlib.sha256(rendered).hexdigest()
    for event in manifest['events']:
        event['monotonic_tick'] += ordinal * 20000
        if 'section_sha256' in event:
            data = snap['gacha'] if event['stage']=='gacha_gate' else snap['paint']['lookup'] if event['stage']=='paint_lookup' else snap['paint']['post_refresh']
            event['section_sha256'] = canonical_hash(data)
    mp = base/'manifest.json'; mp.write_bytes((json.dumps(manifest, sort_keys=True, indent=2)+'\n').encode())
    sk = signing_key if signing_key is not None else Ed25519PrivateKey.generate()  # test-only
    pub = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    challenge = challenge_override if challenge_override is not None else f'{ordinal:02x}' * 32
    sig = sk.sign(signature_message(mp.read_bytes(), challenge))
    pk = base/'pub.bin'; pk.write_bytes(pub)
    sg = base/'sig.bin'; sg.write_bytes(sig)
    return CaptureBundle(sp, mp, pk, sg, hashlib.sha256(pub).hexdigest(), challenge)


@pytest.fixture
def pair(tmp_path):
    pytest.importorskip('cryptography.hazmat.primitives.asymmetric.ed25519')
    return [make_bundle(tmp_path/'a', 1), make_bundle(tmp_path/'b', 2)]


def test_synthetic_agreement_no_promotion(pair):
    report = compare_signed_bundles(APK_DIGEST, pair)
    assert report['status'] == 'synthetic_submissions_agree_not_runtime_evidence'
    assert report['bundle_count'] == 2
    assert report['between_bundle_observation_values_agree'] is True
    assert report['between_bundle_disagreement_fields'] == []
    assert report['all_observation_stages_complete'] is True
    assert report['all_per_capture_paint_states_stable'] is True
    assert all(r['ed25519_signature_valid'] for r in report['bundle_summaries'])
    assert all(r['comparison_fields']['lookup_resolved_paint_id'] == 1323 for r in report['bundle_summaries'])
    for field in ('production_paint_mapping_verified', 'production_mappings_changed',
                  'external_capture_origin_independently_authenticated',
                  'independent_signer_control_established',
                  'verifier_key_pins_or_challenges_independently_trusted'):
        assert report[field] is False
    output = json.dumps(report)
    assert 'ordered_paint_ids' not in output
    assert 'fixture-001' not in output
    assert 'fixture-002' not in output
    assert pair[0].challenge not in output


def test_claimed_passive_runs_do_not_establish_authentication(tmp_path):
    b = [make_bundle(tmp_path/'1', 1, kind='passive_runtime'),
         make_bundle(tmp_path/'2', 2, kind='passive_runtime')]
    result = compare_signed_bundles(APK_DIGEST, b)
    assert result['status'] == 'self_reported_signed_submissions_agree_origin_not_authenticated'
    assert result['all_capture_kinds_claim_passive_runtime'] is True
    assert result['production_paint_mapping_verified'] is False


@pytest.mark.parametrize('what,disagreement', [
    ('paint_id', 'lookup_list_sha256'), ('paint_order', 'lookup_list_sha256'),
    ('selected_index', 'lookup_selected_index'), ('gacha_called', 'gacha_call_observed'),
    ('gacha_count', 'gacha_predicted_gate'),
])
def test_disagreement_reported_not_promoted(tmp_path, what, disagreement):
    def change(s):
        if what == 'paint_id':
            s['paint']['lookup']['ordered_paint_ids'][15] = 1234
            s['paint']['lookup']['observed_paint_id'] = 1234
        if what == 'paint_order':
            ids = s['paint']['lookup']['ordered_paint_ids']; ids[0], ids[1] = ids[1], ids[0]
        if what == 'selected_index':
            s['paint']['lookup']['selected_index'] = 0
            s['paint']['lookup']['observed_paint_id'] = 1000
        if what == 'gacha_called':
            s['gacha']['observed_apply_gacha_called'] = False
        if what == 'gacha_count':
            s['gacha']['config_count'] = 0
            s['gacha']['observed_apply_gacha_called'] = False
    b = [make_bundle(tmp_path/'a', 1), make_bundle(tmp_path/'b', 2, change=change)]
    report = compare_signed_bundles(APK_DIGEST, b)
    assert report['status'] == 'signed_submissions_disagree_no_runtime_conclusion'
    assert disagreement in report['between_bundle_disagreement_fields']
    assert not report['production_paint_mapping_verified']


def test_unstable_paint_stage_does_not_count_as_corroborated(tmp_path):
    def change(s):
        s['paint']['post_refresh']['ordered_paint_ids'][15] = 333
        s['paint']['post_refresh']['observed_paint_id'] = 333
    b = [make_bundle(tmp_path/'a', 1, change=change), make_bundle(tmp_path/'b', 2, change=change)]
    report = compare_signed_bundles(APK_DIGEST, b)
    assert report['between_bundle_observation_values_agree']
    assert not report['all_per_capture_paint_states_stable']
    assert report['status'] == 'signed_submissions_incomplete_or_mutating_no_runtime_conclusion'


def test_partial_stage_reports_incomplete(tmp_path):
    # Keep all stage markers but provide an out-of-bounds index without a paint ID.
    def invalid(s):
        s['paint']['lookup']['selected_index'] = 50
        s['paint']['lookup'].pop('observed_paint_id')
        s['paint']['post_refresh']['selected_index'] = 50
        s['paint']['post_refresh'].pop('observed_paint_id')
    b = [make_bundle(tmp_path/'c', 3, change=invalid), make_bundle(tmp_path/'d', 4, change=invalid)]
    report = compare_signed_bundles(APK_DIGEST, b)
    assert not report['all_observation_stages_complete']
    assert report['status'] == 'signed_submissions_incomplete_or_mutating_no_runtime_conclusion'


def test_duplicate_capture_rejected(pair):
    with pytest.raises(ValueError, match='reuse'):
        compare_signed_bundles(APK_DIGEST, [pair[0], pair[0]])


def test_reused_challenge_rejected_even_with_distinct_keys(tmp_path):
    a = make_bundle(tmp_path/'a', 1)
    b = make_bundle(tmp_path/'b', 2, challenge_override='01'*32)
    with pytest.raises(ValueError, match='reuse challenge_sha256'):
        compare_signed_bundles(APK_DIGEST, [a, b])


def test_reused_signer_key_rejected_even_with_fresh_signature(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    signer = Ed25519PrivateKey.generate()  # in-memory test-only
    a = make_bundle(tmp_path/'a', 1, signing_key=signer)
    b = make_bundle(tmp_path/'b', 2, signing_key=signer)
    with pytest.raises(ValueError, match='reuse signer_public_key_sha256'):
        compare_signed_bundles(APK_DIGEST, [a, b])


def test_identical_raw_snapshot_rejected_even_with_distinct_manifest_and_key(tmp_path):
    a = make_bundle(tmp_path/'a', 1, same_snapshot=True)
    b = make_bundle(tmp_path/'b', 2, same_snapshot=True)
    with pytest.raises(ValueError, match='reuse raw_snapshot_sha256'):
        compare_signed_bundles(APK_DIGEST, [a, b])


@pytest.mark.parametrize('tamper', ['signature', 'key', 'challenge', 'snapshot', 'manifest', 'apk'])
def test_integrity_fail_closed(pair, tamper):
    a, b = pair
    if tamper == 'signature':
        b.signature.write_bytes(bytes([b.signature.read_bytes()[0]^1])+b.signature.read_bytes()[1:])
    elif tamper == 'key':
        b.public_key.write_bytes(a.public_key.read_bytes())
    elif tamper == 'challenge':
        b = b._replace(challenge='fb'*32)
    elif tamper == 'snapshot':
        b.snapshot.write_bytes(b.snapshot.read_bytes()+b' ')
    elif tamper == 'manifest':
        b.manifest.write_bytes(b.manifest.read_bytes()+b' ')
    else:
        with pytest.raises(ValueError, match='APK SHA-256'):
            compare_signed_bundles('ab'*32, [a,b])
        return
    with pytest.raises(ValueError):
        compare_signed_bundles(APK_DIGEST, [a,b])


@pytest.mark.parametrize('count', [1, 9])
def test_bad_capture_count_rejected_early(count, pair):
    with pytest.raises(ValueError, match='2-8'):
        compare_signed_bundles(APK_DIGEST, [pair[0]]*count)


@pytest.mark.skipif(not APK.exists(), reason='local APK unavailable')
def test_native_only_real_apk(tmp_path):
    result = assess(APK)
    assert result['cross_bundle_assessment'] is None
    assert result['capture_bundles_supplied'] == 0
    assert result['production_paint_mapping_verified'] is False
    path = tmp_path/'dev81.json'
    assert main(['--apk', str(APK), '--output', str(path)]) == 0
    assert json.loads(path.read_text()) == result


@pytest.mark.skipif(not APK.exists(), reason='local APK unavailable')
def test_end_to_end_real_apk_two_synthetic_bundles(pair):
    result = assess(APK, pair)
    assert result['cross_bundle_assessment']['status'] == 'synthetic_submissions_agree_not_runtime_evidence'
    assert not result['independent_runtime_origin_verified']
    assert not result['production_mappings_changed']


def test_cli_rejects_preexisting_report(tmp_path):
    p = tmp_path/'report.json'; p.write_text('do not alter')
    with pytest.raises(SystemExit):
        main(['--apk','/path/to/unavailable.apk','--output',str(p)])
    assert p.read_text() == 'do not alter'


def test_package_contains_no_private_key_handler():
    code = (ROOT/'csr2cdn/_research/dev81_capture_corrob.py').read_text()
    assert 'Ed25519PrivateKey' not in code
    assert 'network_requests' in code
    assert 'production_mappings_changed' in code


def test_three_signed_reports_same_observations(tmp_path):
    b = [make_bundle(tmp_path/str(i), i) for i in (1,2,3)]
    report = compare_signed_bundles(APK_DIGEST, b)
    assert report['bundle_count'] == 3
    assert report['between_bundle_observation_values_agree']
    assert not report['independent_signer_control_established']


def test_mixed_self_reported_kinds_never_corroborate_runtime(tmp_path):
    b = [make_bundle(tmp_path/'a', 1, kind='passive_runtime'),
         make_bundle(tmp_path/'b', 2, kind='synthetic')]
    report = compare_signed_bundles(APK_DIGEST, b)
    assert report['status'] == 'synthetic_submissions_agree_not_runtime_evidence'
    assert not report['all_capture_kinds_claim_passive_runtime']


def test_snapshot_observed_id_mismatch_rejected_even_if_signed(tmp_path):
    def invalid(s):
        s['paint']['lookup']['observed_paint_id'] = 9999
    b = [make_bundle(tmp_path/'a', 1, change=invalid), make_bundle(tmp_path/'b', 2)]
    with pytest.raises(ValueError, match='observed paint ID differs'):
        compare_signed_bundles(APK_DIGEST, b)


@requires_symlinks
def test_rejected_symlink_input(tmp_path):
    a = make_bundle(tmp_path/'a', 1)
    b = make_bundle(tmp_path/'b', 2)
    alias = tmp_path/'alias.json'; alias.symlink_to(a.snapshot)
    b = b._replace(snapshot=alias)
    with pytest.raises(ValueError, match='regular'):
        compare_signed_bundles(APK_DIGEST, [a,b])


def test_invalid_native_stage_marker_rejected_before_signature(tmp_path):
    a = make_bundle(tmp_path/'a', 1)
    b = make_bundle(tmp_path/'b', 2)
    m = json.loads(b.manifest.read_text()); m['events'][1]['native_rva'] = '0xBAD'
    b.manifest.write_text(json.dumps(m))
    with pytest.raises(ValueError, match='native RVA'):
        compare_signed_bundles(APK_DIGEST, [a,b])


@pytest.mark.skipif(not APK.exists(), reason='local APK unavailable')
def test_cli_two_signed_synthetic_bundles(tmp_path, pair):
    out = tmp_path/'evidence.json'
    args = ['--apk', str(APK)]
    for c in pair:
        args += ['--capture', str(c.snapshot), str(c.manifest), str(c.public_key),
                 str(c.signature), c.trusted_key_sha256, c.challenge]
    args += ['--output', str(out)]
    assert main(args) == 0
    content = json.loads(out.read_text())
    assert content['cross_bundle_assessment']['bundle_count'] == 2
    assert content['cross_bundle_assessment']['status'].startswith('synthetic')
    assert content['private_capture_echoed_to_report'] is False
    assert not content['production_mappings_changed']
