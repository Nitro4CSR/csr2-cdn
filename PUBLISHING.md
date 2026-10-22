# Release status

`csr2cdn.__version__` and `pyproject.toml` both identify `0.7.1`, asserted by
`tests/test_release_metadata.py`. The suite passes with no failures; the
symlink-rejection tests skip where the OS withholds the privilege to create a
symlink, which is reported as a skip rather than a failure.

## What must never be published

The user-supplied APK, Unity bundles, private endpoint caches, native
extraction scratch files and received crew data MUST remain outside the source
archive and the wheel. Verified for 0.7.1: neither artifact contains any of
them, nor any real player or crew identifier.

The offline research modules in `csr2cdn/_research/` require those inputs, so
they are excluded from the wheel and kept in the sdist as provenance only. They
are private: do not document them as public API.

## Superseded notes

Earlier builds in this line carried a warning that the cosmetic resolver was
investigation-only, because the index-15/ID-1323 paint mapping was conditional
and paint zero was unresolved. **That no longer applies.** Both resolved against
the live service in 0.7.1 (index 0 -> 1156, index 15 -> 1323), with the
composition rule and the 190/190 roster result recorded in
`VALIDATION_STATUS.md`. The remaining conditional claims are listed there under
known limits; do not describe the whole resolver as conditional.

# Publishing csr2-cdn

The project uses GitHub Actions and PyPI Trusted Publishing. No PyPI API token
needs to be stored in GitHub.

## One-time setup

While signed in to the PyPI account that will own this project, open
[account publishing](https://pypi.org/manage/account/publishing/) and add a
pending GitHub publisher:

| Field | Value |
| --- | --- |
| PyPI project name | `csr2-cdn` |
| Owner | `Nitro4CSR` |
| Repository name | `csr2-cdn` |
| Workflow filename | `publish.yml` |
| Environment name | `pypi` |

Once the project exists, publisher settings are under the project's Publishing
page instead. The first successful upload creates the PyPI project.

## Releases

1. Update both versions in `pyproject.toml` and `csr2cdn/__init__.py`, then update
   `CHANGELOG.md`.
2. Push the changes to GitHub and wait for the Tests workflow to pass.
3. Create and publish a GitHub release tagged `v<version>` from the tested commit
   (for example, `v0.5.0`).
4. The Publish to PyPI workflow tests Python 3.9 and 3.13 on Windows and Linux, checks the tag/version,
   builds and validates the wheel/source archive, and publishes through the
   `pypi` environment. Only the publishing job receives OIDC permission.
5. Verify the new version at [PyPI](https://pypi.org/project/csr2-cdn/).

If publisher setup was incomplete on the first attempt, rerun the failed
publishing job after completing setup. The workflow also has a manual Run
workflow action accepting an existing release tag. PyPI versions cannot be
overwritten: publish a new version when changing an already uploaded package.

Only tracked source is built. The local `dist/`, virtual environment and
verification downloads are ignored by Git.

See [PyPI's official Trusted Publishing documentation](https://docs.pypi.org/trusted-publishers/).
