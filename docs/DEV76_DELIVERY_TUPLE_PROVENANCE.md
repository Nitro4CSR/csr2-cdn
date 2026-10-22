# Dev76 — Offline provenance of delivery-return pair and list consumption

## Scope and provenance

This is a **CSR2 6.8.0 APK-only** static IL2CPP ARM64 audit, chained through the Dev75, Dev74, Dev73 and Dev72 native checks. `PlayerProfile.PopCarIfInDeliveryWaitingList` is independently identified using the Dev75 IL2CPP managed method-pointer check at `0x34E68F8`. Its complete bounded span `0x34E68F8`–`0x34E6AF7` (0x200 bytes) is SHA-256 pinned. A separate eight-byte pair constructor at `0x49AFFB0` is pinned. More than thirty exact native instructions, their direct-call destinations and four branch edges must match before evidence can be written.

This is not a game execution trace, source-level decompilation of every callee, private profile dump, complete interprocedural proof or paint-list capture. No live player data, car state, endpoint cache or Unity bundles were supplied for Dev76. The pair's real values, lookup index, gacha outcome and painted appearance remain unobserved.

## Verified native behavior

The normal path of `PlayerProfile.PopCarIfInDeliveryWaitingList` accesses two profile-related list fields via the player's object at `+0x740` and `+0x748`. It requires both lists' counts to be nonzero, and a lookup at `0x34E6A00` to return a nonnegative 32-bit index. On that path:

1. Both list-item read calls (`0x34E6A44`, `0x34E6A64`) explicitly pass **position 0**, not the computed lookup index.
2. The returned first value is passed as constructor `w1`, and the returned second value as `w2` into `0x49AFFB0` at `0x34E6A7C`. The constructor's single `STP W1, W2, [X0]` stores the two adjacent 32-bit words in little-endian order.
3. Both list-removal calls (`0x34E6AA0`, `0x34E6ABC`) explicitly pass **the earlier computed index**, preserved in `w20`, not the hard-coded item-read position 0. The callee at `0x4A73A84` decrements the list count and performs element shifting when necessary, supporting its interpretation as a removal routine.
4. The no-entry path constructs `(-1, -1)` at `0x34E6AD8`, with the returned packed 64-bit value loaded at `0x34E6ADC`. Invalid/null-object paths are exceptional and not reconstructed by the synthetic model.

The upstream scene uses the signed low 32 bits of this packed return for its positive-value gacha eligibility condition. When positive, it uses the signed upper 32 bits as the tentative **gacha configuration index**. Neither field is thereby a paint ID or direct indication of the garage paint index.

### Why the mismatch between read position and removal index matters

If the computed index is nonzero, **the values returned to the gacha eligibility gate are from position 0 while the two consumed elements are from the computed index**. This is a pinned native distinction, not an assertion about whether that state occurred for the Mustang. A synthetic example with first list `[111,222]`, second list `[2,7]` and computed index `1` returns `(111,2)` while leaving `[111]` and `[2]` in the two lists. The example is deliberately not a real game observation.

Repeatedly invoking `PopCarIfInDeliveryWaitingList` as a debugging probe could change the very lists being tested. A future runtime verification, when authorized and available, should use **non-mutating observation** of actual list contents and selected visual paint state instead.

## What the APK does not establish

- Whether the Tutorial Mustang appears in either real delivery list.
- The list counts, computed lookup index or actual packed delivery result.
- Whether the gacha branch executed and whether `ApplyGachaConfig` inserted any paint ID or wrote back a garage paint index.
- The complete paint-list order at the positional lookup or subsequent profile-driven paint refresh.
- Any production verified mapping for paint index 15 or paint index 0.

The prior conditional replay **index 15 → ID 1323 (Ford Dark Highland Green)** remains only a candidate. It derives from earlier Unity evidence **not present or replayed in Dev76**. Production mappings and network/service behavior are unchanged.

## Reproduce offline

```bash
python -m csr2cdn.dev76_delivery_tuple_provenance \
  --apk CSR2_6.8.0.apk \
  --output dev76-delivery-tuple-evidence.json
```

The diagnostic refuses to overwrite an existing output, fails closed on mismatched native hashes/words/calls/branches, and emits only bounded source-independent facts plus explicitly synthetic examples. It performs no network or authenticated gameplay requests and distributes no APK, bundles or endpoint cache.
