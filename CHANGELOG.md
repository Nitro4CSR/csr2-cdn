# Changelog

## 0.7.1

Crew reads, cosmetic resolution and leaderboard fields, validated against the live service
rather than inferred from the binary. Asset database 34049 (`6_8_0_Release`).

### Highlights

- **Crew cosmetics resolve completely.** Every value on a live 29-row roster: the twelve-slot
  appearance at 190/190, plus `car_tnr_setup` and `car_gacha_config`, which were previously
  parsed and discarded.
- **Only `paint` is an index**, composed per car from the cosmetics bundle, the flattened
  unlockable milestones and the gacha configs. `Ford_Mustang302_1970` index 0 resolves to
  `1156` and index 15 to `1323`; both had been conditional or unresolved for ten cycles.
  Every other slot is a global library ID whose per-car list is an eligibility set.
- **A wheel's name** comes from `car_tnr_setup.RIMS` against `CarTunerStarsRimLibrary`.
- **Tuner Stars body parts** map onto CDN asset codes via `csr2cdn.car_body_parts`. They have
  no library because they have no name: no localisation key embeds a kit, hood or wing index.
- **The crew tournament tree** decodes, including its fortnightly cadence and the fact that
  `hash` is a match-up key rather than a digest.
- **Every supported endpoint audited live**, not only the crew reads. That found six fields the
  Showdown Leagues endpoints send and the decoders dropped, and the backend's
  `"Monadic::Nothing"` absent-value sentinel.
- All twenty-one cosmetic libraries decode, four only through the new type-tree fallback.

### Packaging

- `csr2cdn/_research/` collects the 54 offline investigation modules. It is private, excluded
  from the wheel, and kept in the source distribution as provenance. The public API is 62
  modules; nothing public imports from it.
- Fixed: `csr2cdn.__version__` had read `0.7.1.dev81` since that cycle while the distribution
  moved on. `tests/test_release_metadata.py` now asserts the two agree and that the version is
  not a dev build.
- `README.md` documents the crew, cosmetic, body-part, tournament and leaderboard surface. The
  0.7.x investigation notes that previously occupied it moved to `docs/0.7.1-research-log.md`.
- Symlink-rejection tests skip where the OS withholds the privilege to create a symlink rather
  than failing, so Windows reports no failures.
- `run_live` takes `at`, the instant to evaluate schedules against, so a report is reproducible.

### Not modelled, by intent

- `facebook_id`, and opaque auth/token fields anywhere in a response. Only known keys are
  decoded, so a token added server-side is never held on a model. Both remain in `extras`.

### Known limits

- No Prestige Cup has been active during validation, so that endpoint's response shape is the
  one supported read never observed.
- `tier`, `rarity`, `license_level`, `avatar_index` and `preferred_avatar_type` are raw wire
  values; no label table has been located for any of them.
- `meta.scores` in the tournament tree had a single observation equal to the reward tier, so
  `current_score` is surfaced and explicitly documented as unverified.

---

The entries below are the development log for this release, newest first. They record how each
finding was reached, including the readings that were wrong and how the live service refuted
them.

## 0.7.1.dev84 — Endpoint audit: every supported read, not just the crew ones

Earlier cycles proved coverage on `crews/checkUserCrew` and `crews/viewMembers` and treated that
as the field inventory. It was not: the package supports ten reads, and auditing all of them
against the live service found six fields the Showdown Leagues endpoints send and the decoders
dropped.

### Found and fixed

- **`LeaderboardEntry.crew_id` never populated on a leagues board.** The decoder knew
  `crew_uid`, `crewUID` and `crew_id`; the leagues board spells it `crewId`. Same class of bug as
  the dev83 `member_count` fix. It is an empty string on all 21 live rows, because that board
  ranks players rather than crews, so the value today is None either way -- but the spelling is
  read now, so a populated one is no longer discarded silently.
- Add `LeaderboardEntry.last_updated` (Unix seconds, 20 distinct across 21 live rows, so
  per-row), `multiplier`, and `sp_boost_data`.
- Add `LeaderboardScore.last_updated` and `sig_timestamp`.

### The backend's Nothing sentinel

- Add `MONADIC_NOTHING = "Monadic::Nothing"` and `_optional_str`. Every live leagues row sends
  that literal string as its `multiplier` instead of omitting the key -- a Haskell-style `Maybe`
  encoding leaking onto the wire. Read naively it reports "Monadic::Nothing" as a real
  multiplier, so it is normalised to None, as is the empty string. A genuine value such as
  `"1.5x"` is untouched, and `"Monadic::Just 2"` is not mistaken for the sentinel.
- This sits alongside the sentinels already known here: `-1`/`"-1"` group terminators in the
  unlockable arrays, and `INT32_MAX`/`INT32_MIN` for unset cosmetics.

### The response signature is reported, not retained

- The leagues score response carries a 64-hex `sig` plus `sig_timestamp`. `signature_present`
  reports whether one arrived; the signature itself is **not** modelled, because it belongs to
  the opaque-token family this package already withholds alongside `auth` and `hidden_token`.
  It stays reachable in `extras`.

### Exhaustiveness, measured

- 7 of 8 reachable endpoints read live. Across every one, the only unmodelled field name left is
  `facebook_id`, which is withheld by intent.
- `checkUserCrew` 33 keys / 0 unmodelled, `viewMembers` 60 / 0 (bar `facebook_id`),
  `gcc_progress` 15 / 0, `gcc_progress_range` 15 / 0, `leagues` 19 / 0, `leagues_score` 12 / 0,
  `leagues_preview` 14 / 0.
- Two paths had no data to exhaust rather than a gap: no Prestige Cup is active, and the
  *current-showdown selector* is ambiguous today because 25 Showdowns are scheduled at once with
  one requestable, which is the selector refusing to guess. The showdown board's own rows were
  read by name and use the same decoder, so the shape is covered.
- The audit now ignores purely numeric keys. An earlier pass reported the tournament event IDs
  `272`..`277` as unmodelled field names when they are dict keys holding data.

### Determinism and environment

- `run_live` accepts `at`, the instant to evaluate event schedules against, defaulting to the
  real clock and threaded into every discovery call and the reported `at_utc`. Without it a
  report silently depended on when it was taken, and two tests that pinned fixture schedules
  began failing the moment those windows elapsed -- which is exactly what happened on
  2026-10-22. Both now pass their own fixture clock.
- The seven symlink-rejection tests now skip, via a `requires_symlinks` marker in a new
  `tests/conftest.py`, when the OS withholds the privilege to create a symlink -- Windows
  without Developer Mode. They were failing for an OS setting rather than a defect, which buries
  real regressions. Stated tradeoff: where symlinks cannot be created, that rejection path goes
  unexercised; it still runs on POSIX. Windows now reports **0 failures**.
- Discovery mocks in `test_live_validation` accept the keyword arguments the real API takes.

## 0.7.1.dev83 — The plain roster scalars

Every field on the live `crews/checkUserCrew` and `crews/viewMembers` replies now reaches a
typed attribute, except three that are withheld on purpose. Ten new fields, all confirmed
29/29 on the live roster.

### Corrections to the dev82 field inventory

- The dev82 inventory over-reported. It regex-matched `_counter(raw, "key")` call sites, but
  `CrewOptionalStats` and `CrewMemberOptionalStats` pass their key names as a tuple into a
  generator, so every field they already read was counted as uncovered. Nine of the
  "uncovered" roster fields were already modelled: `garage_value`, `career_earning`,
  `cash_donated`, `collections_rank`, `season_pass_rp_boost`, `members`, `max_members`,
  `total_invites`, `total_requests`.
- `cc_contrib` was a false positive too; it has been served by `CrewMember.season_crew_rp`
  since dev29.
- Coverage is now measured by searching every module for the key as a quoted literal, which
  over-reports coverage rather than under-reporting it, so a name it calls unmodelled is.

### New typed fields

- `CrewOptionalStats` gains `crew_status` (join policy, live `"JoinByRequest"`), `app_ver` and
  `debug_season`, plus a `seats_free` property. These sit beside the four crew counters already
  there rather than on `OwnCrew`, so each wire key has exactly one typed reader.
- `CrewMemberOptionalStats` gains `token_donated`, `license_level`, `tier`, `rarity`,
  `is_super_rare`, `avatar_index` and `preferred_avatar_type`.
- `tier`, `rarity`, `license_level`, `avatar_index` and `preferred_avatar_type` are exposed as
  **raw wire values**: no label table has been located for any of them. Live value sets are in
  `VALIDATION_STATUS.md`.

### Fixed

- `OwnCrew.member_count` was `None` on every real response. It read `memberCount` and
  `membersTotal`; the live 6.8.0 reply spells the current roster size `members`.

### Tuner Stars body parts

Add `csr2cdn.car_body_parts`, covering the four upper-case `car_tnr_setup` keys that had no
library. Asset naming verified exhaustively against the live asset list.

- **There is no name to look up.** `Localisation_FlatBuffer_EN` holds 22,048 `TEXT_` keys and not
  one embeds a kit, hood or wing index. The only kit strings are UI chrome
  (`TEXT_BODYKIT_BUTTON` -> "BODYKITS", `TEXT_HOOD_BUTTON` -> "HOODS") and tutorial copy. The
  game identifies these parts by index and renders them as numbered thumbnails, which is exactly
  why they have no library while `RIMS`, `TIRE` and `BOOST_COLOR` do. A part's only stable
  identifier is its asset code, so that is what the module returns.
- Asset naming, for a model key `{stem}_{year}`: `BODYKIT` level N splices into the stem as
  `{stem}N_{year}_loda`, while `HOOD`/`WING` suffix as `{stem}_{year}_Hood{N}{a|b}_loda`.
- **25 cars ship the full kits+hoods+wings triple and all 25 are TNR models.** The shape is
  uniform across every one of them: kit levels `0..K` with K of 3 (15 cars) or 6 (10 cars), and
  exactly `1 + 2K` hood and wing options. `shape_is_regular` reports True for 25/25, and exists
  so a newly shipped car that breaks the rule is noticed rather than mis-resolved.
- That matches the tutorial copy exactly: "Each kit comes with a secondary Hood option to fit."
  Stock has only `0a`, with `{N}a` and `{N}b` per level above it.
- No kit car has a `_common` bundle, so unlike the dev82 cosmetics there is no `CarVisualsData`
  list to compose against; the asset list is the ground truth.
- Lower-cased asset codes: kit-car assets are published lower-case, so matching is
  case-insensitive. A case-sensitive scan finds nothing, which invalidated one validation pass
  during this cycle before it was caught.
- Separately identified: the lower-case `body{N}{a|b|c}` / `engine{N}` / `interior{N}` `_loda`
  series belongs to **Classic restoration**, not Tuner Stars. 7 of 17 live cars carry it.

#### HOOD and WING: a variant over the fitted kit

- They select the **primary or secondary option of the fitted kit**, not a position in the car's
  option list: `0` -> `Hood{BODYKIT}a`, `1` -> `Hood{BODYKIT}b`.
- The game bounds them to `{0, 1}` and forces both to `0` while `BODYKIT` is `0`; only a kit at
  level 1 or above admits a `1`. That constraint refutes the competing reading outright, since an
  index into the option list would range over `0..2K`.
- The asset list corroborates it independently: **no car ships a `0b`** (0/25), every car ships
  `0a` (25/25). Under this reading that absence is exactly why a stock kit forces `0`, and the
  `1 + 2K` option count stops being a coincidence and becomes a derivation -- K levels times two
  variants, plus one stock option (25/25).
- Exhaustively verified: every (kit level, variant) pair on every one of the 25 kit-capable cars
  resolves to an asset that exists, with zero failures.
- Constraint violations are reported, not resolved: `variant_out_of_range` outside `{0, 1}`, and
  `invalid_for_stock_kit` for a secondary with no kit fitted, the one case with no asset to point
  at. `bodykit_unknown` when the kit level is absent, since the variant is meaningless alone.
- `stock` is reserved for a car with no kit assets at all -- all 29 live rows. A kit-capable car
  at `BODYKIT = 0` resolves to its real level-0 asset instead.

#### WHEELS is retired

- `WHEELS` was split into `RIMS` and `TIRE`, both of which already resolve against their own
  libraries. The key is vestigial: the service still sends it and the game still carries a
  `TEXT_WHEELS_BUTTON` tab, but nothing drives it. Every independent line of evidence agrees --
  no `Wheel`-suffixed `_loda` asset exists for any car, and all 29 live rows report `0`.
- Reported as `retired_slot`: read and deliberately not resolved, which a caller can tell apart
  from a key that was never looked at. **With this, every key in `car_tnr_setup` is accounted
  for.**

#### Two libraries closed out

- `TunerStarsLiveryZonesSetLibrary` is TNR-specific and expected-thin rather than a decode
  failure. It is the fifth Tuner Stars library after the four that needed the type-tree
  fallback, and its 1255 bytes yield no labelled records because it holds none: TNR cars take
  zone masks from the shared `LiveryZonesSetLibrary`, which resolves 19/19 live.
- `CarCameraAnimationLibrary` is out of scope -- camera angles, not cosmetics. Recorded as
  excluded by intent, not as an unread gap.

### The tournament tree, decoded

The last uncovered subsystem on either crew endpoint. Validated against the live tree on
2026-10-21; all six events agree with the model.

- Add `CrewTournament`, `CrewTournamentEvent` and `CrewTournamentRival`, reached as
  `CrewOptionalSnapshot.tournament`. `CrewTournamentShape` is unchanged and stays the
  presence-only view on `CrewPresentation`.
- **`hash` is not a digest.** It is the match-up key: the three participating crew IDs joined
  by `"_"`. The decoded set equalled `crews[].id` on 6/6 events, so the field carries nothing
  the `crews` array does not. Exposed as `matchup_key_consistent` rather than as a value.
- **`vanity_reward` is `"<tier>_<unix seconds>"`.** Confirmed on 7/7 values. The timestamps are
  exactly 14 days apart, every one a Thursday at 10:00 UTC:
  2026-08-13, 08-27, 09-10, 09-24, 10-08, 10-22.
- **The event ID is a global fortnight counter.** The six IDs are consecutive (272–277) and the
  spacing is a fixed fortnight, so `cadence_days` derives as 14 from the stamps themselves.
  Extrapolating ID 1 lands on 2016-03-24, near CSR2's launch year — consistent with a
  since-launch counter, but one capture cannot prove the epoch, so nothing depends on it.
- **`meta` describes the current event, not a past one.** `meta.vanity_reward` equalled the
  newest event's, whose reward time was still in the future at capture.
- **`meta.prev_match` names the *current* match-up**, despite its name: its three crew IDs
  equalled event 277's, not 276's. Reported as `prev_match_is_current_event` so the misleading
  wire name cannot mislead a caller. `car_paint_id` is misnamed the same way.
- `meta.scores` was a single integer equal to the reward tier. One observation with two
  plausible readings, so it is surfaced as `current_score` and explicitly documented as
  **not established**.
- `extra` was an empty object on every capture. `extra_populated` is True only when it actually
  carries something, so a future payload is noticed rather than silently ignored.

- `rivals[].name` is a **point-in-time** crew name, recorded as it stood at that event, not the
  crew's current name. Do not use it as a stable key; `crew_id` is the stable one.

### What is printed, and what is not

Policy set by the maintainer on 2026-10-21: in-game player IDs, crew IDs and license plate text
are fine to print. They are values a player can read off the roster and tournament screens.

- `license_plate_text` is modelled on `CrewMemberOptionalStats`, length-capped like every other
  player-supplied string. 29/29 live rows, 16 distinct.
- Tournament event rosters are retained in full as `events[].members` (in-game player IDs, wire
  order preserved), alongside `member_count` and `distinct_member_count`.
- `events[].rivals` carries rival `crew_id`, `name`, `logo_id` and `logo_colour` as ordinary
  printable fields.
- `events` and `rivals`/`members` tuples stay out of repr purely for readability -- six events
  of three rivals and thirty members each is an unreadable repr. This is explicitly not a
  privacy measure, and tests assert the values remain reachable.

Two categories remain withheld unconditionally, and both are a different kind of thing from an
in-game ID:

- **Opaque auth and token fields** anywhere in the tree, and any unrecognised wire key. Only the
  known keys are decoded, so a token added to an event is not merely hidden from repr but never
  held on the model at all.
- **`facebook_id` and `last_log_in_time`** on a roster row. A Facebook ID is a real-world social
  account rather than game data, and the login time is behavioural tracking; neither is needed
  to describe a crew. Both stay reachable through `CrewMember.extras`.

### Withheld on purpose

- `facebook_id`, `last_log_in_time` and `license_plate_text` are supplied on all 29 live rows
  and are deliberately **not** modelled. None is needed to describe a crew, and each identifies
  or tracks a person — a plate is player-authored and players routinely put their own name on
  it. `test_dev071_dev3_cosmetics_isolation` already listed the plate as a secret and caught an
  attempt to model it during this cycle.
- All three stay reachable through `CrewMember.extras`. Withholding governs typed output, not
  caller access.

## 0.7.1.dev82 — Crew roster cosmetics fully resolved

Every cosmetic value on a live 29-row crew roster now resolves. The twelve-slot appearance is
**190/190 (100%)** with nothing unaccounted, and two roster blocks that the package previously
dropped on the floor — `car_tnr_setup` and `car_gacha_config` — are decoded as well. Asset
database 34049 (`6_8_0_Release`). Validated against the service, not inferred from the binary.

### How the codes are encoded

- Add `csr2cdn.car_visuals_data`, which decodes a car's cosmetics bundle (`<crdb>_common`, or
  the bare model key for Classic and LPClassic models) into its per-car cosmetic lists:
  `dedup(CarVisualsData.<Slot>IDs + flatten(AllUnlockables.<slot>IDs) + GachaConfigs.<Key>)`.
  The unlockable lists are ragged arrays whose milestone groups are terminated by `-1`
  (`"-1"` for wheel names); the sentinels are separators, not entries.
- **Only `paint` carries an index.** For every roster car the wire paint value was absent from
  that car's own ID list (0/14) while reading it as a position produced a paint of the car's own
  marque. `interior`, `calliper`, `livery_zones_set` and `livery` are global library IDs, landing
  inside the car's list as members (calliper 14/14, interior 13/14) and resolving 29/29. The
  binary agrees: `CarVisuals` declares `current_paint_index` alongside `current_interior_id`,
  `current_calliper_id`, `current_livery_id`, `current_liveryZoneSet_id`, `current_rims_id`,
  `current_flag_id`, `current_boostColor_id` and `current_tire_id`. `car_paint_id` is misnamed.
- For global-ID slots the per-car list is an *eligibility set*, reported as `eligible` rather
  than used to relocate the value.
- Confirm `Ford_Mustang302_1970` index `0` → paint `1156` "Ford Calypso Coral" and index `15` →
  `1323` "Ford Dark Highland Green". Dev72–81 held `15 → 1323` as conditional and `0` as
  unresolved after ten cycles of APK analysis; neither needed the APK.
- Gacha configurations extend the paint index space at the end, so existing indices keep their
  meaning. One roster car reported index 10 into a 10-entry shipped list, which its first gacha
  paint fills exactly: `2694` "Porsche British Racing Green" on a Porsche. `INT32_MAX` and
  `INT32_MIN` are recognised as unset markers — every sampled `WrapPaintID` is `INT32_MAX`,
  the sentinel dev77 identified.
- `wheel` carries the rim bundle's own CDN asset code, `{model_key}_{BundleName}`; the prefix is
  stripped to match the bundle's list. An absent name is reported as
  `name_not_in_bundle_list` rather than invalid, because Classic models list only part of their
  rims while the assets exist.
- `decal_number_zone` is a placement selector over the car's `RacingNumber1..3` mesh anchors,
  not a library record: `CarVisuals.GetNumberZonesCount` returns the length of the car's
  `RacingNumberGO` collection and `ApplyNumberZoneToMeshes` applies one. Every car shipping
  anchors has exactly three. `0` hides the number and `1..N` select an anchor. A live row reports
  `3`, which rules out the boolean reading the field's 0/1-only UI suggests: the toggle is the UI
  affordance, the stored value is the placement.
- Zone masks and livery sets are **separate** per-car lists against separate libraries:
  `CarVisualsData.CarLiveryZonesSetIDs` → `LiveryZonesSetLibrary`, and
  `AllUnlockables.carLiverySetIDs` → `LiverySetLibrary`. Merging them was dressing unrelated cars
  in a Ferrari zone set.
- Zone mask `0` is a **real record** (`FULL BODY`), not an absence, so no slot treats `0` as
  "nothing applied" any more. `ZERO_MEANS_NONE` is now empty and kept only as a documented
  negative result.

### Two roster blocks that were being discarded

- Add `csr2cdn.crew_cosmetic_fields`. `CrewMemberOptional` does not retain unmodelled wire keys,
  so `car_tnr_setup` and `car_gacha_config` were parsed and dropped; they are now decoded from
  the raw reply and zipped back onto the rows by index.
- `car_tnr_setup` carries the Tuner Stars parts fitted to the car, keyed by part name.
  **This is where a wheel's name lives** — `RIMS` is a `CarTunerStarsRimLibrary` ID, so
  `1000007` → `3B` and `1000200` → `84A`. `TIRE` resolves against `CarTunerStarsTireLibrary`
  and `BOOST_COLOR` against `CarTunerStarsBoostColorLibrary`.
- The rim and boost-colour libraries start at `1,000,001`, so a `0` from a car with no Tuner
  Stars part fitted is reported as `none_or_stock`, not as a failed lookup. That is 27 of the 29
  live rows; both genuine Tuner Stars cars on the roster resolve.
- `BODYKIT`, `HOOD`, `WING` and `WHEELS` are reported as `no_library_known`: they are aftermarket
  body-part slots in a small ordinal space (`BODYKIT` `6` observed) with no library located yet.
  Named rather than silently dropped.
- `car_gacha_config` is the cosmetic set a gacha roll applied, under short keys: `paid` paint,
  `inid` interior, `caid` calliper, `livid` livery, `lzsid` livery zone mask, `whbn` wheel bundle
  name. Live: `Porsche_Manthey911GT3RSRewardRecycled_2024` → paint `2694` "Porsche British Racing
  Green", `lzsid` `9` "CONTRAST", `livid` `1396` "Porsche_Manthey911GT3RS_MantheyGold_1".
  `INT32_MIN` marks a slot the roll left alone.

### Labels

- Add `LIBRARY_SLOT_ALIASES`: the decoded libraries use a different slot vocabulary from the
  roster, which is the sole reason three joins were marked unverified. `livery_zones_set` is
  served by `LiveryZonesSetLibrary`, whose records the binary parser labels `livery_zones_set`
  and the type-tree fallback labels `livery_zone_mask` — the alias accepts both, since which
  decoder wins varies per bundle. Both number-decal colour fields are served by
  `CarColorLibrary`'s `color` records. Coverage for `livery_zones_set` went 0% → 100%.
- Add `csr2cdn.visual_library_typetree`, a UnityPy type-tree decoder covering all twenty-one
  shipped libraries. The existing binary parser fails closed on `CarTunerStarsLiveryLibrary`,
  `CarTunerStarsLiverySetLibrary`, `CarTunerStarsTireLibrary` and
  `CarTunerStarsBoostColorLibrary`, leaving a Supra's livery `1000029` with no label source;
  `decode_library` prefers the binary parser and falls back to the type tree.
- Allow the `tire` and `boost_color` standalone slots in `GameVisualLibrary` manifests.
- Resolve labels by ID across model keys as a last pass. Some records are bound to a single
  model because the decoder reads a per-ID *exclusion* list as a binding: interior `1000133`
  "Toyota Black Leather" is recorded against `Toyota_GRSupraTNR_2020` and was worn by a
  `Toyota_SupraMK4TNR_1994`. A label belongs to the ID; only eligibility is model-specific.

### Service

- Treat the crewless reply as a result rather than a fault: `OwnCrew.from_response` accepts the
  verified `{"Error": "Player not in crew", "error_code": 306}` envelope as `in_crew=False`,
  while every other unmarked or mismatched envelope still raises.

### Tests

- Add 72 offline synthetic tests. Suite: 1859 passed, 246 skipped. The 7 failures are
  pre-existing symlink-privilege errors on Windows without Developer Mode. Read-only
  throughout: no gameplay writes, no save-API calls, no player identifiers in output.

## 0.7.1.dev81 — Offline cross-capture corroboration guard

- Add `csr2cdn.dev81_capture_corrob` to compare 2–8 separately signed Dev78/79 evidence sets, using Dev80 Ed25519 verification and a single pinned APK audit.
- Reject exact repeated capture labels, snapshot bytes, manifests, key hashes, or challenges; report stage/paint mismatches and incomplete observation separately.
- Keep all runtime-origin, signer-independence and production paint mapping verification flags false; include tests with synthetic/contradictory capture claims and no credential or gameplay requests.

## 0.7.1.dev80 — Optional offline detached Ed25519 capture attestation

- Add `csr2cdn.dev80_capture_attestation`, validating challenge-bound detached Ed25519 signatures over exact Dev79 manifest bytes with verifier-supplied raw public key and independently obtained key fingerprint.
- Require complete optional attestation inputs; reject signature/key/challenge tampering, malformed files and missing manifests. Recheck snapshot/APK/manifest integrity during verification and retain the Dev72–79 audit.
- No bundled signing secrets or automatic trust in self-reported capture. Signatures do not authenticate gameplay execution; production paint index 15 -> ID 1323 stays conditional and index 0 remains unresolved.

## 0.7.1.dev79 — Offline stage-manifest consistency and provenance limitations

- Add `csr2cdn.dev79_capture_provenance`, a strict optional JSON companion-manifest validator for Dev78 paint snapshots, binding raw snapshot and local APK SHA-256.
- Check stage-specific canonical payload hashes, native RVA anchors, strictly increasing event counters, required intermediate profile-update marker, and stated capture-method consistency.
- Reject malformed, unknown, inconsistent and oversized/symlinked evidence. A matching self-reported manifest never independently authenticates game execution or promotes production paint IDs.
- Add synthetic-only fixture and comprehensive negative regressions; preserve pinned Dev72–77 audit, index 15 → ID 1323 conditional and index 0 unresolved.

## 0.7.1.dev78 — Offline runtime paint snapshot validation gate

- Add `csr2cdn.dev78_runtime_paint_snapshot` with strict, bounded, non-mutating snapshot schema, stage-order/index/ID checks, and conservative provenance policy.
- Compose optional passive gacha guard observations with the pinned Dev75 and Dev77 predicates without replaying mutating delivery-pop logic.
- Every report reruns the Dev72–77 native audit; independent snapshot provenance is explicitly unverified and neither index 15 → 1323 nor index 0 is promoted.
- Add a deliberately synthetic example, documentation, and negative tests for malformed/sensitive/untrusted input.

## 0.7.1.dev77 — Pinned four-field gacha config validity predicate

- Add `csr2cdn.dev77_gacha_config_validity`, an offline APK-only ARM64 analysis of `CarVisualsGachaConfig.IsValid` at `0x381E36C`, SHA-pinned with all 17 instruction sites and three branch edges.
- Verify that a configuration is invalid iff all four int32 fields (`+0x1C`, `+0x20`, `+0x24`, `+0x28`) equal `INT32_MAX`; a non-sentinel in any field yields validity.
- Compose synthetic examples with Dev75 fallback without treating any register/configuration value as observed Mustang state; preserve Dev72–76 guards.
- No production resolver/mapping changes; `15 → 1323` conditional, paint index 0 unresolved. No new network, gameplay, or private-profile calls.

## 0.7.1.dev76 — Offline delivery-tuple list provenance and consumption guards

- Add `csr2cdn.dev76_delivery_tuple_provenance`, a fingerprint-pinned offline audit of `PlayerProfile.PopCarIfInDeliveryWaitingList` and its two-integer constructor in CSR2 6.8.0 ARM64.
- Confirm the packed low/high halves are read at position zero from two profile lists, but removal uses a separately computed list index; this can consume state and must not be invoked as a read-only probe.
- Pin the method and pair-constructor SHA-256 bodies, native instruction sites, BL targets and branch edges; add synthetic boundary and negative-binary regressions.
- Keep actual delivery state, gacha invocation, paint-list order and paint ID 1323 unresolved; make no production resolver changes or gameplay/network requests.

## 0.7.1.dev75 — Pinned gacha eligibility and config-index predicates

- Resolve and validate three native managed call targets, including `PlayerProfile.PopCarIfInDeliveryWaitingList`, `CarVisualsGachaConfig.IsValid`, and `CarVisuals.set_CurrentGachaConfigIndex`.
- Pin 32 ARM64 scene instructions and seven guard branch edges. Verify signed pop-return eligibility, garage fallback fields, and separate gacha-config-index negative/bounds/filter/null checks.
- Add a deterministic, explicitly hypothetical scenario model and 30 regression tests. Preserve all Dev74/73/72 native checks and APK-only evidence reproducibility.
- No runtime paint-list observation or production resolver changes. Paint 15 → ID 1323 stays conditional; index 0 unresolved.

## 0.7.1.dev74 — Gacha paint-index writeback and guarded aftermarket list mutations

- Add a pinned, APK-only Dev74 analysis of `CarVisuals.ApplyGachaConfig` and `CarVisuals.AddAftermarketPaintsToCar`, with managed method pointer verification, bounded SHA-256 fingerprints and ARM64 control-flow witnesses.
- Identify possible *pre-setup* gacha paint-list insertions and garage selected-index writeback, separate from two Tutorial-excluded stores inside `CarVisuals.Setup`.
- Verify guarded aftermarket-append behavior and a second list-bound check before positional paint lookup; branch reachability is not actual runtime execution.
- Add 21 focused offline tests covering these call paths, fail-closed binary changes, CLI no-overwrite, privacy and production-mapping nonpromotion.
- Preserve index 15 → paint ID 1323 as historical conditional evidence only; paint index 0 remains unresolved and production mappings are unchanged.

## 0.7.1.dev73 — Tutorial paint-list append exclusion and profile reapplication

- Extend Dev72's source-constrained ARM64 CFG to verify both Dev60 pre-selection paint-list append sites (`0x3802AA8`, `0x380309C`) are unreachable for `Tutorial=1`, in addition to the two already excluded garage-index writebacks.
- Verify the conditional crew-scene gacha call occurs before setup; a separate reachable scene continuation can later apply the garage paint index via `PlayerProfile.UpdateCarVisuals` → `PaintApplier.ApplyTo` → `ForceUpdateOfCarPaint`.
- Pin two new native method identities, method body SHA-256 fingerprints and fourteen exact instruction/call sites; add an APK-only, privacy-preserving evidence command and eighteen offline regression tests.
- No live paint-list capture, no new roster or network reads, and no production paint-label changes. Index 15 → ID 1323 stays conditional; index 0 unresolved.

## 0.7.1.dev72 — Tutorial-source paint writeback reachability

- Verify the two native source guards and build a branch-level intramethod CFG for `CarVisuals.Setup`.
- For the cached Tutorial-source Mustang, neither indexed garage writeback site is reachable in the pinned 6.8.0 method.
- Preserve the conditional 1323 paint-ID result and all privacy and non-production flags; no resolver changes.
- Add offline tests for native instructions, branch decoding, CFG reachability, tampering, and privacy.

## 0.7.1.dev71 — Crew setup paint-index selection

- Verify native `SceneManagerGarage.CarLoaded` calls `CarVisuals.Setup(carInstance, updateCarInstance=True)`.
- Verify paint index sync, `ForceUpdateOfCarPaint` list growth and ID lookup, and two conditional index writebacks.
- Add pinned offline report and regression tests; production paint mapping unchanged.

## 0.7.1.dev70 — Crew loader completion to visual setup

- Verified four additional 6.8.0 native method bodies and 16 ARM64 instruction sites, with managed IL2CPP pointer matches and SHA-256 fingerprints.
- Traced GarageCarLoader.CarLoaded and AssetRequestCompleted, and proved SceneManagerGarage.CarLoaded directly calls GarageCarVisuals.Setup, then CarVisuals.Setup.
- Clarified that crew-specific visual loading should not be conflated with generic CarLoader overrides. No proof of complete runtime paint-list ordering or later indirect mutations.
- Preserved index 15 → paint 1323 as a conditional static reconstruction; index 0 unresolved. No production changes, auth calls or network operations.

## 0.7.1.dev69 — Native crew garage-loader handoff

- Fingerprint five real CSR2 6.8.0 ARM64 methods and verify 12 native instruction sites linking the crew hangout/garage paths.
- Verify the direct copy of crew paint index to garage selected paint index and subsequent `GarageCarLoader` constructor/load calls.
- Distinguish this crew path from the generic `CarLoader` override path documented in Dev68.
- Retain paint ID 1323 only as a conditional static candidate; neither paint 15 nor 0 receives a verified production label.
- No new game requests or private asset distribution.

## 0.7.1.dev68 — Separate loader paint index and paint ID overrides

- Verified the native `CarLoader.LoadCar` → `CarLoaded` → `SetupCarVisuals` argument chain from the supplied CSR2 6.8.0 APK.
- Fingerprinted three full method bodies and 20 exact ARM64 instruction sites, including four actual branch destinations and the setter/append calls.
- Established that a non-sentinel override index takes the index setter path; only sentinel-index fallback may insert an explicit ID, while a null override bypasses these two overrides.
- Conservatively retain index 15 → ID 1323 as conditional; crew load path and actual override presence unobserved. Paint index 0 remains unresolved, old Transparent hypothesis withdrawn.
- Added privacy-safe offline analyzer and 19 new tests; no changes to production mappings.

## 0.7.1.dev67 — Milestone load routes and later paint insertion

- SHA-256-pin six native APK method bodies and 15 ARM64 instruction sites for JSON/binary CarMilestoneDataManager config loads and car-loader/race paint insertion.
- Confirm `CarLoader.SetupCarVisuals` conditionally calls `SetPaintIDAddIfNecessary` and copies the resulting CurrentPaintIndex back to the garage car. Human race setup has two direct insertion calls (one with explicit argument zero); AI race setup has another. These calls do not establish what ran for the crew car or what the roster's zero means.
- Reconcile the public FTUE 50-level scheme and current Mustang CarInfo (`IsTunerStarsCar=false`) without claiming the live manager dictionary or rendered paint list was observed. Conditional paint index 15 → ID 1323 unchanged; no production resolver edits.
- Offline Dev67 CLI, redacted evidence output, 13 new regression tests, source and wheel distribution. Original APK, Unity bundles and private roster cache excluded.

## 0.7.1.dev66 — current CarInfo Tuner Stars flag

- Decode CSR2 UnityFS-v8 / Unity serialized-v22 `CarMetadata` offline with embedded type trees and bounded LZ4.
- Verified current Mustang `IsTunerStarsCar = false` from all 1,278 CarInfo records, preserving offline privacy.
- Join that static flag with native APK and public milestone scheme checks; index 15 → 1323 remains conditional.
- Add standalone decoder CLI, combined diagnostic and regression tests. No production mappings changed.

# Dev65 — CarInfo bundle-source candidate and native load chain

- Verified two native setup callsites plus independent `CarInfo` flag-byte reads at record offset `0x21`.
- Resolved `CarMetadata.ASTC.1594` from the SHA-256-verified official database-34011 public index using `CDN.url_for`. **The asset contents and their connection to CarInfo remain unverified.**
- Added `dev65_carinfo_bundle_target` offline diagnostic, 12 regression tests, no user-identifying output, and an explicit public asset download target.
- Production paint resolver unchanged; index 15 -> 1323 remains conditional, index 0 unresolved.

# Dev64 — CarInfo Tuner Stars predicate provenance

- Verified compiled `CarInfo.IsTunerStarsCar` field, `CarDatabase.GetCar` pointer, CarInfo-bundle callback, and the ARM64 getter load at record offset `0x21`.
- Compared public db34011 index and car-scheme metadata; did **not** infer a Tutorial vehicle flag or assign conditional paint ID `1323` as a verified label.
- Added offline `dev64_carinfo_tuner_flag` audit and 13 regression tests. The APK, uploaded bundle, and private roster cache remain outside distributables.

# 0.7.1.dev63 — Native milestone predicates and FTUE scheme join

Dev63 traces `CarGarageInstance.HasMilestonesForCar` and `get_IsTunerStarsCar` through the pinned CSR2 6.8.0 APK. It independently joins the cached Mustang pricing record `EliteCustoms_FTUECar` to a 50-level `CarMilestoneData` scheme and the `AftermarketConfig.FTUECar` setting. Neither predicate was observed at runtime; the Tuner Stars result comes from a separate car-data flag. The replay index 15 → paint ID 1323 (Ford Dark Highland Green) remains conditional. Production mappings unchanged, index 0 unresolved, no networking.

```bash
python -m csr2cdn.dev63_garage_milestone_predicates \
  --apk CSR2_6.8.0.apk --bundle Ford_Mustang302_1970_common.ASTC.14 \
  --private-cache-zip endpoint-cache.zip --source-catalog dev36-source-ids.json \
  --output dev63-garage-predicate-evidence.json
```

See `docs/DEV63_GARAGE_MILESTONE_PREDICATES.md`.

## 0.7.1.dev62 — Native restoration setup guards and field separation

- Trace and pin the `CarVisuals.Setup` calls to `HasMilestonesForCar`, `IsTunerStarsCar` and `SetupAftermarketLockedData`, including both skip branches.
- Verify the `SetupAftermarketLockedData` call to `LockedCustomisationData.SetupMilestones` with the garage object, and the milestone source and prepared field writes (`+0x20` → `+0x30`). The existing `AllUnlockables` object remains a separate field at `+0x28`, returned directly when non-null by `GetAllUnlockables`.
- Compare the saved roster milestone level 50 without claiming that it changes paint option order. Conditional source-data replay retains index 15 → ID 1323 (Ford Dark Highland Green), but the runtime branch conditions remain unobserved. Neither index 0 nor 15 is a verified production mapping.
- Add a fail-closed standalone offline analyzer, 18 focused tests, redacted evidence report and complete reproducible packaging. No authenticated/server reads, new CDN downloads or production cosmetic changes.

## 0.7.1.dev61 — Compiled eCarSource constants and private roster source guard

- Decode and pin all twelve `eCarSource` constant values and the AArch64 `eCarSourceExtension.IsIAP` method pointer/body; verify `CarVisuals.Setup` source masking and branch destinations.
- Compare an explicitly supplied existing private cached roster (offline; no identity export) with the compiled enum: the car with paint index 15 reports `Tutorial = 1`, which triggers neither source-specific early-append branch tested in Dev60.
- The conditional unshifted index-15 replay selects ID 1323 (*Ford Dark Highland Green*), while Dev60's competing 129 scenario is excluded for a Tutorial source **under the cached-to-native source assumption**. Runtime paint remains unverified; no production mapping changes.
- Add synthetic enum, negative/bad metadata, branch classification, private cache privacy and optional live-operator tests. Do not bundle APK, Unity asset or cache.

## 0.7.1.dev59 — Native serialized unlockables fast path and milestone fallback

- Verified the *non-null direct return* path of `LockedCustomisationData.GetAllUnlockables` (`this+0x28`) using exact ARM64 instruction words, full-method hashes, APK IL2CPP method-pointer records and source-bundle type-tree fields.
- Traced the separate `SetupMilestones` (`this+0x20` to prepared `this+0x30`) and `GetAllUnlockables` *cache-miss fallback*. Verified the `CarVisuals.SetupAftermarketLockedData -> SetupMilestones` callsite.
- The current Mustang bundle serializes a populated `AllUnlockables` object; its 30 nonnegative paint entries equal the flattened 10 source paint milestone groups. Native append replay retains **conditional index 15 -> ID 1323, Ford Dark Highland Green**, without assigning a verified roster label.
- Added native mutation guards, offline evidence reports, milestone fallback sensitivity checks and 11 tests. No authenticated reads, CDN calls, private cache reads or production resolver mutations.

## 0.7.1.dev58 — Conditional native paint-index replay from uploaded current UnityFS bundle

- Trace the pinned CSR2 6.8.0 native call chain `CarVisuals.Setup -> ForceUpdateOfCarPaint -> AddAftermarketPaintsToCar -> LockedCustomisationData.GetAllUnlockables` from exact ARM64 method bodies and callsites.
- Verify selected paint index is bounds-checked against the car-local list, aftermarket option IDs are appended only if nonnegative and not already present, and the rendering path dereferences the resulting car-local list.
- Replay the observed append algorithm against the operator-supplied `Ford_Mustang302_1970_common.ASTC.14` base and `AllUnlockables.carPaintIDs`: 4 base IDs + 26 appended IDs = 30 entries; **conditional** index 15 -> paint ID **1323**, labelled **Ford Dark Highland Green** by the independent official database 34011 source catalogue.
- Index 15 -> 1323 remains a *conditional candidate*, not a verified live roster join. `GetAllUnlockables` can lazily aggregate milestone data, and full runtime state/order is not captured. Keep paint 0 and 15 production labels unresolved and preserve all production mappings.
- Add exact native fingerprint and instruction witnesses, offline reproducibility, redacted reports, synthetic safety tests, and no-network operation. Exclude game APK, current Unity asset, private roster and cache from distributables.

## 0.7.1.dev57 — Current per-car UnityFS bundle and unlockable groups

- Added standard-library UnityFS/LZMA, serialized-v17 type-tree decoder for actual current car-visual assets; supports optional lz4 block decoding if installed.
- Current uploaded Ford Mustang 302 base lists and all 11 gacha entries match Nitro4CSR historical data in their tested fields.
- Found independent 36 milestone / 30 paint-ID unlockable collection, containing `-1` separators. Index 15 is outside the four-entry base list; unlockables raw position 15 is separator, not a paint ID.
- Reconciled all 30 unlockables paint IDs with official database 34011 sources without assuming a crew mapping. Paint 0 and 15 still unresolved; no production changes.
- Added synthetic decoder and CLI tests, optional operator-bundle integration witness; original asset and private roster excluded from source/wheel.

## 0.7.1.dev56 — per-car CarVisualConfigs archive analysis

- Added `csr2cdn.dev56_car_visual_configs` offline inspector for Unity-extracted `CarVisuals` arrays and gacha presets.
- Preserves source array order, checks independently observed interior, caliper, livery and wheel values without inventing joins, and optionally checks all base/gacha IDs against a public source catalogue.
- Real historical car-config comparison confirms that received paint index 15 is out of the four-entry base list. The archived 2021 config is **not** certified current; runtime paint-list extensions and initialization order remain unverified.
- Retains the withdrawal of the earlier Transparent alias for roster paint zero. No production resolver changes, no proprietary source assets or private cache in distributions.
- Added regression tests for index boundaries, gacha overlap, field separation, malformed arrays, symlink rejection and CLI overwrite protection.

## 0.7.1.dev55 — Native setup branch and cache readiness

- Verify raw source-extension dispatch values `2`, `9`, `10` from `CarVisuals.Setup`
  mask `0x604`; verify alternate `eCarSourceExtension.IsIAP` call and branch targets.
- Clarify sign/sentinel checks, list membership/append and final index adjustment.
- Read bounded, hash-verified public cache descriptors plus two metadata blocks;
  output counts only, never open cached game/crew responses or publish model keys.
- No reconstructed runtime order, no index 0/15 assignment, no production
  resolver changes. Add focused native mutation and cache-tamper regression tests.

## 0.7.1.dev54 — Offline native paint-list setup witness

- Verified IL2CPP ARM64 constructor and setup of car-specific ordered paint-ID list, including selected index transfer and offset distinctions.
- Superseded the previous operator display assumption that roster paint 0 should be called Transparent; both 0 and 15 now unresolved.
- Added fail-closed exact native byte checks and synthetic regression tests; no change to production cosmetic resolvers.

## 0.7.1.dev53 — Offline native car-local paint-list population

- Verified compiled `CarVisuals.AddAftermarketPaintsToCar` calls into
  `get_LockedCustomisationData`, checks existing car-local paint IDs, and
  can append absent values.
- Added APK build-pinned native instruction/hash witness and privacy-safe
  cached source inventory with SHA-256 manifest validation.
- Added 8 focused regression tests. No semantic roster paint mapping
  promoted, index 15 unresolved, no server/gameplay requests.

## 0.7.1.dev51 — compiled crew JSON paint handoff (offline)

- Trace the exact `car_paint_id` IL2CPP literal from `PlayerCrewMember.FromJSONDict` via ELF relative relocations and its encoded string-literal usage, through a JSON integer read into a stack slot, to a direct `CrewMemberCarInfo.SetPaint` call. Confirm that the setter writes the value to the index-named crew field without global source-ID conversion in that path.
- Add bounded, fail-closed native witness verification, method SHA-256 fingerprints, redacted-only optional Dev38 comparison, and five synthetic ARM64 regression tests. Full suite: 1,357 passed, one skipped.
- Do not infer a universal wire-index conversion or resolve paint `15`; preserve the operator-approved `0 → Transparent` display label and production mappings. APK, endpoint cache, disassembly and private roster data are excluded from distribution. See `docs/0.7.1-dev51-native-crew-paint-handoff.md`.

## 0.7.1.dev50 — compiled crew cosmetic wire-key evidence

- Offline-only bounded IL2CPP literal-table inspection: validates the exact compiled `car_paint_id`, `car_interior_id`, `car_calliper_id`, and `car_wheel_name` spellings and independently audits the crew paint-index class API.
- Reuses Dev49 SMP-native JSON witness without conflating it with the crew-service serializer. Optional Dev38 redacted aggregates are reconciled by numeric ID and occurrence count.
- No production cosmetic mappings changed; paint 0 remains the operator-approved Transparent display alias, paint 15 remains unresolved.
- Private APK, crew cache and source assets are excluded from distribution. See `docs/0.7.1-dev50-crew-wire-literal-contract.md`.

## 0.7.1.dev49 — Native SMP paint JSON roundtrip (offline)

- Verify actual ARM64 `SMPHostInfo.SerializeToJson` and `SerializeFromJson` read/write the `AppliedPaintIndex` int32 field (`0x68`) through JSON methods without an index/ID conversion at the witnessed instructions.
- Verify corresponding getter and setter instructions, with bounded method byte SHA-256 fingerprints and negative-fixture tests. Distinguish **SMP-host JSON** from the unverified remote crew `car_paint_id` wire path.
- No production mapping modifications, no game/CDN requests, no APK/private replay cache in distributables. See [Dev49 research](docs/0.7.1-dev49-native-smp-paint-json.md).

## 0.7.1.dev48 — Native IL2CPP paint method-pointer audit (offline)

- Resolve actual ARM64 method addresses using IL2CPP v31 tokens, the `Assembly-CSharp.dll` module and ELF relative relocations. SHA-256 fingerprint bounded native method-pointer spans; keep native code and original APK out of outputs/distributables.
- Confirm through native instructions that crew `SetPaint` and SMP `UpdatePaintIndex` store the provided integer directly; detect a crew-car snapshot copy from selected garage car offset `0x6c` to paint-index field offset `0x20`.
- Native paint libraries distinguish index-to-ID and ID-to-index and have different invalid-value return codes. These paths do not yet establish the server `car_paint_id` wire representation, so no resolver, display alias, or mapping is modified.
- Add synthetic ELF/metadata security and regression fixtures, offline-only CLI, method fingerprints and reproducible documentation. See [Dev48 research](docs/0.7.1-dev48-native-paint-methods.md).

## 0.7.1.dev47 — APK paint representation evidence (offline)

- Add version-31 IL2CPP metadata auditor for explicit paint index/ID class fields and conversion method signatures.
- Optional privacy-safe aggregate replay of existing crew paint values against the Dev36 public source catalogue.
- Distinguish compiled symbol names from unverified native method behavior and wire-field semantics.
- No production mapping modifications or network requests; source APK and private cache excluded.

## 0.7.1.dev44 — Context-aware event-AI cosmetic provenance (offline)

- Add `csr2cdn.dev44_event_cosmetic_context` using the pre-existing verified local endpoint cache and Dev36 public source-ID catalogue, with no network, auth or crew reads. The reader allowlists six public event-metadata files and verifies cached SHA-256/size before analysis.
- Separate event AI `AIPaintID`, `AIInteriorID` and `AICalliperID` membership from `Restrictions[].CarPaintID`. Treat `2147483647` only as an observed sentinel *candidate*; no true semantics, roster source joins or new mappings are asserted.
- Analyze `AIWheelType` count/type/syntax distributions independently of numeric TNR rim IDs and actual roster wheel strings; raw wheel values are never exported.
- Replay the original event metadata and match the previous Dev44 per-block evidence exactly, including seven CareerRaceEvents tutorial/prize-car records that are not nested in `RaceEvents[]`.
- Add synthetic tampering/manifest/privacy/CLI regression tests. Do not bundle the operator cache. See [Dev44 research](docs/0.7.1-dev44-event-field-context.md).

## 0.7.1.dev43 — offline lexical key-path field/source triage

- Add `csr2cdn.dev43_field_path_triage` to compare sampled JSON metadata-cache key **spellings** and **value types** with the 14 roster wire fields in the existing Dev41 report. Three explicitly non-semantic lexical grades; bounded existing-cache-only inspection.
- Default per-field/source-block report is counts-only, with fingerprints, sampling limits and explicit **zero verified joins**. Exact key paths are available only in a separate opt-in private file (which may contain sensitive key names), with exclusive-creation protections. No source values, network calls, authenticated reads, native NMG decoding or accepted mapping changes.
- Validate Dev41 wire-field/type inventory, preserve `0 → Transparent` as operator-approved display alias only, keep paint ID 15 unresolved, and add synthetic integration/security tests. [Dev43 research](docs/0.7.1-dev43-field-path-lexical-triage.md).

## 0.7.1.dev42 — source-shape research on customization metadata (offline)

- Add `csr2cdn.dev42_customization_schema_audit` to inspect the seven allowlisted customization sources as two **distinct** kinds of evidence: opaque binary NMG files in an optional local APK and bounded JSON field *shapes* in an optional existing MetadataCache. No service sync or network access.
- Sample and classify JSON key **syntax** into paint/interior/calliper/wheel/color/livery/customization groups. By default output only per-block aggregate shape counts and hashes, never source values, keys, player IDs or model keys. Opt-in **separate private key-path export** contains sampled key paths but no values and uses exclusive file creation.
- Add independent input bounds, symlink and overwrite protection, and cross-check an existing Dev41 provenance report without suggesting that same-looking names or numeric IDs establish a native roster-field join. Production decoders and mappings unchanged; Transparent remains an operator-approved display label only.
- Twelve synthetic focused tests plus full regression suite. No original metadata blocks, proprietary APKs, private caches, or gameplay data shipped. Requires operator-supplied existing metadata cache/APK for real structural measurements. See [Dev42 notes](docs/0.7.1-dev42-customization-schema-research.md).

## 0.7.1.dev41 — offline field-to-library provenance audit and verification flag correction

- Distinguish native decoder support from verified roster-field name mappings. `VisualAssetCandidate.name_mapping_verified` is now strict; `native_schema_decoded` and `roster_id_match_candidate` are available for supported source decoders and provisional numeric-ID matches.
- Add `csr2cdn.dev41_field_source_provenance`, a no-network privacy-preserving field-to-asset evidence map of 14 observed wire fields, native primary array names, pending TNR decoders and seven unparsed NMG customization metadata blocks.
- The new report validates matching Dev36/Dev38 branch, database and source hashes before referencing aggregate coverage; Dev39 palette overlap is kept in its own namespace. User-approved paint ID `0` display alias `Transparent` requires explicit consent and matching evidence. Paint ID `15` remains unresolved.
- No authenticated requests, CDN downloads, new native decoders, automatic alias promotion, eligibility rules or production mapping changes. Full Linux test suite: 1,290 passed, 1 skipped (requires absent operator database fixture). See [Dev41 notes](docs/0.7.1-dev41-field-source-provenance.md).

## 0.7.1.dev40 — operator-approved Transparent display evidence and targeted wrap-source audit

- Add `csr2cdn.dev40_paint_id_investigation` to cross-validate Dev36 source catalogue, Dev38 actual received missing IDs, and Dev39 palette report against branch, database version, SHA-256 strings and record counts. Investigates only actual received unknown paint identifiers—not library numbering gaps.
- Allow the operator's explicit **Transparent** display label for paint ID **0** via `--accept-transparent-zero`, only when the same-version palette source reports ID 0 as Transparent. This is a **user-approved display alias** and does not change source library semantics or production paint resolver trust.
- Keep paint ID **15** unresolved. Explicitly report 0/15 collisions in *different* interior/caliper namespaces as unrelated source evidence.
- Add a bounded, opt-in three-GET public-only `CarWrapLibrary` probe (version, index, wrap bundle) or zero-request local bundle check. Wrap IDs are never equated with paint IDs.
- Add synthetic and real-operator-report-based tests, no-overwrite/private output guards, and Work instructions. All authenticated/gameplay reads remain zero; no proprietary asset bundles shipped. See [Dev40 notes](docs/0.7.1-dev40-received-paint-ids-and-approved-display-alias.md).

## 0.7.1.dev37 — offline source-ID lookup and bounded gap analysis

- Add `csr2cdn.dev37_source_id_lookup` to query individual cosmetic numeric IDs in a previously exported Dev36 public source catalogue, with per-attribute source labels and categories and no network/gameplay reads.
- Export independent, opt-in CSVs of all occupied source IDs and *internal source-numbering gaps*. Explicitly distinguish gaps from unresolved historical roster IDs and independent attribute namespaces from actual same-attribute conflicts.
- Validate catalogue/summary metadata consistency, source counts, individual records, and six SHA-256 metadata strings. Include no-overwrite output guards, CSV formula-safety, bounded inputs, and offline regression tests.
- User-supplied database `34011` catalogue: 5,726 source records, 401 internal numbering gaps, zero collisions within a cosmetic attribute. No new mapping has been accepted. See [Dev37 notes](docs/0.7.1-dev37-source-id-lookup-and-gap-audit.md).

## 0.7.1.dev36

- Add explicit-online `dev36_latest_visual_ids` to read the current database
  version for an operator-selected release (6.8.0 default), then validate
  and catalogue all six standard/TNR paint/interior/calliper source bundles.
- Add optional per-ID private source catalogue with source names and categories.
- Add optional *true* unresolved numeric paint/interior report, requiring
  preexisting locally saved own-crew and roster JSON fixtures. No gameplay I/O.
- Preserve strict limits: eight public GETs, size validation, no redirects,
  no credentials, no trusted mappings, and explicit no-roster-data status.
- Add synthetic CDN, failure/permission, fixture/privacy and dry-run tests.
- Real-source validation remains pending on a network-enabled environment.

## 0.7.1.dev35 (unreleased) — redacted private rim source structure hypotheses

- Add `csr2cdn.dev35_private_rim_analysis` for **offline-only**, fail-closed, redacted analysis of the explicitly exported Dev34 private rim source fields. Optional independent SHA-256 comparison against a saved replay report.
- Count adjacent versus nonadjacent repeated root `CarNames` strings, collapse-of-runs cardinality, duplicate source rim names and IDs, and restricted decimal/`0x` references coinciding with native rim source integers. These are **structural and numeric syntax hypotheses only**; no positional `CarNames`–`DefaultRim` pairing, wheel namespace mapping, eligibility rule, trusted label, or name disclosure.
- Add synthetic native-fixture and CLI regressions for failed baselines, malformed records, output redaction, no-overwrite and no-network operation. Production decoders, strict loaders and existing mappings are untouched. See [Dev35 investigation notes](docs/0.7.1-dev35-private-rim-structural-hypotheses.md).
- Previous operator-submitted Dev30 measurements remain the real-source baseline; no original private export or source bundle was available during local Dev35 tests. Not a release candidate.

## 0.7.1.dev34 (unreleased) — opt-in private native rim field inspection from an existing cache

- Add an explicit local-only `--private-rim-fields-output NEWFILE` option to the unchanged Dev30 replay command. After the SHA-verified offline native rim replay, capture the exact per-rim canonical `BrandName`, `Category`, `CompatibleCars` and source rim names/IDs, plus two independent ordered root arrays, in a **separate PRIVATE file** with exclusive creation and restrictive POSIX permissions. Source rims are NOT missing roster cosmetic IDs.
- Keep normal CLI stdout and replay JSON **counts-only**, and continue to prevent raw naming data from being exported by default. The private field export is opt-in, requires a saved rim source and rejects changed files or existing targets; it never initiates network or gameplay calls and does not assert name/eligibility joins.
- Add synthetic regression tests for explicit opt-in boundaries, redacted regular reports, cache mutation, source mismatch, file permissions and no-network replay. Native production resolvers, TNR decoding, strict loaders and trusted mappings are unchanged. See [Dev34 notes](docs/0.7.1-dev34-private-local-rim-inspection.md).

## 0.7.1.dev33 (unreleased) — cross-field rim diagnostics and honest replay-baseline evidence

- Add bounded, counts-only cross-field analysis of `CompatibleCars` references against the **native** `BrandName` / `Category` tuples within primary Tuner Stars rim records. Report whether repeated compatibility references occur within one or across multiple declared rim groups, without disclosing names, source IDs, record-level joins or assigning roster-wheel eligibility.
- Correct Dev30 replay's baseline summary: `matching_source_hashes_confirm_same_bytes_not_eligibility` is now **false** unless the validated baseline status, exact slot coverage, branch, database version, index hash and every replayed source SHA-256 all agree. Expose individual booleans for diagnosing mismatches; do not silently accept incomplete baselines.
- Add synthetic cross-field, integration and mismatch regression tests. Production label decoders, strict loaders, TNR source parsing and existing mapping trust gates are unchanged. No operator cache/source binaries or gameplay data packaged; no network/gameplay calls in this local build. See [Dev33 notes](docs/0.7.1-dev33-crossfield-source-evidence.md).

## 0.7.1.dev32 (unreleased) — offline relationship topology of the native Tuner Stars rim source

- Profile the per-rim `CompatibleCars` arrays as a bounded bipartite/co-occurrence graph: distinct reference sets, reused sets, degree buckets, connected-component counts and sizes. These are **within-source** structural counts only, not vehicle eligibility or roster wheel-name joins.
- Add counts-only repetition profiles for root `CarNames` and `DefaultRim` arrays, without positional pairing. Surface the declared `BrandName`/`Category` rim fields as counts-only lexical profiles.
- Wire the new metrics into the existing SHA-verified, zero-network Dev30 local-source replay. Add synthetic unit tests including malformed and overlarge input rejection and replay integration.
- Preserve existing decoder semantics, the strict production loader and bounded opt-in CDN behavior. No original game binaries were added to the distribution; no authenticated/gameplay requests or accepted mappings. See [Dev32 notes](docs/0.7.1-dev32-rim-source-topology.md).

## 0.7.1.dev31 (unreleased) — cross-platform cache-test fix and cautious rim namespace shape evidence

- Split Dev30's path-injection and symlink tests. Path-injection and simulated link-defense tests execute on **all** platforms; the actual symlink-creation integration test skips **only** when OS permissions or filesystem capabilities explicitly prevent creation, while unexpected errors still fail the test.
- Extend the Dev27/Dev30 cached-original rim source audit with bounded, **counts-only** lexical-shape profiles for CompatibleCars references, root CarNames and root DefaultRim strings (syntax and character-length distributions, not source names).
- Report distinct root car-name cardinality, distinct default-rim cardinality and whether distinct-name count happens to equal default entry count. The separately validated Dev30 real-source report contained 138 root name entries with four repeated entries, versus 134 defaults: **134 distinct names equals 134 default entries**, not evidence of correspondence or positional pairing.
- Retain exact/casefold/punctuation comparisons, SHA checks, request budgets and strict privacy; add synthetic regressions including 1,800 CompatibleCars occurrences (larger than the 1,716 in the operator's supplied audit). No change to production wheel/name decoder, eligibility rules or trusted mapping behavior.
- Operator-provided original-source hashes/aggregate counts are preserved as external evidence, not re-fetched in this environment. No raw game assets, cached source files, gameplay responses, or identifiers bundled. **Not a release candidate.**

## 0.7.1.dev30 (unreleased) — opt-in public-source cache and reproducible rim namespace analysis

- Use the user-provided successful Dev29 public-source aggregate audit as evidence, preserving its SHA-256 fingerprints, branch and 6-GET budget without inventing original ASTC bytes or roster IDs.
- Add `csr2cdn.dev30_public_source_replay` for explicit, bounded, read-only public CDN capture of up to four canonically validated original source bundles into a new local directory and hash-verified **offline** replay. No default online requests, no game login, no raw source exports to reports.
- Count rim lexical namespace overlap under exact, casefold and punctuation-insensitive casefold without exposing strings or treating a match as a roster-wheel or eligibility join; note false-positive risk from lossy transformations.
- Add synthetic mocked-HTTP, cache-tamper, manifest path-injection, no-overwrite and offline-no-network regression tests. Production decoders, trust gates and gameplay access are unchanged. No original game assets bundled; not a release candidate.

## 0.7.1.dev29 (unreleased) — opt-in bounded public CDN TNR source validation

- Add `csr2cdn.dev29_public_cdn_forensics`: dry-run by default; explicitly opted-in read-only **public CDN** version, asset index and up to four exact TNR bundles. No account, gameplay, HUB, or metadata access.
- Validate exact asset-index versions/sizes, download caps, no redirects, canonical TNR/rim decoders and privacy-safe structural reports; refuse unverifiable bundles, name joins, and eligibility promotions.
- Synthetic online-contract regressions, preserving production loader, source comparison and previously trusted mapping behavior. The local execution environment cannot resolve the public CDN, so no real server result is claimed.
- No user/game data, original proprietary assets, or secrets packaged. Remains an investigation build.

## 0.7.1.dev28 (unreleased) — opaque TNR trailer screen and rim consistency checks

- Remain package-only and offline. No gameplay, CDN, authentication, or network calls.
- Add bounded, aggregate-only scan of byte-aligned candidate Unity strings in **uninterpreted** validated TNR post-primary data, explicitly not a schema or compatibility parser; disclose no strings, IDs or model keys.
- Expand independently validated Tuner rim audit with empty, duplicated and unmatched root/CompatibleCars reference counts, without deriving compatibility or wheel-name joins.
- Fix the *Dev25 offline wheel evidence* false-positive for `*_Wheelbase` / `*_Wheels` by requiring whole `_Wheel` token boundaries, reusing the Dev27 boundary definition. Production and Dev24/Dev23 resolution paths are unchanged.
- Synthetic tests only; the missing numeric paint/interior IDs and eligibility semantics cannot be recovered from the source ZIP.

## 0.7.1.dev27 (unreleased) — offline rim metadata and TNR syntax counts

- Keep production label resolution, TNR primary decoder, strict native loader, and Dev26 comparison-only ambiguity handling unchanged.
- Add a fail-closed, privacy-safe **structural** audit of the validated Tuner Stars rim source, counting explicit CompatibleCars, AvailableSizes, root CarNames and DefaultRim evidence without publishing source names or accepting roster wheel joins.
- Add local asset database `_Wheel` filename pattern inventory, distinguishing delimiter-bound candidates from prefix-only lookalikes. A filename is not a roster name mapping.
- Cross-tab TNR IncludeToCar integers by source Category syntax; still **no eligibility semantics or supplementary trailer interpretation**.
- Entirely offline, synthetic regression data only; no gameplay/CDN requests, missing-ID reconstruction, UI verification, or release.

## 0.7.1.dev26 (unreleased) — source-only cross-library ambiguity audit

- Keep the canonical visual UnityFS decoder, production strict library loader,
  Dev24 live probe, and TNR eligibility decisions unchanged.
- Permit **only the offline forensic comparison loader** to retain duplicates
  in the same paint/interior/calliper ID from the corresponding standard/TNR
  source pair. Count them as ambiguities rather than silently accepting a name
  or failing before comparison can measure them.
- Reject duplicate source inputs and ID collisions across unrelated source
  pairs. Expose only aggregate overlap counts; never source IDs or roster data.
- All work is offline-only; no game requests, CDN queries or asset downloads.

## 0.7.1.dev25 (unreleased) — offline TNR source interpretation

- Preserve the Dev23 TNR decoder and Dev24 two-read source-ID comparison unchanged.
- Add `csr2cdn.dev25_visual_forensics` with an independent fail-closed source
  audit of primary `IncludeToCar` values, model category scopes, and remaining
  unknown trailer bytes; eligibility/UI trust stays explicitly unverified.
- Add opt-in paint/interior-only numeric-ID diagnostics by cohort, independent
  model-wheel asset and native wheel-string shape counts, and experimental
  standalone color palette overlap counts.
- No original game assets or private fixtures packaged, no new gameplay/CDN
  requests, no wheel/color auto-joins, no pruning or publication.

## 0.7.1.dev24 (unreleased) — controlled TNR source comparison

- Add a fully offline pure standard-vs-TNR source-ID comparison for paint, interior and caliper, broken out by TNR-looking versus other roster models.
- Add `--compare-standard-tnr` to the existing two-read TNR probe, requiring all three standard and three Tuner Stars native libraries before any authorized gameplay request.
- Report additional ID/name candidates, remaining misses and cross-source collisions in counts-only JSON. Preserve strict privacy, no wheel/color guesses, no automatic acceptance.
- No live requests, online asset downloads or publication.

## 0.7.1.dev23 (unreleased) — actual Tuner Stars visual libraries

- Decode three uploaded UnityFS/LZMA sources with **separate** TNR layouts:
  139 paints, 47 interiors (both zone names), and 32 calipers.
- Enforce unique high-range native IDs and exact TNR car-category scoping;
  merge without colliding with standard paint/interior/caliper libraries.
- Keep standard visual matches intact; bind TNR ID/name candidates only for
  supported TNR-model syntax, including native `TNR_YYYY` and `TNR0_YYYY`.
- Extend the two-request TNR probe to distinguish source-backed TNR candidate
  names from standard-library matches. Do not infer in-game label accuracy,
  wheel/color joins or supplementary native eligibility arrays.
- No source assets bundled, authenticated requests, or publication.

## 0.7.1.dev22 (unreleased) — TNR-source cohort investigation

- Add a zero-network-default, two-read-only-call TNR visual probe; no GCC read,
  new endpoint, player data export, or write operation.
- Split standard paint/interior/caliper/livery misses into TNR-looking model
  keys versus other models, preserving unverified semantics.
- Construct nine Tuner Stars-specific Android ASTC asset URLs from a *local*
  asset database. All but the previously decoded rim library remain native
  source-schema pending.
- Keep player names/IDs, car model strings, wheel strings, and server JSON
  out of the report. Distinct unmatched numeric IDs require explicit opt-in.
- Defer authenticated testing, exact TNR-source joins, and publication.

## 0.7.1.dev21 (unreleased) — offline asset-database freshness and local-file audit

- Add typed `VisualAssetRefreshReport` and `VisualAssetRefreshSlot` and a separate zero-network `csr2cdn.visual_asset_refresh` CLI. Compare **two supplied** asset databases for the 12 evidenced visual libraries: new versions, missing sources, new entries and suspicious size changes without guessing newer CDN versions.
- Audit local Android ASTC files by exact database-derived filename and byte size, flag missing, mismatched and unsafe symlink paths. A local byte-size match is **not** a source integrity check, authenticity claim or a successful UI join.
- Keep the original visual-library decoder, 0.7.1.dev20 source-ID diff, optional diagnostics and the four-request bulk gameplay validator unchanged. No official wheel/racing-color join is claimed and no authenticated or CDN requests are run.

## 0.7.1.dev20 (unreleased) — offline visual source-version comparisons

- Add `compare_visual_sources` typed API and zero-network CLI for exact library-version ID/label diffs, including separate interior zone-name changes. Output is counts-only by default.
- Add `recheck_visual_missing_ids` for previously approved opt-in numeric-ID reports, to measure whether refreshed *global* ASTC sources could cover paint/interior/caliper gaps without requiring another gameplay read.
- Treat wheel strings and three racing/decal color/zone joins as unverified even if IDs appear in newer standalone libraries. No fake labels or automatic joins.
- Maintain unchanged four-request bulk validator, published 0.7.0 and all previously verified APIs; no authenticated or Metadata CDN requests.

## 0.7.1.dev19 (unreleased) — offline unmatched-visual diagnostics

- Add typed `VisualGapDiagnostics` / `VisualGapSlot` for attribute-first,
  read-only analysis of current vehicle cosmetic coverage, accessible as
  `.paint.library_id_missing`, `.wheel.join_unverified`, etc.
- Count source-ID misses separately from unsupported wheel/decal-color joins;
  report color-palette ID and Tuner Stars rim-name overlaps as **candidates only**.
- Add default privacy-safe `visual_gap_diagnostics` to the existing bulk
  validator when visual libraries are loaded; optional
  `--show-unmatched-visual-ids` exposes only distinct numeric codes and
  occurrence counts, never wheel strings or player/model identifiers.
- Keep authenticated request count, source decoders, existing label bindings
  and published 0.7.0 unchanged. No new live validation; 0.7.1 CI pending.

## 0.7.1.dev18 (unreleased) — post-live aggregate review and gap triage (offline)

- Add `csr2cdn.bulk_gap_triage` to inspect a bounded, already-sanitized Dev17
  JSON report with **zero** authenticated requests, ID disclosure or server-data writes.
- Prioritize per-slot unresolved cosmetic coverage without exposing raw codes or
  individual roster records; keep the unresolved-ID analysis a future explicit
  opt-in task, since the original run intentionally saved no raw responses.
- Separate mapping gaps (paint/interior/caliper etc.) from **unverified joins**
  (wheel string and three color-related fields). An available color/rim
  asset never implies that its codes are interchangeable with roster fields.
- Gate retention *candidates* for expanded GCC, Crew RP and car translations on
  the relevant numeric evidence; never infer full pagination, native stat units,
  UI validation, automatic acceptance or pruning from a sanitized summary.
- Record the 2026-10-18 operator-authorized Dev17 live results as *historical*
  observations and keep new CLI behavior offline-only.

## 0.7.1.dev17 (unreleased) — bulk-test consolidation and evidence review (offline)

- Add `BulkUIReference` for opt-in, bounded, numeric user-interface observations (own crew rank, score, member count). User-supplied observations never automatically certify freshness or game-data equivalence.
- Add `review_bulk_evidence` and the `review` section to the existing four-read `crew_bulk_validation` report. Differentiate decoded roster/GCC/optional fields, exact translation/visual bindings, partial reads, and experiment outcomes; never equate expanded rows with verified offset pagination.
- Preflight all local catalogue, translation, visual, metadata, and UI reference files before any opt-in authenticated reads. The unchanged default is a zero-network dry run; explicit `--execute` still performs at most four existing read-only operations.
- Document the source-bundle command for the eventual single-shot bulk check, its privacy defaults, and the manual keep/fix/prune decision gate. No new native schemas, server claims, library endpoints or gameplay requests in this build. Published 0.7.0 is unchanged.

## 0.7.1.dev16 — Native Android ASTC decals, wraps, livery sets and rims (offline)

- Decode seven operator-supplied UnityFS libraries using observed Unity type-tree fields: flag (198), racing-number (222), license plate (35), wrap (110), livery-set (635), livery-zones-set (13), and Tuner Stars rim (480).
- Bind verified numeric IDs to existing attribute-first roster appearance slots for flag, racing number, license-plate style and livery-zones set; retain raw IDs, exact labels, and source SHA-256. Unmapped IDs remain unresolved.
- Expose wraps, livery sets and Tuner Stars rims through explicit `GameVisualLibrary.match` lookups only; *no inferred wheel-name or wrap-to-roster join*. Preserve signed negative wrap IDs. Rim compatibility and defaults are root-level source fields, not per-rim display names.
- Update asset planning from schema-pending to decode-supported, maintaining separate roster-join evidence. All new reads are offline. No proprietary bundles distributed, no gameplay bulk test or publication.

## 0.7.1.dev15 (unreleased) — exact offline ASTC asset planning

- Introduce `VisualAssetPlan`/`VisualAssetCandidate` and `plan_visual_assets_from_file` to plan the next official Android ASTC visual-library downloads from a provided local asset database.
- Use exact asset codes, versions and quality-specific size fields; defaults to seven candidate libraries not yet native-decoded. Preserve `.url`, `.filename`, decoder evidence and missing-slot status through attributes. Reject malformed selections and versions.
- Add zero-network `python -m csr2cdn.visual_asset_planner --asset-database <path> --show-urls`; no CDN or gameplay requests, no private account inputs.
- Do **not** infer wheel bindings from the Tuner Stars rim library or cosmetic joins from library names alone. No new native visual schemas are claimed. Prior Dev14 record decoders and the deferred four-read gameplay bulk test remain unchanged.

## 0.7.1.dev14 (unreleased) — native caliper and colour library records

- Decode the operator-supplied Android ASTC `CarCalliperLibrary.ASTC.1004`
  (384 unique named IDs) from its UnityFS type tree; bind exact roster `car_calliper_id`
  to `vehicle.visuals.calliper.name` and retain raw `.code` and SHA-256 provenance.
- Decode `CarColorLibrary.ASTC.594` (11 distinct numeric colour IDs).
  Ten have names. The game source's ID 9 has an empty `NameID`; it is not
  given a fabricated label or exported as a named record.
- Permit explicit `GameVisualLibrary.match(model, 'color', numeric_id)` lookup
  and normalized colour manifest rows. Do **not** equate colour-library IDs to
  decal colour codes (or any other roster field) without verified join evidence.
- Keep all previously supported visual bundles, interior zone attributes, and
  bulk-validation request limits unchanged. All decoding and binding is offline.
- No proprietary game assets in the Python distributions, no game/CDN reads,
  no GitHub changes, and no publication.

## 0.7.1.dev13 (unreleased) — attribute-first interior zone names

- Add `car.visuals.interior.name.zone1` and `.zone2` from the verified
  native `CarInteriorLibrary` Zone1Name / Zone2Name fields.
- Keep `car.visuals.interior.name` string-compatible with the existing
  zone-one label; retain `car.visuals.interior.names` as the ordered tuple.
- On incomplete or manually supplied interior mappings, expose `.zone2=None`
  rather than inventing it; unmatched interiors still have `name=None`.
- Export `InteriorDisplayName`; no added CDN/gameplay requests, and no
  proprietary asset bundles included in distributions.
- Continue to use Android ASTC assets for Android; High remains an explicit
  separate quality variant. The original asset database identifies
  `CarCalliperLibrary.ASTC.1004` and `CarColorLibrary.ASTC.594` as next sources.

## 0.7.1.dev12 (unreleased) — Android ASTC native visual libraries

- Decode operator-provided CarPaintLibrary, CarLiveryLibrary and CarInteriorLibrary UnityFS bundles, including bounded LZMA1 blocks and Unity serialized type-tree-backed ID/name records.
- Add real global visual ID mappings to existing attribute-first vehicle.visuals.* API; preserve both interior zone names and SHA-256 provenance.
- Add local visual-library inspection CLI, optional bulk-probe `--visual-asset-bundle`, synthetic regression tests and zero-network safeguards. No gameplay reads or publication.
- Distinguish Android ASTC asset preference from separate High/iOS compatibility testing. Unity layout support is specific to verified 6.8.0 sample files.

## 0.7.1.dev11 (unreleased) — offline visual Metadata CDN schema reconnaissance

- Add `VisualSourceInventory`, `VisualBlockShape`, and `VisualArrayShape` as typed, attribute-first schema evidence for cached visual-related Metadata CDN JSON blocks; no HTTP or auto-sync.
- Inspect up to eight allowlisted blocks, including `AftermarketCollections` for *schema inspection only*; identify candidate nested record arrays with bounded sample key/type signatures, opt-in to paths and field names, never emit source values.
- Preserve cache-reported CDN hashes separately from computed local SHA-256. Missing, oversized, malformed and unsupported inputs fail safely; no guessed label matches.
- Integrate optional schema evidence into existing four-read bulk probe without additional requests. A confirmed visual JSON layout can use the existing explicit layout decoder; output records only schema/slot coverage.
- Existing 0.7.0 gameplay source, expanded GCC experiment and local translation/name attributes remain unchanged. Combined live test deferred.

## 0.7.1.dev10 (unreleased) — Bound visual attributes and selectable car name style

- Add immutable local visual bindings to `CrewMemberVehicle` and `CrewOptionalSnapshot`: `vehicle.visuals.paint.name`, `.code`, `.source_library`, `.source_hash`, plus equivalent attributes for the observed visual-code slots. Missing source matches remain `None`; raw appearance IDs remain unchanged.
- Persist the caller's selected `SHORT` / `MEDIUM` / `LONG` style when binding translations (`MEDIUM` by default), instead of limiting style selection to report formatting.
- Add `with_game_labels(translations, visuals, style=...)` to bind both sources in one step; preserve `with_translations` and all existing models.
- Bind visual labels into the bulk-probe typed snapshot, without changing the four-read contract or exposing member details by default.
- Actual Metadata CDN visual-library JSON record layouts remain unverified; no native name claims, network requests, or new endpoints.

## 0.7.1.dev9 (unreleased) — Attribute-first car-name API

- Add string-compatible `car.name` (MEDIUM default), nested `car.name.short`, `.medium`, `.long`, and `car.names` as a fresh ordered list of all three variants.
- Preserve explicit missing variants and retain the historical `.choose(...)` and direct `.short/.medium/.long` attributes.
- Add offline `CrewMemberVehicle.with_translations(...)` and `CrewOptionalSnapshot.with_translations(...)` for `member.vehicle.name`/`.names` attribute access without implicit CDN requests.
- Reuse typed name objects in opt-in member label reports and retain privacy defaults; add explicit `car_names` variants only when member details are authorized.
- No endpoint changes, gameplay reads, release tag or publication.

## 0.7.1.dev8 — real English localisation UnityFS decoder (unreleased)

- Decode the supplied UnityFS v8 `Localisation_EN.ASTC.6312` translation asset, with two matching Unity string arrays (26,854 keys and values).
- Extract 1,343 car identifiers with SHORT/MEDIUM/LONG variants; MEDIUM default, missing forms unresolved. Trim source-only surrounding whitespace for display.
- Add offline `--translation-unityfs` to native-source inspection and combined crew bulk validation, retaining zero-network defaults and explicit output opt-in.
- Preserve Dev7 FlatBuffers/visual JSON adapters unchanged; add synthetic UnityFS regressions, no packaged proprietary game data.
- All new gameplay and metadata reads remain deferred until the planned combined live test.

## 0.7.1.dev7 (unreleased) — Native-label source adapters (offline)

- Add a bounded FlatBuffers translation-table decoder accepting only explicitly
  supplied field indices; normalize SHORT/MEDIUM/LONG game labels with MEDIUM as default.
  IL2CPP translation symbols are observed but binary file schema is not yet proven.
- Add hash-provenanced JSON visual-code extraction from an existing local
  `MetadataCache` using explicit library/record path/slot layouts.
- Add a privacy-preserving metadata schema inspector, source CLI, export
  opt-ins and bulk-probe integration without additional network requests.
- Reject malformed offsets, duplicate keys, ambiguous visual codes,
  missing source hashes and unknown schemas instead of guessing names.
- Existing 0.7.0 stays untouched; 0.7.1 new labels need native/UI validation.

## 0.7.1.dev6 — source-correct game names and visual-code library adapters (unreleased)

- Prefer current game Metadata CDN blocks through existing `CDN.get_metadata` / `MetadataCache`, not stale APK NMG fingerprints, for current metadata inventory. No metadata was fetched online in this build.
- Add strict normalized **game** car-name translation inputs supporting `SHORT`, `MEDIUM` (default), and `LONG`, with exact model-key resolution and no missing-variant substitution. HUB `Localisation` is a distinct interface-translation source, not assumed to be game car-name translations.
- Add per-vehicle, per-slot exact visual-code mapping input with library provenance. Labels come from operator-supplied *decoded* library records; native library schema is NOT yet independently decoded, so these are candidates only. Preserve raw IDs and all previous outputs.
- Add a zero-request local CDN metadata-cache inventory and new optional `crew_bulk_validation` arguments. Never fetch additional game endpoints automatically; member labels require `--show-members`.
- Add regression tests for name style, strict IDs, duplicate mappings, privacy, and four-response offline bulk reports. Hold the combined live test as requested.

## 0.7.1.dev5 (unreleased) — source-fingerprinted customization candidates

- Inventory seven actual APK binary NMG customization metadata blocks offline with bounded ZIP reads and SHA256 fingerprints; no parsing or invented cosmetic labels.
- Add an explicit, schema-checked `CosmeticCandidateCatalog` for operator-supplied model/slot/ID/name hypotheses with source block/digest/path evidence; reject duplicates, malformed IDs and mismatching APK checksums.
- Add aggregate per-slot coverage to the existing optional-data and bulk-probe reports. Candidate names are opt-in, remain unverified, and do not reveal player IDs.
- Preserve the 0.7.1.dev4 read contracts and zero-network dry-run; no new game endpoint, release or GitHub change.

## 0.7.1.dev4 — unreleased (exact offline vehicle catalogue cross-reference)

- Add bounded, deterministic `VehicleCatalog` matching roster `current_car` keys against the `DBName` fields of an operator-provided HUB `TextData/CarData.json` export. Match strings exactly; ambiguous duplicate keys fail closed.
- Expose candidate Tier, Star and EV markers with explicit community provenance; do not manufacture display names or translate paint/wheel/decal IDs without a source.
- Add optional `--car-catalog-json` to the existing four-read bulk probe. Catalogue loading uses local disk only and makes zero extra requests; report only match coverage unless `--show-members` is explicitly set.
- Add regression coverage for privacy, schema errors, duplicate keys, opt-in printing, local-fixture integration and zero-network dry runs.
- No online game test, PyPI publication, or changes to the released 0.7.0 package.

## 0.7.1.dev3 — unreleased (crew cosmetics and resilient bulk diagnostics)

- Add observed own-crew emblem and limited presentation metadata, plus tournament **shape-only** counts; no event payload, token or tournament values retained.
- Add typed current-vehicle paint, interior, livery, wheel and decal identifiers from existing member roster fields; identifier values remain provisional and are not rendered as in-game asset names.
- Preserve opaque tuning setup and custom license-plate text as private/unparsed data. Default reports show only presence and field coverage; member-level cosmetics require explicit `--show-members`.
- Make the planned four-read 0.7.1 bulk run continue when either GCC read fails: preserve the other three responses, return redacted per-read status and exit code 4 for partial results. Own-crew/roster failures remain fatal because they are required for identity-safe joins.
- Add offline privacy, invalid-wire-data, standalone and fault-injection tests. No authenticated live reads, repository publication or additional endpoints.

## 0.7.1.dev2 — unreleased (optional crew/member/vehicle data and consolidated probe)

- Add typed opt-in projections of known own-crew, member progression and vehicle fields from existing read-only responses, with strict numeric validation and no extra car lookups.
- Add optional snapshot service API, privacy-safe coverage summaries, guarded garage aggregation and value/individual-record opt-ins.
- Add offline-first bulk validation for optional data and the dev1 expanded GCC candidate in one future user-authorized four-read session. No automatic pagination or season certification.
- Keep published 0.7.0 behavior and experimental GCC contract separate. No live tests, game writes or publication in this build.

## 0.7.1.dev1 — unreleased (GCC range exploration)

- Preserve published `0.7.0` common GCC top-10/±5 read without changes.
- Add a bounded, separately opted-in native-serializer GCC range probe.
- Provide an offline-first diagnostic CLI with optional own-crew ID matching and controlled per-crew printing.
- Keep offset / expanded-range behavior experimental until live validation; never assert full pagination.
- Defer optional crew/member statistics and vehicle fields to subsequent 0.7.1 builds.
- No authenticated reads or release publication performed in this build.

## 0.7.0.dev34 (unreleased) — Prestige leaderboard UI window and crew-filtered read

- Add an explicit top-20 / +/-10 global Prestige window candidate using the existing native serializer; no claim that this exact range has passed a live check.
- Trace and allowlist the separate `leaderboard/{board}/scores/crewmembers` event read in CSR2 6.8.0 (`EventLeaderboard.RefreshCrewStandings`, native mode top 10 / +/-30); expose the decoded crew-tab leaderboard in `CSR2Services` and in opt-in CLI output.
- Retain exact six-decimal Prestige times, keep UI rank semantics unverified for the crew tab, print names only when requested, and fall back to safe response-key/type diagnostics for unknown crew schemas.
- Correct the public `__version__` marker left stale in Dev33; release CI remains pending. No authenticated new-route reads or publication.

## 0.7.0.dev33 (unreleased) — Prestige UI-accurate race time display

- Interpret Prestige `FastestHalfMileTime` scores as microseconds in the **Prestige-specific** presentation layer, matching the operator-confirmed UI: `7102993` → `7.102993` seconds; always exactly six decimals and never use floating point.
- Preserve the raw integer score for precise rankings and ties. Optional printed entries expose both `score_microseconds` and `time_seconds`; the own-player result carries `own_player_time_seconds`.
- Add `--ui-time 7.102993` for an exact operator-supplied UI comparison; keep the old raw-microsecond `--ui-score` flag for compatibility. Never infer UI validation from a CLI comparison alone.
- Record the game UI's top-20 global / ±10 neighbor / separate crew-member tab observations as scope notes. Existing read-only common-window results (top 10 entries + ±5) stay unchanged; no speculative new Prestige endpoints or ranges are introduced.
- Keep 0.7.0 publication blocked on the configured cross-platform GitHub CI and final release review.

## 0.7.0.dev32 (unreleased) — Prestige validation and CI gates

- Add zero-network-by-default `csr2cdn.prestige_release_validation` with read-only native common-window and optional top3-and-you cross-range checks. Print private Prestige names/ranks/scores only with explicit opt-in; match player identities by IDs, not display names.
- Resolve the native/metadata Prestige board once per authorized test, preserving the same event board and offset across both standings reads. Report optional recent operator-provided UI comparison candidates without declaring score units or rank accuracy confirmed.
- Scope GCC 0.7.0 to the observed top-10 plus own-crew ±5 window; defer arbitrary GCC pagination and optional crew statistics to 0.7.1.
- Prepare an unexecuted 15-job Windows/Ubuntu/macOS and CPython 3.9–3.13 CI matrix, plus distribution build and strict metadata check. Final version remains `0.7.0.dev32` until release approval.

## 0.7.0.dev31 (unreleased) — deterministic crew-season lifecycle checks

- Introduce `GCCSeasonTiming` for cautious `end_time`/`time_left` correlation with the read timestamp; derive a candidate 14-day start for diagnostics only, never invent a verified server season ID.
- Introduce `CrewSeasonTransition.between(previous, current)` to evaluate an **observed** boundary advance and member/GCC zero-reset pattern; a successful synthetic test is explicitly not a live observation. A later live snapshot may be nonzero because players earn RP immediately after reset.
- Carry the existing own-crew `crew_rp` and `crew_garage_value` as **unverified and distinct** crew statistics; output requires explicit opt-in. Preserve the validated seasonal member/GCC matching and dynamic roster count.
- Invalidate a non-atomic member-vs-GCC comparison when its timestamps straddle a candidate boundary; allow ±1 UTC hour for a 14-calendar-day rollover across daylight-saving transitions.
- Add `python -m csr2cdn.crew_season_validation --simulate` for a zero-network, synthetic before/after reset rehearsal; retain exactly the previous three read-only contracts. Final 0.7.0 and real season lifecycle validation remain blocked.

## 0.7.0.dev30 (unreleased) — known crew wire fields and cautious season-time probes

- Correct the selected numeric inventory to include the live-observed snake_case crew statistics (`crew_rp`, `crew_level`, level bounds, garage/career totals, `members`, `max_members`, invite/request counts) and `career_earning`/`cash_donated` member aggregates. Preserve previous alias candidates without promoting ambiguous stats as typed seasonal RP.
- Extend bounded, redacted one-level schema discovery to `tournament`, `crew_logo`, `car_gacha_config`, `car_tnr_setup` and existing `logo`; never print nested values or player/account identifiers.
- Expose GCC `end_time`, `time_left`, `cardinality`, `bucket`, `tier` types and explicit opt-in candidate scalars; evaluate a **hypothetical** Unix-seconds/seconds correlation against GCC read time only when plausible. Native field names support the investigation but do not certify units, season ID or rollover.
- Compare distinct own `crew_rp`, complete roster `cc_contrib` sum and exact-ID GCC `score` with optional values, strict identity/coverage and <=30s sequential read gates. No synonym mapping or automatic semantic promotion.
- Synthetic regression suite, preserved three signed read contracts, CLI default zero-network and redacted errors. Dev30 offline-only; no authenticated run, game-state write, Prestige rerun or publication. See [Dev30 notes](docs/0.7.0-dev30-existing-endpoints.md).

## 0.7.0.dev29 (unreleased) — redacted inventory of existing crew read endpoints

- Add `CSR2Services.get_crew_endpoint_inventory` using exactly the established checkUserCrew, viewMembers and GCC viewcrew read contracts, and the independent `python -m csr2cdn.crew_endpoint_inventory` CLI. No speculative routes or additional pages.
- Aggregate original response-envelope keys/types, roster field coverage, the GCC `scores` and nested `logo` shape; surface candidate season/pagination metadata names without values or semantic claims. Enforce privacy filters, strict caps and redacted error handling; default zero-value output and zero-network dry run.
- Preserve GCC progress row `logo` / other `extras` and response-level payload `extras` in typed objects, omitted from repr. Only print selected numeric own-crew and aggregate roster candidates with a separate explicit opt-in.
- Add synthetic offline regression/privacy tests; no live authentication, game-state changes, Prestige rerun or publication. Final 0.7.0 remains blocked by existing release gates.

## 0.7.0.dev28 (unreleased) — source-backed Crew RP snapshots

- Add public `CrewRPSnapshot` and the opt-in read-only `CSR2Services.get_crew_rp_snapshot()` method using the observed roster `cc_contrib` and exact-ID-matched GCC progress `score` and `rank`.
- Detect incomplete, duplicate or changing rosters, wrong own-crew matches, stale or skewed responses, and possible score resets without fabricating a 14-day season ID. Return typed results and redacted summary; never conflate non-atomic consistency with season proof.
- Use own-crew `memberCount` dynamically where available instead of hardcoding 29. Add GCC progress alias properties for score and server-returned rank; preserve the legacy wire and offline GCC results decoder.
- Dev27 independent authorized validation: 29 member contributions summed to 38,226,786; exact GCC score 38,226,786; server rank 253; timestamps displayed 13:31:17 UTC on 2026-10-16. No new authenticated reads or publication performed while preparing Dev28.

## 0.7.0.dev27 (unreleased) — clock-stable tests and sequential GCC comparison

- Fix the Showdown test mixing wall-clock schedule boundaries with a fixed `at=AT` evaluation. Its window now uses the same fixed test fixture time. Leave live-runner time-relative tests unchanged where the real time is part of the intended behavior.
- Add a transparent *sequential* cross-read comparison of all roster `cc_contrib` values against the exact crew-ID-matched GCC progress `score` when both existing allowlisted reads are opted in.
- Record local read-completion timestamps, coverage/match gates and signed numeric difference; never claim the reads are atomic or prove the active season. No new server requests or publishing changes.
- Confirmed live data from dev26: 21 crew rows, one exact ID match, score 38,226,478, rank 253 (2026-10-16 13:14 UTC); these are not fabricated test expectations or current constants.

## 0.7.0.dev26 (unreleased)

- Add a strict, separately typed GCC progress `scores` row decoder for observed `crew_id`, `name`, `rank`, `score` shape.
- Match own crew by exact crew ID, not name or historical leaderboard rank; provide source-reported score/rank and snapshot deltas.
- Print all decoded crew rows only with the existing explicit `--gcc-print-score-candidates` option; keep crew IDs/tokens private.
- Keep GCC results `cc_rp` and generic progress `score` separate; season scope and final release remain blocked.
- Add 14 focused regression tests for decoder, ID match, privacy, errors, and read-only request boundary.

## 0.7.0.dev25 (unreleased) — GCC progress `scores` schema probe

- Distinguish dev24's actual `scores` progress response from native GCC `results` crew records, without inventing rank/total/season semantics.
- Print bounded whitelisted shape census, with separate opt-ins for sanitized schema key names and numeric/name hints.
- Return diagnostic exit code 3 until the GCC standings truly decode; keep only known allowlisted read-only requests and no raw body logging.
- Add ten synthetic privacy, shape, CLI and request-boundary regression tests.
- Preserve individual `cc_contrib` validation and all previous behavior; 0.7.0 release remains blocked.

## 0.7.0.dev24 — Experimental GCC current-progress read and typed member seasonal contribution (unreleased)

- Promote screenshot-matched `cc_contrib` as `CrewMember.season_crew_rp` only when explicitly present and valid, preserving candidate and source provenance. `score` fallback remains unpromoted, as do lifetime and profile RP.
- Reconstruct native GCC current-progress read path (RVA `0x38a7dac` → `0x34b83b8` → `0x3504770`). Add opt-in `gcc_progress_contract`, validating exact category 3 and parameter order/range. Its `leaderboard/crew-champs-v2/viewcrew` path is **APK-default inferred, not live/runtime verified**.
- Add explicit `--gcc-live` and `--gcc-only` to print decoded crew standings, total, ranks and own-crew delta; unknown envelopes get value-free structural diagnostics, no raw response dump.
- Add synthetic contract, privacy, no-network-default, invalid-route and typed-key tests. Overall release blocked; no live reads performed here or publication.

## 0.7.0.dev22 — Native seasonal Crew RP candidate probes (unreleased)

- Add *separate, unverified* `CrewMember.season_crew_rp_candidate` and `season_crew_rp_source`: exact 6.8.0 roster parser precedence `cc_contrib` then `score`; neither can masquerade as profile or lifetime RP. Accept zero; reject booleans, negative/fractional values, and invalid strings. Preserve the existing legacy `crew_rp` decoding unchanged.
- Add value-free, always-safe native field census to the current `viewMembers` diagnostics, including missing, null, malformed and parseable contributions, with opt-in `--crew-only --crew-season-probe` distinct member-ID coverage and explicit blocked/season-not-verified flags. Include `cc_contrib` and `score` in the opt-in static-key schema census.
- Add offline `GCCCrewStanding`/`GCCCrewStandings` decoder for the native `RemoteCrewInfo` mapping (`cc_rp` season, `rp` all-time, `crew_rank` rank, `score` fallback). Do **not** invent GCC `viewcrew` URLs or introduce any new network route.
- Add synthetic privacy, precedence, malformed-values, coverage, GCC and dry-run regression tests. No live validation, account/profile writes, Prestige rerun or publication. Crew RP remains blocked until season-scoped in-game comparisons.

## 0.7.0.dev21 — Native player-RP semantics and package-fixture integrity

- Trace the exact `player_rp` wire key to `UserManager.FillNonSecureBlobDict` (RVA `0x368b79c`) which calls `PlayerProfile.get_RP` (RVA `0x34be580`). Expose `CrewMember.player_rp` separately; **do not** map it into `crew_rp`, `RP_season`, or `RP_allTime`.
- Preserve the absent/unknown seasonal Crew RP as `None`; add a value-free `player_profile_rp_populated` count. Keep text crew roles and all previously working read-only paths.
- Confirm native `PlayerCrewMember.FromJSONDict` reads uppercase `RP` to object offset `0x88`, while `CrewRankPanel.RefreshUI` reads the *separate* season field at offset `0x94`. `PlayerCrew.set_Members` uses local profile GCC state when updating the local member's season value; the supplied evidence does not establish a crew-wide season-RP wire source.
- Repair the full-project source ZIP's exclusion filter to preserve the six synthetic Showdown `.meta` fixtures; require source-ZIP, sdist and wheel tests in packaging checks.
- Not yet live verified: profile RP coverage, in-game crew-season RP, any actual RP/role values, and remaining Prestige/release gates.

## 0.7.0.dev20 — privacy-filtered crew wire-schema diagnosis

- Dev19 live report confirmed 29 text roles and 87 matching RP-looking field occurrences, but zero decoded Crew RP. A substring match may count car-performance schema keys (e.g., `carPP`) and cannot establish seasonal RP.
- Add `--crew-rp-schema` as a **separately opt-in**, crew-only, no-values, aggregate census of repeated RP-looking field *names*. It excludes dynamic, sensitive-looking or singleton keys, never prints identifiers, auth state, nicknames, payloads, or RP values. Use this output for native semantic tracing; do not map unknown keys to `crew_rp` yet.
- Add family counts, preserve the existing typed RP logic unchanged, and add privacy/ambiguity regressions.
- This is diagnostic only. **Crew RP has not been recovered from live data.**

## 0.7.0.dev20 — Crew RP wire-shape audit (read-only)

- Expose privacy-safe aggregate wire-shape diagnostics from the crew roster decoder.
- Distinguish missing RP keys, unparseable keys, nested candidates and native compact-list RP slots, without emitting raw field names, IDs, nicknames, roles, scores, or raw network data.
- Keep RP missing instead of inferring lifetime RP, crew totals or alternative leaderboard scores.
- Preserve working Prestige/Showdown paths; no live RP source is yet verified.

## [0.7.0.dev20] — Native uppercase RP and typed crew-role check (unreleased)

- Correct the verified `PlayerCrewMember.FromJSONDict` wire-key casing: the Android 6.8.0 client reads **`RP`** (uppercase), while dev17 only read lowercase `rp` and hypothetical crew aliases. Keep compact-list lowercase `rp` support, and distinguish explicit season aliases when available.
- Add `CrewMember.crew_rp_source` and `rp_all_time` so numeric RP cannot be silently presented as verified seasonal Crew RP; retain positional field compatibility and `None` for missing/invalid values.
- Add canonical `CrewMember.role_normalized` for the native 0–4 `CrewRole` enum (NEWBIE, MEMBER, SENIOR, ADMIN, LEADER) without changing the existing `role` value.
- Expand value-free `--crew-only` diagnostics to count uppercase RP, explicit season field sources, raw native all-time RP, and populated/recognized role fields. Do not emit identifiers, values, or response dumps.
- Live dev17 report confirms 29 roster records, 29 nicknames, 29 player levels, **0 typed Crew RP**. Dev18 is offline-only until the same authorized run is repeated; seasonal RP semantics require comparison against the game.
- Prestige Cup's 21 live-retrieved entries remain independently verified for supplied Season 277, but score/rank and pagination are not yet verified. No publication.

## [0.7.0.dev17] — Typed crew-member nickname, RP and rank (unreleased)

- Promote native crew roster `name`, `rp`, and `level` into typed `CrewMember.nickname`, `crew_rp`, `player_rank` attributes; retain compatible `name`, car, and other fields. Handle dictionary aliases and both supported compact native layouts.
- Add `--crew-only` to sanitized live validation: check own crew and roster only, with counts of member records containing each field and no raw player details. The opt-in `services --execute crew` CLI also shows typed member values locally.
- Add source and installed-wheel regression tests for field extraction, missing/invalid values, zero values, native list layouts, privacy, and crew-only selection.
- **Live milestone:** Dev16 integrated Season 277 Prestige standings read succeeded (21 decoded records), but score/rank equivalence, pagination, cached-season/identity mode and cross-platform CI remain unverified. Whether server member `rp` is current-season Crew RP remains to be checked in-game.
- No save-game/chat features, publication, or authentication tracing.

## [0.7.0.dev16] — Native Prestige Cup template and timed-board reconstruction (unreleased)

- Retrieve the type-46 special-ladder binary asset by its current AssetDatabase version, decode the 6.8.0 Prestige repeatable race group and preserve source-specific structural diagnostics.
- Resolve `silver_prestige` and `Silver_Prestige` telemetry case-insensitively only on structurally valid event groups, including the native binary template.
- Reconstruct an active Prestige timed-board ID from explicit runtime season and verified car-tier inputs, the season-specific Prestige car mapping, attached binary leaderboard object, seven-day repeat-window projection, generated first race EventID and current ranking definition.
- Add read-only CLI options `--prestige-season`, `--prestige-car-json`, `--prestige-car-tier` and optional Python API overrides. No guessed fallback; invalid or missing input prevents a standings read.
- Preserve the optional `[events]` extra: no LZ4/UnityPy dependency at ordinary import time. Add regression tests and source-backed offline reconciliation.
- **Not yet live verified:** current cached crew season and leaderboard mode, actual standings/rank/score, pagination; cross-platform CI and final 0.7.0 are still blocked.

## [0.7.0.dev15] — Preserve season-numbered Prestige car metadata (unreleased)

- Decode the seasonal `CrewLeaderboardRewardDefinitions.SeasonalRewardCars` mapping from Unity event metadata, retaining exact season identifiers rather than discarding car lookups.
- Expose an internal `seasonal_prestige_car` lookup without guessing a current season, Prestige event group or leaderboard ID.
- Reject conflicting or malformed season records, and add synthetic offline regressions.
- Live Prestige standings remain unresolved; season-specific car metadata alone is not a leaderboard.

## [0.7.0.dev14] — Investigate native SpecialLadderEvents registration (unreleased)

- Include `SpecialLadderEvents` as a distinct read-only Prestige metadata source based on CSR2 6.8.0's `RaceEventDatabase.ProcessSpecialLadderRaceEventData` path.
- Extract groups under the native `LadderEvents` container separately from cup series, career and Showdown. Do not classify generic ladder groups as Prestige without evidence.
- Add value-free source coverage counts: groups, groups with leaderboard attachments, and exact native `Silver_Prestige` matches; report unavailable sources explicitly.
- Add synthetic fixtures for correctly shaped ladder metadata, misclassified ladder groups and discovery request gating. Live Prestige board retrieval still requires verification.

## [0.7.0.dev13] — Preserve unnamed Prestige event groups (unreleased)

- Trace the native UI Prestige predicate to `RaceEventGroup.get_TelemGroupName` and confirm serialized `id` is independent of `EventGroupName`.
- Preserve native `Silver_Prestige` race groups from modular Unity asset objects even where no UI display name is present. Keep them separate from Showdown groups; require authoritative schedule and leaderboard details before request creation.
- Add value-free coverage counts for runtime and unnamed Prestige groups and new synthetic decoder-to-board tests.
- Production Prestige discovery and standings are still unverified; 0.7.0 release remains blocked.

## [0.7.0.dev12] — Native Prestige telemetry and live runner wiring (unreleased)

- Configure CareerRaceEvents and InvitationalRaceSeries loaders in the normal
  `--prestige-current` live validation entry point, correcting the dev11 wiring bug.
- Match the actual CSR2 6.8.0 `RaceEventData.IsPrestigeEvent` string literal
  `Silver_Prestige` against the parent race group's telemetry classification;
  earlier synthetic `PRESTIGE`/`PRESTIGE_CUP` telemetry matches were inaccurate.
- Keep the explicit-name fallback only where the metadata does not provide a
  telemetry classification; never override a non-Prestige telemetry label.
- Report configured, attempted, loaded and unavailable additional metadata sources,
  and count exact native telemetry matches separately from other candidates.
- Add offline integration tests covering the CLI, full source fetch chain, actual
  native-classification value, board preparation and sanitized result handling.
- No credentials, account-specific data, APK binaries, save-game capabilities,
  or global chat features are included. Production Prestige remains unverified.

## [0.7.0.dev11] — Source-corrected Prestige discovery (unreleased)

- Replace incorrect string/filename `EventFile` matching. CSR2 6.8.0 stores
  `SeriesEvent.EventFile` and `RaceEventGroup.EventFile` as native int32 fields.
- Add the separately processed `CareerRaceEvents.SMPRaceEvents` collection and
  `InvitationalRaceSeries` to automatic Prestige discovery sources.
- Report value-free diagnostics for numeric event-file counts, positive Prestige
  classifications, and additional-source coverage instead of claiming a cup
  series reference resolves a leaderboard.
- Keep requiring a positively classified event group, schedule, first race ID,
  leaderboard attachment and ranking definition before making a live read.
- Preserve the live-verified dev9 crew and Showdown implementations. Production
  Prestige Cup discovery and standings remain unverified pending an authorized test.

## 0.7.0.dev10 (unreleased)

- Integrate Prestige Cup research into the live-verified dev9 baseline.
- Discover separate `CupInvitationalRaceSeries` metadata and modular `RaceSeries`
  events; classify via explicit Prestige telemetry before resolving boards.
- Add PlayerID-only current-Prestige read API and live validation selector.
- Preserve existing crew, Championship/Elite Showdown, and legacy Leagues behavior.
- Resolve explicit Prestige `SeriesEvent.EventFile` to matching decoded race
  groups only when the group has no contradictory telemetry classification.
- Add synthetic offline regressions for metadata loading, event classification,
  native board construction and safe incomplete-source handling.
- Real active Prestige Cup resolution and response semantics remain unverified.

# Changelog

## 0.7.0.dev9 — seasonal names and crew roster compatibility (development)

- Resolve the public "Championship Showdown" label to a uniquely active `SMP_SHOWDOWN_<season>_W2` and "Elite Showdown" to `SMP_SHOWDOWN_<season>_W1` using current metadata, never a fixed season/calendar mapping. Keep exact event-name selection for non-alias names; do not fall back to an unrelated event when W1/W2 is inactive.
- Signal inactive seasonal events separately; refuse missing leaderboard inputs or overlapping active seasons.
- Recognize additional explicit crew roster wrappers, native positional member-list formats, and a uniquely identifiable member array when the wire envelope uses an undocumented field name. Never treat unknown/malformed responses as empty rosters.
- When a crew response is still unknown, provide only a bounded, key-free, value-free structural summary (container counts) through the local validation harness. No account records or session internals are logged.
- Add synthetic regressions, retaining all 0.6.0 and prior 0.7.0 behaviors. Public crew roster compatibility remains subject to a new authorized live test.


## 0.7.0.dev8 — service compatibility and metadata merge corrections (development)

- Align account-session handling with the working reference implementation; retain token integrity and expiry checks, and bind game-service reads to the caller-selected PlayerID.
- Remove an ineffective, unverified alternate account-selection retry.
- Preserve dictionary-keyed leaderboard definitions through runtime metadata merging.
- Add regression tests for both corrections using synthetic, non-sensitive data.
- Actual own-crew and named Showdown service reads still require live verification; no final release.


## 0.7.0.dev7 — runtime event loading and guarded session retry (development)

- Add streamed, bounded downloads of category-47 ASTC-quality Unity asset bundles via the existing CDN and a UnityPy decoder for TextAsset JSON and MonoBehaviour type-tree event records. Merge runtime event groups, schedules and leaderboard definitions into dynamic Showdown discovery.
- Activate runtime asset loading in automatic PlayerID-plus-Showdown-name lookups and the opt-in live-validation runner. Suppress raw payloads and distinguish runtime-source failures from absent active events.
- When the portal returns a token naming a different player, optionally retry once using a directly selected PlayerID and its corresponding request hash. Preserve strict identity validation; fail without service reads if the response still does not match. No login result has been verified live.
- Add synthetic decoding, streaming, integration, privacy and identity-retry tests. Keep save management and chat excluded; retain legacy Showdown Leagues support.
- Production bundle schema and service authorization are not yet validated. Do not publish a final 0.7.0 release.

## 0.7.0.dev6 — modular event-source preflight (development)

- Confirmed via CSR2 6.8.0 native call paths that standalone Showdown metadata
  can be supplemented by event data loaded from asset bundles. An empty
  current-event list from standalone metadata is not proof of inactivity.
- Added an explicitly supplied, already-decoded modular Showdown group input,
  de-duplicated by EventGroupName like the native merge. The loader is
  offline-only unless the application supplies its own authoritative source.
- Added a native asset-type-47 catalogue selector for identifying event
  metadata bundles in an existing current asset database; it does not
  download or decode them.
- Added a local `--modular-groups-file` testing option, a source-coverage label
  in sanitized live-test summaries, and regression tests.
- Kept strict PlayerID/session checks; the reported production session
  mismatch and authoritative asset-bundle discovery remain release blockers.
  No network compatibility is claimed.

## 0.7.0.dev5 — four-input Showdown resolution (development)

- Surface typed native-derived inputs and provenance for start, duration,
  ranking direction and ordered first race ID.
- Add direct event group time support, conservative native repeat-cycle
  calculation, and explicit refusal of unresolved schedule-level recurrence.
- Detect ambiguous schedule IDs, inherit supported schedule windows, and
  accept Unix timestamp strings without guessing arbitrary epoch formats.
- Add ten new offline regression scenarios and document remaining real-metadata
  and client-state verification requirements. No private save-game functionality,
  global chat retrieval, or server-authentication logging added.

## 0.7.0.dev4 — named Showdown resolution (development)

- Add `get_showdown_leaderboard(showdown_name=...)` and `prepare_showdown(showdown_name=..., discovery=...)`: the public Showdown selector no longer requires a leaderboard name, ID, or a bundled event list.
- Recover the normal EventLeaderboard server-ID template and first-race EventID derivation from the CSR2 6.8.0 native method; use current schedule and template ranking data to calculate complete normal board names.
- Resolve named events, recognize arrays of explicit schedule time windows and inherited `BasedOn_ScheduleID`, and fail safely on ambiguous or unavailable inputs.
- CLI and optional live-validation runner accept `--name` / `--showdown-name`; never send requests for an unresolved board.
- Preserve legacy Showdown Leagues and all existing CDN/crew operations; no save-game or chat functionality.
- Native-derived identity construction is offline-tested; real event schedules and service responses are still unverified.


## 0.7.0.dev3 — automatic crew discovery (unreleased)

- Trace the native `crews/checkUserCrew` read and its `CheckUserCrewResponse`
  `crewUID` field. Introduce `OwnCrew`, `get_my_crew()`, and an optional
  `crew_uid` parameter on `get_crew_members()`.
- Automatically discover the authenticated account's own crew before requesting
  its roster, with a short memory-only cache and explicit refresh.
- Make `csr2cdn services crew` work without a supplied UID; offline preview
  shows the own-crew lookup. Interactive CLI sessions can prompt for PlayerID.
- Have the opt-in live runner validate own-crew discovery by default and report
  `not_in_crew` separately. Unresolved Showdown now yields a failing exit code.
- Preserve `EventGroupName`-only Showdown metadata candidates rather than
  silently dropping real groups. Do not treat unresolved schedule or board IDs
  as successful validation.
- Offline fixture tests cover read-only contracts, automatic lookup, no-crew
  cases, cache refresh, privacy, and real-metadata-shaped discovery.

## 0.7.0.dev2 — live-read validation harness (unreleased)

- Add an explicit opt-in, read-only smoke test (`python -m csr2cdn.live_validation`).
- Resolve the metadata product version separately from the APK app version
  before attempting current Showdown discovery.
- Prompt for caller-controlled PlayerID locally without command-line disclosure;
  require a terminal that supports hidden input.
- Report only sanitized availability, schema-validation outcomes and record
  counts; never save or display request internals or response records.
- Refuse ambiguous/unresolved Showdown IDs; accept explicit, resolved board
  identifiers and optional crew/Prestige/legacy read test targets.
- No public release is made and live protocol compatibility is unverified.

## 0.7.0.dev1 — offline Showdown discovery preflight (unreleased)

- Recognize current Showdown candidates from refreshable game metadata blocks
  using native `RaceEventGroups` and `ScheduleList` keys, without bundling
  event IDs or static calendar data.
- Add `ShowdownDiscovery`, `scan_showdowns`, and `prepare_current_showdown`,
  plus `services showdowns` and `showdown --current` offline CLI commands.
- Only build a request when a full leaderboard name is available; template IDs
  and event IDs are not substituted for unresolved server identifiers.
- Suppress session details from CLI failures and prepared-object representations.
- Keep discontinued Showdown Leagues APIs for backward compatibility; add no
  chat retrieval or save-management operations.
- Validate local metadata fixtures and failure scenarios without live requests.

## 0.7.0.dev0 — first implementation (unreleased, offline-first)

- Add public experimental `CSR2Services` reads for crew members and current cars,
  classic Showdown, Showdown Leagues progress/preview/score, and Prestige Cup.
- Implement session-backed read contracts, request timeout,
  bounded responses, no redirects, token expiry handling and explicit opt-in live I/O.
- Add typed `CrewMembers`, `CrewMember`, `CrewCar`, `LeaderboardPage`,
  `LeaderboardEntry` and `LeaderboardScore` decoders and clear protocol errors.
- Add refreshable external `EventCatalog` with event ID, leaderboard name,
  season, segment, instance and crew scopes; refuse missing or ambiguous mappings.
- Add offline `csr2cdn services` CLI, dynamic event lookup, fixture decode,
  leaderboard ranges and current player score/rank support.
- Keep all existing 0.6.0 APIs, and keep the private save-game project fully
  separate; no save read, upload, or profile-fetch routes are included.
- Keep classic Showdown and Prestige Cup generic leaderboard route, response
  shape and score semantics **provisional** until final live validation.
- The version is a development pre-release: do not tag or publish as final 0.7.0.

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

## 0.7.1.dev38 — Received unmatched cosmetic IDs, Work-ready read-only test

- Add `csr2cdn.dev38_received_unmatched_ids`: exact paint, interior and
  calliper numeric roster-ID membership test against the corresponding two
  standard/TNR cosmetic source libraries, emitting each *received* absent ID.
- Support an integrity-checked, previously exported Dev36 catalogue (zero CDN
  traffic), or bounded fresh retrieval of the selected branch's index and six
  libraries (up to eight public CDN GETs).
- Support explicit, read-only two-operation crew sampling through the existing
  authenticated service reader, plus a completely offline saved-fixture path.
  Portal auth and potential 401 retry can add HTTP requests.
- Group repeated IDs per attribute, report TNR-syntax versus other occurrences,
  and omit player IDs, names, model keys, wheels and raw responses.
- Require new local output path; preserve all production mappings and decoders.
- Cover the Work execution path using simulated service/CDN responses and the
  5,726-record real Dev36 public source catalogue with synthetic crew fixtures.

## 0.7.1.dev39 — Read-only CarColor palette overlap investigation

- Accept the sanitized Dev38 report and check only its real unmatched received
  paint IDs against a **separate** `CarColorLibrary` source. Explicitly preserve
  source-vs-roster namespace boundaries and do not promote palette overlaps.
- Opt-in current-branch public CDN probe: three bounded HTTPS GETs and exact
  native palette decoding, including blank-name record IDs. Offline local-file
  replay makes zero network requests.
- Report one row per missing received paint ID with occurrence counts, exact
  palette membership, source name when available, source SHA-256, and whether
  the palette came from the same advertised database version as Dev38.
- All tests use synthetic source bundles and fake network responses. No new
  gameplay requests, private player data, mappings, or releases.

## 0.7.1.dev52 — Car-local paint index native witness

- Added `csr2cdn.dev52_car_paint_list_native`: offline, fail-closed ARM64 audit
  of the validated CSR2 6.8.0 IL2CPP `CarVisuals` methods.
- Verified `CurrentPaintIndex` is stored separately from the integer paint-ID
  list (`CarPaintIDs`); `SetPaintIDAddIfNecessary` searches that list and can
  append a previously absent paint ID, selecting a local list position.
- The command fingerprints targeted method bodies and refuses unknown native
  builds. It does **not** obtain the affected vehicle's actual ordered paint
  list, convert received paint `15`, or prove the native meaning of paint `0`.
- Added synthetic fail-closed instruction-pattern regressions. No changes to
  production paint resolution, TNR decoder, other trusted labels or service
  clients. The APK and private endpoint cache remain outside distribution.

- Optional Dev38 received-ID aggregate reconciliation; warns that existing numeric
  source-ID overlaps are not, by themselves, verified car-local mappings.

## 0.7.1.dev60 — Native pre-unlockables paint guard and sensitivity audit

- Add `csr2cdn.dev60_setup_paint_guards`, an entirely offline, SHA-256 pinned `CarVisuals.Setup` ARM64 audit against the operator-supplied CSR2 6.8.0 APK.
- Verify source-conditional early insertion of a garage visual paint ID into the car-local list **before** `ForceUpdateOfCarPaint`. Both primary and fallback insertion sites are tested with exact opcode pins.
- Trace separate early `CarVisuals.CurrentPaintIndex` and later garage paint-index reads, plus an optional fallback correction to the garage index; no assumptions that these runtime branches execute for the affected crew car.
- Replay the current Mustang `.ASTC.14` base and serialized unlockable arrays, with zero or one optional prior insertion. The no-insertion replay selects ID 1323 (Ford Dark Highland Green) at index 15; some possible early insertions yield ID 129 (Ford Magnetic). Neither is a verified roster label.
- Add 16 targeted regression tests, including real pinned inputs when available; no game requests, player data, resolver or production mappings changed. The proprietary APK and asset bundle are never distributed.
