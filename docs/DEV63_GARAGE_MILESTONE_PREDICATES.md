# Dev63 — Garage milestone and Tuner Stars predicate trace

## New native findings (CSR2 6.8.0 ARM64)

The pinned `CarGarageInstance.HasMilestonesForCar` method (`0x3476a10`) obtains the car database key from garage instance offset `0x20` and delegates to `CarMilestoneDataManager.HasMilestonesForCar` (`0x2e23bec`). The latter gets the car's milestone scheme via a pricing lookup and checks its currently loaded scheme collection. This **does not** read or compare the roster's milestone-level integer directly. Each method body and the selected branch/call instructions are SHA-256 verified against the uploaded APK.

`CarGarageInstance.get_IsTunerStarsCar` (`0x3476364`) obtains the garage car key and uses a separate car database lookup; it then reads byte `+0x21` of the returned car-data record. This is not the source enum `Tutorial`. The concrete flag value for the user's current garage-car instance was not captured.

## Cached public source join

`CarPricingCompact.meta`: vehicle `Ford_Mustang302_1970` has `SchemeID: EliteCustoms_FTUECar`. `CarMilestoneData.meta`: the identically named scheme is present uniquely, with 50 milestone entries at levels 1 through 50. `AftermarketConfig.meta` independently names this vehicle as its `FTUECar`. All three `.meta` files were checked against SHA-256 hashes in the local endpoint-cache manifest. The previously captured roster has Tutorial source, received paint index 15, and milestone level 50. No player identifier was exported.

**Interpretation:** Public metadata strongly supports `HasMilestonesForCar == true` if the game's manager has loaded the same scheme data and pricing mapping, but it does not directly observe the runtime return value. The Tuner Stars predicate remains unmeasured. Thus `CarVisuals.SetupAftermarketLockedData` is *conditionally* enabled when the first predicate is true and second false; it is not a proven execution observation.

## Paint interpretation

The same ordered-list replay (four base paint IDs plus 26 distinct valid unlockable IDs in native append order) yields index 15 → paint ID 1323, labeled **Ford Dark Highland Green** in the official database-34011 paint source catalogue. This is still conditional on that runtime paint-list order and no intervening customization mutation. It is not installed as a production mapping. Paint 0 remains unresolved, and the discredited Transparent alias remains withdrawn.

## Reproduce with operator-provided files

```bash
python -m csr2cdn.dev63_garage_milestone_predicates \
  --apk CSR2_6.8.0.apk \
  --bundle Ford_Mustang302_1970_common.ASTC.14 \
  --private-cache-zip endpoint-cache.zip \
  --source-catalog dev36-source-ids.json \
  --output dev63-garage-predicate-evidence.json
```

The diagnostic reads only three allowlisted public metadata files and the single matching roster car in the local private cache. The output contains no identities, no raw crew JSON, and no executable native bytes. No new HTTP, game or authentication requests. The APK, bundle, catalogue and private cache are excluded from source/wheel distributions.

## Next target

Locate the actual car database entry and its Tuner Stars flag for the Mustang, or trace the car-data lookup's source. The current endpoint cache contains pricing metadata and the visual bundle but not a verified runtime car-data flag. Avoid conflating FTUE/Tutorial and Tuner Stars categories until the underlying bit can be verified.
