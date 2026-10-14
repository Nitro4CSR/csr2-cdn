"""Client for the asset CDN.

Three kinds of file live there:

===========================================  ===========================================
what                                         path
===========================================  ===========================================
branch pointer                               ``/asset_database_{branch}.version``
asset database                               ``/asset_database.{database_version}.json``
asset bundle                                 ``/{platform}/{quality}/{code}.{quality}.{version}``
===========================================  ===========================================

The bundle name comes from ``AssetDirectory.GetBundleFilename``, which builds
``{code}.{quality}.{version}``. Quality is one of the ``AssetQuality`` enum
values; the database only reports ``High`` and ``ASTC`` sizes.

:class:`CDN` also ties the discovery chain together. Nothing about the current
game version is hard coded: the store gives the app version, that gives the base
branch, that gives ``product_version``, and that lets the metadata service
announce the current branch. Give it a ``zid`` and it can do all of it::

    cdn = CDN(zid="94866657860")
    cdn.branch             # '6_7_0_Release_OTA_1'
    cdn.product_version    # '6.7.81'
    cdn.download_asset("CarPaintLibrary")
    cdn.get_metadata("CarFusionProfileData")

Every step can be short circuited by passing ``branch``, ``product_version`` or
``release_version`` to the constructor.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from csr2cdn import _http
from csr2cdn.database import DEFAULT_QUALITY, Asset, AssetDatabase
from csr2cdn.errors import AssetNotFoundError, BranchNotFoundError, Csr2CdnError, MissingZidError
from csr2cdn.metadata import MetadataBlock, MetadataCache, MetadataClient
from csr2cdn.store import APP_STORE_ID, PACKAGE_ID, AppIds, normalize_release

DEFAULT_BASE_URL = "https://csr2.cdn.zynga.com"
DEFAULT_PLATFORM = "ANDROID"
DEFAULT_USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 13; SM-G991B Build/TP1A.220624.014)"

PathLike = Union[str, "os.PathLike[str]"]
AssetRef = Union[Asset, str, Tuple[str, Any]]

#: Name of the manifest :meth:`CDN.sync_assets` keeps in the target directory.
SYNC_MANIFEST = ".csr2cdn-sync.json"


class SyncResult(NamedTuple):
    """What :meth:`CDN.sync_assets` did."""

    downloaded: List[str]
    unchanged: List[str]
    failed: Dict[str, BaseException]
    removed: List[str]
    database: AssetDatabase

    @property
    def changed(self) -> bool:
        return bool(self.downloaded or self.removed)

    def __repr__(self) -> str:
        return (
            f"<SyncResult downloaded={len(self.downloaded)} unchanged={len(self.unchanged)} "
            f"failed={len(self.failed)} removed={len(self.removed)}>"
        )


class CDN:
    """Reads branch versions, asset databases, asset bundles and metadata."""

    def __init__(
        self,
        zid: Optional[str] = None,
        branch: Optional[str] = None,
        product_version: Optional[str] = None,
        release_version: Optional[str] = None,
        allow_preemptive: bool = True,
        probe: bool = False,
        package_id: str = PACKAGE_ID,
        app_store_id: str = APP_STORE_ID,
        base_url: str = DEFAULT_BASE_URL,
        session: Optional[Any] = None,
        timeout: float = 30.0,
        platform: str = DEFAULT_PLATFORM,
        quality: str = DEFAULT_QUALITY,
        user_agent: str = DEFAULT_USER_AGENT,
        metadata: Optional[MetadataClient] = None,
        cache_dir: Optional[PathLike] = None,
        version_ttl: float = 300.0,
        retries: int = _http.DEFAULT_RETRIES,
    ):
        """
        :param zid: your player id. Attaching it here makes
            :meth:`get_metadata` and branch resolution work without repeating it.
        :param branch: skip branch discovery and use this branch.
        :param product_version: skip the bootstrap and use this product version.
        :param release_version: skip the store lookup and use this app version.
        :param allow_preemptive: let a staged preemptive branch win when it is
            announced and newer.
        :param probe: also ask the CDN about plausible successor branches, which
            finds a branch that is uploaded but not yet announced, and lets
            branch discovery work without a zid at all.
        :param cache_dir: keep downloaded databases here. Database URLs are
            immutable, so a cached database is never stale and a repeat run
            costs nothing. ``.version`` lookups are cached for *version_ttl*
            seconds, which also makes repeated probing cheap.
        :param retries: transient failures retried per request, with backoff.
        :param version_ttl: lifetime of branch version lookups in seconds;
            zero or a negative value disables reuse of those cached lookups.
        """
        self.zid = str(zid) if zid is not None else None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.platform = platform
        self.quality = quality
        self.user_agent = user_agent
        self.allow_preemptive = allow_preemptive
        self.probe = probe
        self.app = AppIds(package_id=package_id, app_store_id=app_store_id)
        self._session = session
        self._owns_session = session is None
        self._retries = retries
        self._metadata = metadata
        self.cache_dir = os.fspath(cache_dir) if cache_dir else None
        self.version_ttl = version_ttl
        self._branch = branch
        self._product_version = str(product_version) if product_version else None
        self._release_version = str(release_version) if release_version else None
        self._base_branch: Optional[str] = None
        self._database: Optional[AssetDatabase] = None

    # -- plumbing ---------------------------------------------------------
    @property
    def session(self):
        if self._session is None:
            self._session = _http.build_session(retries=self._retries)
        return self._session

    @property
    def metadata(self) -> MetadataClient:
        """The metadata client, sharing this client's session."""
        if self._metadata is None:
            self._metadata = MetadataClient(session=self.session, timeout=self.timeout)
        return self._metadata

    def close(self) -> None:
        if self._session is not None and self._owns_session:
            self._session.close()
            self._session = None

    def __enter__(self) -> "CDN":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _get(self, url: str, stream: bool = False):
        kwargs: Dict[str, Any] = {"headers": {"User-Agent": self.user_agent}, "timeout": self.timeout}
        if stream:
            kwargs["stream"] = True
        response = self.session.get(url, **kwargs)
        response.raise_for_status()
        return response

    # -- cache ------------------------------------------------------------
    def _cache_path(self, kind: str, name: str) -> Optional[str]:
        if not self.cache_dir:
            return None
        directory = os.path.join(self.cache_dir, kind)
        os.makedirs(directory, exist_ok=True)
        return os.path.join(directory, name)

    def _read_cache(self, kind: str, name: str, ttl: Optional[float] = None) -> Optional[Any]:
        path = self._cache_path(kind, name)
        if not path or not os.path.exists(path):
            return None
        if ttl is not None and (ttl <= 0 or (time.time() - os.path.getmtime(path)) >= ttl):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None

    def _write_cache(self, kind: str, name: str, payload: Any) -> None:
        path = self._cache_path(kind, name)
        if not path:
            return
        temporary = f"{path}.part"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
            os.replace(temporary, path)
        except OSError:
            pass

    def clear_cache(self) -> None:
        """Delete everything under ``cache_dir``."""
        if not self.cache_dir or not os.path.isdir(self.cache_dir):
            return
        import shutil

        shutil.rmtree(self.cache_dir, ignore_errors=True)

    def _require_zid(self, zid: Optional[str]) -> str:
        resolved = str(zid) if zid is not None else self.zid
        if not resolved:
            raise MissingZidError(
                "a zid is required; pass zid= to this call or attach one with CDN(zid=...)"
            )
        return resolved

    def refresh(self) -> None:
        """Forget the resolved branch, product version and cached database."""
        self._branch = None
        self._product_version = None
        self._base_branch = None
        self._database = None

    # -- urls -------------------------------------------------------------
    def version_url(self, branch: str) -> str:
        return f"{self.base_url}/asset_database_{branch}.version"

    def database_url(self, database_version: Union[str, int]) -> str:
        return f"{self.base_url}/asset_database.{database_version}.json"

    def asset_url(
        self,
        code: str,
        version: Union[str, int],
        platform: Optional[str] = None,
        quality: Optional[str] = None,
    ) -> str:
        platform = platform or self.platform
        quality = quality or self.quality
        return f"{self.base_url}/{platform}/{quality}/{code}.{quality}.{version}"

    def url_for(
        self,
        asset: AssetRef,
        version: Optional[Union[str, int]] = None,
        platform: Optional[str] = None,
        quality: Optional[str] = None,
    ) -> str:
        """URL for an :class:`~csr2cdn.database.Asset`, a ``(code, version)`` pair or a code."""
        code, resolved = self._split_ref(asset, version)
        return self.asset_url(code, resolved, platform=platform, quality=quality)

    # -- discovery --------------------------------------------------------
    @property
    def package_id(self) -> str:
        return self.app.package_id

    def store_version(self, refresh: bool = False, strategy: str = "first") -> str:
        """The newest app version published in a store, e.g. ``"6.7.1"``.

        Costs one Play request in the normal case. ``strategy="max"`` asks every
        source and takes the highest, trading latency for an earlier signal.
        """
        if self._release_version is None or refresh:
            from csr2cdn.store import latest_store_version

            self._release_version = latest_store_version(
                self.app, session=self.session, timeout=self.timeout, strategy=strategy
            )
        return self._release_version

    def store_versions(self) -> Dict[str, Optional[str]]:
        """What each store source reports, for working out why discovery went wrong."""
        from csr2cdn.store import store_versions

        return store_versions(self.app, session=self.session, timeout=self.timeout)

    @property
    def release_version(self) -> str:
        """The store version with the patch component dropped, e.g. ``"6.7.0"``."""
        return normalize_release(self.store_version())

    @property
    def base_branch(self) -> str:
        """The release branch the bootstrap reads ``product_version`` from."""
        if self._base_branch is None:
            from csr2cdn.branches import base_branch_candidates

            candidates = base_branch_candidates(
                release_version=self.store_version(),
                app=self.app,
                session=self.session,
                timeout=self.timeout,
            )
            for candidate in candidates:
                if self.try_database_version(candidate) is not None:
                    self._base_branch = candidate
                    break
            else:
                raise BranchNotFoundError(
                    f"none of the release branches {candidates!r} exist on the CDN; "
                    "pass branch= or product_version= to skip the bootstrap"
                )
        return self._base_branch

    @property
    def product_version(self) -> str:
        """The data product version, e.g. ``"6.7.81"``.

        Read from the base release branch's database header, since it is not the
        same as the app version the store reports.
        """
        if self._product_version is None:
            info = self.version_info(self.base_branch)
            found = info.get("product_version")
            if not found:
                database = self.get_database(version=info["version"])
                found = database.product_version
            if not found:
                raise Csr2CdnError(
                    "could not read product_version from the base branch; pass product_version="
                )
            self._product_version = str(found)
        return self._product_version

    def resolve_branch(
        self,
        zid: Optional[str] = None,
        allow_preemptive: Optional[bool] = None,
        fallback: Optional[Iterable[str]] = None,
        verify: bool = True,
        probe: Optional[bool] = None,
        probe_options: Optional[Dict[str, int]] = None,
        refresh: bool = False,
    ) -> str:
        """Work out which branch to use, and remember it.

        With a zid the metadata service is asked what it announces. With
        ``probe=True`` the CDN is also asked about plausible successor branches,
        which works with no zid at all and finds branches that are uploaded
        before they are announced.
        """
        if self._branch is not None and not refresh:
            return self._branch
        from csr2cdn.branches import resolve_branch

        probing = self.probe if probe is None else probe
        resolved_zid = str(zid) if zid is not None else self.zid
        if not resolved_zid and not probing:
            raise MissingZidError(
                "branch discovery needs a zid; pass zid=, attach one with CDN(zid=...), "
                "or use probe=True to discover the branch from the CDN alone"
            )
        fallbacks = list(fallback or ())
        try:
            fallbacks.append(self.base_branch)
        except Csr2CdnError:
            if not fallbacks:
                raise
        self._branch = resolve_branch(
            zid=resolved_zid,
            product_version=self.product_version if resolved_zid else None,
            cdn=self,
            metadata=self.metadata,
            allow_preemptive=self.allow_preemptive if allow_preemptive is None else allow_preemptive,
            fallback=fallbacks,
            verify=verify,
            probe=probing,
            probe_options=probe_options,
        )
        return self._branch

    def probe_branches(
        self,
        branch: Optional[str] = None,
        allow_preemptive: Optional[bool] = None,
        **depths: int,
    ) -> Dict[str, int]:
        """Which successors of *branch* exist on the CDN, mapped to their version.

        Defaults to probing from the base release branch, so this works without
        a zid::

            cdn.probe_branches()        # {'6_7_0_Release': 31146, '6_7_0_Release_OTA_1': 31951}
        """
        from csr2cdn.branches import probe_branches

        return probe_branches(
            self,
            branch or self._branch or self.base_branch,
            allow_preemptive=self.allow_preemptive if allow_preemptive is None else allow_preemptive,
            **depths,
        )

    @property
    def branch(self) -> str:
        """The branch this client works against, resolving it if necessary."""
        return self.resolve_branch()

    def branch_names(self, zid: Optional[str] = None):
        """Both branch names the metadata service currently announces."""
        from csr2cdn.branches import branch_names

        return branch_names(self._require_zid(zid), self.product_version, metadata=self.metadata)

    # -- versions ---------------------------------------------------------
    def version_info(self, branch: Optional[str] = None, refresh: bool = False) -> Dict[str, Any]:
        """The parsed ``.version`` document for *branch*."""
        name = branch or self.branch
        if not refresh:
            cached = self._read_cache("versions", f"{name}.json", ttl=self.version_ttl)
            if cached is not None:
                return cached
        document = self._get(self.version_url(name)).json()
        self._write_cache("versions", f"{name}.json", document)
        return document

    def database_version(self, branch: Optional[str] = None) -> str:
        """The current asset database version for *branch*."""
        return str(self.version_info(branch)["version"])

    def try_database_version(self, branch: str, strict: bool = True) -> Optional[str]:
        """Like :meth:`database_version` but ``None`` when the branch isn't there.

        Only a "not found" answer becomes ``None``. A connection failure or a
        500 is raised, because treating it as "branch missing" would quietly
        push branch discovery onto the wrong branch. Pass ``strict=False`` to
        swallow those too.
        """
        try:
            return self.database_version(branch)
        except Exception as exc:  # noqa: BLE001 - re-raised unless it means "missing"
            if _http.is_missing(exc) or not strict:
                return None
            raise

    def branch_exists(self, branch: str) -> bool:
        return self.try_database_version(branch) is not None

    # -- databases --------------------------------------------------------
    def get_database(
        self,
        version: Optional[Union[str, int]] = None,
        branch: Optional[str] = None,
    ) -> AssetDatabase:
        """Download an asset database by version or by branch.

        Give one or the other, never both. With neither, the client's own branch
        is used, resolving it if necessary.
        """
        if version is not None and branch is not None:
            raise ValueError("give version= or branch=, not both")
        if version is None:
            version = self.database_version(branch)
        cached = self._read_cache("databases", f"asset_database.{version}.json")
        if cached is not None:
            return AssetDatabase.from_json(cached)
        document = self._get(self.database_url(version)).json()
        self._write_cache("databases", f"asset_database.{version}.json", document)
        return AssetDatabase.from_json(document)

    @property
    def database(self) -> AssetDatabase:
        """The current database for this client's branch, downloaded once."""
        if self._database is None:
            self._database = self.get_database()
        return self._database

    def use_database(self, database: AssetDatabase) -> AssetDatabase:
        """Attach an already loaded database, so asset lookups skip the download."""
        self._database = database
        if database.branch_name and self._branch is None:
            self._branch = str(database.branch_name)
        return database

    def download_database(
        self,
        path: PathLike,
        version: Optional[Union[str, int]] = None,
        branch: Optional[str] = None,
    ) -> str:
        """Download a database straight to *path*, unparsed."""
        if version is not None and branch is not None:
            raise ValueError("give version= or branch=, not both")
        if version is None:
            version = self.database_version(branch)
        response = self._get(self.database_url(version))
        with open(path, "wb") as handle:
            handle.write(response.content)
        return os.fspath(path)

    # -- assets -----------------------------------------------------------
    def find_asset(self, code: str) -> Asset:
        """Look a code or alias up in the current database."""
        asset = self.database.assets.get(code)
        if asset is None:
            raise AssetNotFoundError(
                f"no asset named {code!r} in database {self.database.version} "
                f"(branch {self.database.branch_name})"
            )
        return asset

    def download_asset(
        self,
        asset: AssetRef,
        version: Optional[Union[str, int]] = None,
        platform: Optional[str] = None,
        quality: Optional[str] = None,
    ) -> bytes:
        """Download one asset bundle and return its bytes.

        *asset* may be an :class:`~csr2cdn.database.Asset`, a code or alias, or a
        ``(code, version)`` pair. With a bare name and no *version*, the version
        is looked up in the current database.
        """
        return self._get(self.url_for(asset, version, platform, quality)).content

    def download_asset_to(
        self,
        asset: AssetRef,
        path: PathLike,
        version: Optional[Union[str, int]] = None,
        platform: Optional[str] = None,
        quality: Optional[str] = None,
        skip_existing: bool = False,
        chunk_size: int = 1 << 16,
    ) -> str:
        """Download one asset bundle to *path*, which may be a directory.

        The body is streamed to a ``.part`` file and renamed into place, so an
        interrupted download never leaves a half written bundle behind. With
        *skip_existing* an already complete file is left alone; completeness is
        checked against the size the database reports when that is known.
        """
        code, resolved = self._split_ref(asset, version)
        quality = quality or self.quality
        target = os.fspath(path)
        if os.path.isdir(target):
            target = os.path.join(target, f"{code}.{quality}.{resolved}")
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if skip_existing and self._looks_complete(target, asset, quality):
            return target

        temporary = f"{target}.part"
        response = self._get(self.asset_url(code, resolved, platform, quality), stream=True)
        try:
            with open(temporary, "wb") as handle:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        handle.write(chunk)
        finally:
            response.close()
        os.replace(temporary, target)
        return target

    def _looks_complete(self, target: str, asset: AssetRef, quality: str) -> bool:
        if not os.path.exists(target):
            return False
        expected = asset.size(quality) if isinstance(asset, Asset) else 0
        return expected <= 0 or os.path.getsize(target) == expected

    def download_assets(
        self,
        assets: Sequence[AssetRef],
        directory: PathLike,
        platform: Optional[str] = None,
        quality: Optional[str] = None,
        workers: int = 8,
        on_done: Optional[Any] = None,
        skip_existing: bool = False,
    ) -> Dict[str, Union[str, BaseException]]:
        """Download many assets into *directory* using a thread pool.

        Returns a mapping of asset code to the written path, or to the exception
        raised for that asset. Nothing is raised for individual failures, so one
        bad asset does not lose the rest of the batch.
        """
        os.makedirs(os.fspath(directory), exist_ok=True)
        # Keep the Asset objects where we have them, so sizes are available, but
        # resolve versions up front so the pool does not race on the lazy database.
        prepared: List[AssetRef] = [
            ref if isinstance(ref, Asset) else self._split_ref(ref, None) for ref in assets
        ]
        results: Dict[str, Union[str, BaseException]] = {}

        def _one(ref: AssetRef) -> Tuple[str, Union[str, BaseException]]:
            code = ref.code if isinstance(ref, Asset) else ref[0]
            try:
                return code, self.download_asset_to(
                    ref, directory, None, platform, quality, skip_existing=skip_existing
                )
            except BaseException as exc:  # noqa: BLE001 - reported per asset
                return code, exc

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for code, outcome in pool.map(_one, prepared):
                results[code] = outcome
                if on_done is not None:
                    on_done(code, outcome)
        return results

    def sync_assets(
        self,
        directory: PathLike,
        assets: Optional[Iterable[AssetRef]] = None,
        search: Optional[str] = None,
        asset_type: Optional[Union[str, int]] = None,
        with_dependencies: bool = False,
        platform: Optional[str] = None,
        quality: Optional[str] = None,
        workers: int = 8,
        remove_stale: bool = False,
        name_for: Optional[Callable[[Asset], str]] = None,
        on_done: Optional[Any] = None,
    ) -> SyncResult:
        """Bring *directory* up to date with the current database.

        Only assets whose version changed since the last sync are downloaded.
        The versions are kept in a small manifest in the directory itself, so
        this is stateless from your side and safe to run on a timer::

            result = cdn.sync_assets("./assets", search="CarPaintLibrary")
            if result.changed:
                rebuild_whatever_uses(result.downloaded)

        :param assets: what to sync; defaults to the whole database. Combine
            with *search* and *asset_type* to narrow it down.
        :param remove_stale: delete files for assets that left the selection or
            the database.
        :param name_for: name the files yourself, e.g.
            ``lambda a: a.code.replace("TunerStars", "TNR")``. Defaults to the
            client's own ``{code}.{quality}.{version}``.
        """
        directory = os.fspath(directory)
        os.makedirs(directory, exist_ok=True)
        quality = quality or self.quality
        database = self.database

        selected = list(assets) if assets is not None else list(database.assets)
        resolved: List[Asset] = []
        for item in selected:
            resolved.append(item if isinstance(item, Asset) else self.find_asset(
                item[0] if isinstance(item, tuple) else item
            ))
        if search:
            needle = search.lower()
            resolved = [a for a in resolved if needle in a.code.lower()]
        if asset_type is not None:
            resolved = [a for a in resolved if str(a.type) == str(asset_type)]
        if with_dependencies:
            seen, expanded = set(), []
            for asset in resolved:
                for item in asset.walk_dependencies(include_self=True):
                    if item.code.lower() not in seen:
                        seen.add(item.code.lower())
                        expanded.append(item)
            resolved = expanded

        namer = name_for or (lambda asset: asset.filename(quality))
        manifest_path = os.path.join(directory, SYNC_MANIFEST)
        manifest = self._read_manifest(manifest_path)
        entries = manifest.get("assets", {})

        stale: List[str] = []
        wanted = {asset.code: asset for asset in resolved}
        if remove_stale:
            for code, entry in list(entries.items()):
                if code in wanted:
                    continue
                old = os.path.join(directory, entry.get("file", ""))
                if entry.get("file") and os.path.exists(old):
                    os.remove(old)
                entries.pop(code, None)
                stale.append(code)

        outstanding: List[Asset] = []
        unchanged: List[str] = []
        for asset in resolved:
            entry = entries.get(asset.code)
            target = os.path.join(directory, namer(asset))
            if entry and str(entry.get("version")) == str(asset.version) and os.path.exists(target):
                unchanged.append(asset.code)
            else:
                outstanding.append(asset)

        downloaded: List[str] = []
        failed: Dict[str, BaseException] = {}

        def _one(asset: Asset) -> Tuple[Asset, Union[str, BaseException]]:
            target = os.path.join(directory, namer(asset))
            try:
                return asset, self.download_asset_to(
                    asset, target, None, platform, quality, skip_existing=False
                )
            except BaseException as exc:  # noqa: BLE001 - reported per asset
                return asset, exc

        if outstanding:
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                for asset, outcome in pool.map(_one, outstanding):
                    if isinstance(outcome, BaseException):
                        failed[asset.code] = outcome
                    else:
                        downloaded.append(asset.code)
                        old = entries.get(asset.code, {}).get("file")
                        new = os.path.relpath(outcome, directory)
                        if old and old != new:
                            previous = os.path.join(directory, old)
                            if os.path.exists(previous):
                                os.remove(previous)
                        entries[asset.code] = {"version": str(asset.version), "file": new}
                    if on_done is not None:
                        on_done(asset.code, outcome)

        self._write_manifest(
            manifest_path,
            {
                "branch": database.branch_name,
                "database_version": database.version,
                "quality": quality,
                "platform": platform or self.platform,
                "assets": entries,
            },
        )
        return SyncResult(downloaded, unchanged, failed, stale, database)

    @staticmethod
    def _read_manifest(path: str) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _write_manifest(path: str, payload: Dict[str, Any]) -> None:
        temporary = f"{path}.part"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(temporary, path)

    # -- metadata ---------------------------------------------------------
    def get_snapshots(self, zid: Optional[str] = None,
                      product_version: Optional[str] = None, *, staging: bool = False):
        """Fetch CDNSnapshots and return a SnapshotCDN sharing this session.

        Each call refreshes the catalogue. Keep the returned client to reuse
        it; no asset database or branch lookup is needed with product_version.
        """
        from csr2cdn.snapshots import SnapshotCDN

        return SnapshotCDN.from_metadata(
            self._require_zid(zid), product_version or self.product_version,
            client=self.metadata, staging=staging, session=self.session, timeout=self.timeout,
        )

    def get_metadata(
        self,
        *names: str,
        zid: Optional[str] = None,
        product_version: Optional[str] = None,
        hashes: Optional[Dict[str, str]] = None,
    ) -> Dict[str, MetadataBlock]:
        """Fetch metadata blocks by name.

        The zid comes from ``CDN(zid=...)`` unless given here, and the product
        version is resolved automatically::

            cdn.get_metadata("CarFusionProfileData", "CollectionSlots")
        """
        wanted: List[str] = []
        for name in names:
            if isinstance(name, str):
                wanted.append(name)
            else:
                wanted.extend(name)
        return self.metadata.get(
            wanted,
            zid=self._require_zid(zid),
            product_version=product_version or self.product_version,
            hashes=hashes,
        )

    def get_metadata_one(
        self,
        name: str,
        zid: Optional[str] = None,
        product_version: Optional[str] = None,
        hashes: Optional[Dict[str, str]] = None,
    ) -> Optional[MetadataBlock]:
        """One block, or ``None`` when the service considers you current on it."""
        return self.get_metadata(
            name, zid=zid, product_version=product_version, hashes=hashes
        ).get(name)

    def metadata_cache(
        self,
        directory: PathLike,
        zid: Optional[str] = None,
        product_version: Optional[str] = None,
    ) -> MetadataCache:
        """A :class:`~csr2cdn.metadata.MetadataCache` wired to this client.

        Hash bookkeeping and file writing are handled for you::

            cache = cdn.metadata_cache("./metadata")
            cache.sync(["CarFusionProfileData", "CollectionSlots"])
        """
        return MetadataCache(
            directory,
            zid=self._require_zid(zid),
            product_version=product_version or self.product_version,
            client=self.metadata,
        )

    def killswitches(self, zid: Optional[str] = None) -> Dict[str, Any]:
        """The ``FeatureKillswitches`` block, unwrapped."""
        return self.metadata.killswitches(self._require_zid(zid), self.product_version)

    # -- internals --------------------------------------------------------
    def _split_ref(self, asset: AssetRef, version: Optional[Union[str, int]]) -> Tuple[str, Any]:
        if isinstance(asset, Asset):
            return asset.code, asset.version if version is None else str(version)
        if isinstance(asset, tuple):
            code, asset_version = asset
            return code, str(asset_version) if version is None else str(version)
        if version is not None:
            return asset, str(version)
        found = self.find_asset(asset)
        return found.code, found.version

    def __repr__(self) -> str:
        return (
            f"<CDN {self.base_url} branch={self._branch or '?'} "
            f"platform={self.platform} quality={self.quality}>"
        )


__all__ = [
    "CDN",
    "DEFAULT_BASE_URL",
    "DEFAULT_PLATFORM",
    "SYNC_MANIFEST",
    "AssetRef",
    "SyncResult",
]
