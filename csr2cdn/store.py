"""Finding the current game version without hard coding it.

The chain that gets from "nothing" to "the current branch name" is:

1. the stores give the app version, e.g. ``6.7.1``
2. that becomes the release branch to bootstrap from, ``6_7_0_Release``
3. that branch's ``.version`` file gives a database version
4. that database's header gives ``product_version``, e.g. ``6.7.81``
5. ``product_version`` lets you ask the metadata service for
   ``FeatureKillswitches``, which announces the real current branch

Only step 1 leaves the ecosystem. Two stores are consulted, both per country,
because the two stores roll out independently:

* Google Play through ``google_play_scraper`` when it is installed
  (``pip install csr2-cdn[stores]``), falling back to parsing the listing. Play
  serves the same version to every storefront, so one country is asked and the
  call is a single request. Play only publishes a version string for single APK
  apps, and CSR2 ships as a bundle, so this can legitimately answer nothing.
* the iTunes lookup API, a plain JSON endpoint with no scraping and no
  dependency, which publishes a version for every app. Its storefronts update
  separately, so several are asked, concurrently.

Sources are tried in order and the first answer wins, so the usual cost is one
request. ``strategy="max"`` asks everything and takes the highest version, at
the price of every source's latency on every call.

:data:`VERSION_SOURCES` is a list of callables tried in turn. Each takes an
:class:`AppIds` and returns a version string or ``None``; exceptions are
swallowed so one dead source cannot break the chain. Replace or extend it to
plug in your own lookup, or skip step 1 entirely by passing ``release_version=``
to :class:`~csr2cdn.cdn.CDN`.
"""

from __future__ import annotations

import inspect
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

from csr2cdn.errors import StoreVersionError

#: CSR2 on Google Play.
PACKAGE_ID = "com.naturalmotion.customstreetracer2"
#: CSR2 on the App Store.
APP_STORE_ID = "887947640"


class AppIds(NamedTuple):
    """The store identifiers of an app."""

    package_id: str = PACKAGE_ID
    app_store_id: str = APP_STORE_ID


#: The default app: CSR2.
CSR2 = AppIds()

ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup?id={app_store_id}&country={country}"
PLAY_URL = "https://play.google.com/store/apps/details?id={package_id}&hl=en&gl={country}"
APKPURE_URL = "https://apkpure.com/csr-2-realistic-drag-racing/{package_id}"

#: Play storefront to ask. Play reports the same version everywhere, so one is enough.
PLAY_COUNTRIES: Tuple[str, ...] = ("gb",)

#: App Store storefronts checked by default. Each country updates separately,
#: so several are worth asking, and they are asked concurrently.
APP_STORE_DEFAULT_COUNTRIES: Tuple[str, ...] = ("gb", "us", "de", "au", "nz")

#: Backwards compatible alias for the Play default.
DEFAULT_COUNTRIES: Tuple[str, ...] = PLAY_COUNTRIES

#: Every Google Play storefront, for an exhaustive sweep.
GOOGLE_PLAY_COUNTRIES: Tuple[str, ...] = (
    "ae", "ag", "al", "am", "ao", "ar", "at", "au", "aw", "az", "ba", "bd", "be", "bf", "bg", "bh",
    "bj", "bo", "br", "bs", "bw", "by", "bz", "ca", "ch", "ci", "cl", "cm", "cn", "co", "cr", "cv",
    "cy", "cz", "de", "dk", "do", "dz", "ec", "ee", "eg", "es", "fi", "fj", "fr", "ga", "gb", "gh",
    "gr", "gt", "gw", "hk", "hn", "hr", "ht", "hu", "id", "ie", "il", "in", "is", "it", "jm", "jo",
    "jp", "ke", "kg", "kh", "kr", "kw", "kz", "la", "lb", "li", "lk", "lt", "lu", "lv", "ma", "md",
    "mk", "ml", "mt", "mu", "mx", "my", "mz", "na", "ne", "ng", "ni", "nl", "no", "np", "nz", "om",
    "pa", "pe", "pg", "ph", "pk", "pl", "pt", "py", "qa", "ro", "rs", "ru", "rw", "sa", "se", "sg",
    "si", "sk", "sn", "sv", "tg", "th", "tj", "tm", "tn", "tr", "tt", "tw", "tz", "ua", "ug", "us",
    "uy", "uz", "ve", "vn", "ye", "za", "zm", "zw",
)

#: Every App Store storefront, for an exhaustive sweep.
APP_STORE_COUNTRIES: Tuple[str, ...] = (
    "ae", "ag", "ai", "al", "am", "ar", "at", "au", "az", "ba", "bb", "be", "bf", "bg", "bh", "bj",
    "bm", "bn", "bo", "br", "bs", "bt", "bw", "bz", "ca", "cg", "ch", "ci", "cl", "cm", "co", "cr",
    "cv", "cy", "cz", "de", "dk", "dm", "do", "dz", "ec", "ee", "eg", "es", "fi", "fj", "fr", "ga",
    "gb", "gd", "gh", "gm", "gr", "gt", "gw", "gy", "hk", "hn", "hr", "hu", "id", "ie", "il", "in",
    "is", "it", "jm", "jo", "jp", "ke", "kg", "kn", "kr", "kw", "ky", "kz", "lb", "lc", "lk", "lr",
    "lt", "lu", "lv", "ma", "md", "mg", "mk", "ml", "mn", "mo", "mr", "ms", "mt", "mu", "mw", "mx",
    "my", "mz", "na", "ne", "ng", "ni", "nl", "no", "np", "nz", "om", "pa", "pe", "pg", "ph", "pk",
    "pl", "pt", "pw", "py", "qa", "ro", "rs", "rw", "sa", "sb", "sc", "se", "sg", "si", "sk", "sn",
    "sr", "st", "sv", "sz", "tc", "td", "th", "tj", "tm", "tn", "tr", "tt", "tw", "tz", "ug", "us",
    "uy", "uz", "vc", "ve", "vg", "vn", "ye", "za", "zm", "zw",
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_VERSION_RE = re.compile(r"^\d+\.\d+(?:\.\d+){0,2}$")
_LD_JSON_RE = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)
_AF_SCRIPT_RE = re.compile(r"AF_initDataCallback\([\s\S]*?\);</script")
_AF_KEY_RE = re.compile(r"key:\s*'(ds:\d+)'")
_AF_DATA_RE = re.compile(r"data:([\s\S]*?), sideChannel")
_PLAY_VERSION_PATHS = ((1, 2, 140, 0, 0, 0), (1, 2, 140, 0, 0))

VersionSource = Callable[..., Optional[str]]


# -- helpers --------------------------------------------------------------
def version_key(version: str) -> Tuple[int, ...]:
    """Sort key for dotted versions, so ``6.10.0`` beats ``6.9.0``."""
    return tuple(int(part) if part.isdigit() else 0 for part in str(version).split("."))


def newest(versions: Iterable[Optional[str]]) -> Optional[str]:
    """The highest version in *versions*, ignoring blanks and junk."""
    valid = [v for v in (_clean(item) for item in versions) if v]
    return max(valid, key=version_key) if valid else None


def _clean(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if _VERSION_RE.match(value) else None


def _get(url: str, session: Optional[Any], timeout: float):
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    if session is None:
        import requests

        return requests.get(url, headers=headers, timeout=timeout)
    return session.get(url, headers=headers, timeout=timeout)


def _walk(node: Any, key: str) -> Optional[str]:
    if isinstance(node, dict):
        if key in node:
            found = _clean(node[key])
            if found:
                return found
        for value in node.values():
            found = _walk(value, key)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _walk(item, key)
            if found:
                return found
    return None


def _ld_json_version(html: str) -> Optional[str]:
    for blob in _LD_JSON_RE.findall(html):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        found = _walk(data, "softwareVersion")
        if found:
            return found
    return None


def _at_path(node: Any, path: Sequence[int]) -> Any:
    for index in path:
        try:
            node = node[index]
        except (IndexError, KeyError, TypeError):
            return None
    return node


def _play_html_version(package_id: str, country: str, session, timeout: float) -> Optional[str]:
    response = _get(PLAY_URL.format(package_id=package_id, country=country), session, timeout)
    response.raise_for_status()
    html = response.text
    found = _ld_json_version(html)
    if found:
        return found
    for match in _AF_SCRIPT_RE.findall(html):
        keys, values = _AF_KEY_RE.findall(match), _AF_DATA_RE.findall(match)
        if not keys or not values:
            continue
        try:
            dataset = json.loads(values[0])
        except json.JSONDecodeError:
            continue
        for path in _PLAY_VERSION_PATHS:
            found = _clean(_at_path(dataset, path))
            if found:
                return found
    return None


# -- sources --------------------------------------------------------------
def app_store_version(
    app: AppIds = CSR2,
    session: Optional[Any] = None,
    timeout: float = 15.0,
    countries: Optional[Sequence[str]] = None,
    workers: int = 8,
) -> Optional[str]:
    """The newest version across App Store storefronts.

    Uses the iTunes lookup API, a plain JSON endpoint. iOS builds are not app
    bundles, so a version string is always published, which makes this the
    dependable source. Unlike Play, each storefront updates separately, so
    several are asked, concurrently, and the whole call costs about one request
    of latency rather than one per country.
    """
    wanted = list(countries or APP_STORE_DEFAULT_COUNTRIES)

    def _one(country: str) -> Optional[str]:
        try:
            response = _get(
                ITUNES_LOOKUP_URL.format(app_store_id=app.app_store_id, country=country),
                session,
                timeout,
            )
            response.raise_for_status()
            results = (response.json() or {}).get("results") or []
        except Exception:  # noqa: BLE001 - a dead storefront is not fatal
            return None
        return newest(entry.get("version") for entry in results)

    if len(wanted) == 1:
        return _one(wanted[0])
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(wanted)))) as pool:
        return newest(pool.map(_one, wanted))


def google_play_version(
    app: AppIds = CSR2,
    session: Optional[Any] = None,
    timeout: float = 15.0,
    countries: Optional[Sequence[str]] = None,
) -> Optional[str]:
    """The version Play reports.

    Play serves the same version to every storefront, so one country is asked by
    default and the call is a single request. Uses ``google_play_scraper`` when
    it is installed, which is what the Jess bot does, and parses the listing
    otherwise. Returns ``None`` when Play publishes no version, which is normal
    for an app bundle.
    """
    wanted = list(countries or PLAY_COUNTRIES)
    found: List[Optional[str]] = []
    try:
        from google_play_scraper import app as play_app
    except ImportError:
        play_app = None

    for country in wanted:
        try:
            if play_app is not None:
                result = play_app(app.package_id, lang="en", country=country)
                found.append(result.get("version"))
            else:
                found.append(_play_html_version(app.package_id, country, session, timeout))
        except Exception:  # noqa: BLE001 - a dead storefront is not fatal
            continue
    return newest(found)


def apkpure_version(
    app: AppIds = CSR2,
    session: Optional[Any] = None,
    timeout: float = 15.0,
    countries: Optional[Sequence[str]] = None,
) -> Optional[str]:
    """The version APKPure lists. A mirror, so treat it as a last resort."""
    response = _get(APKPURE_URL.format(package_id=app.package_id), session, timeout)
    response.raise_for_status()
    html = response.text
    found = _ld_json_version(html)
    if found:
        return found
    match = re.search(r"Latest Version\s*</div>\s*<div[^>]*>\s*([\d.]+)", html)
    if match:
        return _clean(match.group(1))
    match = re.search(r'name="description"[^>]*content="[^"]*?([\d]+\.[\d.]+)\s*APK', html)
    return _clean(match.group(1)) if match else None


#: Sources tried by :func:`latest_store_version`. Replace or extend freely.
VERSION_SOURCES: List[VersionSource] = [
    google_play_version,
    app_store_version,
    apkpure_version,
]


def _call_source(
    source: VersionSource,
    app: AppIds,
    session: Optional[Any],
    timeout: float,
    countries: Optional[Sequence[str]],
) -> Optional[str]:
    """Call a source, passing only the keyword arguments it accepts.

    Custom sources are free to take just ``(app)``, or to ignore the session and
    the country list entirely.
    """
    kwargs: Dict[str, Any] = {"session": session, "timeout": timeout, "countries": countries}
    try:
        parameters = inspect.signature(source).parameters
    except (TypeError, ValueError):  # builtins and odd callables
        return source(app)
    if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        kwargs = {key: value for key, value in kwargs.items() if key in parameters}
    return source(app, **kwargs)


def store_versions(
    app: AppIds = CSR2,
    sources: Optional[Iterable[VersionSource]] = None,
    session: Optional[Any] = None,
    timeout: float = 15.0,
    countries: Optional[Sequence[str]] = None,
) -> Dict[str, Optional[str]]:
    """What every source reports, keyed by source name. Useful for debugging."""
    out: Dict[str, Optional[str]] = {}
    for source in sources if sources is not None else VERSION_SOURCES:
        name = getattr(source, "__name__", str(source))
        try:
            out[name] = _call_source(source, app, session, timeout, countries)
        except Exception as exc:  # noqa: BLE001
            out[name] = f"error: {exc}"
    return out


def latest_store_version(
    app: AppIds = CSR2,
    sources: Optional[Iterable[VersionSource]] = None,
    session: Optional[Any] = None,
    timeout: float = 15.0,
    countries: Optional[Sequence[str]] = None,
    strategy: str = "first",
) -> str:
    """The newest published app version, e.g. ``"6.7.1"``.

    ``strategy="first"`` (the default) stops at the first source that answers,
    so the usual cost is the single Play request and nothing else. Later sources
    are only paid for when the earlier ones come back empty.

    ``strategy="max"`` asks every source and returns the highest version any of
    them reports. It costs every source's latency on every call, but catches a
    rollout that has reached one store and not the other.

    :raises StoreVersionError: when no source produced a version.
    """
    if strategy not in ("max", "first"):
        raise ValueError("strategy must be 'max' or 'first'")
    notes: List[str] = []
    answers: List[str] = []
    for source in sources if sources is not None else VERSION_SOURCES:
        name = getattr(source, "__name__", str(source))
        try:
            found = _call_source(source, app, session, timeout, countries)
        except Exception as exc:  # noqa: BLE001 - a dead source must not stop the chain
            notes.append(f"{name}: {exc}")
            continue
        if found:
            if strategy == "first":
                return found
            answers.append(found)
        else:
            notes.append(f"{name}: no version published")
    best = newest(answers)
    if best:
        return best
    raise StoreVersionError(
        "could not determine the current app version from any source ("
        + "; ".join(notes)
        + "). Pass release_version= to skip this step."
    )


# -- version arithmetic ---------------------------------------------------
def normalize_release(version: str) -> str:
    """Drop the patch component: ``6.7.1`` -> ``6.7.0``.

    Only a convenience. Branch names are not derived by rule, since patch level
    branches such as ``6_4_1_Release`` and ``4_5_1_Release_OTA_1`` exist; see
    :func:`csr2cdn.patterns.release_candidates`, which tries both forms.
    """
    parts = str(version).strip().split(".")
    if len(parts) < 2 or not all(part.isdigit() for part in parts[:2]):
        raise StoreVersionError(f"{version!r} does not look like an app version")
    return f"{int(parts[0])}.{int(parts[1])}.0"


def previous_releases(release: str, count: int = 2) -> List[str]:
    """Earlier releases to fall back on, newest first: ``6.7.0`` -> ``6.6.0``, ``6.5.0``."""
    major, minor = (int(part) for part in normalize_release(release).split(".")[:2])
    out = []
    for _ in range(count):
        if minor > 0:
            minor -= 1
        elif major > 0:
            major -= 1
            minor = 9
        else:
            break
        out.append(f"{major}.{minor}.0")
    return out


__all__ = [
    "APP_STORE_COUNTRIES",
    "APP_STORE_DEFAULT_COUNTRIES",
    "APP_STORE_ID",
    "CSR2",
    "DEFAULT_COUNTRIES",
    "GOOGLE_PLAY_COUNTRIES",
    "PACKAGE_ID",
    "PLAY_COUNTRIES",
    "VERSION_SOURCES",
    "AppIds",
    "apkpure_version",
    "app_store_version",
    "google_play_version",
    "latest_store_version",
    "newest",
    "normalize_release",
    "previous_releases",
    "store_versions",
    "version_key",
]
