# Dev73 — Tutorial paint-list preappend exclusion and later paint reapplication

## Inputs and evidence grade

All new Dev73 checks need **only** the locally supplied CSR2 6.8.0 APK. They extract original 64-bit IL2CPP metadata and ARM64 native code offline, verify the previously pinned Dev72 CFG and source enum, check managed method tokens against native pointers, pin the added native method bodies by SHA-256, then check exact ARM64 words/BL targets. No Unity bundle, private roster file, endpoint cache, authenticated request or network activity is required. The separate, earlier static candidate `15 → 1323` is carried forward with an explicit **not revalidated** marker; it is not evidence from this APK-only run.

This work has not executed the game, observed crew-specific runtime branch outcomes, or captured a live ordered paint list. A control-flow edge being reachable is **not** proof that it executed. Unmodeled calls, cross-method side effects and subsequent frame callbacks remain open.

## Extended native CFG results

Dev72 established `eCarSource.Tutorial=1`, `0x38029C0` falling back to `IsIAP`, and `0x3802B98` falling through to common setup, reducing reachable `CarVisuals.Setup` instructions from **1,008** to **759**. Dev73 reuses the same SHA-pinned method and constrains exactly those two source-classification branches, taking both successors of all other modeled conditional branches.

| Instruction (RVA) | Instruction purpose | Any-source CFG | Tutorial CFG |
|---|---|---|---|
| `0x3802AA8` | Early pre-selection paint-list append from Dev60 | Reachable | **Bypassed** |
| `0x380309C` | Fallback pre-selection paint-list append from Dev60 | Reachable | **Bypassed** |
| `0x3802C10` | Garage paint-index writeback from Dev72 | Reachable | **Bypassed** |
| `0x380370C` | Other garage paint-index writeback from Dev72 | Reachable | **Bypassed** |
| `0x38035F4` | `SetupAftermarketLockedData` direct call | Reachable | Reachable |
| `0x38036A0` | `ForceUpdateOfCarPaint` direct call | Reachable | Reachable |

The first two results are *new* compared with Dev72: both concrete Dev60 insertion instructions lie exclusively in the branches bypassed for Tutorial. This does not show that all paint-list mutations are impossible. In particular, `ForceUpdateOfCarPaint` can call `AddAftermarketPaintsToCar` (`0x380B61C`) before its positional paint-ID retrieval (`0x380B648`). Whether and what it appends depends on runtime state.

## Additional crew-scene path

`SceneManagerGarage.CarLoaded` includes a **conditional** call to `CarVisuals.ApplyGachaConfig` at `0x36127AC`, located before the `CarVisuals.Setup` call at `0x36129D8`. A CFG continuation after setup can reach a later `PlayerProfile.UpdateCarVisuals` direct call at `0x3612A5C`. Dev73 fingerprints the following independently identified native methods:

- `PlayerProfile.UpdateCarVisuals` at `0x34E8864`, SHA-256 `39f53b4c81abe94c9d314cb86f2ef41aa8f16f9699bc27eda42b8f520fe3114e` over `0x344` bytes.
- `PaintApplier.ApplyTo` at `0x3805BE4`, SHA-256 `70284525cdeb528bb897abd25edbf157ceea52bb9f0fe9964c34e49da743eab0` over `0x40` bytes.

At `0x34E897C`, `PlayerProfile.UpdateCarVisuals` reads the garage selected paint index from `CarGarageInstance+0x6C`. At `0x34E8988` it invokes `PaintApplier.ApplyTo`. That helper compares `CarVisuals+0x11C` with the requested index, can store the requested index at `0x3805C08`, and can call `ForceUpdateOfCarPaint` again at `0x3805C0C`.

This establishes an additional **possible reapplication of the same garage index** after initial setup, not an observed mutation to the list or a proof that it was executed for the Tutorial car. The gacha branch and possible later callbacks still require investigation. The current 30-entry static candidate, its physical source asset identity and the selected paint are **not** verified as the live runtime list.

## Result and remaining decision gate

**No production mappings are promoted.** Index 15 retains the historical conditional paint ID **1323 — Ford Dark Highland Green**; index 0 remains **unresolved**. Dev73 does not include the raw APK or any private/cache/bundle data.

The next decisive check is a legitimate read-only capture of the actual car-local ordered `CarVisuals.CarPaintIDs` **immediately before the paint lookup**, with the selected index, after any applicable gacha/aftermarket initialization and before/after profile paint reapplication. Alternatively, a sufficiently exhaustive static proof of list construction, gacha branch exclusion and lack of post-setup mutation could establish equivalence. No invasive game modifications or new authenticated gameplay interactions were used here.

## Reproduce offline (APK only)

```bash
python -m csr2cdn.dev73_tutorial_paint_list_paths \
  --apk CSR2_6.8.0.apk \
  --output dev73-tutorial-paint-list-evidence.json
```

The CLI refuses to overwrite an existing file and emits a redacted, stable JSON report. It does not download or open private endpoint/roster inputs.
