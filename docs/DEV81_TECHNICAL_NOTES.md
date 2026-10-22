# Dev81 technical notes — Signed cross-capture consistency

**Version:** `0.7.1.dev81`  
**Target:** CSR2 6.8.0 ARM64 APK  
**Investigation:** Offline consistency checks between 2–8 separately signed Dev78 snapshot/Dev79 stage-manifest bundles.

## Scope

No live CSR2 runtime capture, Unity bundle, or authenticated gameplay state was supplied in this session. Dev81 therefore implements a conservative **correlation gate**, not an instrumented runtime observer and not a definitive Mustang paint map. The native APK check remains delegated to the pinned Dev77 audit. Dev78 validates the observed fields, Dev79 anchors the events/hashes, and Dev80 checks Ed25519 signatures bound to manifest bytes and a verifier-supplied challenge.

Dev81 enforces pairwise distinct **capture-label hashes, raw snapshot hashes, raw manifest hashes, signer public-key hashes and challenge hashes**. A repeated value causes failure, rather than a false claim of two independent captures. Different values do *not* establish reviewer, device or session independence: one submitter could trivially regenerate keys, challenges, labels and whitespace.

For each accepted bundle it derives an observation vector containing the gacha-call flag, selected gacha configuration, predicted native gate, ordered paint-list SHA-256 at lookup and post-refresh, selected paint index at both points, and resolved/observed paint IDs. Disagreement labels remain explicit. Stage changes within a capture prevent a positive agreement status even if all submitted captures show the same change. Missing, inconsistent, or out-of-range evidence never yields a verified mapping.

## Verification

After the final regression test adjustment, test collection contained **2,040 items**. Five disjoint batches returned **1,993 passes, 47 skips and 0 failures** (the 47 skips depend on missing external fixtures). **All 31 focused Dev81 tests passed**. Tests cover signature/header manipulation, signed JSON tampering, native stage anchors, differing paint IDs, paint order, selected indices, gacha outcomes, repeated capture material, and safety invariants.

An independently installed wheel reports `csr2cdn.__version__ == importlib.metadata.version('csr2-cdn') == 0.7.1.dev81`. The source tree and installed wheel produce byte-identical reports for:

- The pinned APK-only offline diagnostic, **784 bytes**.
- Two synthetic signed capture bundles with ephemeral test-only keys, **4,419 bytes**.

Both synthetic bundles deliberately encode `15 -> 1323`; no live paint-list state was captured. Signatures and stage checks can be valid on synthetic data without implying real gameplay. No private signing keys were persisted or bundled. The signed synthetic fixture's public keys and signatures were generated under a temporary test directory outside the distributables.

## Current conclusion

**All production mapping flags are false.** The candidate Ford Dark Highland Green (`1323`) at paint index `15` remains conditional; index `0` remains unresolved. The actual Tutorial Mustang gacha eligibility, paint-list order, post-refresh state and independently trusted runtime origin remain outstanding.

The next meaningful milestone is a permitted, non-mutating observation with independent corroboration of acquisition method, device/client identity, signer trust, issued challenges and the exact native lookup and post-refresh stages. Self-reported signed hashes cannot substitute for that review.
