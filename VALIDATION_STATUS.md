# 0.7.0.dev34 Prestige view expansion (unreleased)

The current source adds two **offline-tested** read-only requests: an explicitly opt-in global Prestige window `top=20, after=10, before=10` using the signed `/view` path, and an APK-traced native event crew-filtered `/scores/crewmembers` route with its own default `top=10, after=30, before=30` request range. Neither new request's live response has been observed. Decoded crew-tab ranks may be global or crew-local; do not treat these as validated until a future authorized UI comparison. The original Dev32 `/view` top10/±5 and Dev33 microsecond formatter remain intact.

New CLI switches: `--ui-window`, `--crew-filtered`, optionally `--print-entries`. The CLI defaults to a dry run with zero network requests. No online test, GitHub publication or package release has been performed. The broader GitHub OS/Python CI matrix remains pending. See [Dev34 Prestige view notes](docs/0.7.0-dev34-prestige-views.md).

# 0.7.0.dev33 Prestige display update (unreleased)

The operator confirmed Prestige's `FastestHalfMileTime` score `7102993` renders
as `7.102993` seconds, with six decimal places. The own-player rank 1139 also
matched the in-game UI. The UI provides top 20 globally, ±10 around the player,
and a separate crew-member standings tab; these observations do **not** establish
read contracts for those additional views. The existing common-window API
remains top 10 entries plus ±5, with ties potentially truncating equal-rank
participants at the window edge. In the private dev32 21-row response, six
rank-5 entries were present, whereas the operator reports nine tied at fifth.

Dev33 performs exact microsecond-to-seconds formatting in Prestige-only output;
GCC `score` remains seasonal Crew RP. The new `--ui-time` comparison is optional,
and no credentials or leaderboard endpoint changes were made. Offline validation
and CI status must be checked independently. Final 0.7.0 is not published.

# CSR2-CDN 0.7.0.dev32 validation status (unreleased)

Dev32 adds a **read-only Prestige Cup rank/score and native-range validation probe**, with controlled name output, exact player-ID matching when available, recent optional game-UI references, and one opt-in second native top3-and-you read. It does **not** infer score units, active event identity without required inputs, or arbitrary pagination. No live Prestige request was performed while preparing Dev32.

**0.7.0 agreed scope:** GCC crew leaderboard top ten and ±5 around the authenticated crew, not complete global pagination. Operator has independently reviewed matching Crew RP UI figures; real rollover observation remains pending but is not a release prerequisite. Optional open stats and full leaderboard pagination are deferred to 0.7.1.

**Remaining gates:** authorized Prestige rank/score comparison and bounded range behavior, real cross-platform CI results, and final 0.7.0 release candidate packaging/review. Dev32 prepares the Python 3.9–3.13 × Windows/Ubuntu/macOS CI matrix; workflow success is not yet claimed. No publication or game-state changes. See [Dev32 release-gate notes](docs/0.7.0-dev32-release-gates.md).

---

# CSR2-CDN 0.7.0.dev31 validation status (unreleased)

**Dev31: offline lifecycle preparation on top of Dev30.** Based on the independently reported Dev30 live comparison, the complete member contribution total exactly matched the own-crew-ID-matched GCC score, in two reads 0.230 seconds apart. GCC `end_time=1792663200` and `time_left=496558` implied 2026-10-22 10:00 UTC as candidate end and server time within 0.923 seconds of the recorded GCC read. The own-crew `crew_rp` is distinct and is **not** the season total.

**What is newly tested offline:** an explicitly synthetic positive-to-zero 29-member reset, a 14-day-advanced championship end, zero matched GCC score, independent unverified own-crew/garage statistics, missed resets and earned-after-reset counterexamples, wrong crew, duplicate/partial roster, timestamp skew, and a possible one-hour UTC DST shift. No server reset has yet been observed. Do not assert a verified active season ID or a reset based solely on the simulation. Live values are always read from the server; no local value is zeroed.

**No Dev31 live request, game-state write, Prestige rerun, or publication.** Final 0.7.0 remains blocked on real season lifecycle/UI checks, broader leaderboard pagination, remaining Prestige checks and cross-platform CI. See [Dev31 notes](docs/0.7.0-dev31-season-lifecycle.md).

---

# CSR2-CDN 0.7.0.dev30 validation status (unreleased)

Dev30 is **offline-prepared** on the supplied dev29 full source and the previously obtained dev29 field/type inventory. Numeric candidates now use the live-observed snake_case wire names. Optional diagnostics expose bounded GCC timing/grouping values, nested schema names/types, and independently named, read-gap-gated own-crew `crew_rp` / roster `cc_contrib` / GCC `score` comparisons. These do **not** independently certify season identity, time units or 14-day resets. Original authentication, three read contracts and the public Crew RP model remain unchanged.

**No Dev30 authenticated live call has been made.** The supplied Dev29 independent run counted 29 contributions totalling 38,507,576; it did not do a same-run GCC score comparison. No game writes, Prestige reruns or publication. Final 0.7.0 remains blocked by verified season rollover, leaderboard pagination if needed, remaining Prestige checks and cross-platform release CI. See [Dev30 endpoint evidence](docs/0.7.0-dev30-existing-endpoints.md).

---

# CSR2-CDN 0.7.0.dev29 validation status (unreleased)

Dev29 adds an **offline-prepared**, redacted schema inventory for the same three authenticated read-only crew calls. The CLI dry run makes zero network requests; the optional future live mode will inspect the original checkUserCrew/viewMembers/GCC progress envelopes and `logo` object *without saving raw replies*. Default output is field names, types and aggregate coverage; opt-in selected numeric candidates are explicitly unverified. No new endpoints, pagination variants or writes are introduced. See [Dev29 audit](docs/0.7.0-dev29-endpoint-inventory.md).

There has been **no Dev29 authenticated live test**. Any native declaration absent from previous live outputs remains unverified until the next authorized read. Crew RP's Dev27 matching evidence remains intact; current-season identity and rollover, full-board pagination, other Prestige release gates and cross-platform CI remain outstanding. Final 0.7.0 is not approved for publication.

---

# CSR2-CDN 0.7.0.dev28 validation status (unreleased)

**Crew RP data-source objectives functionally solved for the tested snapshot.** Dev27's independently authorized 2026-10-16 13:31:17 UTC run returned 29 numeric member `cc_contrib` counters adding to **38,226,786**, and an exact-ID-matched GCC progress `score` of **38,226,786** at rank **253**. Its two reads completed in the same displayed second but were **sequential, not atomic**. There is still no independently established backend season ID, rollover behavior, UI comparison for this precise read, or complete global leaderboard pagination.

Dev28 adds `CrewRPSnapshot` and the explicit opt-in `get_crew_rp_snapshot` read method, client-side stale/skew/membership-change detection, and adaptive occupied roster validation from own-crew `memberCount` when available. A valid current pair is usable; no 14-day season proof is fabricated. Service API code has no new route and performs no write operation; snapshots stay in memory. See [Dev28 Crew RP](docs/0.7.0-dev28-crew-rp.md).

**Release status remains blocked:** real season rollover and independent UI/season validation, arbitrary leaderboard pagination if required, remaining Prestige checks, and cross-platform CI are outstanding. No new authenticated live requests, Prestige rerun, game-state changes, GitHub or PyPI publication were performed while preparing Dev28.

---

# CSR2-CDN 0.7.0.dev28 validation status (unreleased)

Dev26 independently matched exactly one own-crew ID in 21 GCC progress rows, yielding **38,226,478** score and **rank 253** on 2026-10-16 at 13:14:32 UTC. This establishes the crew-ID join, not the meaning or active-season scope of generic `score`. The earlier UI RP/rank values are historical, not expected fixed constants.

An independent subsequent dev26 wheel run found **one real, source-reproducible Showdown test failure** caused by mixing `datetime.now` schedule bounds with a fixed October 15 evaluation date. Dev27 fixes that fixture and adds a sequential (non-atomic) roster-sum versus GCC-score comparison using only existing opt-in read-only calls. It never labels the progress score as verified `cc_rp` or a confirmed 14-day season.

No live test has been executed against dev27; do not claim season semantics, pagination completeness, or release readiness from offline tests. Final 0.7.0 remains blocked by live UI/season checks, other Prestige validations and cross-platform CI.

---

# CSR2-CDN 0.7.0.dev26 validation status (unreleased)

**Dev25 GCC progress wire shape decoded in Dev26, season meaning still unverified.** The last authenticated progress response had 21 `scores` rows, each carrying `crew_id` / `name` / `rank` / `score` / `logo`. The new typed decoder preserves rank and score *as received*, matches the exact crew ID against the authorized own-crew read, and optionally prints all returned leaderboard rows. It does not convert generic `score` to `cc_rp` or claim active-season RP without season/accuracy evidence.

The old screenshot reference (37,448,821 RP / rank 257) cannot uniquely identify a later leaderboard row: rank 257 was a different crew in the dev25 output, and a visually similar UNDERDOGZ crew occupied rank 256. Dev26 will resolve this through exact ID matching on the next authorized live check.

**531 offline tests passed** including 14 new dev26 tests. No live authenticated requests were made during implementation. Final 0.7.0 remains blocked on season/score meaning and own-crew live matching, remaining Prestige checks and CI. Nothing published. See [Dev26 progress decoder](docs/0.7.0-dev26-gcc-progress-decoding.md).

---

# CSR2-CDN 0.7.0.dev25 validation status (unreleased)

**Dev24 GCC read response recognized structurally, *not decoded as standings*.** The independently authorized dev24 current-progress request returned `scores` with 21 dictionary rows, but none carried top-level `cc_rp` and no rank/crew total was decoded. Dev25 distinguishes the native GCC **results** records (`RemoteCrewInfo`) from the unknown **progress** `scores` rows; no guess that `score` is seasonal crew RP or that row ordering equals global rank is permitted.

A new bounded row-key/type census and explicitly opt-in value-printing flags (`--gcc-show-schema-keys`, `--gcc-print-score-candidates`) are available through the same allowlisted read-only GCC progress request or through locally captured JSON. Both show diagnostic evidence, not verified seasonal standings; unverified GCC output returns exit code 3. No live reads performed while preparing this change. Reference totals **37,448,821 RP / rank 257**, context **Manthey 911 Prestige Cup** are operator-supplied historical UI observations, not live API verifications.

**517 synthetic/offline tests pass. Release remains blocked.** Prestige was not rerun. No write calls or GitHub/PyPI publication.

---

# CSR2-CDN 0.7.0.dev24 validation status (unreleased)

**Experimental GCC current-progress live probe prepared, not executed.** Native 6.8.0 code traces a category-3 GCC `viewcrew` fetch with `app_ver, top, after, before, offset` and common range `10, 5, 5, 0`. An APK-default endpoint prefix suggests `leaderboard/crew-champs-v2/viewcrew`, but its runtime configuration and active-season scope are not verified. This route runs **only** behind `--execute --print-member-values --gcc-live` and prints decoded response values or privacy-safe schema diagnostics. It does not query completed-season results or invent season numbers.

**Member RP:** following dev23's live 29-member comparison and multiple screenshot matches, a new typed `season_crew_rp` selects valid `cc_contrib` only; `score` and `player_rp` remain distinct and cannot populate it. Season rollover is still unverified. The 14,308 difference in aggregated RP was a timing-tolerated screenshot comparison, not proof of live leaderboard semantics.

**507 offline tests passing. No authenticated live GCC read, game writes, Prestige rerun, CI publication, commits, tags or PyPI publication. Crew leaderboard, season scope and the overall 0.7.0 release remain blocked.** See [dev24 GCC live probe](docs/0.7.0-dev24-gcc-live-probe.md).

# CSR2-CDN 0.7.0.dev23 validation status (unreleased)

**Read-only value-printing probe added; not live-executed by author.** The user verified 29/29 numeric `cc_contrib` candidates in dev22. Dev23 optionally prints member nicknames/contribution values from the same existing authenticated read, sums them, and compares against operator UI reference 37,448,821 RP / rank 257 (Manthey 911 Prestige Cup). It does not claim season equivalence and does not request GCC leaderboard from an unverified URL. A separate offline GCC JSON decoder can print standings when available. **Crew RP and 0.7.0 release remain BLOCKED.** Prestige was not rerun. No publication.

# CSR2-CDN 0.7.0.dev22 validation status (unreleased)

**Offline implementation only:** the 6.8.0 native parser's `cc_contrib` (member season contribution), `score` (context-dependent member fallback), and `cc_rp` (remote crew seasonal total) are now represented by *separately named candidates*. A live read has **not** shown any of these fields populated or established active-season/UI equivalence. Crew RP remains **BLOCKED**. The GCC leaderboard route remains offline-only until its full configured signed read contract is verified. No game writes, Prestige rerun, or publication.

For an authorized, privacy-safe own-crew live first pass:

```console
python -m csr2cdn.live_validation --execute --crew-only --crew-season-probe --crew-rp-schema
```

The report prints key and identity **counts only**, and its season/UI verification gates always remain false pending separate evidence. Do not infer the active 14-day season from lifetime RP, profile RP, or scores without a season identifier and in-game check.

# CSR2-CDN 0.7.0.dev21 validation status

- Independent **dev18 authorized** crew-only read returned **29** roster entries: nickname 29/29, player rank 29/29, role populated/recognized 29/29, but RP 0/29 from every tested field, including uppercase `RP`. This disproves the claim that uppercase `RP` alone was the live fix.
- CSR2 6.8.0 native `PlayerCrewMember.FromJSONDict` maps uppercase `RP` to `RP_allTime` (object offset `0x90`), while `CrewRankPanel.RefreshUI` reads `RP_season` (object offset `0x94`). `PlayerCrew.set_Members` additionally updates the *own player's* GCC contribution from local profile state. These are separate RP semantics.
- **Dev19 is a diagnostic, not a fabricated RP fix.** It attaches aggregate, value-free wire-shape counters for the actual `crews/viewMembers` rows to `--crew-only` live validation: key presence, numeric parseability, nested RP-label candidates, compact-record layout and role source type. The report never includes raw keys, member identities, role values or RP scores.
- If live RP labels are absent from the crew roster, the next research task is to identify the *native, read-only source* that supplies seasonal member contributions. Do not substitute the crew's total RP, lifetime RP or leaderboard data without explicit semantics.
- Dev16 successfully returned 21 Prestige standings for supplied season 277/Porsche metadata; score/rank accuracy, pagination and cross-platform CI remain unverified. Nothing is published.


Dev20: crew-role text mapping passed in prior live testing (29/29); native RP
remains missing (0/29). New opt-in schema-key diagnostics are offline only until
tested against a live authorized roster. No change to Season 277 Prestige
standings read path or the service write capabilities.


Dev20 authorized validation established exactly 29 `player_rp` keys, plus 29 each of `season_pass_rp_boost` and unrelated `car_decal_numberplate_style_id`. The current native trace identifies `player_rp` as `PlayerProfile.get_RP`, *not* verified GCC season contribution. Dev21 retains missing `crew_rp`, adds a separately typed profile stat and safe count. The dev20 missing-fixture packaging regression is corrected and covered by testing the extracted full-project ZIP as well as sdist and wheel. No publication.
