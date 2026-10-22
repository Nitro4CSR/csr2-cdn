# Dev65 — CarInfo bundle loading chain and current-asset candidate

This note is an offline inspection of the **supplied CSR2 6.8.0 APK** and a
SHA-256-verified copy of the official **database 34011** public asset index.
It does not connect to CSR2 servers and does not read user/crew records.

## Native findings

- `CarDatabase.SetupCarDatabaseAsync` builds the coroutine that can load or
  prepare data used by `CarDatabase`.
- `CarDatabase.CarInfoBundleReady` calls `CarDatabase.SetupCarDatabase`
  at `0x30641ac` (`BL 0x3064210`).
- The `SetupCarDatabaseAsync.MoveNext` coroutine also calls the same setup
  method at `0x306db68`.
- `CarDatabase.SetupCarDatabase` iterates car records and reads byte offset
  `0x21` at `0x30646f8` (`ldrb w8, [x21, #0x21]`). It branches on the byte.
- `CarGarageInstance.get_IsTunerStarsCar` independently reads byte offset
  `0x21` at `0x347644c` from the `CarInfo` returned by `CarDatabase.GetCar`.
- These two uses provide **independent corroboration of the record byte offset**,
  over and above the IL2CPP field-name evidence in Dev64.
- The exact value of this flag for `Ford_Mustang302_1970` has **not** been observed.

## Public asset candidate — contents unverified

The verified database-34011 index includes an asset with the exact code
`CarMetadata`, version `1594`, asset type `7`, with ASTC size `2,157,014`
bytes (about 2.06 MiB). The package's own `CDN.url_for()` generates:

https://csr2.cdn.zynga.com/ANDROID/ASTC/CarMetadata.ASTC.1594

This asset was **not** present among the cached public downloaded assets.
Its presence in the official index **does not prove** it contains `CarInfo`
records or the Tuner Stars flag. A fresh public CDN fetch was attempted but
this execution environment could not resolve the CDN host. Inspect the
contents of the exact versioned asset before making that claim.

There are both `car_metadata` and `car_information` managed-string names in
IL2CPP metadata, so equating an asset label with a record schema without
inspection would be premature.

## Paint mapping remains conditional

Prior work's replay still gives index 15 -> paint ID `1323` — Ford Dark
Highland Green **if** the game's runtime paint options and initialization
match that reconstruction and the relevant Tuner Stars/restoration branches.
Dev65 **does not verify** that condition or change production paint labels.
The `Transparent` alias for zero is withdrawn.

## Run offline

```bash
python -m csr2cdn.dev65_carinfo_bundle_target \
  --apk CSR2_6.8.0.apk \
  --cache-zip endpoint-cache.zip \
  --output dev65-carinfo-bundle-evidence.json
```

No APK, downloaded Unity bundle, private ZIP, login material or player data is
included in the Dev65 source/wheel releases. The report contains only
fingerprinted method evidence and public asset-index metadata.
