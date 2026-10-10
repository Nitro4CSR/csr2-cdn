# Changelog

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
