"""Offline investigation tooling. Private, and excluded from the wheel.

These modules are the research scaffolding behind the library's findings:
IL2CPP/ARM64 witnesses, pinned APK audits, Unity bundle readers, and the
capture provenance/attestation chain. Every one of them needs an input the
project deliberately never publishes -- the user's own APK, Unity bundles, or
private endpoint captures -- so none of them is usable from a PyPI install.

They are kept in the repository and the source distribution, because they are
the provenance for claims in CHANGELOG.md and VALIDATION_STATUS.md, and they
are excluded from the wheel so that `pip install csr2-cdn` ships a coherent
public API rather than 54 dev-numbered research helpers.

Nothing in the public API imports from here, and nothing here is re-exported
by `csr2cdn.__all__`. Treat it as private: names and signatures may change
without notice.

Running these from a checkout needs the research extras, for example
`pip install -e .[attestation]` for the Ed25519 capture verification.
"""
