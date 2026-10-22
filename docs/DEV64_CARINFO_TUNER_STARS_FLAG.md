# Dev64 — CarInfo Tuner Stars field provenance

## Verified

The CSR2 6.8.0 IL2CPP metadata declares `CarInfo.IsTunerStarsCar`. The compiled `CarGarageInstance.get_IsTunerStarsCar` calls `CarDatabase.GetCar` at `0x3065390` with the garage car key and tests the returned record byte at `0x21`. The `CarDatabase.CarInfoBundleReady` native callback invokes `SetupCarDatabase`. Native callsites and pinned method fingerprints are verified.

## Missing

The private roster exposes source `Tutorial` and level 50. Public pricing and milestone metadata confirm `EliteCustoms_FTUECar`, but these do not encode the per-car Tuner Stars flag. The cached database 34011 asset index contains 23,882 descriptors, none with an obvious `CarInfo` asset code; this **does not** prove that CarInfo is unavailable under a different asset key or within an embedded/included resource. The field offset is corroborated by its use in the getter but has not been independently resolved from IL2CPP field-offset metadata.

## Conditional paint replay

The best-supported static reconstruction selects ID `1323` (Ford Dark Highland Green) at Mustang paint index 15 **if** the loaded `CarInfo.IsTunerStarsCar` flag allows aftermarket setup and no other runtime mutation changes the order. This is not a verified runtime paint and must not be committed as a production mapping. No inference from `Tutorial`, FTUE configuration, or car model name is sufficient.

## Reproduction

```bash
python -m csr2cdn.dev64_carinfo_tuner_flag \
  --apk CSR2_6.8.0.apk \
  --bundle Ford_Mustang302_1970_common.ASTC.14 \
  --private-cache-zip endpoint-cache.zip \
  --source-catalog dev36-source-ids.json \
  --output dev64-evidence.json
```

The tool makes zero HTTP or authenticated gameplay requests and reports no private player identifiers. Inputs are supplied locally by the operator and never included in the source archive or wheel.
