# csr2-cdn

A Python client for the CSR2 asset CDN and its metadata service: resolve the
current asset database branch, download asset databases, address every asset by
name, fetch asset bundles, and pull metadata blocks. Also access the complete
CSR2 HUB CDN through `HubCDN`: all resource folders and root files, not just
snapshots. `SnapshotCDN` accesses the official car PNG CDN using the
`CDNSnapshots` metadata catalogue.

Not affiliated with, endorsed by or connected to Zynga, NaturalMotion or any of
their subsidiaries. Game metadata requests need your own `zid`; HUB does not.

```bash
pip install csr2-cdn            # requests only
pip install csr2-cdn[stores]    # adds google-play-scraper for the Play lookup
pip install csr2-cdn[images]    # adds UnityPy for HUB bundle image extraction
```

## Official car snapshots (0.6.0)

```python
from csr2cdn import CDN

with CDN(zid="YOUR_PLAYER_ID", product_version="6.8.0") as cdn:
    snapshots = cdn.get_snapshots()  # fetch CDNSnapshots through the metadata service
    print(snapshots.cars["Apollo_S_2008"])
    # {'GACHA': True, 'PRIZE': True, 'DEFAULT': True, 'DEFAULT_REVERSED': True}

    snapshots.download_snapshot_to("Apollo_S_2008", "apollo.png", "GACHA")
    snapshots.download_snapshot_to(
        "Apollo_S_2008", "apollo-reversed.png", "DEFAULT", reversed=True
    )
```

The public kinds are `GACHA`, `PRIZE`, and `DEFAULT`. `reversed=True` selects
the separate `DEFAULT_REVERSED` file; it is only valid for `DEFAULT`.
Availability varies by car. `available(car, kind, reversed=False)` checks the
manifest, while `variants(...)` returns its exact filenames in selection order.
`snapshot_url(...)` returns the selected URL and `download_snapshot(...)`
returns PNG bytes. CRDB names are case-sensitive and need no asset database.

No CRDB list or snapshot manifest is bundled. Car names, flags, exact paths and
endpoints are derived from the manifest supplied or fetched at runtime.

Unlisted names are allowed: the client infers a filename from the most common
selected template for that mode in the current manifest (falling back to a
conventional stock filename only if the manifest has no template)
and the server may return an error. Pass `strict=True` to require a listed
snapshot. A listed file can also disappear from the server; `SnapshotError`
preserves its `status_code` and `path`. The client never substitutes another
snapshot kind or flips an image locally.

```python
from csr2cdn import SnapshotCDN, metadata_block_ids

# An already downloaded manifest needs no player ID or network lookup.
with SnapshotCDN.from_file("CDNSnapshots.meta") as snapshots:
    print(snapshots.snapshot_url("Apollo_S_2008", "PRIZE"))

# Or fetch directly without the general CDN wrapper:
with SnapshotCDN.from_metadata("YOUR_PLAYER_ID", "6.8.0") as snapshots:
    print(snapshots.available("Abarth_500_2014", "PRIZE"))

block_ids = metadata_block_ids()  # bundled list of 277 IDs, including CDNSnapshots
# metadata_block_ids("block_ids.json") reads an updated user-supplied list.
```

Call `snapshots.refresh()` to reload its original metadata/file source and
replace the catalogue and endpoints together. A failed refresh preserves the
previous catalogue. For a directly constructed client, use
`snapshots.refresh(new_manifest)`. Refreshing does not happen on every image
request; callers control when to fetch updates.

URLs come from `BaseUrlProd` in the manifest; `staging=True` selects
`BaseUrlStaging`. Re-fetch with `cdn.get_snapshots()` to refresh availability,
or use `MetadataCache.sync(["CDNSnapshots"])` and reload the saved `.meta` file.
Block IDs are a discovery seed; the metadata server may not serve every block
for every player/version. Fetching metadata needs your own player ID; the PNG
GET requests do not add one.

```bash
csr2cdn --zid YOUR_PLAYER_ID --product-version 6.8.0 snapshots --search Apollo
csr2cdn --zid YOUR_PLAYER_ID --product-version 6.8.0 snapshot Apollo_S_2008 --kind GACHA -o apollo.png
csr2cdn snapshot Apollo_S_2008 --manifest CDNSnapshots.meta --reversed -o reversed.png
```

See [the APK findings and selection rules](docs/official-snapshots.md) for how
the killswitch, manifest and duplicate-looking configuration variants relate.

## CSR2 HUB CDN

Added in 0.5.0. `CDN` continues to use the game service. `HubCDN` connects to
`https://cdn.csr2hub.space`, using the folder layout of the
[archived CSR2-HUB repository](https://github.com/Nitro4CSR/CSR2-HUB).
HUB requests do not need a player id, store lookup, game branch, or GitHub API.
The archive is a layout reference, not a current catalogue: live files may have
been added, changed or removed since it was archived.

```python
from csr2cdn import HubCDN

with HubCDN() as hub:
    cars = hub.get_text_data("CarData")
    translations = hub.get_localisation("PT-BR")
    database = hub.get_database()  # AssetDatabases/last.ver -> AssetDatabases/<version>
    older = hub.get_database(29385)
    print(database.assets.CarPaintLibrary.version)

    path = hub.snapshot_path("Abarth_500_2014", "SnapshotsFull")
    print(hub.url_for(path))
    hub.download_to(path, "./hub")  # hub/SnapshotsFull/Abarth/Abarth_500_2014.png
    cvd = hub.download("CVD/Abarth_500_2014")  # raw Unity bundle bytes
    versions = hub.version_info()             # version-control.json
    history = hub.release_history()           # release-history.json
```

`url_for(path)`, `download(path)`, `download_to(path, directory)`, `get_text(path)`
and `get_json(path)` accept **any decoded, case-sensitive relative path**. This
covers new folders and files without needing a package update. URLs are escaped
automatically, including spaces, `#` and `?`. Do not pre-encode paths or supply a
complete URL. Absolute paths and traversal components are rejected.

`path_for(category, name, ...)` provides the following layouts. Unless shown
otherwise, `name` is a filename or relative subpath inside the category.

| Category | Example path / naming rule |
| --- | --- |
| `Addressables` | `Addressables/1.4.7/catalog_1.4.7.bin`; pass `version="1.4.7"` and the exact filename |
| `AssetDatabases` | `AssetDatabases/29385` or `AssetDatabases/last.ver`, no added extension |
| `CVD` | `CVD/Abarth_500_2014`, no extension; a Unity bundle |
| `DynamicEvents` | `DynamicEvents/data.json` or the exact `.ASTC` bundle filename |
| `Gacha` | `Gacha/Abarth/Abarth_500_2014.zip`; inferred manufacturer and `.zip` |
| `Icons` | `Icons/BC/Mercedes_icon` or `Icons/Models/Abarth_500_2014_icon.png`; exact subpath |
| `Libraries` | `Libraries/_data.zip`; exact filename |
| `Linker` | `Linker/LinkerData.json` or `Linker/community/_boot.zip`; exact subpath |
| `Localisation` | `Localisation/PT-BR.json`; adds `.json` if absent |
| `ProfileStyles` | `ProfileStyles/Bg_LemansGiveway.png`; adds `.png` if absent |
| `ScreenLoading` | `ScreenLoading/0.jpg` or `ScreenLoading/SL_Config.json` |
| `Snapshots` | `Snapshots/Abarth/Abarth_500_2014.png`; inferred manufacturer and `.png` |
| `SnapshotsFull` | `SnapshotsFull/Abarth/Abarth_500_2014.png`; inferred manufacturer and `.png` |
| `SnapshotsGacha` | `SnapshotsGacha/Abarth/Abarth_500_2014/10.png` with `index=10`; omit index for legacy `SnapshotsGacha/Dallara/Dallara_Stradale_2019.png` |
| `SnapshotsRC` | `SnapshotsRC/AstonMartin_DB5Classic_1964/00.png`; requires `index="00"`, no manufacturer directory |
| `TextData` | `TextData/CarData.json`; adds `.json` if absent |

Root files such as `aCRDB.txt`, `UA.PP`, `version-control.json` and
`release-history.json` are available through the generic path methods too.
Use these same generic methods for companion files such as snapshot `.meta` files.
`HUB_CATEGORIES` exports the folder names. There is no assumed directory-listing
API: choose paths from the published data, a known manifest, or your own list.
The client does not use the archived GitHub file tree as a live inventory.

### Snapshots and icons

```python
with HubCDN() as hub:
    url = hub.snapshot_url("MercedesBenz_SLR_Coupe")
    png = hub.download_snapshot("Abarth_500_2014", "SnapshotsGacha", index=10)
    restored = hub.snapshot_path("AstonMartin_DB5Classic_1964", "SnapshotsRC", index="00")
    hub.download_to(restored, "./hub")

    # Exact icon filenames matter: the sample script's bare "MercedesBenz"
    # is not the archived/live icon filename. The asset is "Mercedes_icon".
    icon_bundle = hub.download_icon("Mercedes_icon")
    model_png = hub.download_icon("Abarth_500_2014_icon.png", category="Models")
    images = hub.export_images("Icons/BC/Mercedes_icon", "./images")
```

Branded snapshot/Gacha paths map `MercedesBenz`, `MercedesAMG` and
`MercedesAMGF1` to `Mercedes`, `LandRover` to `Landrover`, and `AMGeneral` to
`AM General`. Use `manufacturer="Exact Folder"` to override this. Car names and
icon filenames keep their original case. Icon names are not guessed because
the CDN mixes names, suffixes, Unity bundles, and direct images.

`export_images` uses the optional `[images]` extra for Unity `Texture2D` and
`Sprite` objects, saving numbered PNGs under the resource's relative path.
The raw bundle stays in memory. Direct PNG/JPEG resources are saved unchanged
without UnityPy. ZIPs, addressable catalogues and other binary resources can be
downloaded intact; they are not automatically unpacked or interpreted.

### Batches and updates

```python
paths = ["TextData/CarData.json", "Libraries/_data.zip", "DynamicEvents/data.json"]
with HubCDN() as hub:
    results = hub.download_files(paths, "./hub", workers=8)
    # Each result is a pathlib.Path or the exception for that file.

    result = hub.sync_files(paths, "./hub")
    print(result.downloaded, result.unchanged, result.failed)
    hub.sync_files(paths, "./hub", force=True)
```

HUB resources are mutable. Sync stores ETag/Last-Modified validators and local
sizes in `.csr2hub-sync.json`, then makes conditional requests on subsequent
runs. Without server validators it downloads again. Deleted or size-changed
local files are refetched. Use `force=True` to repair other local corruption.
Errors preserve the previous complete file, and retries occur on the next run.
Sync retains unselected files; run one sync at a time per directory.

Downloads stream to unique temporary files and replace their targets only after
success. `download_to(..., preserve_paths=False)` saves just the filename when
desired. Batch downloads always preserve directories to avoid name collisions.

Pass `base_url=`, `session=`, `headers=`, `timeout=` or `retries=` to customize
HUB connectivity. Caller-provided sessions remain open when the client closes.
`HubError` exposes `path` and `status_code` for request failures, keeping a 404
distinct from a forbidden response or an outage. An HTTP error never triggers
an automatic fallback to potentially stale GitHub resources.

```bash
csr2cdn hub categories
csr2cdn hub url "Icons/BC/Mercedes_icon"
csr2cdn hub get TextData/CarData.json --json
csr2cdn hub download Libraries/_data.zip CVD/Abarth_500_2014 -o ./hub
csr2cdn hub sync TextData/CarData.json DynamicEvents/data.json -o ./hub
csr2cdn hub database -o hub-db.json
csr2cdn hub database --database-version 29385 -o old-hub-db.json
csr2cdn hub snapshot Abarth_500_2014 --kind SnapshotsGacha --index 10 -o ./hub
csr2cdn hub snapshot AstonMartin_DB5Classic_1964 --kind SnapshotsRC --index 00 -o ./hub
csr2cdn hub images Icons/BC/Mercedes_icon -o ./images
csr2cdn --timeout 60 hub --hub-base-url https://cdn.csr2hub.space get version-control.json --json
```

HUB uses `hub --hub-base-url`; the global `--base-url` is for the game CDN.
Game discovery, platform, quality and metadata flags do not apply to HUB.

## Quick start

Nothing about the current game version is hard coded. Attach your `zid` and the
client works the rest out:

```python
from csr2cdn import CDN

cdn = CDN(zid="94866657860")

cdn.branch                  # '6_7_0_Release_OTA_1', discovered
cdn.product_version         # '6.7.81', read from the CDN

asset = cdn.database.assets.Lamborghini_AventadorLP7004_2011_loda
data = cdn.download_asset("Lamborghini_AventadorLP7004_2011_loda")
blocks = cdn.get_metadata("CarFusionProfileData")
```

Without a `zid`, branch discovery still works by probing:

```python
cdn = CDN(probe=True)
cdn.branch                  # '6_7_0_Release_OTA_1'
```

Any step can be pinned to skip the lookups above it:

```python
CDN(branch="6_7_0_Release_OTA_1")   # no discovery at all
CDN(zid="948...", product_version="6.7.81")   # no store lookup
CDN(zid="948...", release_version="6.7.1")    # no store request, own version
```

## Addressing assets

The catalogue is reachable by attribute, by code and by alias. Lookups are
case-insensitive, which matters because dependency lists store codes in
lowercase while the catalogue does not.

```python
database.assets.CarPaintLibrary                  # attribute
database.assets["Localisation_PT-BR"]            # exact code
database.assets.Localisation_PT_BR               # alias, same asset
database.assets["carpaintlibrary"]               # case-insensitive
"10A18Nb" in database.assets

len(database.assets)
database.assets.search("Lamborghini")            # substring match
database.assets.of_type(43)
database.assets.total_size("ASTC")
```

Codes that are not valid Python identifiers get an alias:

| code | alias |
| --- | --- |
| `Lamborghini_AventadorLP7004_2011_loda` | unchanged |
| `Ford_GT40MkII_1966_Wheel_1_Calliper1_A_~_meshes` | `Ford_GT40MkII_1966_Wheel_1_Calliper1_A_meshes` |
| `Localisation_PT-BR` | `Localisation_PT_BR` |
| `10A18Nb` | `_10A18Nb` |

On the 6_7_0_Release_OTA_1 database (23,496 assets) this produces no
collisions. Should a future database ever produce one, the first code keeps the
attribute, the others stay reachable through `assets["exact code"]`, and the
clash is listed in `database.assets.alias_conflicts`.

### Assets

```python
asset.code            # "Lamborghini_AventadorLP7004_2011_loda"
asset.alias           # attribute name
asset.version         # "6"      (as stored)
asset.version_int     # 6
asset.type            # "1"
asset.client_asset    # 4
asset.sizes           # {"High": 67825, "ASTC": 66120}
asset.size("ASTC")    # 66120
asset.filename()      # "Lamborghini_AventadorLP7004_2011_loda.ASTC.6"
asset.raw             # the underlying dict, live

asset.dependency_codes        # raw strings, as stored
asset.dependencies            # resolved Asset objects
asset.missing_dependencies    # codes with no matching asset
asset.walk_dependencies()     # transitive, breadth first
```

### Header

```python
database.branch_name
database.version
database.product_version
database.base_version
database.gusanu_fy_nhin
database.cusanu_fy_ass_metel_gloyw
database.header          # the raw dict, unknown keys kept
```

## How the branch is discovered

The game does not guess branch names. `Account.get_AssetDatabaseBranch` uses
`FeatureKillswitches.ExplicitDataBranchName` when it is set, otherwise the
`asset_data_branch_name` baked into the build, otherwise `Default_Android`.
Separately, when preemptive downloading is on, the client also polls
`FeatureKillswitches.PreemptiveDownloadDataBranchName`, which points at data for
a release that has not shipped yet.

Reaching the same answer from nothing takes five steps:

```
store version 6.7.1  ->  release 6.7.0  ->  base branch 6_7_0_Release
  ->  database version 31146  ->  product_version 6.7.81
  ->  FeatureKillswitches  ->  6_7_0_Release_OTA_1
```

Only the first step leaves the ecosystem. `product_version` is read from the
database header rather than computed, because it does not track the app version
(`4_3_0_Release_OTA_1` reports 4.3.1, and the current era reports 6.7.81 for
app version 6.7.1).

```python
from csr2cdn import resolve_branch
from csr2cdn.branches import branch_names

names = branch_names(zid="948...", product_version="6.7.81")
names.explicit      # '6_7_0_Release_OTA_1'
names.preemptive    # '' when nothing is staged

branch = resolve_branch(
    zid="948...",
    product_version="6.7.81",
    allow_preemptive=True,
    fallback=["6_7_0_Release"],
    probe=False,
)
```

Candidates are checked against the CDN and the one reporting the highest
database version wins, since those versions increase globally. `verify=False`
returns the first candidate without any request.

### Branch name shapes

Four suffixes exist, and the patch component is not always zero:

| branch | kind | product_version |
| --- | --- | --- |
| `4_1_0_Release` | release | 4.1.0 |
| `4_3_0_Release_OTA_1` | ota | 4.3.1 |
| `4_3_2_Release_1` | numbered | 4.3.2 |
| `4_0_1_Release_Preemptive_OTA` | preemptive | 4.0.0 |
| `6_4_1_Release_OTA_1` | ota | 6.4.82 |
| `6_7_0_Release_OTA_1` | ota | 6.7.81 |

Patch level branches occur in the current era too (`6_4_1_Release`), so the
bootstrap tries both `x_y_z` and `x_y_0`.

A branch's `.version` file can point at a database whose header names a
*different* branch: `asset_database_6_4_1_Release.version` served a database
whose header says `6_4_1_Release_OTA_1`. The header is what identifies the data,
so `database.branch_name` is the answer, not the branch you asked for.

```python
from csr2cdn import parse_branch, successors

parse_branch("4_3_2_Release_1").kind        # 'numbered'
parse_branch("4_5_1_Release_OTA_1").release # '4.5.1'
successors("6_7_0_Release_OTA_1")           # 16 names worth probing
```

### Probing

`probe=True` asks the CDN about every plausible successor of the branches it
already knows. It is a fixed round of requests, not a search: sixteen names for
the defaults, adjustable through `ota_depth`, `patch_depth` and `minor_depth`.

```python
cdn.probe_branches()
# {'6_7_0_Release': 31146, '6_7_0_Release_OTA_1': 31951, '6_7_0_Release_OTA_2': 32010}

cdn.resolve_branch(probe=True, refresh=True)   # '6_7_0_Release_OTA_2'
```

Probing is what catches a branch that is uploaded before the killswitch
announces it, and it is the reason discovery works without a `zid` at all.
Combining both routes is the safest setup: the announcement is authoritative,
the probe is early.

### The store lookup

Two stores are consulted, because they roll out independently:

- **Google Play** through `google_play_scraper` when it is installed
  (`pip install csr2-cdn[stores]`), the same library the Jess bot uses, falling
  back to parsing the listing. Play serves the same version to every storefront,
  so one country (`gb`) is asked and the call is a single request. Play only
  publishes a version string for single APK apps and CSR2 ships as a bundle, so
  this can legitimately answer nothing.
- **The App Store** through the iTunes lookup API, a plain JSON endpoint needing
  no scraping and no dependency. iOS builds are not bundles, so a version is
  always published. Its storefronts update separately, so five are asked, and
  they are asked concurrently: the call costs roughly one request of latency,
  not five.

Sources are tried in order and the first answer wins, so a normal lookup is one
Play request. Nothing else is paid for unless Play comes back empty.

```python
from csr2cdn import store

store.latest_store_version()                   # first answer wins, ~1 request
store.latest_store_version(strategy="max")     # ask everything, take the highest
store.store_versions()                         # what each source says

store.app_store_version(countries=store.APP_STORE_COUNTRIES)  # all 154, in parallel
store.google_play_version(countries=["us", "de"])             # if you ever need more
```

`PLAY_COUNTRIES` is `("gb",)` and `APP_STORE_DEFAULT_COUNTRIES` is
`gb, us, de, au, nz`. The full `GOOGLE_PLAY_COUNTRIES` and `APP_STORE_COUNTRIES`
lists are exported for an exhaustive sweep when you want the earliest possible
signal and can afford the requests.

Adding your own source is a function taking the app ids. Only the keyword
arguments it declares are passed, so the short form is fine:

```python
def from_my_scraper(app):
    return "6.7.1"

store.VERSION_SOURCES = [from_my_scraper] + list(store.VERSION_SOURCES)
```

A source that raises or returns `None` is skipped. Passing `release_version=` to `CDN` skips the whole step, and `probe=True` with
a `fallback` branch skips it too.

`cdn.store_versions()` prints the same per-source breakdown, which is the first
thing to look at when discovery picks a branch you did not expect.

## Metadata blocks

There is no per-file URL. You POST the block ids you want with the hash you
already hold for each, and the service returns the ones you are behind on.
Blocks you are current on come back as `null` and are skipped, so an empty
result means "nothing changed".

With a `zid` attached to the client, a name is enough:

```python
cdn = CDN(zid="948...")
blocks = cdn.get_metadata("CarFusionProfileData", "CollectionSlots")
one = cdn.get_metadata_one("PristineCarsConfig")
config = cdn.killswitches()
```

Or use the metadata client directly:

```python
from csr2cdn import MetadataClient

client = MetadataClient()
blocks = client.get(
    ["CarFusionProfileData", "CollectionSlots"],
    zid="948...",
    product_version="6.7.81",
    hashes={"CollectionSlots": "previously stored hash"},
)

block = blocks["CarFusionProfileData"]
block.hash       # store this to skip the block next time
block.text       # exactly what the service sent
block.data       # parsed, including the {"BlockName": {...}} envelope
block.content    # the envelope unwrapped
block.save("CarFusionProfileData.meta")
```

### Metadata on disk

The service decides what to send from the hashes you claim to hold, so using it
well means storing a hash per block and sending it back. `MetadataCache` does
that bookkeeping:

```python
cache = cdn.metadata_cache("./metadata")

updated = cache.sync(["CarFusionProfileData", "CollectionSlots"])
# ['CarFusionProfileData'] — the other one was already current

cache.load("CollectionSlots")     # parsed and unwrapped
cache.hashes()                    # what is stored
cache.stored()                    # block names on disk
cache.sync(names, force=True)     # ignore stored hashes
```

It writes `<name>.meta` files and a `hashes.json` beside them. A hash is only
recorded once its file is written, and a hash whose file has gone missing is
dropped, so deleting a `.meta` file forces a refetch.

`MetadataClient` on its own keeps no state at all, if you would rather handle
the hashes yourself.

## Keeping a directory in sync

`sync_assets` downloads only what changed since the last run. Versions are kept
in a small manifest inside the directory, so nothing is needed from your side
and it is safe to run on a timer:

```python
result = cdn.sync_assets("./assets", search="CarPaintLibrary")

result.downloaded   # codes fetched this run
result.unchanged    # codes already current
result.failed       # {code: exception}, the rest of the batch still completed
result.removed      # codes deleted, with remove_stale=True
result.changed      # True when anything was downloaded or removed
```

Narrow the selection with `search=`, `asset_type=`, `with_dependencies=True` or
an explicit `assets=` list, name the files yourself with `name_for=`, and pass
`remove_stale=True` to delete files that left the selection:

```python
cdn.sync_assets(
    "./assets",
    assets=[cdn.database.assets[code] for code in TARGET_LIBRARIES],
    name_for=lambda asset: asset.code.replace("TunerStars", "TNR"),
    remove_stale=True,
    on_done=lambda code, outcome: print(code, outcome),
)
```

Deleting a file is enough to force a refetch, and a failed asset is not recorded
as current, so the next run retries it.

## Databases and assets

A database comes by version or by branch, one or the other, never both:

```python
cdn.get_database(version="31951")
cdn.get_database(branch="6_7_0_Release_OTA_1")
cdn.get_database()                      # the client's own branch
cdn.download_database("db.json", branch="6_7_0_Release")   # straight to disk
```

An asset comes by name, with or without a version:

```python
cdn.download_asset("CarPaintLibrary")            # version from the database
cdn.download_asset("CarPaintLibrary", 12)        # version as int
cdn.download_asset("CarPaintLibrary", "12")      # or str
cdn.download_asset(asset)                        # or an Asset object
cdn.download_asset_to("CarPaintLibrary", "./bundles")

results = cdn.download_assets(list(cdn.database.assets.search("Lamborghini")),
                              "./bundles", workers=8)
```

Passing a version skips the database entirely, so a bare client with no `zid`
and no branch can still fetch a bundle you already know the version of.

Bundles are streamed to a `.part` file and renamed into place, so an interrupted
download never leaves a half written file behind. `skip_existing=True` leaves
complete files alone, checking against the size the database reports.

## Caching

Database URLs are immutable: `asset_database.31951.json` is the same file
forever. Point the client at a cache directory and a repeat run costs nothing:

```python
cdn = CDN(zid="948...", cache_dir="~/.cache/csr2cdn")
cdn.database          # downloaded once, then read from disk
cdn.clear_cache()
```

`.version` lookups are cached too, for `version_ttl` seconds (300 by default),
which is what makes repeated probing cheap. `version_info(refresh=True)` forces
a fresh read.

`download_assets` returns a mapping of code to the written path, or to the
exception raised for that asset, so one bad download does not lose the batch.
Platform and quality default to `ANDROID` and `ASTC` and can be set per call or
on the client. Bundle names follow `AssetDirectory.GetBundleFilename`:
`{code}.{quality}.{version}`.

## Building your own database

```python
from csr2cdn import AssetDatabase

database = AssetDatabase.from_json([{"branch_name": "my_branch"}, []])
database.add_asset("MyAsset", version="3", dependencies=["other_asset"])
database.save("my_database.json")
```

Any field may be absent, `null` or empty. The six header fields always exist and
default to `None`. Absent asset fields report `"0"`, except `dependencies`,
which reports `[]`:

```python
asset.version        # "0"
asset.type           # "0"
asset.client_asset   # "0"
asset.sizes          # {"High": "0", "ASTC": "0"}
asset.dependencies   # []
```

Defaults are reported, not written. Loading and re-dumping a database reproduces
the source document byte for byte. Call `asset.fill_defaults()` to store them.
Assets created through `add_asset` are filled in.

Comparing two databases:

```python
diff = new_database.diff(old_database)
diff.added, diff.removed, diff.changed
```

## IDE completion

Completion works at runtime for free (IPython, Jupyter, the REPL) because the
collection implements `__dir__`. Static analysers never run your code, so they
need a declaration file:

```bash
csr2cdn stubs asset_database_6_7_0_Release_OTA_1 --output csr2_assets
```

That writes `csr2_assets.py`, `csr2_assets.pyi` and a copy of the database. Then:

```python
from csr2_assets import assets, database

assets.Lamborghini_AventadorLP7004_2011_loda.version   # completes in PyCharm and VSCode
```

Regenerate after every OTA, since new assets appear with each branch.

## Command line

```bash
csr2cdn --zid 948... sync -o ./assets --search CarPaintLibrary
csr2cdn --zid 948... metadata CarFusionProfileData -o ./metadata --sync
csr2cdn --zid 948... diff 31146          # current database against an older one
csr2cdn --zid 948... branch              # the resolved branch
csr2cdn --zid 948... branch --raw        # both announced names
csr2cdn --zid 948... release             # every step of the chain
csr2cdn --probe probe                    # successor branches that exist
csr2cdn --branch 6_7_0_Release_OTA_1 version
csr2cdn --zid 948... database --output db.json
csr2cdn assets db.json --search Lamborghini --urls
csr2cdn --zid 948... download --code CarPaintLibrary --with-dependencies -o ./bundles
csr2cdn --branch 6_7_0_Release_OTA_1 download --code CarPaintLibrary --asset-version 12 -o .
csr2cdn --zid 948... metadata FeatureKillswitches --output ./meta
csr2cdn stubs db.json --output csr2_assets
```

`--zid`, `--branch`, `--product-version`, `--release-version`, `--probe`,
`--no-preemptive` and `--cache-dir` are global and apply to every subcommand.

## Notes

- Sessions: pass `session=` to `CDN` or `MetadataClient` to reuse connections or
  set proxies. Both work as context managers. The default session retries
  connection failures, 429s and 5xx with backoff, and pools connections for the
  download threads.
- A 404 and a failure are kept apart: `try_database_version` returns `None` only
  when a branch genuinely is not there, and raises otherwise, so a network blip
  cannot quietly push branch discovery onto the wrong branch. `strict=False`
  restores the swallow-everything behaviour.
- The database only reports `High` and `ASTC` sizes, so those are the qualities
  the CDN serves for Android. Other `AssetQuality` values (`Low`, `ATC`, `DXT`,
  `PVRTC`, `ETC2`) can be passed but may not exist.
- Python 3.9 or newer. The only runtime dependency is `requests`.
- `cdn.refresh()` forgets the resolved branch, product version and cached
  database, which is what you want in a long running process after an OTA.
- `CDN(package_id=..., app_store_id=...)` points the whole chain at a different
  app; the defaults are CSR2's.
