# Dev56: Unity CarVisualConfigs source evidence (offline)

The `Everything/x.CarVisualConfigs/ConfigFiles` archive published by Nitro4CSR contains *Unity-extracted* `CarVisuals` text for individual cars. These files expose ordered `CarPaintIDs`, `CarInteriorIDs`, `CarCalliperIDs`, livery and wheel arrays, plus independent `GachaConfigs` records. Source: https://github.com/Nitro4CSR/CSR2-DataBase/tree/Everything/x.CarVisualConfigs

## Provenance and age

The archived file used for the investigation was `x.CarVisualConfigs/ConfigFiles/Ford_Mustang302_1970.txt`, Git blob SHA-1 `e9bb0570d3770e009615920238cedb5f1a736f5e`; its most recent GitHub commit for this file is dated August 20, 2021. **This does not prove it is the file used by the 6.8.0 client in October 2026.** The repo's original text export is a *source example*, not bundled in this package.

The archived visual config contains four base paint IDs (1156, 451, 1159, 1160) and 11 gacha configurations with 11 distinct paint IDs in their union (there are four base/gacha overlaps). All 11 distinct paint identifiers are present in the independently cached standard or TNR paint libraries at database 34011. The base arrays also include the sampled roster's interior and caliper IDs. The observed wheel-name suffix occurs in seven gacha presets, but not the single base wheel entry. These are actual *source coincidences* and do not establish the client runtime selection.

The archived base array is four items long, so a received paint value of 15 is **not a valid zero-based index into that archived base array**. Do not treat the 11 gacha records as 11 positions appended to the base list: the actual `CarVisuals.Setup` and aftermarket pathways may alter the runtime list, and the archive may be stale. Also, the independently observed livery ID in the roster is not present in the archived config; this illustrates that the vehicle's visual state can differ from historic source options.

## Command

Place a Unity-exported per-car `.txt` file on disk (do not place private roster JSON into this package). Optionally provide the public Dev36 source-ID catalogue:

```sh
python -m csr2cdn.dev56_car_visual_configs \
  --config-file /private/selected-car-config.txt \
  --source-catalog dev36-source-ids.json \
  --paint-index 15 \
  --interior-id 66 \
  --calliper-id 4 \
  --wheel-name ExampleCar_Wheel2A_3D \
  --output dev56-source-evidence.json
```

The optional observed values are operator-provided and should not be construed as the latest state of a live roster. The regular report does not emit a model key, roster identities or wheel strings. It prints no raw source arrays or untrusted paint names. Input is local only: zero network and gameplay requests, 4 MiB extracted-config limit, symlinks rejected, manifest counts checked, and no overwrite of existing report.

## Validity boundary

* `CarPaintIDs[index]` can only be an **archived base-array candidate**. It is never returned as a verified roster mapping.
* Gacha preset `PaintID`, `InteriorID`, `CalliperID`, `WheelBundleName` and livery fields are stored as distinct attributes; gacha configurations are **not** entries to append in order.
* Interior/caliper numeric checks and wheel-suffix presence can strengthen a cross-field hypothesis, but must not be confused with a runtime join.
* Source-catalogue presence means numeric identifiers exist in the appropriate official library. It does not prove eligibility or a paint-index conversion.
* The archive last changed years before the current 6.8.0 client. The decisive next source is the contemporary `<car>_common.ASTC` or equivalent visual config for the selected vehicle, then its runtime extension/order logic.
* The withdrawal of the earlier `0 -> Transparent` assumption remains in force. No production mapping changes are made.

The intended next investigation is a bounded, read-only **current public CDN** retrieval of that exact car's common visual bundle, followed by a Unity extraction and a SHA-256-proven comparison with the historical config. No crew read is necessary if the vehicle model key is recovered privately from the existing cached roster.
