# Official snapshot CDN: CSR2 6.8.0 findings

Analysis date: 2026-10-14. Sources: the user-provided Android 6.8.0 APK,
its ARM64 `libil2cpp.so` and IL2CPP metadata, and the separately supplied
`CDNSnapshots.meta` and `block_ids.json`. The local research traces are kept
outside the distributable package. This is an independent implementation;
no game binaries or bulk snapshot manifest are bundled.

## What EnableCDNSnapshotLookup does

`CDNSnapshotManifest.IsInManifest` (RVA `0x381ef0c`) and
`CarSnapshotManager.TryDownloadFromCDN` (`0x3800834`) check the
`FeatureKillswitches.EnableCDNSnapshotLookup` static backing field at offset
`0x691`. If enabled, the game constructs its snapshot cache filename and checks
it against the metadata manifest. This is a client-side feature gate; the flag
is not an authentication parameter sent with the PNG request.

`CDNSnapshotManifest.OnConfigLoadedFromJson` (`0x381ed98`) reads
`BaseUrlProd`, `BaseUrlStaging`, and `list`. `GetCDNUrl` (`0x381f1c4`) chooses
the endpoint through `Endpoint.IsProdEnvironment`, ensures a trailing slash,
and normalizes path separators before concatenation. The supplied manifest
uses `https://csr2.cdn.zynga.com/cdn-snapshots` for production.

`DownloadSnapshotFromCDN`'s coroutine (`0x3801b90`) uses
`UnityWebRequestTexture.GetTexture`, obtains the texture, optionally caches
the downloaded bytes on disk and the texture in memory, and invokes the
callback. A failed request invokes the callback with null.
`CarSnapshotter.OnCDNSnapshotDownloaded` (`0x2eb8cc8`) then falls back to
loading the car for rendering. The Python package cannot reproduce that Unity
rendering fallback, so it reports download failures instead.

`SnapshotCDN` deliberately does not require the game's feature flag to be on:
the caller explicitly asks to access the endpoint. It gets the authoritative
file list from the existing metadata service, independently of the HUB CDN
and the asset-bundle database.

## Names and availability

The supplied manifest has 6,048 unique paths. It indexes 1,275 CRDB names,
including the mystery-car placeholder. There are 2,546 DEFAULT, 1,273
DEFAULT_REVERSED, 1,456 GACHA_CAR and 771 PRIZE_CAR filenames, plus two
placeholder paths. Several variants can belong to the same car/mode.

`Default/` is a directory, not part of the CRDB name. Both DEFAULT and
DEFAULT_REVERSED live there in this manifest. PRIZE_CAR and GACHA_CAR live
at the endpoint root. Every configuration filename in this manifest specifies
size 512. The client preserves directory names from listed paths rather than
reconstructing them.

`GetSnapshotCacheName` (`0x37fcb90`) uses this core suffix:

```text
_p{paint}_i{interior}_c{caliper}_s{size}_n{number_plate}_lz{livery_zone}_l{livery}_m{mode}
```

The method reads `AppliedInteriorID`, `AppliedCalliperID`,
`AppliedLiveryZonesSetID`, and `AppliedLiveryID` from the car instance.
`-2147483648` is an unset/sentinel value, not a different camera view.
Other suffixes encode decals, wheels, Elite customization and restoration.
`_fgc{n}` is appended when `CarGarageInstance.ForcedGachaConfig` is nonnegative;
thus `_fgc0` means forced Gacha configuration 0.

Two live pairs were checked on 2026-10-14:

| Pair | Result |
| --- | --- |
| Acura_NSXTypeSRewardRecycled_2022 GACHA_CAR, with and without `_fgc0` | Identical SHA-256; 161,494 bytes; 512×512 |
| Apollo_S_2008 DEFAULT, unset interior/caliper versus `i1840_c0` | Identical SHA-256; 150,939 bytes; 512×512 |

These samples confirm aliases exist; they do not prove all configurations are
interchangeable. The implementation retains every exact variant. It prefers
paint 0, no additional suffix, unset interior/caliper, then highest available resolution, shorter
suffixes, and lexical path order. The order is independent of manifest order.
If only a customized filename exists, that exact filename is used. Call
`variants()` and `download(path)` to choose another listed configuration.

Simple `Default/<CRDB>.png` filenames are indexed as DEFAULT, without any
per-car exception. This includes `Default/Mystery_Car_1234.png` in the supplied file. The root
`Mystery_Car_1234.png` has no encoded mode and is retained in
`unclassified_paths`; no GACHA or PRIZE availability is invented for it.
Other future unrecognized names are similarly preserved for direct access.

## Python behavior

`cars` is a fresh dictionary keyed only by CRDB names, with boolean GACHA,
PRIZE, DEFAULT and DEFAULT_REVERSED flags. The last flag lets applications
disable the reversed option independently of the normal DEFAULT option.
Selection takes `kind="GACHA"`, `"PRIZE"` or `"DEFAULT"` and, for DEFAULT,
`reversed=True/False`. It never switches modes silently.

For an unlisted car or unavailable mode, non-strict selection infers a filename
from the most common selected template for that mode in the current manifest.
This preserves its current directory, resolution and suffixes. Only when no
template exists does it use the conventional stock paint-0, unset
interior/caliper/livery, size-512 filename, with `Default/` for DEFAULT modes. This is a best-effort guess, not a promise.
`available()` remains false and the guessed entry is not added to `cars`.
`strict=True` raises `SnapshotNotFoundError` before requesting a PNG.

HTTP/network errors become `SnapshotError`; a successful response must have a
PNG signature. Saves are atomic and failed downloads preserve the previous
file. `DEFAULT_REVERSED` is downloaded from its own URL, not mirrored locally.

## Scope of verification

The metadata protocol integration is tested with representative service
responses. The user-supplied live manifest is tested against every listed
configuration filename, and representative PNG downloads are checked against
the production server. No player's credentials are included in tests or
package data. A fresh authenticated metadata fetch requires the caller's zid.

## Dynamic catalogue lifecycle

No car-name list, per-car exception or full snapshot manifest ships in the
package. The counts above describe the supplied research sample only.
`refresh()` reloads the original metadata service or file, including new and
removed cars, changed availability, paths and endpoints. Directly constructed
clients accept `refresh(new_manifest)`. Failed refreshes retain the previous
valid state. Caller-controlled refresh avoids a metadata request per PNG.
The bundled metadata block IDs are an optional discovery seed, never a
whitelist: any new block ID can be requested directly.
