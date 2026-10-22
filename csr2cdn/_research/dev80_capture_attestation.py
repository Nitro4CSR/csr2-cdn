"""Dev80: optional detached Ed25519 verification for offline capture bundles.

A signature binds an externally provided challenge and exact raw manifest bytes.
The Dev79 manifest in turn binds snapshot bytes and local APK bytes. The
verifier's out-of-band trust in the public key and challenge, and truthfulness
of instrumented runtime events, CANNOT be established by this program.
No private keys are loaded, generated, or stored in production code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from .dev79_capture_provenance import assess as assess_dev79, read_bounded_json, sha256_file

DOMAIN = b'csr2cdn.dev80.capture-attestation.v1\x00'
HEX64 = re.compile(r'[0-9a-f]{64}\Z')


def _digest_hex(value: Any, label: str) -> str:
    if type(value) is not str or not HEX64.fullmatch(value):
        raise ValueError(label + ': expected 64 lowercase hexadecimal characters')
    return value


def read_exact_regular_file(path: Path, expected_bytes: int) -> bytes:
    """Bounded descriptor-based reads, with symlink rejection where available."""
    flags = (os.O_RDONLY | getattr(os, 'O_BINARY', 0) |
             getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('attestation input must be a regular file')
            result = stream.read(expected_bytes + 1)
    except OSError as exc:
        raise ValueError('cannot read local attestation file') from exc
    if len(result) != expected_bytes:
        raise ValueError(f'attestation input must be exactly {expected_bytes} bytes')
    return result


def signature_message(raw_manifest: bytes, challenge_hex: str) -> bytes:
    """Stable, unambiguous domain-separated signature preimage."""
    challenge = bytes.fromhex(_digest_hex(challenge_hex, 'challenge'))
    return DOMAIN + challenge + hashlib.sha256(raw_manifest).digest()


def verify_attestation(raw_manifest: bytes, public_key_bytes: bytes,
                       signature_bytes: bytes, challenge_hex: str,
                       trusted_key_sha256: str) -> dict[str, Any]:
    """Verify signature and externally supplied key pin, not gameplay origin."""
    key_hash = hashlib.sha256(public_key_bytes).hexdigest()
    if key_hash != _digest_hex(trusted_key_sha256, 'trusted_key_sha256'):
        raise ValueError('public key fingerprint differs from verifier-supplied pin')
    if len(public_key_bytes) != 32 or len(signature_bytes) != 64:
        raise ValueError('Ed25519 key must be 32 bytes and signature must be 64 bytes')
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise ValueError('cryptography is needed for attestation; install csr2-cdn[attestation]') from exc
    try:
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
            signature_bytes, signature_message(raw_manifest, challenge_hex))
    except (InvalidSignature, ValueError) as exc:
        raise ValueError('detached Ed25519 signature verification failed') from exc
    return {
        'status': 'ed25519_signature_valid_with_externally_supplied_key_pin_not_runtime_authentication',
        'signature_scheme': 'Ed25519',
        'signature_domain': DOMAIN[:-1].decode('ascii'),
        'raw_manifest_sha256': hashlib.sha256(raw_manifest).hexdigest(),
        'public_key_sha256': key_hash,
        'verifier_challenge_sha256': hashlib.sha256(bytes.fromhex(challenge_hex)).hexdigest(),
        'detached_signature_valid': True,
        'public_key_fingerprint_matches_input_pin': True,
        'challenge_bound_to_signed_payload': True,
        'out_of_band_key_trust_independently_established': False,
        'challenge_freshness_independently_established': False,
        'actual_gameplay_capture_independently_authenticated': False,
        'game_execution_stage_alignment_independently_verified': False,
        'production_paint_mapping_verified': False,
        'production_mappings_changed': False,
    }


def assess(apk: Path, snapshot_path: Path | None = None,
           manifest_path: Path | None = None,
           public_key_path: Path | None = None,
           signature_path: Path | None = None,
           trusted_key_sha256: str | None = None,
           challenge: str | None = None) -> dict[str, Any]:
    supplied = [public_key_path, signature_path, trusted_key_sha256, challenge]
    if any(v is not None for v in supplied) and (not all(v is not None for v in supplied)
            or snapshot_path is None or manifest_path is None):
        raise ValueError('attestation requires --snapshot, --manifest, --public-key, --signature, --trusted-key-sha256 and --challenge together')
    # Keep raw manifests stable across the underlying validation; a separate
    # signature must not be checked against a replacement manifest.
    raw_manifest_before = None
    if public_key_path is not None:
        _, raw_manifest_before = read_bounded_json(manifest_path)
    dev79 = assess_dev79(apk, snapshot_path, manifest_path)
    attested = None
    if public_key_path is not None:
        manifest, raw_manifest = read_bounded_json(manifest_path)
        if raw_manifest_before != raw_manifest:
            raise ValueError('manifest changed during validation')
        if hashlib.sha256(read_bounded_json(snapshot_path)[1]).hexdigest() != manifest['snapshot_sha256']:
            raise ValueError('snapshot changed during validation')
        if sha256_file(apk) != manifest['apk_sha256']:
            raise ValueError('APK changed during validation')
        key = read_exact_regular_file(public_key_path, 32)
        signature = read_exact_regular_file(signature_path, 64)
        attested = verify_attestation(raw_manifest, key, signature, challenge, trusted_key_sha256)
    return {
        'status': 'dev80_offline_detached_capture_attestation',
        'client': 'CSR2 6.8.0',
        'dev79_stage_manifest_assessment': dev79,
        'attestation_supplied': attested is not None,
        'attestation_assessment': attested,
        'missing_capture_artifacts': (
            ['runtime_snapshot', 'stage_manifest', 'detached_signature_and_trust_pin']
            if snapshot_path is None else
            ['stage_manifest', 'detached_signature_and_trust_pin']
            if manifest_path is None else
            ['detached_signature_and_trust_pin'] if attested is None else []
        ),
        'conditional_index_15_paint_candidate': 1323,
        'paint_index_0_runtime_mapping_verified': False,
        'independent_runtime_origin_verified': False,
        'production_paint_mapping_verified': False,
        'production_mappings_changed': False,
        'network_requests': 0,
        'authenticated_gameplay_requests': 0,
        'gameplay_state_writes': 0,
        'private_capture_echoed_to_report': False,
        'provenance_limitation': 'Valid signatures bind files and a supplied challenge to a key, not actual gameplay observation or external trust in the signer.',
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--public-key', type=Path, help='External Ed25519 public key file: 32 raw bytes')
    parser.add_argument('--signature', type=Path, help='External Ed25519 detached signature file: 64 raw bytes')
    parser.add_argument('--trusted-key-sha256', type=str, help='Expected SHA-256 key fingerprint obtained out of band')
    parser.add_argument('--challenge', type=str, help='Verifier-provided fresh 32-byte challenge as 64 lowercase hex digits')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        parser.error('refusing to overwrite existing evidence output')
    try:
        result = assess(args.apk, args.snapshot, args.manifest, args.public_key,
                        args.signature, args.trusted_key_sha256, args.challenge)
        body = json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2) + '\n'
        if len(body.encode('utf-8')) > 160_000:
            raise ValueError('evidence report exceeds limit')
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(body)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print('Dev80: offline attestation check complete; no production mapping promoted.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
