# Dev68: `CarLoader` override paint selection — CSR2 6.8.0

## Input / provenance

Native method entry points and ARM64 instruction fingerprints are pinned to the supplied operator-owned `CSR2_6.8.0.apk`. The report also uses the operator-owned current `CarMetadata.ASTC.1594` and `Ford_Mustang302_1970_common.ASTC.14` plus SHA-256-cached public metadata and db34011 paint catalogue. No server or authenticated requests. The source/wheel never contain those game assets or any private roster.

## Confirmed call chain

Compiled metadata lists `CarLoader.LoadCar(garageCar, carDetailsOverride)`, `CarLoader.CarLoaded(info, nodeIndex, car, carDetailsOverride)` and `CarLoader.SetupCarVisuals(info, car, carDetailsOverride)`. Native `LoadCar` at `0x2eb7b84` retains the second argument; the `CarLoaded` callback at `0x2eb8478` retains its fourth argument and passes it as the third argument at `0x2eb84d0` to `SetupCarVisuals`, called at `0x2eb84d4`. The relevant native bodies were SHA-256 fingerprinted and the managed metadata method pointer entries verified.

## Observed conditional dispatch

| Native location | Observation |
|---|---|
| `0x2eb7fc0` | Null `carDetailsOverride` branches around override-specific paint selection to `0x2eb8120`; the normal setup path remains available |
| `0x2eb7fc4` | Reads an override's explicit paint-index-like field from `+0x20` |
| `0x2eb7fc8` | Materializes `2147483647` sentinel; if index differs, branches to index setter path |
| `0x2eb7fd4` | If index is sentinel, reads paint-ID-like field at `+0x10` |
| `0x2eb8134` | Direct call `CarVisuals.set_CurrentPaintIndex` at `0x3806278` |
| `0x2eb814c` | Direct call `CarVisuals.SetPaintIDAddIfNecessary` at `0x3813de4` |
| `0x2eb8154–0x2eb8158` | Copies selected `CarVisuals.CurrentPaintIndex` to garage car at `+0x6C` |
| `0x2eb8328` | Continues with `CarVisuals.Setup` at `0x380275c`, so no override does **not** mean no further paint mutation |

The parameter name and two native code paths strongly distinguish an **index override** from an **ID override**. The interpretation of internal override field semantics is supported by the called API, but field declaration names have not been independently recovered.

## Exact scope

The trace **does not yet establish** that a crew-member vehicle is displayed via `CarLoader` nor whether its `carDetailsOverride` is populated. Other runtime paint-list operations (initial visual setup, restoration unlockables, race-scene helpers, customization changes) remain possible. Numeric `car_paint_id` from crew JSON must not be substituted for either override field without a separate serialization/source join.

The uploaded current Ford Mustang visual asset plus native aftermarket append ordering still conditionally maps index 15 to paint ID `1323` — Ford Dark Highland Green. This is **not a captured rendered paint** and must not become an unconditional production label. Crew paint index 0 is unresolved; the previous `Transparent` assumption stays withdrawn.

## Next verification

Trace the crew display scene's actual loader invocation (including whether it uses `CarLoader.LoadCar` or direct `CarVisuals.Setup`) and any `carDetailsOverride` creation. If one is supplied, inspect whether its paint index or paint ID is `INT_MAX`, and what value is passed. A read-only local runtime capture of the ordered `CarVisuals.CarPaintIDs` (if obtainable without invasive changes) would independently settle the selected paint.

## Reproduce

```bash
python -m csr2cdn.dev68_loader_paint_overrides --apk CSR2_6.8.0.apk \
  --car-metadata-bundle CarMetadata.ASTC.1594 \
  --visual-bundle Ford_Mustang302_1970_common.ASTC.14 \
  --cache-zip endpoint-cache.zip --source-catalog dev36-source-ids.json \
  --paint-index 15 --output dev68-evidence.json
```

The report contains no player identifiers and never invokes network clients.
