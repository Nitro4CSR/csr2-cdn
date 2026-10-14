"""``csr2cdn`` command line interface.

::

    csr2cdn --zid 948... branch
    csr2cdn --zid 948... release
    csr2cdn version --branch 6_7_0_Release_OTA_1
    csr2cdn --zid 948... database --output db.json
    csr2cdn assets db.json --search Lamborghini
    csr2cdn --zid 948... download --code CarPaintLibrary --output ./bundles
    csr2cdn --zid 948... metadata CarFusionProfileData --output ./meta
    csr2cdn stubs db.json --output csr2_assets

Anything the chain would look up can be pinned with ``--branch``,
``--product-version`` or ``--release-version``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional, Sequence

from csr2cdn import __version__
from csr2cdn.cdn import DEFAULT_BASE_URL, DEFAULT_PLATFORM, CDN
from csr2cdn.database import DEFAULT_QUALITY, AssetDatabase
from csr2cdn.errors import Csr2CdnError
from csr2cdn.hub import DEFAULT_HUB_BASE_URL, HUB_CATEGORIES, HubCDN
from csr2cdn.metadata import DEFAULT_METADATA_URL
from csr2cdn.snapshots import SNAPSHOT_KINDS, SnapshotCDN


def _database_from_args(cdn: CDN, args: argparse.Namespace) -> AssetDatabase:
    path = getattr(args, "database", None)
    version = getattr(args, "database_version", None)
    if path and version:
        raise Csr2CdnError("give a database file or --database-version, not both")
    if path:
        return cdn.use_database(AssetDatabase.load(path))
    if version:
        return cdn.use_database(cdn.get_database(version=version))
    return cdn.database


def _add_database_args(parser: argparse.ArgumentParser, positional: bool = True) -> None:
    if positional:
        parser.add_argument("database", nargs="?", help="path to a database JSON file")
    parser.add_argument("--database-version", help="exact database version to fetch")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="csr2cdn", description="CSR2 CDN client")
    parser.add_argument("--version", action="version", version=f"csr2cdn {__version__}")
    parser.add_argument("--zid", help="your player id, needed for metadata and branch discovery")
    parser.add_argument("--branch", help="pin the branch instead of discovering it")
    parser.add_argument("--product-version", help="pin the product version, e.g. 6.7.81")
    parser.add_argument("--release-version", help="pin the app version, e.g. 6.7.1")
    parser.add_argument("--no-preemptive", action="store_true", help="ignore a staged preemptive branch")
    parser.add_argument(
        "--probe",
        action="store_true",
        help="also probe the CDN for successor branches; works without a zid",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="CDN base URL")
    parser.add_argument("--metadata-url", default=DEFAULT_METADATA_URL)
    parser.add_argument("--platform", default=DEFAULT_PLATFORM, help="asset platform directory")
    parser.add_argument("--quality", default=DEFAULT_QUALITY, help="asset quality directory")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--cache-dir", help="cache downloaded databases and version lookups here")
    sub = parser.add_subparsers(dest="command", required=True)

    snapshots = sub.add_parser("snapshots", help="list official snapshot cars and availability")
    snapshot = sub.add_parser("snapshot", help="download an official car PNG or print its URL")
    for command in (snapshots, snapshot):
        command.add_argument("--manifest", help="read CDNSnapshots.meta instead of fetching metadata")
        command.add_argument("--staging", action="store_true", help="use the staging endpoint")
    snapshots.add_argument("--search", default="", help="filter CRDB names (case insensitive)")
    snapshot.add_argument("crdb")
    snapshot.add_argument("--kind", choices=SNAPSHOT_KINDS, default="DEFAULT")
    snapshot.add_argument("--reversed", action="store_true", help="DEFAULT_REVERSED (DEFAULT only)")
    snapshot.add_argument("--strict", action="store_true", help="require a listed snapshot")
    snapshot.add_argument("--output", "-o", help="output PNG filename; otherwise print URL")

    hub = sub.add_parser("hub", help="access every CSR2 HUB CDN resource")
    hub.add_argument("--hub-base-url", default=DEFAULT_HUB_BASE_URL)
    hub_sub = hub.add_subparsers(dest="hub_command", required=True)
    hub_sub.add_parser("categories", help="list known HUB folder layouts")
    hub_url = hub_sub.add_parser("url", help="build a URL from an exact relative path")
    hub_url.add_argument("path")
    hub_get = hub_sub.add_parser("get", help="print JSON/text or download one file")
    hub_get.add_argument("path")
    hub_get.add_argument("--output", "-o", help="output directory (preserves HUB folders)")
    hub_get.add_argument("--json", action="store_true", help="parse and pretty-print JSON")
    hub_download = hub_sub.add_parser("download", help="download relative paths in parallel")
    hub_download.add_argument("paths", nargs="+")
    hub_download.add_argument("--output", "-o", required=True)
    hub_download.add_argument("--workers", type=int, default=8)
    hub_sync = hub_sub.add_parser("sync", help="sync paths using ETag/Last-Modified")
    hub_sync.add_argument("paths", nargs="+")
    hub_sync.add_argument("--output", "-o", required=True)
    hub_sync.add_argument("--force", action="store_true")
    hub_db = hub_sub.add_parser("database", help="download the latest or a numbered HUB database")
    hub_db.add_argument("--database-version")
    hub_db.add_argument("--output", "-o", required=True)
    hub_snapshot = hub_sub.add_parser("snapshot", help="download any of the four snapshot layouts")
    hub_snapshot.add_argument("car")
    hub_snapshot.add_argument("--kind", default="Snapshots", choices=[
        "Snapshots", "SnapshotsFull", "SnapshotsGacha", "SnapshotsRC",
    ])
    hub_snapshot.add_argument("--manufacturer")
    hub_snapshot.add_argument("--index", help="exact index, including leading zeroes for RC")
    hub_snapshot.add_argument("--output", "-o", required=True)
    hub_images = hub_sub.add_parser("images", help="export PNGs from a HUB Unity bundle")
    hub_images.add_argument("path")
    hub_images.add_argument("--output", "-o", required=True)

    branch = sub.add_parser("branch", help="resolve the current branch name")
    branch.add_argument("--fallback", action="append", default=[], help="branch to fall back to; repeatable")
    branch.add_argument("--no-verify", action="store_true", help="do not check candidates against the CDN")
    branch.add_argument("--raw", action="store_true", help="print both announced names as JSON")

    sub.add_parser("release", help="show the discovery chain step by step")

    probe = sub.add_parser("probe", help="list successor branches that exist on the CDN")
    probe.add_argument("--from", dest="from_branch", help="branch to probe from; defaults to the base release")
    probe.add_argument("--ota-depth", type=int, default=3)
    probe.add_argument("--patch-depth", type=int, default=2)
    probe.add_argument("--minor-depth", type=int, default=1)

    version = sub.add_parser("version", help="print the database version of a branch")
    version.add_argument("--raw", action="store_true", help="print the whole .version document")

    database = sub.add_parser("database", help="download an asset database")
    _add_database_args(database, positional=False)
    database.add_argument("--output", "-o", required=True, help="file to write the JSON to")
    database.add_argument("--indent", type=int, default=None)

    assets = sub.add_parser("assets", help="list assets in a database")
    _add_database_args(assets)
    assets.add_argument("--search", help="only codes containing this text")
    assets.add_argument("--type", dest="asset_type", help="only this asset type")
    assets.add_argument("--limit", type=int, default=50, help="0 for no limit")
    assets.add_argument("--urls", action="store_true", help="print download URLs")

    download = sub.add_parser("download", help="download asset bundles")
    _add_database_args(download)
    download.add_argument("--code", action="append", default=[], help="asset code or alias; repeatable")
    download.add_argument("--asset-version", help="version override, used with a single --code")
    download.add_argument("--search", help="download every asset whose code contains this text")
    download.add_argument("--with-dependencies", action="store_true")
    download.add_argument("--output", "-o", default=".", help="directory to write bundles to")
    download.add_argument("--workers", type=int, default=8)

    metadata = sub.add_parser("metadata", help="download metadata blocks")
    metadata.add_argument("names", nargs="+", help="block ids, e.g. CarFusionProfileData")
    metadata.add_argument("--output", "-o", help="directory to write <name>.meta files to")
    metadata.add_argument(
        "--sync",
        action="store_true",
        help="keep hashes in the output directory and fetch only what changed",
    )
    metadata.add_argument("--force", action="store_true", help="ignore stored hashes")

    sync = sub.add_parser("sync", help="keep a directory of asset bundles up to date")
    _add_database_args(sync, positional=False)
    sync.add_argument("--output", "-o", required=True, help="directory to sync into")
    sync.add_argument("--code", action="append", default=[], help="asset code or alias; repeatable")
    sync.add_argument("--search", help="only codes containing this text")
    sync.add_argument("--type", dest="asset_type", help="only this asset type")
    sync.add_argument("--with-dependencies", action="store_true")
    sync.add_argument("--remove-stale", action="store_true", help="delete files no longer selected")
    sync.add_argument("--workers", type=int, default=8)
    sync.add_argument("--quiet", action="store_true", help="only print the summary")

    diff = sub.add_parser("diff", help="compare two databases")
    diff.add_argument("old", help="the older database: a file path or a version")
    diff.add_argument("new", nargs="?", help="the newer database; defaults to the current one")
    diff.add_argument("--limit", type=int, default=20, help="codes to list per section, 0 for all")

    stubs = sub.add_parser("stubs", help="generate a typed module for IDE completion")
    _add_database_args(stubs)
    stubs.add_argument("--output", "-o", required=True, help="module path to write, without .py")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "hub":
        try:
            with HubCDN(base_url=args.hub_base_url, timeout=args.timeout) as hub:
                return _dispatch_hub(args, hub)
        except (Csr2CdnError, ValueError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    from csr2cdn.metadata import MetadataClient

    cdn = CDN(
        zid=args.zid,
        branch=args.branch,
        product_version=args.product_version,
        release_version=args.release_version,
        allow_preemptive=not args.no_preemptive,
        probe=args.probe,
        base_url=args.base_url,
        platform=args.platform,
        quality=args.quality,
        timeout=args.timeout,
        cache_dir=args.cache_dir,
    )
    if args.metadata_url != DEFAULT_METADATA_URL:
        cdn._metadata = MetadataClient(url=args.metadata_url, session=cdn.session, timeout=args.timeout)
    try:
        return _dispatch(args, cdn)
    except Csr2CdnError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        cdn.close()


def _dispatch_hub(args: argparse.Namespace, hub: HubCDN) -> int:
    command = args.hub_command
    if command == "categories":
        print("\n".join(HUB_CATEGORIES))
    elif command == "url":
        print(hub.url_for(args.path))
    elif command == "get":
        if args.output:
            print(hub.download_to(args.path, args.output))
        elif args.json:
            print(json.dumps(hub.get_json(args.path), indent=2, ensure_ascii=False))
        else:
            print(hub.get_text(args.path))
    elif command == "database":
        hub.get_database(args.database_version).save(args.output)
        print(args.output)
    elif command == "snapshot":
        path = hub.snapshot_path(
            args.car, args.kind, manufacturer=args.manufacturer, index=args.index
        )
        print(hub.download_to(path, args.output))
    elif command == "images":
        for path in hub.export_images(args.path, args.output):
            print(path)
    elif command == "download":
        results = hub.download_files(args.paths, args.output, workers=args.workers)
        for path, result in results.items():
            print(f"{path}: {result}", file=sys.stderr if isinstance(result, BaseException) else sys.stdout)
        return int(any(isinstance(r, BaseException) for r in results.values()))
    elif command == "sync":
        result = hub.sync_files(args.paths, args.output, force=args.force)
        print(f"{len(result.downloaded)} downloaded, {len(result.unchanged)} unchanged, {len(result.failed)} failed")
        for path, error in result.failed.items():
            print(f"{path}: {error}", file=sys.stderr)
        return int(bool(result.failed))
    return 0


def _dispatch(args: argparse.Namespace, cdn: CDN) -> int:
    if args.command in ("snapshot", "snapshots"):
        try:
            snapshots = (
                SnapshotCDN.from_file(args.manifest, staging=args.staging,
                                      session=cdn.session, timeout=args.timeout)
                if args.manifest else cdn.get_snapshots(staging=args.staging)
            )
            with snapshots:
                if args.command == "snapshots":
                    print(json.dumps({car: flags for car, flags in snapshots.cars.items()
                                      if args.search.lower() in car.lower()}, indent=2))
                elif args.output:
                    print(snapshots.download_snapshot_to(
                        args.crdb, args.output, args.kind, reversed=args.reversed, strict=args.strict))
                else:
                    print(snapshots.snapshot_url(
                        args.crdb, args.kind, reversed=args.reversed, strict=args.strict))
            return 0
        except (ValueError, OSError) as exc:
            raise Csr2CdnError(str(exc)) from exc

    if args.command == "branch":
        if args.raw:
            names = cdn.branch_names()
            print(json.dumps({"explicit": names.explicit, "preemptive": names.preemptive}))
            return 0
        print(cdn.resolve_branch(fallback=args.fallback, verify=not args.no_verify))
        return 0

    if args.command == "probe":
        found = cdn.probe_branches(
            args.from_branch,
            ota_depth=args.ota_depth,
            patch_depth=args.patch_depth,
            minor_depth=args.minor_depth,
        )
        if not found:
            print("no branches found", file=sys.stderr)
            return 1
        for name, version in sorted(found.items(), key=lambda item: item[1]):
            marker = "  <- newest" if version == max(found.values()) else ""
            print(f"{name}\t{version}{marker}")
        return 0

    if args.command == "release":
        print(f"store version:   {cdn.store_version()}")
        print(f"release:         {cdn.release_version}")
        print(f"base branch:     {cdn.base_branch}")
        print(f"product version: {cdn.product_version}")
        if cdn.zid:
            names = cdn.branch_names()
            print(f"explicit branch: {names.explicit or '(none announced)'}")
            print(f"preemptive:      {names.preemptive or '(none announced)'}")
            print(f"resolved branch: {cdn.resolve_branch()}")
        return 0

    if args.command == "version":
        info = cdn.version_info()
        print(json.dumps(info) if args.raw else info.get("version"))
        return 0

    if args.command == "database":
        database = (
            cdn.get_database(version=args.database_version)
            if args.database_version
            else cdn.get_database()
        )
        database.save(args.output, indent=args.indent)
        print(
            f"{args.output}: branch {database.branch_name}, version {database.version}, "
            f"{len(database.assets)} assets"
        )
        return 0

    if args.command == "assets":
        database = _database_from_args(cdn, args)
        selected = database.assets.search(args.search) if args.search else list(database.assets)
        if args.asset_type:
            selected = [a for a in selected if str(a.type) == str(args.asset_type)]
        total = len(selected)
        if args.limit:
            selected = selected[: args.limit]
        for asset in selected:
            if args.urls:
                print(cdn.url_for(asset))
            else:
                print(f"{asset.code}\tversion={asset.version}\ttype={asset.type}\t{asset.size()} bytes")
        if args.limit and total > args.limit:
            print(f"... {total - args.limit} more (use --limit 0)", file=sys.stderr)
        return 0

    if args.command == "download":
        if args.asset_version and len(args.code) == 1 and not args.search:
            path = cdn.download_asset_to(args.code[0], args.output, version=args.asset_version)
            print(path)
            return 0
        database = _database_from_args(cdn, args)
        wanted = _select_assets(database, args)
        if not wanted:
            print("error: nothing selected, use --code or --search", file=sys.stderr)
            return 1
        results = cdn.download_assets(wanted, args.output, workers=args.workers)
        failures = 0
        for code, outcome in results.items():
            if isinstance(outcome, BaseException):
                failures += 1
                print(f"{code}: {outcome}", file=sys.stderr)
            else:
                print(outcome)
        return 1 if failures else 0

    if args.command == "sync":
        result = cdn.sync_assets(
            args.output,
            assets=[cdn.find_asset(code) for code in args.code] or None,
            search=args.search,
            asset_type=args.asset_type,
            with_dependencies=args.with_dependencies,
            remove_stale=args.remove_stale,
            workers=args.workers,
            on_done=None if args.quiet else _print_sync_progress,
        )
        print(
            f"{result.database.branch_name} {result.database.version}: "
            f"{len(result.downloaded)} downloaded, {len(result.unchanged)} unchanged, "
            f"{len(result.removed)} removed, {len(result.failed)} failed"
        )
        for code, error in result.failed.items():
            print(f"{code}: {error}", file=sys.stderr)
        return 1 if result.failed else 0

    if args.command == "diff":
        old = _open_database(cdn, args.old)
        new = _open_database(cdn, args.new) if args.new else cdn.database
        changes = new.diff(old)
        for label, codes in (
            ("added", changes.added),
            ("removed", changes.removed),
            ("changed", changes.changed),
        ):
            print(f"{label}: {len(codes)}")
            shown = codes if not args.limit else codes[: args.limit]
            for code in shown:
                print(f"  {code}")
            if args.limit and len(codes) > args.limit:
                print(f"  ... {len(codes) - args.limit} more")
        return 0

    if args.command == "metadata":
        if args.sync:
            if not args.output:
                print("error: --sync needs --output", file=sys.stderr)
                return 1
            cache = cdn.metadata_cache(args.output)
            updated = cache.sync(args.names, force=args.force)
            for name in updated:
                print(f"{cache.path(name)}\t{cache.hashes([name]).get(name, '')}")
            unchanged = [n for n in args.names if n not in updated]
            if unchanged:
                print(f"unchanged: {', '.join(unchanged)}", file=sys.stderr)
            return 0
        blocks = cdn.get_metadata(*args.names)
        if args.output:
            os.makedirs(args.output, exist_ok=True)
            for name, block in blocks.items():
                path = os.path.join(args.output, f"{name}.meta")
                block.save(path)
                print(f"{path}\t{block.hash}")
        else:
            for block in blocks.values():
                print(block.text)
        missing = [n for n in args.names if n not in blocks]
        if missing:
            print(f"not served: {', '.join(missing)}", file=sys.stderr)
        return 0

    if args.command == "stubs":
        from csr2cdn.stubs import generate

        database = _database_from_args(cdn, args)
        module, stub = generate(
            database, args.output, source_hint=getattr(args, "database", None) or "db.json"
        )
        print(module)
        print(stub)
        return 0

    return 1


def _print_sync_progress(code, outcome) -> None:
    if isinstance(outcome, BaseException):
        print(f"{code}: {outcome}", file=sys.stderr)
    else:
        print(outcome)


def _open_database(cdn: CDN, reference: str) -> AssetDatabase:
    """A database from a file path, a database version or a branch name."""
    if os.path.exists(reference):
        return AssetDatabase.load(reference)
    if reference.isdigit():
        return cdn.get_database(version=reference)
    return cdn.get_database(branch=reference)


def _select_assets(database: AssetDatabase, args: argparse.Namespace) -> List:
    wanted = []
    seen = set()
    candidates = [database.assets[code] for code in args.code]
    if args.search:
        candidates.extend(database.assets.search(args.search))
    for asset in candidates:
        group = asset.walk_dependencies(include_self=True) if args.with_dependencies else [asset]
        for item in group:
            if item.code.lower() not in seen:
                seen.add(item.code.lower())
                wanted.append(item)
    return wanted


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
