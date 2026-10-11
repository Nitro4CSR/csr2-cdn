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
