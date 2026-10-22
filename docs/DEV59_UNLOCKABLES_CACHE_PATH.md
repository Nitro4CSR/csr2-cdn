# Dev59 — Native `LockedCustomisationData` cache fast path

## Source and reproducibility

Analyzed the operator-supplied CSR2 6.8.0 APK (pinned IL2CPP metadata/native hashes) and the operator-supplied `Ford_Mustang302_1970_common.ASTC.14` bundle (SHA-256 `17372f965b71d39281cca0436dd5ad1bccba55414b8c34568a7cdcc388b33a90`). The analyzer itself ships no proprietary binaries, gameplay response, or private cache. This is a source/compiled-code observation, **not a capture of game runtime state**.

## Native branch verification

The `LockedCustomisationData.GetAllUnlockables` method is pinned at RVA `0x3827fb4` (complete body SHA-256 `0da1ce56c00213bc3a76997c69a3cffb7074d267d938418a2fadce35cb971e4e`). It has the following directly verified instructions:

| RVA | ARM64 | Meaning |
|---|---|---|
| `0x3828074` | `ldr x0, [x21,#0x28]` | Load existing AllUnlockables field/cache |
| `0x3828078` | `cbnz x0, 0x38282e8` | **If non-null, return immediately** |
| `0x3828180` | `ldr x0, [x21,#0x30]` | On cache miss, read prepared milestone list |
| `0x38282c4` | `ldr x0, [x8,#0x28]` | Obtain aggregated destination on fallback |
| `0x38282e4` | `stp x26, x8, [x0,#0x28]` | Write aggregate members on fallback |

The cache offset/field name is corroborated by the uploaded Unity object's serialized `AllUnlockables` and `UnlockableMilestones` fields. Separately, `LockedCustomisationData.SetupMilestones` reads the source milestone list at `this+0x20`, writes the prepared list to `this+0x30`, and calls `ValidateCustomisationRewards`. `CarVisuals.SetupAftermarketLockedData` calls `SetupMilestones` at RVA `0x380dd1c`. `GetUnlockables(index)` also indexes `this+0x30`. Thus the fallback is sensitive to the setup list, but an **already non-null AllUnlockables takes priority**.

## Static-current-bundle evidence

The uploaded Unity bundle contains 4 base paint IDs (`1156, 451, 1159, 1160`) and a serialized `AllUnlockables.carPaintIDs` of 39 entries including 9 negative separators. The source also contains 10 nonempty paint milestone groups. Flattening the groups yields exactly the 30 nonnegative paint IDs from the serialized `AllUnlockables` sequence, in the same order.

The Dev58 verified native append algorithm skips negative IDs and already-present IDs. Applying it to the deserialized source list gives 30 total car-local paint IDs and **index 15 -> ID 1323**, labelled **Ford Dark Highland Green** by the public database 34011 source. This is a **stronger conditional inference** than Dev58, because the native code's direct-return path means it need not rebuild the array from milestone state when the serialized field is intact. It is still *not* an observed live roster paint selection.

## Why the other path matters

If the `AllUnlockables` cache field is absent/cleared, the method constructs a list from prepared milestones. Synthetic sensitivity checks show index 15 may differ if paint groups are excluded (e.g., `131` rather than `1323` when certain preceding groups are omitted). These are stress-test scenarios and **not claims that restoration progression actually removes such groups**. We have no direct observation of whether runtime components are replaced, edited, or influenced by other car-specific initialization before the paint index is resolved.

## Production disposition

- Paint roster values 0 and 15 remain **unresolved** as verified labels.
- ID 1323 is a **static+native conditional candidate**, not an automatic crew field mapping.
- Twenty numeric roster-vs-library matches are not upgraded to index-verified joins.
- No source resolver or production cosmetic mappings changed, no crew cache read, no authenticated game calls, no HTTP.

## Offline reproduction

```bash
python -m csr2cdn.dev59_milestone_unlockables \
  --apk CSR2_6.8.0.apk \
  --bundle Ford_Mustang302_1970_common.ASTC.14 \
  --source-catalog dev36-source-ids.json \
  --paint-index 15 \
  --output dev59-milestone-cache-evidence.json
```

`--source-catalog` is optional. This diagnostic is pinned to the tested APK/bundle hashes and refuses overwriting an existing report.
