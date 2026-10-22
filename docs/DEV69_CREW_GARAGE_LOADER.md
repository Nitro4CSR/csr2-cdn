# Dev69: Native crew hangout / garage-car loader path (CSR2 6.8.0)

## Verified APK evidence

`CrewHangoutScreen.ReloadHangoutCars` directly calls `SceneManagerGarage.RefreshCrewMemberCarsWhileInEnvironment` at native address `0x396ACD8`. The latter is a refresh method; it does *not* directly call `LoadPlayerCrewCar` in the fingerprinted body. A distinct `SceneManagerGarage.LoadCrewMemberCarsOnStart` method calls `SceneManagerGarage.LoadPlayerCrewCar` at `0x361524C`. This is a documented set of closely related scene paths, not a claim of an uninterrupted synchronous call chain across refresh and startup.

`SceneManagerGarage.LoadPlayerCrewCar` copies the crew `CarPaintIndex` at `CrewMemberCarInfo + 0x20` into a newly allocated garage car's selected paint index at `CarGarageInstance + 0x6C` (instructions `0x3616A94` and `0x3616A9C`). It also copies crew interior and caliper IDs from `+0x24` and `+0x28` to garage offsets `+0x7C` and `+0x84`, respectively. No paint ID lookup occurs in these consecutive copy instructions.

After populating the garage car's fields and restoration/gacha information, the same native method constructs `GarageCarLoader` at `0x3616C08`, then tail-branches into `GarageCarLoader.Load` at `0x3616CD0`. `GarageCarLoader.Load` calls `CarPartsLoader.LoadParts`, as well as several separate accessory loading methods. It is **not** the `CarLoader.LoadCar` method whose `carDetailsOverride` dispatch Dev68 previously studied. Therefore Dev68's override branches do not, without additional evidence, describe the initial crew-car load.

The five version-pinned native method bodies and 12 exact ARM64 sites are checked against the original compiled metadata, method-pointer table, SHA-256 hashes and branch destinations. This audit is fail-closed for a changed APK and contains no private identities.

## Still unresolved

This trace proves the *initial handoff* of the crew paint index; it does not prove that `GarageCarLoader` completion callbacks or `CarVisuals` later use the unchanged ordered paint list. We have **not** captured the live paint ID, displayed finish, or post-load selected index. Dev58–66's static reconstruction still conditionally yields **ID 1323 — Ford Dark Highland Green** for the Tutorial Mustang's index 15. This is not a production mapping. Roster paint index 0 remains unresolved. No former "Transparent" color-label hypothesis is reinstated.

Next target: inspect `GarageCarLoader.CarLoaded`, `AssetRequestCompleted`, and `SceneManagerGarage.CarLoaded`, especially whether any source-ID insertion or index write follows the initial crew-index copy. If we can prove no qualifying mutation in the relevant path, the reconstruction becomes stronger without authenticated gameplay requests.

## Run offline

```bash
python -m csr2cdn.dev69_crew_garage_loader \
  --apk CSR2_6.8.0.apk \
  --car-metadata-bundle CarMetadata.ASTC.1594 \
  --visual-bundle Ford_Mustang302_1970_common.ASTC.14 \
  --cache-zip endpoint-cache.zip \
  --source-catalog dev36-source-ids.json \
  --paint-index 15 --output dev69-evidence.json
```

All user-provided files and cached roster data are excluded from source and wheel distributions. This analysis performs no network or authenticated requests.
