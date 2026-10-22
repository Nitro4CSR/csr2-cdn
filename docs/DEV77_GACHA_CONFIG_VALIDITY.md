# Dev77 — Native gacha configuration validity sentinel predicate

## Scope

CSR2 6.8.0 **offline APK-only** ARM64 / IL2CPP analysis. The tool invokes all pinned Dev72–Dev76 audits before inspecting `CarVisualsGachaConfig.IsValid` at native RVA `0x381E36C`. This managed pointer is already independently validated via IL2CPP method metadata in Dev75. Dev77 hashes its contiguous `0x44`-byte method body, checks all 17 instructions, the four integer-field load operands and three conditional branch targets. Changes fail closed.

This is a source-independent validity check, not proof that the Tutorial Mustang entered gacha, that a particular configuration object existed, that any paint ID was appended, or that index `15` resolved to paint ID `1323`. No private state, gameplay requests or runtime captures are involved.

## New technical finding

The method `CarVisualsGachaConfig.IsValid` loads four 32-bit values at object offsets `+0x1C`, `+0x20`, `+0x24`, `+0x28` in order, comparing each to `INT32_MAX` (`0x7FFFFFFF` = `2147483647`). The first three fields use `B.NE` to return literal `true` immediately on the first non-sentinel. The fourth uses `CSET W0, NE` and returns that Boolean. Thus on the **normal non-null object path**:

```
IsValid(config) = (field_1c != 0x7fffffff) or
                  (field_20 != 0x7fffffff) or
                  (field_24 != 0x7fffffff) or
                  (field_28 != 0x7fffffff)

not IsValid(config) = all four fields equal 0x7fffffff
```

The four fields are **configuration members, not an observed paint list, paint index or Tutorial-specific setting**. The routine directly reads neither the paint list nor the source classification. Null input and exceptional callers are not interpreted.

Method fingerprint SHA-256: `28dbb5049711491008f44b0fc7c2f55edc816f39c6a1f045053177b11f2b808e`.

| Native site | Evidence |
| --- | --- |
| `0x381E36C` | `LDR W9, [X0,#0x1C]` |
| `0x381E378` | `B.NE 0x381E3A8` (early true) |
| `0x381E37C` | `LDR W9, [X0,#0x20]` |
| `0x381E384` | `B.NE 0x381E3A8` (early true) |
| `0x381E388` | `LDR W9, [X0,#0x24]` |
| `0x381E394` | `B.NE 0x381E3A8` (early true) |
| `0x381E398` | `LDR W9, [X0,#0x28]` |
| `0x381E3A0` | `CSET W0, NE` (result for final compare) |
| `0x381E3A8` | `MOV W0,#1` (true shared branch) |

## Interaction with Dev75 fallback

The flag-mediated fallback previously identified at `SceneManagerGarage.CarLoaded` requires **all** of:

```
flag_0x160 != 0
IsValid([garageInstance+0x168]) == false
signed32(garage_word_0xB0) == INT32_MIN
```

Dev77 now makes the `IsValid` part explicit: **all four** configuration sentinel fields must equal `INT32_MAX` on a valid, non-null object. Independently, a positive signed low 32-bit word of `PopCarIfInDeliveryWaitingList` can still qualify the Dev75 gate even if `IsValid` is true. Further config-index bounds, secondary rejection and missing-entry guards continue to apply before `ApplyGachaConfig`; eligibility is not evidence the call happened. The synthetic model illustrates these cases and labels each as synthetic. It also fixes secondary filter to false purely for illustration: this is **not** an observed value.

## Production gate still outstanding

No actual configuration field values or delivery tuple for the Mustang were supplied. The actual branch outcome, ordered paint list, selected paint index before positional lookup, and post-setup `UpdateCarVisuals` state are unknown. Candidate paint ID `1323` remains a **conditional** reconstruction from earlier materials not supplied with Dev77; paint index `0` remains unresolved. Production mappings are unmodified. A decisive check requires a legitimate, non-destructive runtime snapshot at the relevant stages, without replaying the mutating delivery-pop method.

## Offline reproduction

```bash
python -m csr2cdn.dev77_gacha_config_validity \
  --apk CSR2_6.8.0.apk \
  --output dev77-gacha-validity-evidence.json
```

The output is deterministic, bounded, SHA-pinned, and refuses an existing file or symlink. The packaging excludes the APK, Unity bundles, private profile inputs, and network caches.
