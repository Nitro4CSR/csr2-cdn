# Dev66: Current Unity 2022 CarInfo bundle and Tuner Stars guard

The operator supplied `CarMetadata.ASTC.1594` from the **database 34011**
asset index, alongside the earlier CSR2 6.8.0 APK and
`Ford_Mustang302_1970_common.ASTC.14`. This source is not in the package.

- UnityFS **v8**, `2022.3.62f2`, one `CAB-CarMetadata` asset, 115 LZ4 blocks;
  serialized Unity file **v22**, little-endian, with embedded type trees.
- Exactly **1,278** `CarInfo` records decoded; the serialized bool layout
  has independent four-byte alignment after each boolean. 25 records have
  `IsTunerStarsCar = true` and 1,253 have `false`. All 1,278 embedded
  `m_Name` and `Key` strings match; this also sanity-checks field alignment.
- The `Ford_Mustang302_1970` record explicitly states
  **`IsTunerStarsCar = false`**. `NeedsRestoration = false` is another
  serialized boolean; it does **not** override the separately verified
  50-level FTUE milestone pricing scheme, nor does it prove the game skips
  the restoration `HasMilestonesForCar` check.
- The native getter reads the managed runtime record's **byte at +0x21**;
  that runtime heap offset **must not be conflated** with the on-disk
  serialized field location. The current record and native lookup are
  separately verified.
- `CarPricingCompact` and `CarMilestoneData` from the SHA-256-verified
  capture associate the Mustang with `EliteCustoms_FTUECar`, levels 1–50.
  This supports a milestone-positive path, but does not capture the game's
  loaded manager dictionary or measure the predicate's return.
- The earlier native-backed append replay still yields
  **paint index 15 → paint ID 1323, Ford Dark Highland Green**, conditional
  on the current bundle's `AllUnlockables` ordering and no further runtime
  mutation. The Tuner Stars guard uncertainty is now resolved **in the
  current static record**, but the live rendered paint list is not captured.
- No conclusion is made for paint index `0` on other vehicles; the earlier
  "Transparent" display assumption remains withdrawn.

## Reproduce offline

```bash
python -m csr2cdn.dev66_carinfo_paint_join \
  --car-metadata-bundle CarMetadata.ASTC.1594 \
  --visual-bundle Ford_Mustang302_1970_common.ASTC.14 \
  --apk CSR2_6.8.0.apk \
  --cache-zip endpoint-cache.zip \
  --source-catalog dev36-source-ids.json \
  --paint-index 15 \
  --output dev66-carinfo-paint-evidence.json
```

Pass only `--car-metadata-bundle` and `--output` for independent extraction
without APK or cache. Requires optional `lz4>=4` (included in the
`events` extra). No network, authenticated requests, player-data export,
production mapping edits, or copies of user assets in distributions.
