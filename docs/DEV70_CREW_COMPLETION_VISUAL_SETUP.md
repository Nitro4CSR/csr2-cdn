# Dev70 — crew car completion to visual initialization (CSR2 6.8.0)

## Input and evidence limits

Pinned against the operator-supplied CSR2 6.8.0 APK's IL2CPP metadata and ARM64 native method pointers. No gameplay, network or authenticated operations are needed. A static method body does **not** expose the running car's exact cosmetic list or prove all indirect / subsequent mutations absent.

## Native path

- `SceneManagerGarage.LoadPlayerCrewCar` copies `CrewMemberCarInfo.CarPaintIndex` into the new garage car selected paint-index field, then invokes `GarageCarLoader.Load` (Dev69).
- `GarageCarLoader.CarLoaded` (`0x33BD754`) has a state-guarded asset-request call (`0x33BD8E4`) and can tail-call `GarageCarLoader.AssetRequestCompleted` at `0x33BCD80` (`0x33BD94C`).
- `GarageCarLoader.AssetRequestCompleted` (`0x33BCD80`) has both asynchronous asset-load (`0x33BCE8C`) and synchronous-completion (`0x33BCEBC`) paths. These load/dispatch events are not themselves the rendered paint selection.
- `SceneManagerGarage.CarLoaded` (`0x3612398`) calls `GarageCarVisuals.Setup` at `0x361292C` (target `0x33C13E0`), then `CarVisuals.Setup` at `0x36129D8` (target `0x380275C`). It can call `ReadyToShowCarWithSnapshot` afterward at `0x3612A08`.
- `GarageCarVisuals.Setup` stores car references and directly invokes `CarVisuals.SetShaderLod`, `ToggleLighting`, `ToggleKeywordRaceMode` and `HideManufacturerPlate` at the inspected sites. This is a different named method from `CarVisuals.Setup` and from generic `CarLoader.SetupCarVisuals`. A lack of a direct insert call in the inspected helper does not exclude indirect paint changes.

The precise delegate wiring between the asynchronous loader callbacks and `SceneManagerGarage.CarLoaded` remains unverified; callsites within each named method are independently verified.

All four new inspected methods are matched back to the managed IL2CPP method token and SHA-256 fingerprinted; 16 exact ARM64 instruction sites / branch targets are checked, and a mismatched APK fails closed.

## Implications for paint index 15

The car-specific base/unlockables replay is unchanged: under the known Tutorial car source, current CarInfo and cached milestone scheme, **index 15 conditionally yields ID 1323 (Ford Dark Highland Green)**. The newly traced completion path shows that crew loading reaches `CarVisuals.Setup`, so the previously studied paint-list initialization is relevant, and generic CarLoader override logic should not be substituted automatically. No runtime paint-list capture or full indirect-call coverage has been performed. Therefore **no production mapping is asserted**.

Received paint index `0` is unresolved, and the former `Transparent` alias is withdrawn.

## Reproduce

```bash
python -m csr2cdn.dev70_crew_completion_path \
  --apk CSR2_6.8.0.apk \
  --car-metadata-bundle CarMetadata.ASTC.1594 \
  --visual-bundle Ford_Mustang302_1970_common.ASTC.14 \
  --cache-zip endpoint-cache.zip \
  --source-catalog dev36-source-ids.json \
  --paint-index 15 \
  --output dev70-evidence.json
```

The evidence JSON contains only static native addresses and redacted vehicle-level inference. Do not distribute the operator's APK, Unity bundles or private endpoint cache.

## Remaining target

Trace `CarVisuals.Setup` and `ForceUpdateOfCarPaint` under the crew-specific call arguments, accounting for the loaded `LockedCustomisationData` object and any indirect callback/list modification that could shift the selected paint index. Production promotion requires an actual verified runtime ordering or other equivalently decisive evidence.
