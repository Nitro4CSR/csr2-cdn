# Changelog

## 0.6.0

- Add `SnapshotCDN` and `CDN.get_snapshots()` for the official PNG endpoint
  discovered through the `CDNSnapshots` metadata block.
- Index CRDB names with GACHA, PRIZE, DEFAULT and DEFAULT_REVERSED availability;
  select exact listed filenames and preserve all configuration variants.
- Support `reversed=True` for DEFAULT, best-effort unlisted car IDs, optional
  strict lookups, raw PNG downloads, and atomic saves.
- Add `snapshot` and `snapshots` commands, including offline manifest input.
- Refresh catalogues and endpoints from their original metadata/file source; derive
  best-effort paths for unlisted cars from current manifest templates. No CRDB
  catalogue or per-car exceptions are bundled.
- Bundle the updated 277 metadata block IDs and expose `metadata_block_ids()`.

## 0.5.1

- Make `version_ttl=0` (and negative values) always bypass the branch version
  cache, including on clocks with coarse precision or a backward adjustment.
- Expire positive cache lifetimes at their exact boundary.
- Require Windows and Linux tests on Python 3.9 and 3.13 before PyPI publishing.

## 0.5.0

- Add `HubCDN` for `https://cdn.csr2hub.space`, independently of the game CDN.
- Support every repository-relative resource path, with layout helpers for all
  16 resource folders in the archived CSR2-HUB blueprint and all four snapshot
  variants, including exact Gacha/restoration image indices.
- Load HUB asset databases into the existing `AssetDatabase` model, resolving
  the current database through `AssetDatabases/last.ver` when no version is given.
- Add JSON/text/byte retrieval, streamed atomic downloads, batch downloads and
  conditional sync for mutable resources using ETag/Last-Modified validators.
- Add optional UnityPy image extraction through the `images` extra, preserving
  raw downloads for all other binary formats.
- Add `csr2cdn hub` commands and usage examples. Existing game CDN APIs remain
  compatible with 0.4.0.
- Add GitHub test/release workflows and PyPI Trusted Publishing setup.
- Require a build backend that supports the project's license metadata and
  remove an undefined name from the public export list.
