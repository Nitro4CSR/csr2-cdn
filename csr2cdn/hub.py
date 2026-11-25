"""CSR2 HUB's repository-shaped CDN, independent of the game's CDN.

Paths are decoded, case-sensitive paths relative to the CDN root. No GitHub
requests or player account are needed. Unknown/new paths work through the
generic download and JSON/text methods without a package update.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Union
from urllib.parse import quote, urlsplit

import requests

from csr2cdn import _http
from csr2cdn.database import AssetDatabase
from csr2cdn.errors import Csr2CdnError

DEFAULT_HUB_BASE_URL = "https://v2cdn.csr2hub.space"
# Top-level folders of the v2 hub CDN (from its content-tree.json manifest).
HUB_CATEGORIES = (
    "App", "AssetDatabases", "Assets", "CAD", "CGD", "Configs", "CVD",
    "Gacha", "Icons", "Localisation", "NmgSvcs", "Snapshots", "SnapshotsEC",
    "SnapshotsFull", "SnapshotsFullV2", "SnapshotsGacha", "SnapshotsRC",
)
# Snapshot layouts: car PNGs. Branded ones live under <Brand>/<car>; the
# indexed ones under <car>/<index> (SnapshotsGacha adds the brand folder too).
HUB_SNAPSHOT_KINDS = (
    "Snapshots", "SnapshotsFull", "SnapshotsFullV2", "SnapshotsGacha",
    "SnapshotsRC", "SnapshotsEC",
)
#: Icon groups under ``Icons/``.
HUB_ICON_GROUPS = ("Cars", "Collections", "Manufacturers")
#: The root manifest that lists every folder and file (GitHub tree shape).
HUB_CONTENT_TREE = "content-tree.json"
# Car-name prefix -> brand folder, where the v2 CDN's folder differs from the
# prefix. Everything not listed uses the prefix as-is.
HUB_BRAND_MAP = {
    "MercedesBenz": "Mercedes", "MercedesAMG": "Mercedes",
    "MercedesAMGF1": "MercedesPetronas", "Abarth": "ABARTH",
    "GTA": "GTAMotor", "Indy": "Indycar",
}
# Internal category groups (path shapes).
_FLAT_CATEGORIES = frozenset({
    "AssetDatabases", "Assets", "CAD", "CGD", "CVD", "Configs", "NmgSvcs",
})
_BRANDED_SNAPSHOTS = {"Snapshots": ".png", "SnapshotsFull": ".png",
                      "SnapshotsFullV2": ".png", "Gacha": ".zip"}
_CAR_INDEXED = frozenset({"SnapshotsRC", "SnapshotsEC"})
HUB_SYNC_MANIFEST = ".csr2hub-sync.json"
PathLike = Union[str, "os.PathLike[str]"]


class HubError(Csr2CdnError):
    """A HUB request/response failed; HTTP errors retain their status code."""

    def __init__(self, message: str, *, path: str = "", status_code: Optional[int] = None):
        super().__init__(message)
        self.path = path
        self.status_code = status_code


class HubSyncResult(NamedTuple):
    downloaded: List[str]
    unchanged: List[str]
    failed: Dict[str, BaseException]

    @property
    def changed(self) -> bool:
        return bool(self.downloaded)


def _relative(path: str) -> str:
    if not isinstance(path, str) or not path or path.startswith("/"):
        raise ValueError("give a non-empty relative HUB path")
    if "\\" in path or ":" in path or any(ord(c) < 32 for c in path):
        raise ValueError("HUB paths must use forward slashes and contain no drive or URL")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise ValueError("HUB paths cannot contain empty, '.' or '..' components")
    return path


def _component(value: Any) -> str:
    value = _relative(str(value))
    if "/" in value:
        raise ValueError("expected one path component")
    return value


def _suffix(name: str, suffix: str) -> str:
    return name if name.endswith(suffix) else name + suffix


def _target(directory: PathLike, path: str) -> Path:
    root = Path(directory).expanduser().resolve()
    target = (root / _relative(path)).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError("download target escapes the output directory")
    return target


class HubCDN:
    """Read every HUB resource using its repository-relative path.

    The optional session supports proxies/authentication/custom headers. Owned
    sessions retry transient failures. HUB files can change at the same URL;
    ``sync_files`` therefore uses HTTP validators, not game asset versions.
    """

    def __init__(
        self, base_url: str = DEFAULT_HUB_BASE_URL, *, session: Optional[Any] = None,
        timeout: float = 30.0, retries: int = _http.DEFAULT_RETRIES,
        headers: Optional[Dict[str, str]] = None,
    ):
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("base_url must be an HTTP(S) root URL without query or fragment")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"User-Agent": "csr2-cdn/0.6.0", **(headers or {})}
        self._session = session
        self._owns_session = session is None
        self._retries = retries

    @property
    def session(self):
        if self._session is None:
            self._session = _http.build_session(retries=self._retries)
        return self._session

    def close(self) -> None:
        if self._session is not None and self._owns_session:
            self._session.close()
            self._session = None

    def __enter__(self) -> "HubCDN":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def url_for(self, path: str) -> str:
        """Encode a decoded relative path, preserving its case and slashes."""
        return self.base_url + "/" + quote(_relative(path), safe="/")

    def _brand_of(self, car: str) -> str:
        prefix = car.split("_", 1)[0]
        return HUB_BRAND_MAP.get(prefix, prefix)

    def path_for(
        self, category: str, name: str, *, manufacturer: Optional[str] = None,
        index: Optional[Union[str, int]] = None, group: Optional[str] = None,
    ) -> str:
        """Build a path in one of the v2 hub folders.

        * Flat folders (``AssetDatabases``, ``Assets``, ``CAD``, ``CGD``,
          ``CVD``, ``Configs``, ``NmgSvcs``) take an exact filename.
        * ``App`` takes the exact sub-path after ``App/``.
        * ``Icons`` takes a ``group`` (``Cars``/``Collections``/``Manufacturers``,
          default ``Cars``) and the exact icon filename.
        * ``Localisation`` takes a language code (``EN``) or a full ``.ASTC`` name.
        * Branded snapshots (``Snapshots``, ``SnapshotsFull``, ``SnapshotsFullV2``,
          ``Gacha``) place the car under its brand folder; pass ``manufacturer``
          to override the brand derived from the car name.
        * Indexed snapshots place the car in its own folder: ``SnapshotsRC`` and
          ``SnapshotsEC`` as ``<car>/<index>``, ``SnapshotsGacha`` as
          ``<brand>/<car>/<index>``. Indices are exact tokens (RC keeps ``'00'``).

        Use ``url_for``/``download`` directly for root files such as the manifest.
        """
        if category not in HUB_CATEGORIES:
            raise ValueError(f"unknown HUB category: {category}")
        name = _relative(name)
        branded = category in _BRANDED_SNAPSHOTS or category == "SnapshotsGacha"
        indexed = category in _CAR_INDEXED or category == "SnapshotsGacha"
        if manufacturer is not None and not branded:
            raise ValueError("manufacturer only applies to branded snapshot/Gacha paths")
        if index is not None and not indexed:
            raise ValueError("index only applies to SnapshotsRC/EC and SnapshotsGacha")
        if group is not None and category != "Icons":
            raise ValueError("group only applies to Icons")

        if category == "App":
            return "App/" + name
        if category == "Icons":
            grp = group or "Cars"
            if grp not in HUB_ICON_GROUPS:
                raise ValueError(f"unknown icon group: {grp}")
            return f"Icons/{grp}/{name}"
        if category == "Localisation":
            if name.endswith(".ASTC"):
                return f"Localisation/{_component(name)}"
            return f"Localisation/Localisation_{_component(name)}.ASTC"
        if category in _FLAT_CATEGORIES:
            return f"{category}/{_component(name)}"

        car = _component(name)
        brand = _component(manufacturer) if manufacturer is not None else self._brand_of(car)
        if category == "SnapshotsGacha":
            if index is None:
                raise ValueError("SnapshotsGacha requires an index")
            return f"SnapshotsGacha/{brand}/{car}/{_suffix(_component(index), '.png')}"
        if category in _CAR_INDEXED:
            if index is None:
                raise ValueError(f"{category} requires an index (preserve leading zeroes as a string)")
            return f"{category}/{car}/{_suffix(_component(index), '.png')}"
        # branded, non-indexed: Snapshots / SnapshotsFull / SnapshotsFullV2 / Gacha
        return f"{category}/{brand}/{_suffix(car, _BRANDED_SNAPSHOTS[category])}"

    def snapshot_path(
        self, car: str, kind: str = "Snapshots", *, manufacturer: Optional[str] = None,
        index: Optional[Union[str, int]] = None,
    ) -> str:
        if kind not in HUB_SNAPSHOT_KINDS:
            raise ValueError(f"unknown snapshot kind: {kind}")
        return self.path_for(kind, car, manufacturer=manufacturer, index=index)

    def snapshot_url(self, car: str, kind: str = "Snapshots", **kwargs) -> str:
        return self.url_for(self.snapshot_path(car, kind, **kwargs))

    def icon_path(self, name: str, group: str = "Cars") -> str:
        """Path to a hub icon, e.g. ``AMC_..._icon`` (Cars) or ``ABARTH_icon``
        (Manufacturers). Use the exact filename as it appears in the tree
        (``Collections`` icons end in ``_icon.png``, the others have no suffix)."""
        return self.path_for("Icons", _component(name), group=group)

    def _get(self, path: str, *, stream: bool = False, headers=None):
        url = self.url_for(path)
        response = None
        try:
            response = self.session.get(
                url, timeout=self.timeout, stream=stream, headers={**self.headers, **(headers or {})}
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            if response is not None:
                response.close()
            raise HubError(
                f"HUB request failed for {path}: {exc}", path=path,
                status_code=_http.status_of(exc),
            ) from exc

    def download(self, path: str) -> bytes:
        """Fetch bytes without interpreting bundles, images, ZIPs or documents."""
        response = self._get(path)
        try:
            return response.content
        finally:
            response.close()

    def get_text(self, path: str, encoding: str = "utf-8-sig") -> str:
        try:
            return self.download(path).decode(encoding)
        except UnicodeError as exc:
            raise HubError(f"HUB resource is not {encoding} text: {path}", path=path) from exc

    def get_json(self, path: str) -> Any:
        try:
            return json.loads(self.get_text(path))
        except ValueError as exc:
            raise HubError(f"HUB resource is not valid JSON: {path}", path=path) from exc

    def database_version(self) -> str:
        version = self.get_text("AssetDatabases/last.ver").strip()
        if not re.fullmatch(r"[0-9]+", version):
            raise HubError("invalid HUB database version pointer", path="AssetDatabases/last.ver")
        return version

    def get_database(self, version: Optional[Union[str, int]] = None) -> AssetDatabase:
        """Load a HUB database into the package's existing AssetDatabase model."""
        version = self.database_version() if version is None else _component(version)
        return AssetDatabase.from_json(self.get_json(f"AssetDatabases/{version}"))

    def get_config(self, name: str) -> Any:
        """A JSON config file from ``Configs/`` (e.g. ``AppScript_Cars``)."""
        return self.get_json(self.path_for("Configs", _suffix(name, ".json")))

    def get_nmgsvc(self, name: str) -> Any:
        """A JSON service file from ``NmgSvcs/`` (e.g. ``AIDriverNames``)."""
        return self.get_json(self.path_for("NmgSvcs", _suffix(name, ".json")))

    def get_localisation(self, language: str) -> bytes:
        """The localisation ``.ASTC`` bundle for a language code (e.g. ``EN``).

        The v2 hub ships localisation as binary ``.ASTC`` bundles, not JSON, so
        this returns bytes.
        """
        return self.download(self.path_for("Localisation", language))

    def content_tree(self) -> Any:
        """The full ``content-tree.json`` manifest (GitHub tree shape).

        A dict with ``sha``, ``truncated`` and ``tree`` -- a flat list of every
        file and folder, each an entry with ``path``, ``type`` (``blob``/
        ``tree``), ``size`` and ``sha``. This is the v2 hub's index; there is no
        ``version-control.json`` / ``release-history.json`` on this host.
        """
        return self.get_json(HUB_CONTENT_TREE)

    def tree_entries(self) -> List[Dict[str, Any]]:
        """The flat list of entries from :meth:`content_tree`."""
        tree = self.content_tree()
        entries = tree.get("tree") if isinstance(tree, dict) else None
        if not isinstance(entries, list):
            raise HubError("content-tree.json has no 'tree' list", path=HUB_CONTENT_TREE)
        return entries

    def list_dir(self, prefix: str = "") -> List[Dict[str, Any]]:
        """Immediate children (files and folders) under ``prefix``, like the UI.

        ``prefix`` is a folder path without a trailing slash (``""`` for the
        root, ``"Snapshots"``, ``"Icons/Cars"``). Each child is
        ``{"name", "path", "type"}`` with ``type`` ``"tree"`` or ``"blob"``,
        plus ``size`` for files.
        """
        base = (_relative(prefix) + "/") if prefix else ""
        seen: Dict[str, Dict[str, Any]] = {}
        for e in self.tree_entries():
            path = e.get("path", "")
            if base and not path.startswith(base):
                continue
            rest = path[len(base):]
            if not rest:
                continue
            if "/" in rest:
                # a deeper descendant: record its immediate child folder
                top = rest.split("/", 1)[0]
                seen.setdefault(top, {"name": top, "path": base + top, "type": "tree"})
                continue
            child = {"name": rest, "path": path, "type": e.get("type", "blob")}
            if e.get("size") is not None:
                child["size"] = e.get("size")
            seen[rest] = child   # an explicit entry overrides an inferred folder
        return [seen[k] for k in sorted(seen)]

    def find(self, substring: str) -> List[str]:
        """Every file path in the manifest that contains ``substring``."""
        needle = substring
        return [e["path"] for e in self.tree_entries()
                if e.get("type") == "blob" and needle in e.get("path", "")]

    @staticmethod
    def _write_response(response, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as out:
                temporary = Path(out.name)
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        out.write(chunk)
            os.replace(temporary, target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def download_to(self, path: str, directory: PathLike, *, preserve_paths: bool = True) -> Path:
        """Atomically write a resource, keeping its repository directories by default."""
        _relative(path)
        target = _target(directory, path if preserve_paths else path.rsplit("/", 1)[-1])
        response = self._get(path, stream=True)
        try:
            self._write_response(response, target)
        except requests.RequestException as exc:
            raise HubError(f"HUB download interrupted: {path}: {exc}", path=path) from exc
        finally:
            response.close()
        return target

    def download_snapshot(self, car: str, kind: str = "Snapshots", **kwargs) -> bytes:
        return self.download(self.snapshot_path(car, kind, **kwargs))

    def download_icon(self, name: str, group: str = "Cars") -> bytes:
        return self.download(self.icon_path(name, group))

    def download_files(self, paths: Iterable[str], directory: PathLike, *, workers: int = 8) -> Dict:
        """Download a batch; each value is a Path or the failure for that resource."""
        paths = list(dict.fromkeys(paths))
        # Create the shared session before workers start.
        self.session

        def fetch(path):
            try:
                return path, self.download_to(path, directory)
            except Exception as exc:
                return path, exc

        with ThreadPoolExecutor(max_workers=workers) as pool:
            return dict(pool.map(fetch, paths))

    def sync_files(self, paths: Iterable[str], directory: PathLike, *, force: bool = False) -> HubSyncResult:
        """Refresh mutable resources with ETag/Last-Modified conditional requests.

        No validators means a fresh download each time. Missing/size-changed
        local files are refetched. Failed resources retain their old files and
        validators and are retried next time. Unselected files are retained.
        Do not run simultaneous syncs against the same directory.
        """
        manifest_path = _target(directory, HUB_SYNC_MANIFEST)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        if not isinstance(manifest, dict) or manifest.get("base_url") != self.base_url:
            manifest = {}
        entries = manifest.get("files", {})
        if not isinstance(entries, dict):
            entries = {}
        result = HubSyncResult([], [], {})
        for path in dict.fromkeys(paths):
            response = None
            try:
                if path == HUB_SYNC_MANIFEST:
                    raise ValueError("resource path conflicts with the HUB sync manifest")
                target = _target(directory, path)
                previous = entries.get(path, {})
                if not isinstance(previous, dict):
                    previous = {}
                headers = {}
                if not force and target.is_file() and target.stat().st_size == previous.get("size"):
                    if previous.get("etag"):
                        headers["If-None-Match"] = previous["etag"]
                    if previous.get("last_modified"):
                        headers["If-Modified-Since"] = previous["last_modified"]
                response = self._get(path, stream=True, headers=headers)
                if response.status_code == 304:
                    if not headers or not target.is_file():
                        raise HubError(f"unexpected 304 for {path}", path=path, status_code=304)
                    result.unchanged.append(path)
                    continue
                self._write_response(response, target)
                entries[path] = {
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "size": target.stat().st_size,
                }
                result.downloaded.append(path)
            except Exception as exc:
                result.failed[path] = exc
            finally:
                if response is not None:
                    response.close()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=manifest_path.parent, suffix=".part", delete=False
            ) as out:
                temporary = Path(out.name)
                json.dump({"base_url": self.base_url, "files": entries}, out, indent=2)
            os.replace(temporary, manifest_path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return result

    def export_images(self, path: str, directory: PathLike) -> List[Path]:
        """Extract Texture2D/Sprite images from any HUB Unity bundle as PNGs.

        Requires the optional ``csr2-cdn[images]`` extra. Direct PNG/JPEG files
        are saved unchanged. The raw bundle stays in memory, never on disk.
        """
        if path.lower().endswith((".png", ".jpg", ".jpeg")):
            return [self.download_to(path, directory)]
        try:
            import UnityPy
        except ImportError as exc:
            raise HubError("image extraction requires pip install 'csr2-cdn[images]'") from exc
        payload = self.download(path)
        targets = []
        try:
            env = UnityPy.load(payload)
            for index, obj in enumerate(env.objects):
                if obj.type.name not in ("Texture2D", "Sprite"):
                    continue
                target = _target(directory, f"{path}/{index}.png")
                target.parent.mkdir(parents=True, exist_ok=True)
                obj.read().image.save(target)
                targets.append(target)
        except Exception as exc:
            raise HubError(f"image extraction failed for {path}: {exc}", path=path) from exc
        if not targets:
            raise HubError(f"no Texture2D or Sprite images in {path}", path=path)
        return targets


__all__ = [
    "DEFAULT_HUB_BASE_URL", "HUB_CATEGORIES", "HUB_SNAPSHOT_KINDS",
    "HUB_ICON_GROUPS", "HUB_CONTENT_TREE", "HUB_BRAND_MAP", "HUB_SYNC_MANIFEST",
    "HubCDN", "HubError", "HubSyncResult",
]
