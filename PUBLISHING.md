# Publishing csr2-cdn

Publication uses GitHub Actions and the existing PyPI Trusted Publisher for
`Nitro4CSR/csr2-cdn`, workflow `publish.yml`, environment `pypi`.

## Current release hold

The 0.7.0 preparation branch disables the publish job with `if: ${{ false }}`.
Branch pushes and pull requests run tests only. No release may be published
until the owner explicitly approves the final commit, distributions and notes.
This branch-local hold does not change the older workflow on `main` until merged;
do not dispatch that older workflow or publish a release during preparation.

## After explicit owner approval

1. Confirm the reviewed commit has all 15 matrix jobs and the package job green.
2. Enable the publishing job in a reviewed follow-up change; rerun CI.
3. Confirm both package versions match, inspect built distributions and hashes,
   and review `docs/0.7.0-release-notes.md`.
4. Merge the approved release branch and publish the matching `v0.7.0` GitHub
   release on the agreed date. This triggers the publishing workflow.
5. The workflow checks the tag/version, tests the matrix, builds and validates
   distributions, then publishes through the `pypi` environment.
6. Verify the PyPI version and installation from PyPI.

The manual publishing workflow accepts an existing tag and also constitutes
publication; do not dispatch it before approval. PyPI versions cannot be replaced.
Build outputs, virtual environments and private validation reports are excluded
from Git. Never add account/session data or raw live roster responses.
