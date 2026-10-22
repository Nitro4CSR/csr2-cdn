"""Release invariants that silently drifted before 0.7.1.

`csr2cdn.__version__` sat at "0.7.1.dev81" through three dev cycles while
pyproject.toml moved to dev84, so the package reported a version it was not.
PUBLISHING.md treats the two agreeing as a release requirement; this asserts
it instead of trusting it.
"""
import pathlib
import re

import pytest

import csr2cdn

ROOT = pathlib.Path(__file__).resolve().parent.parent


def declared_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert match, "pyproject.toml has no version"
    return match.group(1)


def test_runtime_version_matches_the_distribution_version():
    assert csr2cdn.__version__ == declared_version()


def test_version_is_a_release_not_a_dev_build():
    """Guards against shipping a .devNN or local-version string by accident."""
    version = declared_version()
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:rc\d+)?", version), version
    assert "dev" not in version
    assert "+" not in version


def test_version_is_exported():
    assert "__version__" in csr2cdn.__all__


# -- the research subpackage stays private and out of the public API ----
def test_no_public_module_imports_the_research_package():
    offenders = []
    for path in (ROOT / "csr2cdn").glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"\b_research\b", text):
            offenders.append(path.name)
    assert offenders == [], offenders


def test_research_modules_are_not_re_exported():
    assert not [n for n in csr2cdn.__all__ if re.match(r"dev\d+_", n)]
    assert "_research" not in csr2cdn.__all__


def test_the_research_package_is_excluded_from_the_wheel():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'exclude = ["csr2cdn._research*"]' in text


def test_the_research_package_is_kept_in_the_sdist():
    text = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "recursive-include csr2cdn/_research *.py" in text


def test_no_stray_dev_modules_left_in_the_public_package():
    stray = sorted(p.name for p in (ROOT / "csr2cdn").glob("dev*_*.py"))
    assert stray == [], stray


# -- nothing private ships ----------------------------------------------
#: A CSR2 player ID is an 11-digit number. Matching the shape rather than a
#: literal keeps the maintainer's own ID out of this file, and catches any
#: other account's ID too.
PLAYER_ID_SHAPE = re.compile(r"(?<!\d)\d{11}(?!\d)")

SHIPPED_TEXT = ("README.md", "PUBLISHING.md")


def public_sources():
    for path in (ROOT / "csr2cdn").rglob("*.py"):
        if "_research" not in path.parts:
            yield path


def test_no_player_identifier_in_the_public_package():
    """The maintainer's own player ID was once the documented CDN example."""
    offenders = []
    for path in public_sources():
        for match in PLAYER_ID_SHAPE.finditer(
                path.read_text(encoding="utf-8", errors="ignore")):
            offenders.append("%s: %s..." % (path.name, match.group(0)[:3]))
    assert offenders == [], offenders


def test_no_player_identifier_in_the_published_docs():
    """README.md is the PyPI landing page."""
    offenders = []
    for name in SHIPPED_TEXT:
        path = ROOT / name
        if not path.exists():
            continue
        for match in PLAYER_ID_SHAPE.finditer(
                path.read_text(encoding="utf-8", errors="ignore")):
            offenders.append("%s: %s..." % (name, match.group(0)[:3]))
    assert offenders == [], offenders


def test_the_documented_example_asks_for_the_callers_own_id():
    """The design requires the caller to supply their own ZID."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert 'CDN(zid="YOUR_PLAYER_ID")' in readme

# -- the source distribution must be runnable, not just complete-looking -
# Inspecting an sdist's file list is not the same as running from it. 0.7.1
# shipped without tests/conftest.py (six modules import it for the
# requires_symlinks marker) and without docs/examples/*.json (four capture
# modules read them), because MANIFEST.in listed only *.md and *.csv under
# docs and relied on setuptools' implicit handling for tests.
MANIFEST_RULES = (
    "recursive-include tests *.py",
    "recursive-include docs/examples *.json",
    "recursive-include tests/fixtures *.meta",
    "recursive-include examples *.py",
    "recursive-include csr2cdn/_research *.py",
)


def manifest() -> str:
    return (ROOT / "MANIFEST.in").read_text(encoding="utf-8")


@pytest.mark.parametrize("rule", MANIFEST_RULES)
def test_manifest_carries_every_rule_the_suite_needs(rule):
    assert rule in manifest(), rule


def test_conftest_exists_and_is_covered():
    """Six modules do `from conftest import requires_symlinks`."""
    assert (ROOT / "tests" / "conftest.py").is_file()
    assert "recursive-include tests *.py" in manifest()


def test_every_data_file_the_tests_read_exists():
    """Resolve the literal paths out of the suite and check each one."""
    referenced = set()
    for path in (ROOT / "tests").glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        referenced.update(re.findall(r"docs/examples/[A-Za-z0-9_.\-]+", text))
    assert referenced, "expected the capture tests to reference fixtures"
    missing = [name for name in sorted(referenced) if not (ROOT / name).is_file()]
    assert missing == [], missing


def test_referenced_fixtures_are_matched_by_a_manifest_rule():
    """A fixture under docs/ only ships if its extension is listed."""
    rules = manifest()
    for path in sorted((ROOT / "docs" / "examples").glob("*")):
        if path.suffix == ".json":
            assert "recursive-include docs/examples *.json" in rules
        else:
            assert "recursive-include docs *%s" % path.suffix in rules, path.name
