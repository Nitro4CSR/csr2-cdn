# Dev75 — Gacha eligibility, delivery result, and configuration-index guards

## Provenance and strict scope

This bounded offline analysis uses the supplied CSR2 6.8.0 APK. The complete `SceneManagerGarage.CarLoaded` native body is SHA-256 pinned, and three newly named managed methods are independently resolved through IL2CPP metadata tokens. All previously established Dev74, Dev73 and Dev72 source-specific checks run before the new evidence is emitted.

The investigation observes **no game execution**, real player state, ordered car-specific paint list, or live gacha branch outcome. A purely synthetic decision model demonstrates possible branch outcomes under hypothetical register and object values. This is not full interprocedural, heap, or runtime analysis. Null-object/exception paths are not represented by the synthetic model; it addresses the normal non-null case only.

## Upstream value is a delivery-list method result

The managed pointer of the direct call at `0x361269C` is `PlayerProfile.PopCarIfInDeliveryWaitingList` (`0x34E68F8`). The call passes a garage key from `[x20+#0x18]`. Its 64-bit return in `x0` is preserved into `x26`; the low word is treated as signed for the gate. From the instructions alone, the semantic meaning of the packed result is not fully established; no delivery transaction was invoked by this analyzer.

A second direct call, `0x36126C0` → `CarVisualsGachaConfig.IsValid` (`0x381E36C`), validates the object loaded from `[x20+#0x168]` only if byte `[x20+#0x160]` is nonzero. Validity bit `1` clears the fallback condition; validity bit `0` follows a special comparison of the signed word `[x20+#0xB0]` with `-2147483648`.

## Bounded eligibility predicate

In a normal non-null continuation, the Boolean at `0x36126F4` follows:

```
positive = signed32(low32(popResult)) > 0
fallback = (garageByte0x160 != 0) and (not IsValid(garageObj0x168)) \
           and (signed32(garageWord0xB0) == -2147483648)
enter_gacha_candidate_path = positive or fallback
```

The failed gate jumps to `0x3612808`, skipping the gacha setup block. The gate has **no direct source-enum compare**. This does not exclude source influence inside callees or in the runtime objects. In particular, a previously verified `Tutorial=1` source check within `CarVisuals.Setup` does not determine this separate earlier Boolean.

When `positive`, `0x3612708`–`0x361270C` derives the proposed **gacha configuration index** from the signed upper 32 bits of the return. Otherwise it selects configuration index `0`. This is not `CarGarageInstance`'s paint index and must not be used to infer a paint ID.

Before `CarVisuals.ApplyGachaConfig` at `0x36127AC`, further runtime-dependent skip conditions include:

| Native site | Conditional bypass |
| --- | --- |
| `0x361273C` | configuration index is negative |
| `0x3612740` | opaque downstream filter's low bit is set |
| `0x3612758` | configuration index is at least list count |
| `0x3612770` | selected configuration entry is null |

The callsite passes the garage instance at `0x36127A0` and a Boolean based on the pop result at `0x36127A4`. On the normal call-return path, the one-shot garage flag `+0x160` is cleared at `0x36127B0`. None of these sites records whether the Tutorial Mustang actually entered this path.

## Falsifiable input scenarios

Dev75 tests a deliberately small pure-Python model for hypothetical inputs, including zero/positive/negative signed low words; valid/invalid fallback; `INT32_MIN` exact match; configuration index `0`, negative index, in-range and out-of-range indices; secondary rejection and null entry. The model and report label every scenario as **synthetic only**, and the flags `actual_pop_result_observed`, `actual_gacha_branch_outcome_observed` and `runtime_ordered_paint_list_captured` remain false.

## Production consequence and next gate

The `Tutorial=1` exclusion of the two `CarVisuals.Setup` paint-list append sites and the two setup garage-index writebacks remains valid. Dev75 narrows the gacha eligibility input and branch conditions; it does **not** exclude the gacha paint-list append or possible earlier index writeback identified in Dev74. Nor does it resolve aftermarket mutation, later profile reapplication, or any live ordered paint list.

Paint index `15` → paint ID `1323` (Ford Dark Highland Green) remains a **conditional candidate derived from prior Unity-bundle evidence**; the current APK-only run does not revalidate those bundles. Paint index `0` is unresolved. No production resolver/mapping has changed.

For decisive verification, obtain a legitimate, read-only observation of the Mustang's garage flag, the pop-result and any gacha call outcome, plus the ordered `CarVisuals.CarPaintIDs` and selected paint index immediately before the positional lookup. Keep the post-setup `PlayerProfile.UpdateCarVisuals` paint refresh as a separate observation point. Do not infer live values from Dev75's symbolic scenarios.

## Offline reproduction

```bash
python -m csr2cdn.dev75_gacha_eligibility \
  --apk CSR2_6.8.0.apk \
  --output dev75-gacha-eligibility-evidence.json
```

The CLI fails closed on altered APK hashes/instructions/managed pointers, refuses to overwrite existing reports, and writes no network or player-identifying data. The APK, external Unity bundles, and private cache are not distributed in the project archive/wheel.
