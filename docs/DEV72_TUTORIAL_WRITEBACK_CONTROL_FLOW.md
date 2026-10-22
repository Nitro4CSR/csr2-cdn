# Dev72 — Tutorial-source paint-index writeback reachability

## Sources and reproducibility

The diagnostic uses the locally provided CSR2 6.8.0 APK, current `CarMetadata.ASTC.1594`, `Ford_Mustang302_1970_common.ASTC.14`, operator-provided endpoint cache, and database 34011 source-ID catalogue. No new network/authenticated reads are performed; private input data is not exported.

Method identity and native bytes are verified against Dev71 method fingerprints. The compiled `eCarSource` enum and the `eCarSourceExtension.IsIAP` body are checked using Dev61's independently verified metadata and instructions.

## Native CFG verification

The static CFG walks **both** directions of every conditional branch except the **two** conditional decisions established by the known `Tutorial = 1` source:

- `0x38029C0`: special-source mask `0x604` misses enum value 1, so branch to `0x3802B8C` (`IsIAP` check).
- `0x3802B98`: `IsIAP(1)` is false, so branch to `0x3802D0C` (common setup continuation).

In an unrestricted CFG, 1,008 instructions are reachable and the only two identified `STR W, [garage + 0x6c]` writes occur at `0x3802C10` and `0x380370C`.
Under the Tutorial-specific branches, 759 instructions are reachable, **neither writeback is reachable**, and the common `ForceUpdateOfCarPaint` invocation (`0x38036A0`) remains reachable.

The bounded method SHA-256 is `223c6ad945cbe7b5c1c5e27e331cb2cc53e47e7ff0f30ac10f3d5df3c502426c`. The `source == Tutorial` assumption comes from the saved own-crew roster; its propagation to the garage instance is **not** directly captured as a live execution trace.

This is a conservative **intra-method direct-control-flow proof**, not whole-program symbolic execution. Calls to other methods and later scene callbacks can have side effects; we do not claim to exclude them.

## Interpretation

The crew's received paint index 15 reaches the normal selection path without either of the two known setup writebacks. The current static replay of base paint IDs plus restoration unlockables continues to put **ID 1323 — Ford Dark Highland Green** at position 15. This is **conditional** on the loaded list actually having the reconstructed ordering. No production paint label is assigned, and the received index 0 remains unresolved.

## Offline reproduction

```sh
python -m csr2cdn.dev72_tutorial_paint_writeback \
  --apk CSR2_6.8.0.apk \
  --car-metadata-bundle CarMetadata.ASTC.1594 \
  --visual-bundle Ford_Mustang302_1970_common.ASTC.14 \
  --cache-zip endpoint-cache.zip \
  --source-catalog dev36-source-ids.json \
  --output dev72-tutorial-writeback-evidence.json
```

## Next decisive check

Trace the **indirect paint-list mutations and the actual `ForceUpdateOfCarPaint` list state** in the crew scene. Static controls are now substantially narrowed but cannot prove the final runtime list.
