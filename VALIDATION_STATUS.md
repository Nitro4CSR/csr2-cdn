# Validation status — 0.7.1

## Provenance of these results, and its limits

Everything below was observed by **one operator, against one crew, on one
account, on 2026-10-21/22**, using asset database 34049 (`6_8_0_Release`).
That is the whole evidential base. It has **not** been independently
reproduced, and the maintainer has not verified the cosmetic accuracy claims
separately.

What that does and does not support:

- A claim of the form "this wire value resolved to this label on this roster"
  is a direct observation and is reliable for that capture.
- A claim about a *rule* -- the paint composition order, the hood/wing variant
  reading, the fortnightly cadence -- is an inference from a single account's
  data, corroborated where possible against the asset list or the APK. A
  second account, a different car roster, or a later game version could refute
  any of it.
- Counts such as "190/190" or "29/29" describe that one roster. They are not
  coverage over the game's content.
- Where a reading was refuted during this work it is recorded as such rather
  than quietly replaced, so the log shows which conclusions survived contact
  with live data and which did not.

Anyone depending on these mappings should re-run the checks against their own
account before trusting them.

## Observations

- **190/190 (100%)** twelve-slot appearance values on a live 29-row crew roster resolve, with
  nothing unaccounted, against asset database 34049 (`6_8_0_Release`). Two further roster blocks
  the package used to discard, `car_tnr_setup` and `car_gacha_config`, now resolve as well.
  Validated against the service; the APK was used only to corroborate.
- **Only `paint` is an index** into a per-car list of
  `dedup(defaults + flattened unlockables + gacha paints)`. `Ford_Mustang302_1970`: index `0` →
  `1156`, index `15` → `1323`, both previously conditional or unresolved. `CarVisuals` declares
  `current_paint_index` and `current_*_id` for every other slot, which independently confirms it.
- `interior`, `calliper`, `livery_zones_set` and `livery` are global library IDs; the per-car
  list reports eligibility. An earlier reading of this release treated them as indices; the live
  roster refuted it and the slot model was corrected.
- `wheel` is the rim bundle's CDN asset code. A **Tuner Stars** wheel's name instead comes from
  `car_tnr_setup.RIMS` against `CarTunerStarsRimLibrary` (`1000007` → `3B`, `1000200` → `84A`).
- `decal_number_zone` selects one of the car's `RacingNumber1..3` mesh anchors, `0` hiding the
  number. A live row reports `3`, which rules out reading it as a visibility boolean.
- Zone masks and livery sets are separate lists against separate libraries
  (`LiveryZonesSetLibrary` vs `LiverySetLibrary`). Zone mask `0` is the real record `FULL BODY`,
  so **no slot treats `0` as an absence**; an earlier reading of this release did, and dressed
  unrelated cars in a Ferrari zone set.
- Tuner Stars values (>= 1,000,000) are global IDs in every slot. In `car_tnr_setup` the rim and
  boost-colour libraries start at 1,000,001, so `0` is reported as `none_or_stock` — 27 of 29
  live rows, every one a car with no Tuner Stars part fitted.
- All twenty-one cosmetic libraries decode, four of them only through the new type-tree fallback.
- Known limits: `car_tnr_setup.BODYKIT`, `HOOD`, `WING` and `WHEELS` have no library located yet
  and are reported as `no_library_known` rather than dropped. `TunerStarsLiveryZonesSetLibrary`
  yields no labelled records (1255 bytes; likely a stub) and `CarCameraAnimationLibrary` is
  unread. Only `decal_number_zone` values `0`, `1` and `3` have been observed, so whether every
  anchor is reachable from the UI is unproven. A paint index
  past a car's composed list is possible if a player holds cosmetics absent from the published
  bundle, so the list is a lower bound. Some library records are bound to one model because the
  decoder reads a per-ID exclusion list as a binding; labels work regardless, eligibility for
  those records does not.
- **Every wire field on both crew endpoints now reaches a typed attribute**, except three
  withheld on purpose. Confirmed 29/29 on the live roster: `token_donated`, `license_level`,
  `tier`, `rarity`, `is_super_rare`, `avatar_index`, `preferred_avatar_type` (member) and
  `crew_status`, `app_ver`, `debug_season` (crew).
- Live enum value sets, for which **no label table has been located** — these are raw wire
  values, not resolved names: `tier` {5}, `rarity` {0, 3, 4, 5}, `license_level` {2, 3},
  `avatar_index` {0}, `preferred_avatar_type` {1, 2}, `is_super_rare` {False, True}. The narrow
  spread is one crew on one day; do not read these as the full domains.
- `facebook_id` and `last_log_in_time` are supplied on every row and are deliberately not
  modelled. They remain in `CrewMember.extras`.
- Fixed: `OwnCrew.member_count` was `None` on every real response, having read only
  `memberCount`/`membersTotal` while the live reply spells it `members`.
- The dev82 field inventory over-reported by nine fields; its regex missed key names passed as
  a tuple into a generator. Coverage is now measured by literal search across every module.
- **The `tournament` tree is decoded**, the last uncovered subsystem on either crew endpoint.
  Live verdicts, all six events agreeing: `hash` is the match-up key (the participating crew IDs
  joined by `"_"`, equal to `crews[].id` 6/6, not a digest); `vanity_reward` is
  `"<tier>_<unix seconds>"` (7/7); the stamps are 14 days apart on Thursdays at 10:00 UTC; the
  event ID is a consecutive fortnight counter, so `cadence_days` derives as 14.
- `meta` describes the **current** event. `meta.prev_match` names the current match-up, not the
  previous one, despite its name; this is surfaced as `prev_match_is_current_event`.
- Not established: `meta.scores` was a single integer equal to the reward tier — one
  observation, two plausible readings, so `current_score` is documented as unverified. The
  extrapolated event-1 epoch (2016-03-24) is consistent with a since-launch counter but
  unproven, and nothing depends on it. `extra` was empty on every capture.
- `rivals[].name` is point-in-time, recorded as the crew's name stood at that event; `crew_id`
  is the stable key.
- Printing policy, set by the maintainer 2026-10-21: in-game player IDs, crew IDs and plate text
  are printed. `license_plate_text` is modelled (29/29 live, 16 distinct), tournament event
  rosters are retained in full, and rival crew IDs and names print normally. Large tuples stay
  out of repr for readability only, not for privacy.
- Withheld unconditionally: opaque auth/token fields and any unrecognised wire key (never held
  on the model, not merely hidden), plus `facebook_id` and `last_log_in_time`, which are a
  real-world social account and behavioural tracking rather than game data. Both remain in
  `CrewMember.extras`.
- `car_tnr_setup`'s four upper-case slots are mapped onto CDN asset codes by
  `csr2cdn.car_body_parts`. They have **no library because they have no name**: of 22,048
  `TEXT_` keys in `Localisation_FlatBuffer_EN`, none embeds a kit, hood or wing index. A part's
  only stable identifier is its asset code.
- Asset naming verified against the full live asset list: 25 cars ship kits+hoods+wings, all 25
  are TNR models, and all 25 satisfy the `1 + 2K` rule for K kit levels (K=3 on 15 cars, K=6 on
  10). Matching must be case-insensitive; these assets are published lower-cased.
- `HOOD` and `WING` select the primary or secondary option **of the fitted kit**
  (`0` -> `Hood{BODYKIT}a`, `1` -> `Hood{BODYKIT}b`), not a position in the option list. The game
  bounds them to `{0, 1}` and forces both to `0` while `BODYKIT` is `0`, which rules out the
  positional reading, whose range would be `0..2K`. Corroborated by the asset list without
  reference to the wire: no car ships a `0b` (0/25) while every car ships `0a` (25/25), and the
  `1 + 2K` count follows as K levels x 2 variants + 1 stock (25/25). Every (level, variant) pair
  on all 25 kit cars resolves to an existing asset, zero failures.
- **`WHEELS` is a retired slot**, split into `RIMS` and `TIRE`, which both resolve against their
  own libraries. The key is vestigial: the service still sends it and the game still has a
  `TEXT_WHEELS_BUTTON` tab, but nothing drives it. All the evidence agrees -- no `Wheel`-suffixed
  `_loda` asset exists for any car and all 29 live rows report `0`. Reported as `retired_slot`.
  With this, **every key in `car_tnr_setup` is accounted for.**
- The lower-case `body`/`engine`/`interior` `_loda` series is Classic restoration, a separate
  system from Tuner Stars kits.
- `TunerStarsLiveryZonesSetLibrary` is **TNR-specific and expected-thin**, not a decode failure.
  It is the fifth Tuner Stars library, after the four that needed the type-tree fallback, and at
  1255 bytes it yields no labelled records because there are none: TNR cars take their zone masks
  from the shared `LiveryZonesSetLibrary`, which resolves 19/19 live. Logged and skipped by
  design; do not treat it as broken.
- `CarCameraAnimationLibrary` is **out of scope**. It covers camera angles, not cosmetics, and
  nothing in this package reads it. Recorded here so a later cycle does not chase it.
- **Every supported endpoint audited live, not only the crew reads.** 7 of 8 reachable endpoints
  read; across all of them the only unmodelled field name is `facebook_id`, withheld by intent.
  Counts: `checkUserCrew` 33 keys, `viewMembers` 60, `gcc_progress` 15, `gcc_progress_range` 15,
  `leagues` 19, `leagues_score` 12, `leagues_preview` 14 -- 0 unmodelled in each.
- Fixed: `LeaderboardEntry.crew_id` was never populated on a leagues board, because the decoder
  did not know the `crewId` spelling. Added `last_updated`, `multiplier` and `sp_boost_data` to
  the entry, and `last_updated`/`sig_timestamp` to the score.
- `MONADIC_NOTHING` (`"Monadic::Nothing"`) is a backend absent-value sentinel sent in place of
  omitting a key; every live `multiplier` is it. Normalised to None so it is never read as a
  value.
- The leagues score `sig` (64 hex) is reported via `signature_present` and deliberately not
  retained, as an opaque server integrity value; it remains in `extras`.
- No data to exhaust, as distinct from a gap: no Prestige Cup is active, and the current-showdown
  selector is ambiguous while 25 Showdowns overlap with one requestable. The showdown board's
  rows were read by name and share the leaderboard decoder.
- `run_live` takes `at` so a report is reproducible; two tests that pinned fixture schedules were
  reading the real clock and expired on 2026-10-22.
- The seven symlink-rejection tests skip where the OS withholds symlink creation (Windows without
  Developer Mode) instead of failing. Windows reports 0 failures. Tradeoff: that rejection path
  is unexercised there, and still covered on POSIX.
- No gameplay writes, no save-API calls, and no player identifiers in committed output. The APK,
  Unity bundles and runtime captures remain outside both distributables.
