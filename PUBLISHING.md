# Publishing csr2-cdn

Publication uses GitHub Actions and the existing PyPI Trusted Publisher for
`Nitro4CSR/csr2-cdn`, workflow `publish.yml`, environment `pypi`.

## Approval requirement

The owner approved 0.7.0 publication on 2026-10-17 after the final candidate
passed all 16 CI jobs. Publishing is enabled. Future releases still require
explicit owner approval before merging, tagging or dispatching publication.

## After explicit owner approval

1. Confirm the reviewed commit has all 15 matrix jobs and the package job green.
2. Confirm the publishing workflow is enabled and all release changes passed CI.
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
