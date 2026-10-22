# Dev78 — Offline runtime paint snapshot contract (CSR2 6.8.0)

Dev78 adds `csr2cdn.dev78_runtime_paint_snapshot`, a bounded **offline validator** for operator-provided, passively captured runtime evidence. **It does not capture a running game, issue gameplay calls, authenticate external captures, or change production mappings.** Before assessing any supplied snapshot, it reruns the full SHA/opcode/metadata-pinned Dev72–77 APK evidence chain on a local APK.

## Evidence needed

A future legitimate non-mutating capture of the **Tutorial (`source_id=1`) Ford Mustang 302 1970** should identify the client (`CSR2 6.8.0`), the exact vehicle key (`Ford_Mustang302_1970`), and whether it was acquired through passive observation. Snapshotting must not re-execute `PlayerProfile.PopCarIfInDeliveryWaitingList`, which modifies profile lists. Do not include player IDs, tokens, device IDs, private roster information, URL endpoints, or other extraneous fields; the validator deliberately rejects unrecognized input keys.

The allowed JSON structure is illustrated by `docs/examples/dev78-synthetic-snapshot.json`. That sample is **fabricated solely for testing**. It does not represent game observations, and its paint list (including index 15 → 1323) is synthetic. Set `capture.kind` to `passive_runtime` **only** for an actually observed passive runtime snapshot; this is a declaration, not cryptographic proof.

Optional top-level sections:

- `gacha`: a complete passive observation of the return pair from an *already executed* delivery-pop call, the flags, four config sentinel fields, config collection length, secondary rejection, entry-present status, and whether `ApplyGachaConfig` was actually called. Both return pair members are signed 32-bit integers; the second is the **gacha configuration index**, not the paint index. Do **not** perform a second call to obtain this value.
- `paint.lookup`: the exact ordered `CarVisuals.CarPaintIDs` list, selected paint index, and optionally a separately observed paint ID at the moment of positional lookup.
- `paint.post_refresh`: the corresponding ordered IDs and selected index at the later refresh; requires `paint.lookup` so the two stages can be compared.

Every provided gacha section and paint stage must be complete and correctly typed; missing optional sections are **unknown**, not implicitly false. The paint ID corresponding to an in-bounds index is derived positionally. If a separately supplied observed ID contradicts the list, validation fails. Negative / out-of-range indices are reported as unresolved, not wrapped around Python-style. Ordered list hashes permit exact comparison of stages without echoing the full list.

### Verification policy

- **No snapshot:** native static chain verified; paint-list and gacha runtime state missing.
- **Synthetic snapshot:** structural and native-guard consistency only; never production evidence.
- **`passive_runtime` snapshot:** internally checked self-reported runtime observations; still **not independently authenticated**. `production_paint_mapping_verified` remains false, regardless of values.
- Confirmation that index 15 maps to ID 1323 or that index 0 has any real ID requires independently establishing the provenance and completeness of an authentic runtime capture. This version intentionally has **no promotion mechanism**.

The parser rejects duplicate JSON keys, NaN/Infinity, files larger than 128 KiB, non-UTF-8 content, symlinks, unexpected fields, wrong client/source/vehicle, boolean integer substitutions, inconsistent explicit paint IDs, and observed gacha calls forbidden by the modeled normal-path guards. It refuses to overwrite an output file.

## Reproduce

```bash
python -m csr2cdn.dev78_runtime_paint_snapshot \
  --apk CSR2_6.8.0.apk \
  --output dev78-runtime-snapshot-evidence.json
```

To validate **synthetic test input only**:

```bash
python -m csr2cdn.dev78_runtime_paint_snapshot \
  --apk CSR2_6.8.0.apk \
  --snapshot docs/examples/dev78-synthetic-snapshot.json \
  --output dev78-synthetic-only-evidence.json
```

The validator has no network access paths and needs no Unity bundles or caches. The source and wheel omit APKs, profiles, Unity bundles and endpoint caches. The evidence output includes structural assessments and hashes, not raw private snapshot contents.
