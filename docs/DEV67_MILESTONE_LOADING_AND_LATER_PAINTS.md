# Dev67 — Milestone-manager load routes and later paint-list mutations

## Scope and verified inputs

This research uses the operator's **CSR2 6.8.0 APK** (ARM64 IL2CPP), the current `CarMetadata.ASTC.1594` and `Ford_Mustang302_1970_common.ASTC.14` Unity bundles, the SHA-256-manifest-verified public portions of `endpoint-cache.zip`, and the public paint-ID catalogue from database **34011**. It has **no HTTP, game or authentication interactions**. No player identities are exported.

## Native method fingerprints

Six exact APK methods are SHA-256 verified, with 15 pinned ARM64 instruction sites. The offline diagnostic checks both instruction bytes and the resolved branch destinations of direct calls. Any altered relevant method body fails closed. The report contains the addresses and SHA-256 fingerprints to reproduce this trace.

### CarMilestoneDataManager loading

- `OnConfigLoadedFromJson` conditionally dispatches into `LoadDataFromJson` (`0x2e280a0`).
- `OnConfigLoadedFromBinary` calls `LoadDataFromBinary` (`0x2e276e8`).
- `LoadDataFromJsonDict` includes two calls into `LoadSchemeFromDict` (`0x2e28ac0`). These are native code paths for populating schemes from configuration, not an observation that they ran in the specific session.
- The current public `CarPricingCompact` record references scheme `EliteCustoms_FTUECar`; the matching `CarMilestoneData` scheme defines 50 levels. **Whether the live CarMilestoneDataManager collection contains that scheme has not been observed.**

### Paint insertions outside the main setup method

Four *observed direct callsites* of `CarVisuals.SetPaintIDAddIfNecessary` are at:

| Native address | Caller | Significance |
|---|---|---|
| `0x2eb814c` | `CarLoader.SetupCarVisuals` | Conditional selection by paint ID, after comparison with `2147483647`. Next instructions read the visual's `CurrentPaintIndex` (`+0x11c`) and write the garage object's selected index (`+0x6c`). |
| `0x35bbc0c` | `RaceStateSetupHumanCarHelper.HumanSetupCarVisuals` | Human race-car setup supplies a computed paint argument. |
| `0x35bbe04` | `RaceStateSetupHumanCarHelper.HumanSetupCarVisuals` | A second human race-car path explicitly sets argument `w1 = 0` immediately before the paint-insertion call. **This does not explain the crew's received paint zero values.** |
| `0x35c0f38` | `RaceStateSetupAICarHelper.AiSetupCarVisuals` | AI-car race setup supplies a paint argument. |

These are native direct callsites, not a complete inventory of indirect calls or all possible list mutations. **No callsite is demonstrated to have run for the cached Tutorial Mustang when the crew snapshot was taken or rendered.**

## Conditional paint conclusion

The current Mustang `CarInfo` has `IsTunerStarsCar = false`; the public 50-level FTUE milestone scheme exists. Replaying the previously verified base-list-plus-unlockables append rule against the current bundle yields a **30-entry** candidate paint list with **index 15 → source ID 1323, Ford Dark Highland Green**.

That remains **conditional**, not a production mapping. The loaded scheme dictionary, actual post-loading list, and rendered paint ID have not been captured. The exact meaning of the other received paint index `0` is unknown; the previous `Transparent` alias has been withdrawn.

## Repeatable offline command

```sh
python -m csr2cdn.dev67_milestone_load_and_later_paints \
  --apk CSR2_6.8.0.apk \
  --car-metadata-bundle CarMetadata.ASTC.1594 \
  --visual-bundle Ford_Mustang302_1970_common.ASTC.14 \
  --cache-zip endpoint-cache.zip \
  --source-catalog dev36-source-ids.json \
  --paint-index 15 --output dev67-evidence.json
```

Dependency: optional `lz4` for current UnityFS. Original APK, Unity bundles, public source-ID catalogue and private endpoint cache are not distributed with the source ZIP or wheel. Reports omit the private roster and all player identifiers. **No production mappings are changed.**

## Next investigation

Identify whether `CarLoader.SetupCarVisuals` is the same visual object/path used to render a crew member and inspect the source of its paint-ID input, as well as the initialization order relative to `CarVisuals.Setup` and `ForceUpdateOfCarPaint`. This will help determine whether the static index-15 list is actually used for the crew car. An authenticated gameplay capture is not required for further offline tracing.
