# Dev62 — Restoration milestone initializer and cached unlockables

## Inputs and trust level

Read-only operator files: CSR2 6.8.0 APK (IL2CPP metadata/native ARM64), official-index Mustang `_common.ASTC.14` UnityFS bundle, db34011 catalogue and optionally operator-owned endpoint-cache roster. The complete APK binaries and method bodies are SHA-256-pinned by Dev58/59/61. No network, game calls, player identities or automatic resolver updates.

## Verified native path

The compiled `CarVisuals.Setup` at `0x380275c` calls the garage-car `HasMilestonesForCar` at `0x38035d0`. Its result controls `tbz` at `0x38035d4` (skip if false). It then calls `IsTunerStarsCar` at `0x38035e4` and skips at `0x38035e8` when that result is true. Otherwise it invokes `CarVisuals.SetupAftermarketLockedData` at `0x38035f4` (destination `0x380d1f8`). The two predicates were **not** measured for this crew car.

`SetupAftermarketLockedData` checks `LockedCustomisationData.get_AreMilestonesSetup` at `0x380d448`, preserves the garage object and calls `SetupMilestones` at `0x380dd1c` in the relevant setup branch. The method receives the garage object via the saved argument at `0x380dd10`. Inside the pinned `LockedCustomisationData.SetupMilestones` at `0x3827df8`, the serialized milestone list is read from offset `0x20` (`0x3827e50`) and the prepared milestone list is stored at offset `0x30` (`0x3827e88`).

**Separate object/field:** `LockedCustomisationData.GetAllUnlockables` reads its existing field at offset `0x28` (`0x3828074`), and branches directly to return if non-null (`0x3828078`). Aggregation from the prepared milestone list is a fallback only when this field is absent. This does not establish that other methods never replace or mutate the runtime `AllUnlockables` instance. The uploaded bundle serializes that field with ordered paint IDs, but live object identity has not been captured.

## Roster milestone 50 and paint selection

The single cached roster entry that matches the affected vehicle and received paint index 15 reports Tutorial source, milestone 50 and restoration-status integer 0. The Dev61 source enum excludes early-append paths restricted to Gacha/Prize/Collection/IAP; these assumptions still require that the runtime garage object retain the received source classification.

The replay of four base paint IDs plus 26 distinct nonnegative unlockable IDs yields 30 entries. Index 15 selects **1323 (Ford Dark Highland Green)** *only if* the relevant runtime initializer was called, its `AllUnlockables` field retained the supplied ordered entries, and no additional modifications shifted the paint list. There is no screenshot, renderer state, runtime field capture or client-side paint-label verification. A milestone value of 50 does not directly prove or disprove this mapping.

## Reproduction

```bash
python -m csr2cdn.dev62_aftermarket_milestone_guards \
  --apk CSR2_6.8.0.apk \
  --bundle Ford_Mustang302_1970_common.ASTC.14 \
  --source-catalog dev36-source-ids.json \
  --private-cache-zip endpoint-cache.zip \
  --paint-index 15 --output dev62-aftermarket-guard-evidence.json
```

This is offline, refuses report overwrite and emits only a privacy-safe observation. To close the gap, analyze native `HasMilestonesForCar` and `IsTunerStarsCar` return semantics for the specific garage-car object, and trace any runtime cache replacement or restoration visuals refresh before index lookup. Avoid asserting the ID 1323 label until the full runtime list can be established.
