"""Official car PNG CDN, indexed by the live ``CDNSnapshots`` metadata block."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.parse import quote, urlsplit

import requests

from csr2cdn import _http
from csr2cdn.errors import Csr2CdnError, MetadataError, MissingZidError
from csr2cdn.metadata import MetadataBlock, MetadataClient

SNAPSHOTS_BLOCK = "CDNSnapshots"
SNAPSHOT_KINDS = ("GACHA", "PRIZE", "DEFAULT")
_MODES = {"GACHA": "GACHA_CAR", "PRIZE": "PRIZE_CAR", "DEFAULT": "DEFAULT"}
_UNSET = "-2147483648"
_FIELDS = f"_p0_i{_UNSET}_c{_UNSET}_s512_n_lz{_UNSET}_l{_UNSET}"
_FILENAME = re.compile(
    r"(?P<car>.+?)_p(?P<paint>-?\d+)_i(?P<interior>-?\d+)"
    r"_c(?P<caliper>-?\d+)_s(?P<size>\d+)_n(?P<plate>.*?)"
    r"_lz(?P<zone>-?\d+)_l(?P<livery>-?\d+)"
    r"_m(?P<mode>DEFAULT_REVERSED|DEFAULT|GACHA_CAR|PRIZE_CAR)"
    r"(?P<extra>(?:_.*)?)\.png"
)


class SnapshotError(Csr2CdnError):
    """A snapshot download failed; HTTP status and path remain available."""

    def __init__(self, message: str, *, path: str, status_code=None):
        super().__init__(message)
        self.path = path
        self.status_code = status_code


class SnapshotNotFoundError(SnapshotError):
    """Strict lookup found no listed snapshot for this car and mode."""


def _path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("snapshot paths must be relative, forward-slash paths")
    if any(ord(c) < 32 for c in value) or any(p in ("", ".", "..") for p in value.split("/")):
        raise ValueError("invalid snapshot path")
    return value


def _car(value: str) -> str:
    _path(value)
    if "/" in value:
        raise ValueError("crdb must be a car name, not a path")
    return value


def _mode(kind: str, reversed: bool) -> str:
    if not isinstance(kind, str) or kind.upper() not in _MODES:
        raise ValueError("kind must be GACHA, PRIZE or DEFAULT")
    if not isinstance(reversed, bool):
        raise ValueError("reversed must be a bool")
    kind = kind.upper()
    if reversed and kind != "DEFAULT":
        raise ValueError("reversed=True only applies to DEFAULT")
    return "DEFAULT_REVERSED" if reversed else _MODES[kind]


class SnapshotCDN:
    """Select and download official PNGs without loading a car asset database.

    Build with :meth:`from_metadata`, :meth:`from_file`, or a parsed manifest.
    ``cars`` reports manifest availability, not guaranteed HTTP availability.
    Missing entries use a conventional filename unless ``strict=True``.
    """

    def __init__(self, manifest: Any, *, staging: bool = False,
                 session: Optional[Any] = None, timeout: float = 30.0):
        if isinstance(manifest, MetadataBlock):
            manifest = manifest.content
        if isinstance(manifest, Mapping) and SNAPSHOTS_BLOCK in manifest:
            manifest = manifest[SNAPSHOTS_BLOCK]
        if not isinstance(manifest, Mapping) or not isinstance(manifest.get("list"), list):
            raise ValueError("CDNSnapshots must contain a list of snapshot paths")
        endpoint = manifest.get("BaseUrlStaging" if staging else "BaseUrlProd")
        if not isinstance(endpoint, str):
            raise ValueError("CDNSnapshots is missing the selected base URL")
        parsed = urlsplit(endpoint)
        if (parsed.scheme not in ("http", "https") or not parsed.netloc
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or any(c.isspace() for c in endpoint) or "\\" in endpoint):
            raise ValueError("snapshot base URL must be an HTTP(S) URL without credentials/query/fragment")
        self.base_url = endpoint.rstrip("/")
        self.timeout = timeout
        self._session = session
        self._owns_session = session is None
        self._staging = staging
        self._source_file = None
        self._source_metadata = None
        self._index: Dict[str, Dict[str, Tuple[str, ...]]] = {}
        groups: Dict[str, Dict[str, list]] = {}
        unclassified = []
        self.paths = tuple(dict.fromkeys(_path(p) for p in manifest["list"]))
        for path in self.paths:
            filename = path.rsplit("/", 1)[-1]
            match = _FILENAME.fullmatch(filename)
            if match:
                car, mode = match["car"], match["mode"]
                # Prefer stock/unset configuration, no forced-Gacha suffix,
                # then highest resolution; break ties by exact path, never manifest order.
                rank = (
                    match["paint"] != "0", bool(match["extra"]),
                    match["interior"] != _UNSET, match["caliper"] != _UNSET,
                    -int(match["size"]), len(match["extra"]), path,
                )
            elif (path.startswith("Default/") and path.count("/") == 1
                  and filename.endswith(".png") and "_m" not in filename):
                car, mode = filename[:-4], "DEFAULT"
                rank = (False, False, False, False, 0, 0, path)
            else:
                unclassified.append(path)
                continue
            groups.setdefault(car, {}).setdefault(mode, []).append((rank, path))
        for car in sorted(groups):
            self._index[car] = {
                mode: tuple(path for _, path in sorted(values))
                for mode, values in groups[car].items()
            }
        self.unclassified_paths = tuple(unclassified)
        templates = {}
        for car, modes in self._index.items():
            for mode, paths in modes.items():
                selected = paths[0]
                filename = selected.rsplit("/", 1)[-1]
                if not _FILENAME.fullmatch(filename):
                    continue
                prefix = selected[:-len(filename)]
                templates.setdefault(mode, Counter())[(prefix, filename[len(car):])] += 1
        self._templates = {
            mode: min(counts, key=lambda item: (-counts[item], item))
            for mode, counts in templates.items()
        }

    @classmethod
    def from_file(cls, path, **kwargs) -> "SnapshotCDN":
        """Read a JSON ``CDNSnapshots.meta`` file (wrapped or unwrapped)."""
        with open(path, encoding="utf-8-sig") as handle:
            result = cls(json.load(handle), **kwargs)
        result._source_file = Path(path).resolve()
        return result

    @classmethod
    def from_metadata(cls, zid: str, product_version: str, *,
                      client: Optional[MetadataClient] = None, **kwargs) -> "SnapshotCDN":
        """Fetch a fresh manifest from the metadata service using your own zid."""
        if not zid:
            raise MissingZidError("a zid is required to fetch CDNSnapshots")
        if not product_version:
            raise MetadataError("a product_version is required")
        if client is None:
            with MetadataClient(timeout=kwargs.get("timeout", 30.0)) as owned:
                block = owned.get_one(SNAPSHOTS_BLOCK, zid, product_version)
        else:
            block = client.get_one(SNAPSHOTS_BLOCK, zid, product_version)
        if block is None:
            raise MetadataError("the metadata service did not return CDNSnapshots")
        result = cls(block, **kwargs)
        result._source_metadata = (zid, product_version, client)
        return result

    def refresh(self, manifest=None) -> None:
        """Reload the source metadata/file, or replace with a supplied manifest.

        Cars, availability, inferred templates and endpoint change together.
        A failed refresh leaves the last valid catalogue intact. Directly
        constructed clients must supply a replacement manifest.
        """
        options = dict(staging=self._staging, session=self._session, timeout=self.timeout)
        if manifest is not None:
            updated = type(self)(manifest, **options)
        elif self._source_file is not None:
            updated = type(self).from_file(self._source_file, **options)
        elif self._source_metadata is not None:
            zid, version, client = self._source_metadata
            updated = type(self).from_metadata(zid, version, client=client, **options)
        else:
            raise ValueError("supply a manifest to refresh a directly constructed SnapshotCDN")
        self.base_url = updated.base_url
        self._index = updated._index
        self.paths = updated.paths
        self.unclassified_paths = updated.unclassified_paths
        self._templates = updated._templates

    @property
    def cars(self) -> Dict[str, Dict[str, bool]]:
        """CRDB names only, with GACHA/PRIZE/DEFAULT/DEFAULT_REVERSED flags."""
        return {
            car: {"GACHA": "GACHA_CAR" in modes, "PRIZE": "PRIZE_CAR" in modes,
                  "DEFAULT": "DEFAULT" in modes, "DEFAULT_REVERSED": "DEFAULT_REVERSED" in modes}
            for car, modes in self._index.items()
        }

    def variants(self, crdb: str, kind: str = "DEFAULT", *, reversed: bool = False) -> Tuple[str, ...]:
        """All exact listed paths, in selection order; empty for an unlisted mode."""
        return self._index.get(_car(crdb), {}).get(_mode(kind, reversed), ())

    def available(self, crdb: str, kind: str = "DEFAULT", *, reversed: bool = False) -> bool:
        return bool(self.variants(crdb, kind, reversed=reversed))

    def snapshot_path(self, crdb: str, kind: str = "DEFAULT", *,
                      reversed: bool = False, strict: bool = False) -> str:
        """Choose an exact listed path, or construct an unverified stock path."""
        paths = self.variants(crdb, kind, reversed=reversed)
        if paths:
            return paths[0]
        mode = _mode(kind, reversed)
        prefix, suffix = self._templates.get(mode, (
            "Default/" if mode.startswith("DEFAULT") else "", f"{_FIELDS}_m{mode}.png",
        ))
        path = f"{prefix}{crdb}{suffix}"
        if strict:
            raise SnapshotNotFoundError(f"no listed {mode} snapshot for {crdb}", path=path)
        return path

    def url_for(self, path: str) -> str:
        """Join an exact, decoded relative path to the manifest's endpoint."""
        return self.base_url + "/" + quote(_path(path), safe="/")

    def snapshot_url(self, crdb: str, kind: str = "DEFAULT", **kwargs) -> str:
        return self.url_for(self.snapshot_path(crdb, kind, **kwargs))

    @property
    def session(self):
        if self._session is None:
            self._session = _http.build_session()
        return self._session

    def download(self, path: str) -> bytes:
        """Download an exact PNG path, including variants not selected by default."""
        url = self.url_for(path)
        response = None
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            body = response.content
            if not body.startswith(b"\x89PNG\r\n\x1a\n"):
                raise SnapshotError("snapshot response is not a PNG", path=path,
                                    status_code=response.status_code)
            return body
        except requests.RequestException as exc:
            raise SnapshotError(f"snapshot download failed: {path}: {exc}", path=path,
                                status_code=_http.status_of(exc)) from exc
        finally:
            if response is not None:
                response.close()

    def download_snapshot(self, crdb: str, kind: str = "DEFAULT", **kwargs) -> bytes:
        return self.download(self.snapshot_path(crdb, kind, **kwargs))

    def download_snapshot_to(self, crdb: str, destination, kind: str = "DEFAULT", **kwargs) -> Path:
        """Atomically save a selected PNG to an explicit output filename."""
        body = self.download_snapshot(crdb, kind, **kwargs)
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as out:
                temporary = Path(out.name)
                out.write(body)
            os.replace(temporary, target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return target

    def close(self) -> None:
        if self._session is not None and self._owns_session:
            self._session.close()
            self._session = None

    def __enter__(self) -> "SnapshotCDN":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
