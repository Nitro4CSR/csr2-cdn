# 0.7.0 release candidate — unpublished

## Accepted scope and live evidence

Crew discovery, 29-member roster coverage, text roles, seasonal `cc_contrib`,
and exact member-sum/GCC-score comparisons passed authorized live validation.
The operator accepted Crew RP and UI comparisons. GCC scope is top ten plus
five above/below the authenticated crew. Full pagination is deferred to 0.7.1.

Showdown returned standings using name-based resolution. Prestige's reconstructed
Season 277 Manthey board returned global and crew-filtered standings. The latest
Dev34 comparison returned 41 global and 10 crew entries with distinct identities;
the one shared authenticated player had matching server rank and score.
Microsecond-to-six-decimal timing was accepted from the operator's UI review.
These observations do not prove a complete crew list or universal crew-rank scope.

The actual season rollover remains unobserved. Synthetic reset, boundary,
coverage and read-skew checks passed; live rollover observation is optional
confirmation, not a release prerequisite. Optional statistics and deeper vehicle
data remain outside accepted 0.7.0 scope.

## CI and artifacts

Dev34 preparation commit `a15957022d7778f85ec359311cae7d1f454f4474` passed
all 15 OS/Python combinations and the build job:
https://github.com/Nitro4CSR/csr2-cdn/actions/runs/38965264312

The suite has 695 tests. Build validation includes strict Twine checks and
isolated installation/testing of both the wheel and source distribution.
Final 0.7.0 version/documentation CI and final artifact checks are pending.

## Publication gate

No 0.7.0 release or PyPI publication has occurred. The release-preparation
branch disables the PyPI publishing job with `if: ${{ false }}`. It must remain
disabled until the owner explicitly approves publication of reviewed artifacts.
The draft PR remains unmerged; no release tag has been created.

Historical development reports under `docs/` retain the evidence and limitations
of their respective builds and do not replace this current acceptance record.
