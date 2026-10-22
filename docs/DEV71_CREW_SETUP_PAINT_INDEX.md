# Dev71 — Exact crew visual setup arguments and paint-list lookup

Scope: original CSR2 6.8.0 ARM64 `libil2cpp.so` and matching `global-metadata.dat`; current provided `CarMetadata.ASTC.1594`, `Ford_Mustang302_1970_common.ASTC.14`, and pre-existing public cached scheme/catalogue. No game requests, no live execution. The SDK report is **static code verification** and a *conditional* list reconstruction.

## Verified native signatures and data flow

The managed metadata declares `CarVisuals.Setup(carInstance, updateCarInstance)`. At `SceneManagerGarage.CarLoaded` native RVAs `0x36129c8`/`0x36129d0`/`0x36129d8`, the caller places `True` in `w2`, the garage car object in `x1`, and directly calls `CarVisuals.Setup` at `0x380275c`.

`CarVisuals.Setup` keeps the boolean in `w20` (`0x3802780`), stores the car reference (`0x38028a4`), and may prepare aftermarket milestone state at `0x38035f4`. Its final paint update compares the garage index `car+0x6C` against the visual index `visuals+0x11C` at `0x3803680–0x3803688`. When mismatched or uninitialized, it stores the garage index at `0x380369c` and calls `ForceUpdateOfCarPaint` at `0x38036a0`.

`ForceUpdateOfCarPaint` reads `visuals+0x11C`, checks negative/sentinel values, and conditionally calls `AddAftermarketPaintsToCar` if the index is past the list count (`0x380b61c`). It then **re-reads the selected index**, validates its new range, and invokes the `List<int>` positional lookup (`0x380b648`) to retrieve the paint ID. The position is not a global library ID.

## Index writebacks and unresolved runtime branches

The setup method can write a matching visual-list index into the garage car (`0x3802c10`) under an earlier source-dependent visual branch, and can also write `list.Count-1` at `0x380370c` along a separate fallback path. These are real conditional code sites, not evidence those branches were taken by the Tutorial-source Mustang. `updateCarInstance=True` also enables garage-car synchronization in other visual slots. The branch source checks previously traced in Dev61 still apply.

## Paint 15

With four base paint IDs plus the signed-filtered, de-duplicated unlockables from the supplied current vehicle bundle, the static replay selects position 15 -> `1323` / **Ford Dark Highland Green**. The valid current `CarInfo` flag excludes Tuner Stars handling for this car. However, the live list and branch outcomes were not captured. Do not install 1323 as a production label without further validation. Roster index 0 is also unresolved; the prior `Transparent` alias has been withdrawn.

## Reproduction

```sh
python -m csr2cdn.dev71_crew_setup_paint_selection \
  --apk CSR2_6.8.0.apk \
  --car-metadata-bundle CarMetadata.ASTC.1594 \
  --visual-bundle Ford_Mustang302_1970_common.ASTC.14 \
  --cache-zip endpoint-cache.zip \
  --source-catalog dev36-source-ids.json \
  --paint-index 15 \
  --output dev71-evidence.json
```

The analyzer verifies bounded method SHA-256 hashes, managed method-to-native pointers, compiled parameter names and 22 exact ARM64 instruction words, then composes earlier Dev70 native and Dev66 bundle checks. It neither writes to the game nor reads secrets, and does not distribute the APK, bundles, private cache or roster records.
