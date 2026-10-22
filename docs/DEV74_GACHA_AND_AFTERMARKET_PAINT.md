# Dev74 — Native gacha configuration and aftermarket paint mutation guards

## Provenance, scope and limitations

This offline Dev74 investigation uses the user-supplied **CSR2 6.8.0 APK**, together with the existing Dev73 source provenance. It extracts the original 64-bit IL2CPP metadata and executable code from that APK and performs deterministic, SHA-pinned native instruction/branch checks. The new entrypoints are independently matched to managed IL2CPP method metadata and pointers. The historical paint-ID candidate originates in **prior** bundle-derived evidence, **not** in this APK-only run.

This is conservative, bounded, intra-method native control-flow analysis, **not** observation of live execution or a complete call-graph/heap mutation proof. Native control-flow reachability does not imply the corresponding instruction ran for a Tutorial vehicle, and a possible mutation is not a demonstrated mutation of the real car. Method calls are modeled as returning to their callsites; their side effects are not generally analyzed. No private roster, Unity bundles, endpoint cache, authenticated gameplay or network access was used.

## New SHA-pinned native methods

| Managed method | Native RVA | Span | SHA-256 of bounded method body |
|---|---:|---:|---|
| `CarVisuals.ApplyGachaConfig` | `0x38012A4` | `0x78C` | `0615fa062139322cc5345057f1d7436dd241f5d038278c73cca372621e3d8116` |
| `CarVisuals.AddAftermarketPaintsToCar` | `0x3818CDC` | `0x204` | `52cc34693b48a400e8fc287441b441b5cc37874266a90878ea6a48205150ea64` |

Managed method tokens in IL2CPP metadata resolve to these addresses, and the bounded executable method bytes match the pinned fingerprints. Their control-flow analyses include all documented mutation instructions. Method sizes describe **bounded spans** in this exact APK, not portable method size across game versions.

## Finding A: Gacha configuration is a possible **pre-setup** modifier

`SceneManagerGarage.CarLoaded` has runtime eligibility/index guards at `0x36126F4` and `0x3612758`, before its gacha call at `0x36127AC`. The eligibility check can branch directly to `0x3612808`; on that path the scene can continue into the normal `CarVisuals.Setup` call at `0x36129D8` without applying gacha. Other runtime guard outcomes can allow the gacha call. No verified Tutorial-source check excludes or enforces this call. The actual conditions for the specific Mustang cannot be evaluated without the relevant runtime state.

Within `CarVisuals.ApplyGachaConfig` itself, the following instructions are reachable in different possible native paths:

| RVA | Instruction-level effect |
|---|---|
| `0x38012CC` | Preserve the `CarGarageInstance` argument passed by the scene |
| `0x38014A0` | Store a selected existing paint-list index to `CarVisuals+0x11C` |
| `0x3801584` | Possible paint-ID insertion into the paint list at `CarVisuals+0x70` |
| `0x3801690`, `0x3801798` | Other visual component-list insertions (`CarVisuals+0x88` and `+0x90`); **not** evidence of paint-list insertions |
| `0x38015C0` | Store a selected last-list index to `CarVisuals+0x11C` |
| `0x38015C8` | Directly call `ForceUpdateOfCarPaint` |
| `0x3801858` | Guard on the presence of a garage-instance argument |
| `0x3801878` | Copy `CarVisuals+0x11C` into `CarGarageInstance+0x6C` |

This is a new **possible earlier writeback** to the garage paint index, distinct from the two setup-body writebacks excluded by Dev72/73. The setup-body proof still stands, but does not prohibit the gacha method from updating the value **before** setup begins. There is no evidence that this writeback happened for the specific Tutorial Mustang.

## Finding B: The aftermarket append is conditional and membership-guarded

Inside `ForceUpdateOfCarPaint`, the method reads the selected paint index (`0x380B5F0`), obtains the `CarVisuals+0x70` list count (`0x380B60C`), and compares them at `0x380B610`. The in-range branch at `0x380B614` skips the aftermarket call and joins at `0x380B63C`. If the index is outside the existing list range, `0x380B61C` calls `AddAftermarketPaintsToCar`; the method then reloads/rechecks the index and list count, branching away at `0x380B638` if still outside range. When valid, paint ID is retrieved by position at `0x380B648`.

`AddAftermarketPaintsToCar` iterates a runtime-provided set of candidate paint IDs; at `0x3818E44` it calls a list-membership-style helper, branches past insertion if the helper returns true (`0x3818E48` to `0x3818EB8`), or appends the missing paint ID at `0x3818E9C`. The method is capable of extending the list, but the native evidence **does not reveal the car-specific candidate IDs, list count, or whether an append occurred**.

## Consequences for paint index 15

- The static `Tutorial=1` branch proof is unchanged: within `CarVisuals.Setup`, the two known early paint-list insertion sites and the two known garage-index writebacks remain bypassed.
- Dev74 demonstrates separate possible **pre-setup** gacha mutations and a **conditional** aftermarket append during paint refresh. The former can also write back to the garage selected index.
- These new possibilities do not invalidate the earlier conditional candidate `15 → 1323` (Ford Dark Highland Green), but they prevent promotion without a live ordered car-local list or sufficient proof excluding those paths for this car.
- Paint index `0` remains unresolved. No production mapping is changed.

## Decision gate for a subsequent investigation

Capture the **legitimately accessible, read-only** ordered `CarVisuals.CarPaintIDs` at the positional getter, along with the actual selected index and whether gacha/aftermarket paths ran, or use sufficient further offline static evidence to prove those paths inapplicable. Keep scene initialization, paint refresh and subsequent profile reapplication as separate observation points. Do not infer the car-specific final list from bounded reachability alone.

## Offline reproduction

```bash
python -m csr2cdn.dev74_gacha_paint_mutation \
  --apk CSR2_6.8.0.apk \
  --output dev74-gacha-paint-evidence.json
```

CLI fails closed on mismatched native fingerprints/instructions and refuses to overwrite existing reports. It produces small stable JSON without network calls or player identifiers.
