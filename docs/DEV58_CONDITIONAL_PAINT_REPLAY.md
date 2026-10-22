# Dev58 — Conditional car-local paint index 15 reconstruction

## Inputs (all local)

- CSR2 `6.8.0` APK, two pinned IL2CPP members, with source SHA-256 checked.
- Current, operator-supplied `Ford_Mustang302_1970_common.ASTC.14` (SHA-256 `17372f965b71d39281cca0436dd5ad1bccba55414b8c34568a7cdcc388b33a90`), decoded with the Dev57 UnityFS/v17 type-tree parser.
- An optional, independently cached standard paint-ID source catalogue from branch `6_8_0_Release`, database `34011`.
- No roster or private endpoint cache is opened; zero network or gameplay requests.

## Native evidence

Exact method pointers, SHA-256-pinned bodies, and call destinations are independently verified:

| Caller | Instruction site | Callee / evidence |
| --- | --- | --- |
| `CarVisuals.Setup` | `0x38036A0` | `ForceUpdateOfCarPaint` |
| `CarVisuals.ForceUpdateOfCarPaint` | `0x380B61C` | `AddAftermarketPaintsToCar` only when a valid index is out of list range |
| `CarVisuals.AddAftermarketPaintsToCar` | `0x3818D98` | `LockedCustomisationData.GetAllUnlockables` |
| `CarVisuals.AddAftermarketPaintsToCar` | `0x3818E1C` | Skip negative unlockable entries |
| `CarVisuals.AddAftermarketPaintsToCar` | `0x3818E44` | Check for an existing paint ID in car-local list |
| `CarVisuals.AddAftermarketPaintsToCar` | `0x3818E9C` | Insert missing paint ID in append position |
| `CarVisuals.ForceUpdateOfCarPaint` | `0x380B648` | Read the selected paint ID from car-local `List<int>` using the current index |

`ForceUpdateOfCarPaint` also checks for negative paint indices and `2147483647` before selection. `Setup` runs restoration-specific initialization conditionally (`HasMilestonesForCar`, non-TNR branch). `GetAllUnlockables` has a lazily assembled/cached set of unlockable collections: it is not a proof of the actual runtime list for any given crew-car render.

## Conditional replay against actual 6.8.0 bundle

`CarPaintIDs`: `[1156, 451, 1159, 1160]` (four base values). The source `AllUnlockables.carPaintIDs` has 39 entries including nine `-1` separators. The verified native append algorithm skips negative IDs, skips IDs already in the list, and adds missing IDs *without sorting*.

Applied mechanically to **the static data**: four base IDs plus 26 appended IDs = **30 total**.

| Index | ID | Origin |
| --- | ---: | --- |
| 0 | 1156 | Base |
| 1 | 451 | Base |
| 2 | 1159 | Base |
| 3 | 1160 | Base |
| 4 | 1164 | Appended |
| 5 | 1163 | Appended |
| 6 | 1162 | Appended |
| 7 | 1157 | Appended |
| 8 | 1158 | Appended |
| 9 | 1161 | Appended |
| 10 | 1138 | Appended |
| 11 | 1251 | Appended |
| 12 | 1247 | Appended |
| 13 | 1248 | Appended |
| 14 | 129 | Appended |
| **15** | **1323** | **Appended** |
| 16 | 1246 | Appended |

Independent database `34011` standard `CarPaintLibrary` labels **1323** as **Ford Dark Highland Green**. Unlike Dev57's hypothetical `1246` result, this ordering is grounded in the compiled game's **observed append rule**.

## Why 1323 is NOT yet a confirmed roster paint label

The live `LockedCustomisationData.GetAllUnlockables()` return value has not been captured for the specific crew-view render. Although the uploaded bundle contains `AllUnlockables`, the game also builds/updates unlockable state and list content through restoration-milestone setup and other customization code. There could be extra list entries, or the accessor could return a different ordering after initialization. Therefore the native and static evidence support **only a conditional candidate**.

**Do not** automatically label paint index 15 as 1323, or 0 as `Transparent` or 1156, without a verification of the corresponding crew runtime path. The 20 prior numeric global-library ID overlaps also remain unvalidated as index-to-ID joins.

## Reproduce offline

```bash
python -m csr2cdn.dev58_runtime_paint_replay \
  --apk CSR2_6.8.0.apk \
  --bundle Ford_Mustang302_1970_common.ASTC.14 \
  --source-catalog dev36-source-ids.json \
  --paint-index 15 \
  --output dev58-conditional-paint-replay.json
```

The parser refuses unrecognized APK hashes, nonmatching bundle hashes, oversized/symlinked source files, invalid array values and overwriting an existing report. Distribution archives contain only source, tests and documentation — not the operator APK, bundle or private roster data.
