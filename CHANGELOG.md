## 0.7.0 � 2026-10-17

- Add read-only crew discovery, rosters, roles, player levels and seasonal Crew RP.
- Add matched GCC standings and guarded member-total comparisons; supported scope is top ten plus five crews above/below the authenticated crew.
- Resolve Showdown names from current metadata and native schedule inputs.
- Add native-backed Prestige global and crew-filtered views with exact six-decimal race times.
- Add opt-in diagnostics, coverage checks and synthetic season-rollover validation.
- Validate Windows, Ubuntu and macOS on Python 3.9�3.13, including wheel/source installation checks.
- Preserve existing CDN, HUB and dynamic snapshot APIs. Full GCC pagination and deeper optional data are deferred to 0.7.1.

The entries below are historical development notes; their blockers describe the respective build, not current release status. See VALIDATION_STATUS.md.

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
