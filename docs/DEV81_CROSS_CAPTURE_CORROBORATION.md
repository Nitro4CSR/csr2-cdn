# Dev81 — Offline cross-capture comparison

**Pinned target:** CSR2 6.8.0 ARM64 APK. **Version:** `csr2-cdn 0.7.1.dev81`.

Dev81 adds a bounded, optional **comparison of 2–8 separately signed Dev78/79 snapshot/manifest bundles**. It does not capture gameplay, attach to the client, or observe paint lists. The only local game binary input is the already-supplied APK, validated against the pinned Dev72–77 native chain.

## Evidence chain

Each six-part `--capture` group supplies, in this exact order:

1. **Snapshot JSON:** Dev78 schema, local regular UTF-8 file (up to 128 KiB).
2. **Manifest JSON:** Dev79 stage manifest, with hash of exact snapshot bytes, hash of APK, canonical section digests, ordered events and native anchor addresses.
3. **Ed25519 public key:** 32-byte raw local file (never a private key).
4. **Ed25519 signature:** 64-byte detached signature over `dev80_domain || challenge_bytes || sha256(raw_manifest_bytes)`.
5. **Trusted key SHA-256:** 64 lowercase hexadecimal characters, obtained independently of bundle submitter.
6. **Challenge:** externally issued 32-byte challenge as 64 lowercase hex characters.

Dev81 verifies every file using the existing Dev78/79/80 validators before comparing. All bundles must bind to the *same exact local APK* and its pinned native methods. The comparison requires **distinct capture-label hashes, raw snapshot file hashes, raw manifest file hashes, public-key hashes, and challenge hashes**, rejecting repeated bytes or keys. These are only *duplicate-detection heuristics*: reformatting JSON, generating a new key or relabeling a fabricated capture can satisfy them.

It compares separately reported gacha-call occurrence, candidate configuration index and native-gate result; canonical ordered paint-list SHA-256 at both lookup and post-refresh; selected paint indices; indexed paint IDs; and supplied observed-versus-indexed-ID agreement. Within a submission, a changed list, changed index or changed resolved ID between lookup and refresh prevents a positive agreement status. Missing stage observations, out-of-range indices, contradictory paint IDs or inconsistent manifests fail closed or yield an incomplete assessment. Cross-bundle disagreements are **reported**, not silently accepted.

The report emits compact hashes, derived observations and discrepancy labels, **not raw lists, exact capture labels, raw keys, signatures or challenges**. The signed-file verification may be true while all production-verification flags remain false.

## Reproduce

Without external captures, run the pinned native audit only:

```bash
python -m csr2cdn.dev81_capture_corrob \
  --apk CSR2_6.8.0.apk \
  --output dev81-cross-capture-evidence.json
```

With **two fully supplied, independently sourced** capture sets:

```bash
python -m csr2cdn.dev81_capture_corrob \
  --apk CSR2_6.8.0.apk \
  --capture snapshot-A.json manifest-A.json reviewer-A-pub.bin signature-A.bin \
    TRUSTED_A_KEY_SHA256 VERIFIER_A_CHALLENGE \
  --capture snapshot-B.json manifest-B.json reviewer-B-pub.bin signature-B.bin \
    TRUSTED_B_KEY_SHA256 VERIFIER_B_CHALLENGE \
  --output dev81-cross-capture-evidence.json
```

Use `pip install 'csr2-cdn[attestation]'` for Ed25519 verification support. Missing `--capture` arguments are a native-only check, not an empty proof of corroboration. Supplying just one capture or more than eight causes an error; the tool will not overwrite existing reports.

## Limits and trust boundary

- **Different public keys do not prove distinct human reviewers or distinct devices.** A single actor can control multiple keys, choose challenges, rewrite timestamps, and sign fabricated evidence. Dev81 cannot independently authenticate challenge issuance, reviewer identity, device integrity, actual gameplay execution, or passive instrumentation.
- Matching ordered-list hashes and paint observations can show **internal consistency among submitted signed claims**; this is not independently verified runtime mapping. The status `self_reported_signed_submissions_agree_origin_not_authenticated` means precisely that.
- Bundled synthetic tests intentionally use `15 → 1323` and must never be treated as capture evidence. Both index `15 → 1323` and index `0` remain production-unverified. The code never updates production mappings.
- The CLI makes no network or authenticated gameplay requests and performs no gameplay state writes. The source ZIP/wheel must not include the APK, Unity bundles, private caches, raw user snapshots, private keys, or temporary signatures.

## Next evidence milestone

Obtain legitimate read-only captures from independent observers or independently trusted acquisition systems, preserve out-of-band trust records for each key/challenge, and verify what each system actually measured at the native paint lookup and after refresh. Cryptographic agreement *supplements* but does not replace that external provenance review.
