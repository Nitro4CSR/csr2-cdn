"""Dev80 detached signature verification: synthetic test keys are never shipped."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from conftest import requires_symlinks

from csr2cdn._research.dev80_capture_attestation import (
    DOMAIN, assess, main, read_exact_regular_file, signature_message,
    verify_attestation,
)

ROOT = Path(__file__).resolve().parent.parent
APK = Path('/mnt/data/CSR2_6.8.0.apk')
SNAPSHOT = ROOT / 'docs/examples/dev78-synthetic-snapshot.json'
MANIFEST = ROOT / 'docs/examples/dev79-synthetic-stage-manifest.json'


@pytest.fixture
def sample():
    ed = pytest.importorskip('cryptography.hazmat.primitives.asymmetric.ed25519')
    ser = pytest.importorskip('cryptography.hazmat.primitives.serialization')
    private = ed.Ed25519PrivateKey.generate()  # test-only, never saved/bundled
    public = private.public_key().public_bytes(
        encoding=ser.Encoding.Raw, format=ser.PublicFormat.Raw)
    raw = MANIFEST.read_bytes()
    challenge = 'ab' * 32
    signature = private.sign(signature_message(raw, challenge))
    return private, public, signature, challenge, raw


def test_domain_separator_and_exact_preimage(sample):
    private, public, signature, challenge, raw = sample
    assert DOMAIN.endswith(b'\x00')
    assert signature_message(raw, challenge) == DOMAIN + bytes.fromhex(challenge) + hashlib.sha256(raw).digest()
    assert len(signature_message(raw, challenge)) == len(DOMAIN) + 64


def test_correct_detached_signature_passes_and_does_not_promote(sample):
    _, public, sig, nonce, raw = sample
    output = verify_attestation(raw, public, sig, nonce, hashlib.sha256(public).hexdigest())
    assert output['detached_signature_valid'] is True
    assert output['challenge_bound_to_signed_payload'] is True
    assert output['out_of_band_key_trust_independently_established'] is False
    assert output['challenge_freshness_independently_established'] is False
    assert output['actual_gameplay_capture_independently_authenticated'] is False
    assert output['production_paint_mapping_verified'] is False
    assert output['production_mappings_changed'] is False
    assert sig.hex() not in json.dumps(output)
    assert nonce not in json.dumps(output)


@pytest.mark.parametrize('change', ['snapshot_manifest_mutated', 'nonce_modified', 'signature_modified',
                                     'wrong_key', 'wrong_key_pin', 'no_sig', 'short_public',
                                     'short_signature', 'oversize_signature'])
def test_tampering_rejected(sample, change):
    private, public, sig, nonce, raw = sample
    pin = hashlib.sha256(public).hexdigest()
    if change == 'snapshot_manifest_mutated':
        raw = raw + b'\n'
    if change == 'nonce_modified':
        nonce = 'aa'*32
    if change == 'signature_modified':
        sig = bytes([sig[0]^1]) + sig[1:]
    if change == 'wrong_key':
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        public = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        pin = hashlib.sha256(public).hexdigest()
    if change == 'wrong_key_pin':
        pin = '00'*32
    if change == 'no_sig':
        sig = b''
    if change == 'short_public':
        public = b'A'*31
        pin = hashlib.sha256(public).hexdigest()
    if change == 'short_signature':
        sig = sig[:-1]
    if change == 'oversize_signature':
        sig = sig + b'!'
    with pytest.raises(ValueError):
        verify_attestation(raw, public, sig, nonce, pin)


@pytest.mark.parametrize('bad', ['', 'ab'*31, 'AB'*32, 'zy'*32, '0'*65, None, False, 5])
def test_challenge_rejects_bad_values(sample, bad):
    _, public, sig, _, raw = sample
    with pytest.raises((ValueError, TypeError)):
        verify_attestation(raw, public, sig, bad, hashlib.sha256(public).hexdigest())


@pytest.mark.parametrize('bad', ['', 'ab'*31, 'AB'*32, 'xyz', True, None, 123])
def test_pinned_fingerprint_rejects_bad_values(sample, bad):
    _, public, sig, challenge, raw = sample
    with pytest.raises(ValueError):
        verify_attestation(raw, public, sig, challenge, bad)


def test_read_exact_regular_file_and_reject_bad_sizes(tmp_path):
    file = tmp_path/'key'
    file.write_bytes(b'K'*32)
    assert read_exact_regular_file(file, 32) == b'K'*32
    with pytest.raises(ValueError, match='exactly'):
        read_exact_regular_file(file, 64)
    file.write_bytes(b'Z'*33)
    with pytest.raises(ValueError, match='exactly'):
        read_exact_regular_file(file, 32)


@requires_symlinks
def test_reject_symlink(tmp_path):
    real = tmp_path / 'real'
    real.write_bytes(b'R'*32)
    link = tmp_path / 'link'
    link.symlink_to(real)
    if hasattr(os, 'O_NOFOLLOW'):
        with pytest.raises(ValueError):
            read_exact_regular_file(link, 32)


def test_reject_non_regular_file(tmp_path):
    with pytest.raises(ValueError):
        read_exact_regular_file(tmp_path, 32)


@pytest.mark.parametrize('missing', ['snapshot', 'manifest', 'public_key', 'signature', 'pin', 'challenge'])
def test_partial_attestation_fails_before_apk_read(missing, tmp_path):
    data = {
        'snapshot_path': SNAPSHOT, 'manifest_path': MANIFEST,
        'public_key_path': tmp_path/'key', 'signature_path': tmp_path/'sig',
        'trusted_key_sha256': 'aa'*32, 'challenge':'cc'*32,
    }
    mapping = {'snapshot':'snapshot_path', 'manifest':'manifest_path',
               'public_key':'public_key_path','signature':'signature_path',
               'pin':'trusted_key_sha256','challenge':'challenge'}
    data[mapping[missing]] = None
    with pytest.raises(ValueError, match='requires'):
        assess(tmp_path/'no-such-apk', **data)


@pytest.mark.skipif(not APK.exists(), reason='local APK unavailable')
def test_dev80_native_only_and_synthetic_manifest(tmp_path):
    result = assess(APK)
    assert result['attestation_supplied'] is False
    assert result['production_mappings_changed'] is False
    assert result['missing_capture_artifacts'] == [
        'runtime_snapshot', 'stage_manifest', 'detached_signature_and_trust_pin']
    other = assess(APK, SNAPSHOT, MANIFEST)
    assert other['attestation_supplied'] is False
    assert other['dev79_stage_manifest_assessment']['stage_manifest_assessment']['status'].startswith('synthetic')


@pytest.mark.skipif(not APK.exists(), reason='local APK unavailable')
def test_attestation_with_real_apk_and_synthetic_input(tmp_path, sample):
    _, public, signature, challenge, raw = sample
    pub = tmp_path/'public.bin'
    sig = tmp_path/'signature.bin'
    pub.write_bytes(public)
    sig.write_bytes(signature)
    result = assess(APK, SNAPSHOT, MANIFEST, pub, sig, hashlib.sha256(public).hexdigest(), challenge)
    assert result['attestation_supplied'] is True
    assert result['attestation_assessment']['detached_signature_valid']
    assert result['missing_capture_artifacts'] == []
    assert result['production_paint_mapping_verified'] is False
    serialized = json.dumps(result)
    assert signature.hex() not in serialized
    assert challenge not in serialized
    assert 'capture_id' not in serialized


@pytest.mark.skipif(not APK.exists(), reason='local APK unavailable')
def test_cli_refuses_overwrite(tmp_path):
    existing = tmp_path/'occupied.json'
    existing.write_text('do not overwrite')
    with pytest.raises(SystemExit):
        main(['--apk', str(APK), '--output',str(existing)])
    assert existing.read_text() == 'do not overwrite'


def test_no_private_keys_bundled_in_dev80_code():
    path = ROOT / 'csr2cdn/_research/dev80_capture_attestation.py'
    code = path.read_text()
    assert 'Ed25519PrivateKey' not in code
    assert 'network_requests' in code
