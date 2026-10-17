# 0.7.0 release validation

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
Final candidate commit `8c5930b5ac1a1e9a636470292388c9eecc7a1f5d` also passed all 16 jobs:
https://github.com/Nitro4CSR/csr2-cdn/actions/runs/38965576660

Both final distributions passed strict Twine checks; the installed wheel passed 695 tests.

## Publication approval

The owner explicitly approved publication on 2026-10-17. The publishing job is
enabled for the release. The approval-only workflow/documentation changes are
subject to CI before merge and tagging. Actual publication status is recorded
by the GitHub release and PyPI version, not inferred from this document.

Historical development reports under `docs/` retain the evidence and limitations
of their respective builds and do not replace this current acceptance record.
