# Dev79 — Offline stage-manifest provenance checks (CSR2 6.8.0)

Dev79 adds **optional, externally supplied** companion-file verification to Dev78's runtime snapshot. It does **not** capture a live game, create real runtime evidence, authenticate the submitting operator/instrument, call game APIs, replay profile state, use network access, or promote paint mappings. It reruns the Dev72–77 pinned APK audit for every CLI invocation.

## Two-file input contract

`--snapshot` is the unchanged strict Dev78 JSON input. `--manifest` is an optional **separate** Dev79 JSON file; a manifest without a snapshot is rejected. Both are bounded to 128 KiB, strict UTF-8 JSON, duplicate-key/nonfinite-constant rejected, local regular files with no-follow opens on systems supporting `O_NOFOLLOW`.

The manifest has exactly the following top-level fields:

- `schema`: `csr2cdn.dev79.stage-manifest.v1`.
- `snapshot_sha256`: lowercase SHA-256 of the **exact bytes** in the snapshot file (including whitespace). It is *not* a digest of normalized JSON.
- `apk_sha256`: lowercase SHA-256 of the local CSR2 6.8.0 APK actually validated.
- `capture`: an object with `capture_id` (opaque label, 1–64 safe characters, only its digest is emitted), `kind` (`synthetic` or `passive_runtime`, must match Dev78 snapshot), `method` (`synthetic_fixture` or `read_only_observation` respectively), `no_replayed_gameplay_calls: true`, `session_continuity_claimed: true`. These are **self-asserted claims**; not authentication.
- `events`: 1–4 ordered objects. Each requires `stage`, strictly increasing nonnegative integer `sequence`, strictly increasing nonnegative integer `monotonic_tick`, and exact native `native_rva` as pinned below. `section_sha256` is additionally mandatory for `gacha_gate`, `paint_lookup`, and `paint_post_refresh`, and forbidden for `profile_update`. These digests are SHA-256 of the JSON section with sorted keys and compact ASCII encoding.

| Event stage | Native observation anchor | Corresponding snapshot part |
| --- | --- | --- |
| `gacha_gate` | `0x36126F4` | `gacha` |
| `paint_lookup` | `0x380B648` | `paint.lookup` |
| `profile_update` | `0x34E8988` | An observation of the later profile-update callsite; no section payload |
| `paint_post_refresh` | `0x380B648` | `paint.post_refresh` (subsequent lookup) |

Events must exactly correspond to observed sections. When `paint.post_refresh` is supplied, `profile_update` must be reported **between** `paint_lookup` and the subsequent positional lookup. If the later lookup was not seen, the reporter must not claim this event. Gacha may be omitted if its corresponding observation was not made. Order and stage anchors are checked, but only *within self-reported observations*. An event's numeric `monotonic_tick` is an observer-supplied ordering marker, **not a verified wall-clock timestamp**, and is not corroboration of a game event.

## Threat and verification model

The separate files can expose accidental modifications, incorrect stage ordering, mismatched APK versions, missing/incorrect stage assertions, and digests that do not agree. They do **not** prove that either file was captured from the real Ford Mustang 302 1970 in a legitimate gameplay session; a fabricated snapshot and fabricated manifest can both match. No signature, independently trusted chain of custody, attested instrumentation, or authoritative paint-state capture has been supplied. Hashes are **integrity checks**, not independent identity or provenance proof.

The bundled `docs/examples/dev78-synthetic-snapshot.json` and `docs/examples/dev79-synthetic-stage-manifest.json` are synthetic fixtures. **They are not production evidence.** In particular, the fabricated paint ID at index 15 is `1323` solely to exercise the code. Index 0 remains genuinely unresolved. Dev79 does not modify production mappings; both `production_paint_mapping_verified` and `production_mappings_changed` are always false.

To avoid disclosure, reports do not include raw snapshots, raw ordered lists from the new manifest, or raw capture labels. (The composed Dev78 stage assessment includes the numerical selected IDs it already reports.) The manifest rejects unexpected fields; do not insert player names, account IDs, auth tokens, device IDs, endpoints, or private account data into either file. The validator never invokes `PlayerProfile.PopCarIfInDeliveryWaitingList`, because that method consumes delivery-list state.

## Offline reproduction

No input snapshot:

```bash
python -m csr2cdn.dev79_capture_provenance --apk CSR2_6.8.0.apk --output dev79-stage-manifest-evidence.json
```

Synthetic-only companion files (demonstration; **not live runtime evidence**):

```bash
python -m csr2cdn.dev79_capture_provenance \
  --apk CSR2_6.8.0.apk \
  --snapshot docs/examples/dev78-synthetic-snapshot.json \
  --manifest docs/examples/dev79-synthetic-stage-manifest.json \
  --output dev79-synthetic-manifest-evidence.json
```

A supplied real capture remains self-reported and cannot trigger production promotion. The next gate requires independently documented, passively obtained runtime state with independently trusted provenance and reliable stage alignment (without replaying mutating game methods).
