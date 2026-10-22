# Dev80 — Offline detached Ed25519 attestation for capture manifests

**Client:** CSR2 6.8.0 ARM64 APK. **Package:** `csr2-cdn 0.7.1.dev80`.
**Goal:** verify an externally supplied digital signature over one Dev79 manifest and a separately provided verifier challenge. This feature is optional and disabled when signature inputs are absent. Neither the module nor its fixtures collect gameplay state.

## What is verified

The Dev79 evaluator first runs the pinned Dev72–77 APK-native audit, validates the Dev78 snapshot as strict JSON, and verifies the Dev79 manifest's raw snapshot and APK hashes, per-stage canonical digests, ordered observation markers and native RVAs. Dev80 adds cryptographic verification of a **detached Ed25519 signature** over an exact-message preimage:

```text
ASCII("csr2cdn.dev80.capture-attestation.v1") || 0x00
|| verifier_challenge_as_exact_32_raw_bytes
|| SHA256(manifest_file_exact_raw_bytes)_as_32_raw_bytes
```

The Ed25519 public key is a **32-byte raw public key file**, the signature is a **64-byte raw signature file**, and the challenge is 64 lowercase hexadecimal digits for 32 verifier-selected bytes. `--trusted-key-sha256` is the 64-lowercase-hex SHA-256 digest of the exact 32-byte public-key file, **obtained independently of the bundle submitter**. The validator refuses missing groups of options; challenge, signature, public key, and pin must be provided together with both snapshot and manifest. All inputs are local. The public key may be published; **never share a private key**.

A signer with access to a separately protected Ed25519 private key may compute the exact message bytes defined above and sign them using any conforming Ed25519 implementation. Dev80 does not sign, generate, load, export, or store private keys. Dev80's tests create ephemeral keys only in memory and discard them; **no example signatures or private keys are bundled**. A legitimate signature on synthetic data still proves only signature validity, not gameplay provenance.

Signing the raw manifest means that byte-changing whitespace modifications invalidate the signature. The manifest already binds raw snapshot and APK bytes by SHA-256. Dev80 rechecks the manifest bytes across the native/stage check and rechecks snapshot and APK hashes before accepting the signature, to detect file substitution during validation. Input key/signature readers use descriptor-based bounded regular-file reads and `O_NOFOLLOW` where available, and outputs refuse overwrite.

## Reproduce without an attestation

```bash
python -m csr2cdn.dev80_capture_attestation \
  --apk CSR2_6.8.0.apk \
  --output dev80-attestation-evidence.json
```

This produces native-only evidence with `attestation_supplied: false` and leaves production verification false. To evaluate an externally collected, passive snapshot and accompanying Dev79 manifest **with a separately signed challenge**, supply all six inputs:

```bash
python -m csr2cdn.dev80_capture_attestation \
  --apk CSR2_6.8.0.apk \
  --snapshot snapshot.json \
  --manifest stage-manifest.json \
  --public-key reviewer-ed25519-raw-public.bin \
  --signature reviewer-ed25519-raw-signature.bin \
  --trusted-key-sha256 YOUR_OUT_OF_BAND_PUBLIC_KEY_SHA256 \
  --challenge YOUR_VERIFIER_ISSUED_32_BYTE_HEX_CHALLENGE \
  --output dev80-attestation-evidence.json
```

Install Ed25519 verification support with `pip install 'csr2-cdn[attestation]'` or install `cryptography>=41` in the offline environment. Ed25519 signing in tests is performed using `cryptography`, but the normal APK-only diagnostic does not require this optional dependency.

The verifier should obtain the trusted public-key fingerprint from a trusted channel **not controlled by the capture submitter**, generate a fresh unpredictable challenge **before** the capture/signature exchange, and retain an independent record of its issuance and freshness. Dev80 can only verify that the signed message contains the supplied challenge, **not** whether the challenge was fresh, who chose it, or whether the key was trusted externally.

## Threat model and limits

- A valid signature establishes that the signature key's holder signed these exact manifest bytes in the context of the challenge, subject to standard cryptographic assumptions. It does **not** prove the signature is from a known reviewer unless the verifier independently trusted the public key.
- The key pin and challenge are command-line values, not immutable external trust anchors. Supplying a new self-selected public key, matching self-selected fingerprint, and signature is **not** independently authenticated provenance.
- A signed manifest can still describe a fabricated or incomplete snapshot. Even a trusted reviewer could sign a false self-report. Dev80 does **not** validate on-device instrumentation, true game execution, stage timestamps, or actual display output.
- The `dev78`/`dev79` synthetic examples still contain intentionally fabricated index `15 -> 1323`; they are not evidence for production. No real Mustang runtime capture is present. Index `0` remains unresolved.
- The tool never calls mutating delivery-pop methods, makes network/authenticated gameplay requests or changes production resolver mappings. Output never includes keys, signatures, unredacted capture labels or raw ordered paint-list arrays.

Production report booleans `production_paint_mapping_verified`, `production_mappings_changed`, `independent_runtime_origin_verified`, and `actual_gameplay_capture_independently_authenticated` (when attestation exists) always remain false.

## Future evidence gate

To verify a production mapping, obtain a legitimate, non-mutating capture of the actual Tutorial Mustang's gacha decision and ordered paint list at the lookup and after refresh, with independent confirmation of the capture method, stage alignment and signer identity. A detached signature and challenge help protect a capture bundle in transit but do not replace that evidence.
