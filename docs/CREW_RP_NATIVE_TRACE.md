# CSR2 6.8.0 crew RP: observed wire semantics (dev21)

## Live evidence (2026-10-16)

Dev20 `crews/viewMembers` returned 29 dictionary rows. Three repeated
RP-looking keys were reported without values: `player_rp`,
`season_pass_rp_boost`, and `car_decal_numberplate_style_id` (29 occurrences
each). The known native uppercase `RP`, lower-case `rp`, and explicit
seasonal aliases were absent. Crew RP remained missing for all 29, while
display name, player level, and recognized text roles were present. The
full-project ZIP also accidentally excluded all `*.meta` files, including
synthetic fixtures required by a Showdown test.

## Native disassembly evidence

The CSR2 Android 6.8.0 `libil2cpp.so` and IL2CPP string table show:

1. `UserManager.FillNonSecureBlobDict`, RVA `0x368b798`, calls
   `PlayerProfile.get_RP`, RVA `0x34be580` (direct `bl` at `0x368b798`).
   Its return value is passed as the numeric value under the exact
   string literal `player_rp`: literal loaded at `0x368b79c/0x368b7a0`,
   assigned by the dictionary-int helper at `0x368b7b4`.
2. `PlayerCrewMember.FromJSONDict`, RVA `0x34a3d78`, reads the **different**
   key `RP` at `0x34a4a78` and stores it at member offset `0x88`,
   corresponding to `RP_allTime`. It does not read `player_rp` in this method.
3. `CrewRankPanel.RefreshUI`, RVA `0x269a9cc`, loads `w22` from member
   offset `0x94` at `0x269ab08`, corresponding to the **separate**
   `PlayerCrewMember.RP_season` field, and formats it for display.
4. `PlayerCrew.set_Members`, RVA `0x34a5518`, updates the **local player's**
   GCC player-contribution state using
   `PlayerProfile.SetActiveCrewRP_GCCPlayerContrib` at `0x34a574c` and
   assigns that local member's season field at `0x34a5754`.

## Safe interpretation

The `player_rp` response key identifies a player-profile RP value, not
an authoritative per-member seasonal crew contribution. Its numeric
coverage can be reported, but cannot be substituted into `crew_rp`.
The available native trace does **not** identify a read-only server route
containing all members' `RP_season` values. A separate seasonal
contribution source and a private comparison with the game are still
required. Nor has the native role label been compared to the UI.

## Dev21 change

Expose `CrewMember.player_rp` and value-free `player_profile_rp_populated`.
Keep `CrewMember.crew_rp` absent unless a recognized RP field is actually
present. The distinct `rp_all_time` and role attributes remain unchanged.
No new network request, write API, save-game capability, or authentication
trace was added. Synthetic `.meta` regression fixtures must ship in the
source ZIP, sdist and standalone source tests.

## Dev22 supplemental trace and interpretation

Additional 6.8.0 ARM64 trace from `crew_rp_source_trace_v2.md` (offline):
`PlayerCrewMember.FromJSONDict` (`0x34a3d78`) writes `score` to `RP_season`
near `0x34a4544`, then `cc_contrib` near `0x34a46e4`; the latter wins when
both are present. `FetchCrewMembersResponse` passes `crews/viewMembers` rows
through this decoder. Neither a live field-presence claim nor active-season
identity follows merely from parser support.

`RemoteCrewInfo.FromJSONDict` (`0x34a6cc4`) writes `cc_rp` to the seasonal
crew field near `0x34a70a0`, distinct from the `rp` all-time field.
`FetchGrandCrewChampionshipResponse` routes remote crew rows through this
decoder. The complete signed GCC `viewcrew` request and active-season scope
are unverified, so no network route has been added for it.

Dev22 implements these separate candidates and a read-only roster coverage
probe. The generic `leaderboard/{0}/scores/crewmembers` belongs to event
standings and cannot be substituted for season GCC contribution.
