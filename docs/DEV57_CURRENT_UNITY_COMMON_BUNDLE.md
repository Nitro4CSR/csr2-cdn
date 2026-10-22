# Dev57 — Current CSR2 6.8.0 per-car UnityFS source comparison

The operator supplied the **actual indexed bundle** `Ford_Mustang302_1970_common.ASTC.14` (127,413 bytes; SHA-256 `17372f965b71d39281cca0436dd5ad1bccba55414b8c34568a7cdcc388b33a90`). It is UnityFS v6 using Unity's raw-LZMA1 block encoding; its single 574,352-byte Unity serialized file has version 17 and embedded type trees. The package contains an offline parser for the required MonoBehaviour types. **Neither bundle bytes, game APK, account/crew cache nor authenticated tokens are distributed.**

The current `CarVisuals` object was fully decoded (656/656 bytes) and a second object with `UnlockableMilestones` and `AllUnlockables` was fully decoded (2,756/2,756 bytes).

## Verified results

* Current ordered `CarPaintIDs`: `[1156, 451, 1159, 1160]`. `15` is **out of range** for this base list.
* All six base arrays exactly match the [Nitro4CSR 2021 archived Ford Mustang 302 config](https://github.com/Nitro4CSR/CSR2-DataBase/blob/Everything/x.CarVisualConfigs/ConfigFiles/Ford_Mustang302_1970.txt): paint, interior, caliper, livery, livery-zone set and wheels. Archive blob SHA-1: `e9bb0570d3770e009615920238cedb5f1a736f5e`.
* All 11 gacha preset records match the historical source **for paint, interior, caliper and wheel, in the same order**; `lockPaintsToIndex` is still zero. These are presets and should not be auto-appended to base array order.
* The additional `AllUnlockables.carPaintIDs` contains 39 array entries: **30 distinct valid paint IDs** and **nine `-1` separators**. The uploaded current asset also has 36 `UnlockableMilestones` records, six unlocked interior IDs, six caliper IDs and grouped wheel variants.
* All 30 nonseparator unlockable paint IDs exist in independently cached standard paint library records from database 34011. This is source presence, **not roster value verification**.
* At raw unlockables index 15, the element is **`-1`**, i.e., a group divider. If we discard `-1` and artificially take filtered index 15, the numeric paint ID is **1246**, labelled *Ford Velocity Blue* in the independently cached paint library. **There is no evidence the crew resolver uses that filtered list or order**, so this must not become a roster mapping.

## Remaining gap

We need to trace **which list the client consults when it applies `CrewMemberCarInfo.CarPaintIndex`** for this vehicle, including any unlocked customization and append ordering. Its input can depend on actual runtime customization state, not just bundle static asset groups. The uploaded file verifies the contemporary raw data, but does not justify promoting a global paint ID assignment for roster value `15` (or `0`).

## Offline reproduction

```sh
python -m csr2cdn.dev57_unity_carvisuals \
  --bundle Ford_Mustang302_1970_common.ASTC.14 \
  --source-catalog dev36-source-ids.json \
  --output dev57-current-bundle-evidence.json
```

The parser is deliberately limited to this bundle generation: UnityFS v6 / Unity serialized v17 with embedded type trees. Input size is limited; output will not overwrite an existing file. LZMA support uses only the Python standard library; lz4 is required separately only if input uses LZ4 blocks. No network or gameplay calls occur.
