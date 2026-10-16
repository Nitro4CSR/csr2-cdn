## Prestige leaderboard views (Dev34, unreleased)

Dev34 adds an opt-in **global** Prestige range matching the operator-observed
`top 20 + 10 before/after` layout and a **separate, APK-traced event crew**
leaderboard route `leaderboard/{board}/scores/crewmembers`. The crew-filtered
read requests results from the server rather than locally filtering the
bounded global leaderboard. The crew route uses the native range mode
`top=10, before=30, after=30`; the global top20/±10 request uses a native-
admissible explicit range but has not been shown to match the exact game UI
call site. Both new response shapes are pending live confirmation.

```bash
python -m csr2cdn.prestige_release_validation --ui-window --crew-filtered --print-entries
```

That command is a zero-network dry run. The next authorized online check is
described in [Dev34 Prestige investigation](docs/0.7.0-dev34-prestige-views.md).
The current package release remains blocked by new view verification and CI.

## Prestige Cup timing (Dev33, unreleased)

The Prestige leaderboard's integer `FastestHalfMileTime` score is a time in
**microseconds**. To display it as in the game, use
`format_prestige_time(score)`: `7102993` becomes `"7.102993"` seconds.
This operation is exact and always produces six fractional digits. The raw
integer is preserved for sorting and tie comparisons; **do not apply this
conversion to GCC Crew RP scores**.

```python
from csr2cdn.prestige_time import format_prestige_time
assert format_prestige_time(7102993) == "7.102993"
```

To compare a later authorized read against an operator-supplied UI time, pass
`--ui-time 7.102993` to `python -m csr2cdn.prestige_release_validation`
with the existing `--execute` and confirmed board/season inputs. The game UI
shows top 20 globally, ±10 positions around the player, and separate crew
standings, but those three exact network read contracts are **not** verified;
the package retains its previously verified bounded leaderboard read. See
[Dev33 Prestige notes](docs/0.7.0-dev33-prestige-timing.md).

## Dev31 — season rollover handling without waiting for the server (unreleased)

Dev31 adds an **offline-only rollover rehearsal** and typed `GCCSeasonTiming` /
`CrewSeasonTransition` comparison for the existing Crew RP snapshots. It expects
member `cc_contrib` and matched GCC `score` to reset to zero at each new
14-day championship, **but never resets server values locally or fabricates a
season ID**. It rejects a roster/GCC read pair crossing an inferred season
boundary, allows a one-hour UTC difference across DST for 14 local calendar
days, and compares the own-crew `crew_rp` / garage figures separately and only
prints those statistics with opt-in. The native `end_time` / `time_left` timing
correlation is strong but remains a candidate schedule, not a verified reset.

Zero-network test (synthetic examples only):

```console
python -m csr2cdn.crew_season_validation --simulate
```

See [Dev32 release gates](docs/0.7.0-dev32-release-gates.md) and [Dev31 season lifecycle notes](docs/0.7.0-dev31-season-lifecycle.md).

# csr2-cdn

## Dev30 — deeper audit of the same crew responses (unreleased)

Dev30 updates Dev29's read-only inventory to recognize the *observed* snake_case crew statistics, report one-level `tournament`/`crew_logo`/member car-configuration field names/types, and inspect the GCC `end_time`/`time_left`/`cardinality`/`bucket`/`tier` envelope. `--show-stat-candidates` optionally prints three **separate** RP quantities and cautiously gated differences; `--show-gcc-metadata` separately opts into bounded timing / grouping values and an explicitly hypothetical Unix-time interpretation. Their season meaning is unverified. The same three authenticated read routes are unchanged, and the CLI makes zero network calls without `--execute`. See [Dev30 notes](docs/0.7.0-dev30-existing-endpoints.md).

## Dev29 — inventory of existing crew endpoint fields (unreleased)

Before any further live read, Dev29 adds a redacted inventory of the three **already established** own-crew, roster and GCC progress responses. `python -m csr2cdn.crew_endpoint_inventory` is a zero-network dry run; the later `--execute` mode prompts for PlayerID and makes only those three read-only requests. It reports field names, value types, coverage and nested GCC logo structure without printing IDs, secrets, names or values. `--show-stat-candidates` separately opts into selected numeric own-crew counters and aggregate member statistics; their meanings/units remain unverified. See [Dev29 documentation](docs/0.7.0-dev29-endpoint-inventory.md).

## Crew RP (Dev28; tested member/source mapping)

Crew member `cc_contrib` now maps to `CrewMember.season_crew_rp` (independently compared against game UI during the Manthey 911 Prestige Cup season). The GCC current-progress `score` returned the **exact sum** of 29 contribution values in the 2026-10-16 Dev27 authorized read, and `rank` was server-returned. These are **read-only**, non-atomic values; the server has not yet provided an independently validated season ID or rollover proof.

Use `CSR2Services.get_crew_rp_snapshot()` only with explicit `allow_network=True`. It returns a typed `CrewRPSnapshot` with an exact crew-ID join, adaptive member count (from `memberCount` when available), freshness/coverage checks and an identifier-free `public_summary()`; `comparable` and `delta` are suppressed on incomplete, stale or poorly timed reads. A changed operator season marker or declining score flags a *possible* reset or correction, not verified season rollover. See [Dev28 documentation](docs/0.7.0-dev28-crew-rp.md) for code and CLI examples. Overall 0.7.0 release remains blocked by separate checks.

## Dev24 experimental GCC crew leaderboard read (unreleased)

After screenshot comparison validated native member `cc_contrib` in the tested crew, `CrewMember.season_crew_rp` exposes that field without conflating it with lifetime RP or fallback `score`. The game APK also contains the default GCC prefix and a native category-3 `viewcrew` progress request, reconstructed **experimentally** as `leaderboard/crew-champs-v2/viewcrew` (`top=10, after=5, before=5, offset=0`). Its runtime prefix, season identity, endpoint success, and crew rank/total semantics **have not yet been live confirmed**.

To explicitly try one read-only GCC **progress** request (plus own-crew identification), in an interactive terminal:

```console
python -m csr2cdn.crew_rp_verification --execute --print-member-values --gcc-live --gcc-only --reference-total 37448821 --reference-rank 257 --season-note "Manthey 911 Prestige Cup"
```

This prints any returned crew names, ranks and `cc_rp` candidates. It does not print private player IDs, auth material, or raw responses; an unfamiliar response triggers a bounded schema census. Without `--gcc-live` this additional network call is disabled; without `--execute` there are **zero** network calls. **Release blocked.** See [dev24 notes](docs/0.7.0-dev24-gcc-live-probe.md).

### Dev23 — printable read-only Crew RP comparison (unreleased)

The live dev22 `crews/viewMembers` probe found numeric `cc_contrib` candidates
for 29/29 identified crew members. To compare actual values against the
**current Manthey 911 Prestige Cup season** screenshots, the opt-in dev23
investigator prints *every member nickname, player level, `cc_contrib`,
`player_rp`, and all-time RP when available*. It also prints the sum of
member contribution candidates and its delta versus the crew leaderboard RP
reported by the operator. The reference (37,448,821 RP; crew rank 257) is a
**time-sensitive screenshot reference**, not an authenticated season marker.

From an interactive terminal, after installing the source project:

```console
python -m csr2cdn.crew_rp_verification --execute --print-member-values --expected-members 29 --reference-total 37448821 --reference-rank 257 --season-note "Manthey 911 Prestige Cup"
```

Add `--format json` for human-inspectable structured output. The account's
PlayerID is entered in a hidden prompt and is never printed. **Member
nicknames and RP values intentionally print to the terminal**: do not share
raw output publicly without redaction. Do not pass secrets on the command
line. The command does not write files. Without `--execute`, it makes **zero
network requests**. With it, the only live reads are the existing
`crews/checkUserCrew` and `crews/viewMembers` allowlisted paths. The script
prints any exact `cc_rp`, `score`, `rp`, or `crew_rank` scalar that happens to
be present in the own-crew membership response; no value is fabricated.

A separate **offline** inspection of an already obtained GCC JSON response
prints its entire decoded crew list, `crew_rank`, `cc_rp`, all-time `rp`, and
any own-crew comparison when combined with the live member read:

```console
python -m csr2cdn.crew_rp_verification --gcc-response-json local-gcc-response.json --format table
```

This **does not download GCC results**. The GCC `viewcrew` signed URL,
season selector, and pagination remain unverified in the APK trace and are
**not guessed**. No release gate is unblocked by a coincidental total or
rank match; a 14-day active-season check and member UI equivalence are
still required. See [the dev23 test note](docs/0.7.0-dev23-crew-rp-value-comparison.md).


### Experimental 14-day Crew RP wire test — 0.7.0.dev22 (unreleased)

The CSR2 6.8.0 native `PlayerCrewMember.FromJSONDict` decoder populates the
**current-season-shaped member field** `RP_season` from `score` and subsequently
from `cc_contrib`. The **native source mapping is established**, but live
`crews/viewMembers` key presence, active-season scope, and displayed-RP
accuracy are **not yet verified**.

A separate, explicitly **unverified** `CrewMember.season_crew_rp_candidate`
field (and `.season_crew_rp_source`) exposes the parser-supported
`cc_contrib` / fallback `score` values. It never uses lifetime `RP` / `rp`
or profile `player_rp`; existing `crew_rp` compatibility behavior is unchanged.
A present-but-invalid `cc_contrib` is not silently replaced by `score`.
Zero is a valid contribution candidate.

For a privacy-safe **live first pass**, run in an interactive terminal after
installing this source project (`python -m pip install -e .`):

```console
python -m csr2cdn.live_validation --execute --crew-only --crew-season-probe --crew-rp-schema
```

The command prompts privately for **your own** PlayerID, performs only the
existing authorized `crews/checkUserCrew` and `crews/viewMembers` reads,
and outputs only numeric *counts* and authored status flags: native key
presence / parseability, `cc_contrib` precedence, fallback `score` coverage,
member identity coverage and zero-contributor count. It never prints names,
IDs, RP values, response documents or credentials. Omit `--execute` for a
no-network dry run. You can also specify your own crew with
`--crew-uid OWN_CREW_UID`.

**Interpretation:** `complete_identity_and_candidate_coverage: true` means
only that each returned roster record has a distinct recognized identifier
and a numeric native contribution candidate. It does **not** validate the
active 14-day season or UI equivalence. Compare values against the in-game
crew-member RP privately, including the local player's profile overwrite,
and check the actual active-season ID/bounds and season rollover before
unblocking Crew RP.

`GCCCrewStanding` and `GCCCrewStandings` also decode supplied **offline** GCC
results using `cc_rp` for the candidate **crew season total**, `rp` for
all-time crew RP, and `crew_rank` for rank. Example for an authorized local
fixture: `CSR2Services.decode_gcc_crew_standings(response_json)`.
The complete signed GCC `viewcrew` route and season selection are still
unverified, so no new live GCC request or speculative leaderboard alias has
been added. Prestige behavior is unchanged. **Crew RP remains blocked.**

See [dev22 candidate-read implementation](docs/0.7.0-dev22-crew-season-rp-probe.md).

### Player-profile RP and crew-season RP — 0.7.0.dev21

Native tracing establishes `UserManager.FillNonSecureBlobDict` writes the
`player_rp` key using `PlayerProfile.get_RP`. Dev20 live data contained this
field for all 29 members. Dev21 exposes it separately as `member.player_rp`
and reports only `player_profile_rp_populated` in the crew-only validation.
This profile statistic is **not** a verified current-season Crew RP contribution;
`member.crew_rp` remains `None` when its season-specific source is missing.

The crew hangout instead displays `PlayerCrewMember.RP_season`, while its
`FromJSONDict` method maps uppercase `RP` into `RP_allTime`. The client also
updates the **local player's** GCC contribution from local profile state in
`PlayerCrew.set_Members`; this is not evidence for a 29-member season-RP list.
The next step is tracing a read-only seasonal contribution source rather than
relabelling the profile stat.

Dev21 also restores all *synthetic* Showdown `.meta` files into the full-project
ZIP; they are necessary for the packaged native-preview regression, and contain
no production game data.

### Native crew RP / role preview (0.7.0.dev20)

The dev17 live roster read succeeded (29/29 nicknames and levels) but
returned 0/29 typed RP values. Dev18 corrects the native dictionary's
**uppercase `RP`** wire key, preserves the source of that value, and adds
canonical crew role recognition. The native client distinguishes all-time
RP from the seasonal RP shown in the crew hangout; a populated `RP`
**must be privately compared with the game** before calling it seasonal.
See [dev18 RP/role findings](docs/0.7.0-dev19-crew-rp-role.md).

```powershell
python -m csr2cdn.live_validation --execute --crew-only
```

The command reports only coverage counts, not member records, identifiers,
RP numbers, or roles. To inspect member values locally, use
`csr2cdn services --execute crew`; do not publish detailed roster output.

The dev16 **integrated Prestige Cup live test succeeded**, returning 21
standings entries for explicit Season 277 and the extracted Porsche car.
Accurate game rank/score, pagination, cached season, identity mode and CI still
need confirmation. Dev16 can now decode the special-ladder **binary** Prestige Cup template and
reconstruct a standard timed leaderboard from real metadata, rather than
requiring a manually typed board name. To test **the active Season 277 cup**
read-only with the extracted car record, install the `events` extra and run:

```powershell
python -m csr2cdn.live_validation --execute --skip-crew --prestige-current --prestige-season 277 --prestige-car-json .\Porsche_Manthey911GT3RSRewardRecycled_2024.json
```

The current crew-season ID and car tier remain explicit inputs for this first
live test. Their identity must be checked against active in-game data. The
binary template and ranking metadata are validated before a request can be
sent. The supplied Season 277 inputs yielded a successful authorized live standings
read, but future-season auto-resolution is not complete; see
[dev16 native Prestige findings](docs/0.7.0-dev16-native-prestige.md).

### Earlier Prestige Cup investigation (0.7.0.dev14)

Dev13 retains the dev12 source-loading and native telemetry fixes. It additionally
retains race groups with native `Silver_Prestige` telemetry and serialized `id`
even when `EventGroupName` is missing. Previous decoders discarded those records.
Whether that explains the current live Prestige discovery failure remains unverified. To run
read-only live validation with your own PlayerID, install the `events` extra and
run `python -m csr2cdn.live_validation --execute --skip-crew --prestige-current`.
The runner reports source coverage and counts without printing player details,
authentication material, event identifiers, scores or raw responses. An unresolved
Prestige Cup is **not** a successful service test. The exact active production
leaderboard has not yet been verified.


Prestige Cup discovery now retrieves both `CupInvitationalRaceSeries` and
modular common-event metadata. Run the read-only live preflight on your machine:

```console
python -m pip install ".[events]"
python -m csr2cdn.live_validation --execute --skip-crew --prestige-current
```

A PlayerID-only Python interface is also available:

```python
from csr2cdn import CSR2Services
with CSR2Services("YOUR_PLAYER_ID", allow_network=True) as api:
    page = api.get_prestige_cup_leaderboard()
```

This requires a current Prestige event with an attached, fully derived
leaderboard. **The real live Prestige result is not yet verified.** It is not
correct to interpret an unresolved metadata source as an inactive event.
See [Prestige Cup research and validation](docs/0.7.0-dev10-prestige.md).

## Experimental 0.7.0 game-services API (unreleased developer preview)

A separate, offline-first **read-only** `CSR2Services` API now covers crew
membership/current cars, Showdown standings, legacy Showdown Leagues standings and
preview/score lookups, and a provisional Prestige Cup standings interface.
It has typed crew/leaderboard models, explicit leaderboard ranges, a refreshable
caller-provided event mapping, a game-metadata Showdown schedule preflight,
and an opt-in CLI. **An authorized CSR2 6.8.0 live test succeeded for
own-crew membership and `SMP_SHOWDOWN_277_W2` standings (21 entries).**
Crew roster decoding, full score/pagination semantics, and Prestige Cup remain
unverified. No final `0.7.0` release has been made. The save-game downloader remains separate and private.

```python
from csr2cdn import CSR2Services, EventCatalog, StandingRange

catalog = EventCatalog.from_json_file("current-event-mapping.json")
with CSR2Services("MY_PLAYER_ID", events=catalog) as api:
    own_crew = api.prepare_my_crew()  # offline preview, no crewUID needed
    showdown = api.prepare_showdown(event_id="EVENT_ID")
    prestige = api.prepare_prestige_cup(event_id="CUP_ID")
    leagues = api.prepare_showdown_leagues(
        leaderboard_name="RESOLVED_BOARD", ranges=StandingRange.common()
    )
    # These only build contracts, with no server contact.
```

### Opt-in live read smoke test (0.7.0.dev9)

Run these commands **on your own machine**, in an interactive terminal, with a
PlayerID you control. The test asks for that ID without echoing it or adding it
to command-line arguments. It neither stores credentials nor prints raw service
responses, request payloads, player identifiers or auth diagnostics. No save
download/upload and no chat functionality are included.

```console
python -m csr2cdn.live_validation             # no network, no prompt
python -m csr2cdn.live_validation --execute --showdown-name "Championship Showdown"
python -m csr2cdn.live_validation --execute --showdown-name "Elite Showdown"
```

The runner obtains the metadata *product version* from the existing CDN
resolver (it may differ from APK version `6.8.0`). If known, supply it to skip
that discovery step: `--metadata-product-version 6.8.xx`. It reports only
counts of scheduled events and fully resolved server leaderboard names. It
**does not** mistake a template or schedule event ID for a server leaderboard
name. When multiple Showdowns are active, no automatic board is chosen.

"Championship Showdown" selects only a uniquely active metadata record of the
form `SMP_SHOWDOWN_<season>_W2`; "Elite Showdown" uses `_W1`. Seasons are
selected from discovered active metadata, never inferred from today's calendar.
The season cycle can span two weeks while each W1/W2 event has its own actual
server-provided schedule. When the matching slot is inactive, the runner reports
`inactive_event`; it never guesses another season or picks an unrelated
Showdown event. Exact metadata identifiers remain supported for advanced use, but user-facing Championship/Elite aliases never fall back to an unrelated event.

If more than one current Showdown has a fully resolved board, select the
first by `--showdown-index 0` or the next by `--showdown-index 1`. The
zero-based index sorts candidate event IDs and selects **one** request.
If the metadata lacks resolved IDs, the runner refuses to guess.

Own-crew discovery now runs automatically: the game-service read determines
`crewUID` from the authenticated account before fetching the crew roster. No
manual UID is needed. The first live roster read used a response shape not
recognized by dev8. Dev9 supports additional typed member layouts and includes
key-free structural diagnostics for any still-unrecognized response. An
unknown response is never counted as a successful empty roster. To omit this optional check, use `--skip-crew`.

For direct library use:

```python
with CSR2Services("MY_PLAYER_ID", allow_network=True) as api:
    own_crew = api.get_my_crew()
    if own_crew.in_crew:
        members = api.get_crew_members()  # automatically uses own_crew.crew_uid
```

To test a known resolved leaderboard or explicitly selected crew, use flags:

```console
python -m csr2cdn.live_validation --execute --showdown-board RESOLVED_BOARD
python -m csr2cdn.live_validation --execute --crew-uid OWN_CREW_UID
python -m csr2cdn.live_validation --execute --prestige-board RESOLVED_BOARD
python -m csr2cdn.live_validation --execute --leagues-board RESOLVED_LEGACY_BOARD
```

Each selected feature performs at most one logical read (the package may retry
an HTTP 401 once). Only sanitized results such as `ok`, `unresolved_board`,
`http_rejected`, `response_not_recognized`, and entry counts are displayed.
The read builders remain provisional until the live outcomes have been reviewed.
Do not provide your PlayerID, credentials, or raw game responses in issue
reports. See [live validation instructions](docs/0.7.0-live-validation.md).

### Runtime Showdown discovery (0.7.0.dev9)

In CSR2 6.8.0, the client loads event metadata from asset bundles and can
merge additional Showdown groups into the standalone `ShowdownEventsContainer`.
The metadata-service block alone can list a historical event while omitting a
current runtime event. **Zero active groups from that block is not evidence
that the named Showdown is inactive.** `live_validation` now reports
`source_coverage=runtime_asset_bundles` after successful automatic merging
(or a sanitized runtime-source error if extraction fails). An explicitly
supplied offline-only metadata source still reports `standalone_only`.

For **offline verification of decoded runtime groups**, provide a JSON list
whose elements are actual `RaceEventGroup` mappings obtained from an
independently authorized source. This option does not retrieve those groups
and never substitutes synthetic event IDs for production data:

```console
csr2cdn services --metadata-dir ./my-metadata --modular-groups-file ./runtime-groups.json showdowns
csr2cdn services --metadata-dir ./my-metadata --modular-groups-file ./runtime-groups.json showdown --name "Championship Showdown"
```

Programmatically, use `ShowdownDiscovery.from_json_directory(...,
modular_groups_file=...)` or `ShowdownDiscovery(source, modular_source=...)`.
The native merge preserves standalone groups when a runtime group has the
same `EventGroupName`; incomplete or malformed injected records fail closed.
The client selects asset type `47` when enumerating common-event metadata
bundles. An existing CDN asset database can be inspected offline using:

```python
from csr2cdn import AssetDatabase, modular_event_assets
database = AssetDatabase.load("asset_database.json")
bundles = modular_event_assets(database)
print("event-metadata bundle candidates:", len(bundles))
```

**Dev7 introduced an automatic read-only loader for these bundles.** Install the
optional event decoder once using `pip install 'csr2-cdn[events]'`, then use
the existing Python call `api.get_showdown_leaderboard(showdown_name=...)` or
the live validation runner. The package obtains the current asset database,
selects category-47 entries, streams ASTC-quality Unity bundles with size
limits, and uses UnityPy to extract explicit Showdown groups, schedule records
and ranking definitions. It merges them with standalone metadata without a
built-in event catalogue or client-specific identifiers. Dev8 corrected keyed ranking definitions and session compatibility. A later
authorized production test validated a Showdown standings response and own-crew
lookup. Dev9 adds strict current W1/W2 name aliases, while crew roster and
some rank/score semantics still await verification.

`--execute` is still mandatory for live-validation requests. No bundle content,
player identifiers, or authentication material is logged or included in the
package. Bundles without readable Unity type trees or recognizable JSON
cannot be decoded yet: the loader reports `runtime_catalogue_unavailable`
instead of claiming no event is running. UnityPy has not been exercised against
a genuine CSR2 event bundle here, so compatibility is pending live validation.

The current authorization code is kept internal. The live harness never
outputs session details; a valid service session has now been observed in an
authorized validation. See [live validation](docs/0.7.0-live-validation.md).

### Offline Showdown discovery (0.7.0.dev1)

Given **local** snapshots of `ShowdownEventsContainer.meta`,
`EventSchedule.meta`, and optionally `EventLeaderboards.meta`, the package
can inspect scheduled Showdown candidates and prepare a read contract if a
fully resolved leaderboard name is present in those snapshots:

```python
from datetime import datetime, timezone
from csr2cdn import CSR2Services, ShowdownDiscovery

discovery = ShowdownDiscovery.from_json_directory("./my-metadata")
with CSR2Services("MY_PLAYER_ID") as api:
    for event in discovery.scheduled_now():
        print(event.event_id, event.time_status, event.requestable)
    request = api.prepare_current_showdown(discovery)  # network-free
    print(request.route)
```

```console
csr2cdn services --metadata-dir ./my-metadata showdowns --scheduled-now
csr2cdn services --metadata-dir ./my-metadata showdown --current
```

Time windows alone do **not** prove in-game eligibility, server availability,
or whether the event is segmented. `prepare_current_showdown` refuses missing
or ambiguous board names and does not infer them from event IDs or leaderboard
templates. The local tests use synthetic metadata; actual current metadata
and live leaderboard responses remain to be verified at the final test phase.
There is no chat retrieval. Showdown Leagues remains a legacy compatibility
feature, even though the game no longer currently offers it.

Try the CLI offline: `csr2cdn services crew` (previews the own-crew
lookup; no UID needed), or
`csr2cdn services showdown --leaderboard-name RESOLVED_BOARD`.
See [automatic crew discovery](docs/0.7.0-crew-discovery.md),
[validation follow-up](docs/0.7.0-validation-followup.md),
[offline Showdown preflight](docs/0.7.0-offline-showdown-preflight.md) and
[0.7.0-first-implementation](docs/0.7.0-first-implementation.md) for
all Python/CLI methods, fixture decoding, dynamic mapping and release gates.


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


### Showdown leaderboard identifier inputs (experimental 0.7.0.dev5)

The resolver now tracks and validates the four input values independently:
occurrence start, duration, ranking direction and first ordered race ID.
Supported direct group repeats are resolved to the applicable occurrence;
unsupported schedule-level recurrence and ambiguous definitions fail closed.
Use `ShowdownDiscovery.list_showdowns()` and `candidate.identity_inputs.missing`
to diagnose metadata gaps **offline**, without leaking session details.
See [four-input resolution evidence](docs/0.7.0-four-input-resolution.md).
Live 6.8.0 compatibility of real Showdown metadata still needs validation.

### Showdown leaderboards by name (experimental 0.7.0.dev4)

Only your own PlayerID and the Showdown's name are needed for the proposed
public interface:

```python
from csr2cdn import CSR2Services
with CSR2Services("YOUR_PLAYER_ID", allow_network=True) as api:
    page = api.get_showdown_leaderboard(showdown_name="Championship Showdown")
```

```sh
csr2cdn services --execute showdown --name "Championship Showdown"
```

For offline previews, supply a local metadata directory instead of `--execute`.
Native board-ID derivation and supported schedule shapes are documented in
[Named Showdown resolution](docs/0.7.0-named-showdown.md). Full live-server
compatibility remains unverified, especially recurring schedule formats.
No saved-game operations or chat retrieval are included.



### Prestige Cup special-ladder source diagnostics (development)

The 6.8.0 native `RaceEventDatabase.ProcessSpecialLadderRaceEventData`
registers race groups from `SpecialLadderEvents.LadderEvents`. Development
version 0.7.0.dev14 now checks that source separately from the invitational
series and career/Showdown catalogues. The live preflight reports only
`special_ladder_groups`, `special_ladder_groups_with_leaderboard` and
`special_ladder_native_prestige_groups`, as well as successful/unavailable
source counts. A nonzero ladder count does not imply an active Prestige Cup;
only an authoritative event group, schedule and leaderboard may be queried.

To inspect with an authorized player account locally:

```console
python -m csr2cdn.live_validation --execute --skip-crew --prestige-current
```

Live compatibility of this additional source remains **unverified**.

Development note: dev16 additionally integrates the type-46 binary Prestige event template and guarded runtime board reconstruction. **Prestige leaderboard discovery has not been live-verified**. See `docs/0.7.0-dev16-native-prestige.md`.


### Crew RP wire-shape investigation (dev19)

If the crew-only report has `crew_rp_populated: 0`, the extra
`wire_rp_diagnostics` object reports *counts only* from the actual decoded
`crews/viewMembers` member records. The keys distinguish dictionary records
from 10/11-field compact records, exact `RP`/`rp` and seasonal RP keys,
other RP-labeled or nested properties, values that are null/unparseable, and
role wire type. It **does not** return field values, arbitrary server key names,
player IDs, names, positions, or scores. Run:

```powershell
python -m csr2cdn.live_validation --execute --crew-only
```

A populated lifetime `RP` value does not automatically equal seasonal Crew RP.
Do not infer RP from adjacent numeric fields, crew-wide totals or unrelated
leaderboards. If no RP-labeled fields appear in the live member records, a
separate game-native read-only source will need to be identified and verified.

### Dev20 Crew RP wire-schema investigation (optional)

The dev19 live read showed 87 RP-looking names in 29 roster records, but no known
seasonal RP values. The diagnostic's broad substring rule can catch car fields,
so it is not evidence of Crew RP. An *opt-in* key-only schema census is available:

```powershell
python -m csr2cdn.live_validation --execute --crew-only --crew-rp-schema
```

This reports aggregate, repeated ASCII field names and family counts only.
It does **not** emit any field values, nicknames, player IDs, or raw records.
Sensitive-looking and rare/dynamic field names are suppressed. Unknown keys
are never automatically mapped to seasonal RP; use the observed names to
trace their native semantics. Do not use the result to assert RP coverage.

### Dev25 experimental GCC `scores` response tracing

The current-progress `viewcrew` read returned `scores` with 21 objects, not yet decoded GCC crew standing records. Use the [Dev25 GCC score-shape diagnostic](docs/0.7.0-dev25-gcc-scores-shape.md) to print known field/type counts or explicitly opt into score/position candidate values, **without claiming seasonal Crew RP or crew leaderboard rankings**.


### 0.7.0.dev26 current GCC progress check (unreleased)

The observed `leaderboard/crew-champs-v2/viewcrew` progress response contains `scores` with `crew_id`, `name`, `rank`, `score`, and `logo`. Dev26 can parse them and **match your own crew by ID**, printing score/rank as backend candidates; these are **not yet verified seasonal Crew RP** without active season and contemporaneous in-game checks. Use only with authorized read-only access:

```console
python -m csr2cdn.crew_rp_verification --execute --print-member-values --gcc-live --gcc-only --gcc-print-score-candidates --reference-total 37448821 --reference-rank 257 --season-note "Manthey 911 Prestige Cup"
```

This prints all returned crew names, ranks and scores on opt-in but not IDs or authentication data. [Research notes](docs/0.7.0-dev26-gcc-progress-decoding.md).

### 0.7.0.dev27 sequential own-crew member-versus-leaderboard comparison (unreleased)

The dev26 authorized live read matched one exact own-crew ID with GCC `score=38,226,478`, rank `253` on October 16, 2026. Both fields are server-returned, but `score` has **not** been proven to be current-season Crew RP. Dev27 fixes a mixed-clock Showdown test and adds an opt-in, sequential comparison between the complete roster's `cc_contrib` sum and the GCC own-crew score, without changing the known read-only routes:

```console
python -m csr2cdn.crew_rp_verification --execute --print-member-values --gcc-live --gcc-print-score-candidates --expected-members 29 --season-note "Manthey 911 Prestige Cup"
```

Do **not** use `--gcc-only` for this comparison, since it skips the roster. The output intentionally prints member names and RP counters and the requested leaderboard rows; review it before sharing. Identifiers and credentials are not printed. This compares two sequential reads, **not** one atomic snapshot, and does not establish an active-season identifier or reset schedule. See [Dev27 validation notes](docs/0.7.0-dev27-gcc-sequential-comparison.md).
