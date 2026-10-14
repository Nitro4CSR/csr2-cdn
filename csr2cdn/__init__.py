"""Python client for the CSR2 asset CDN and metadata service.

Typical use::

    from csr2cdn import CDN

    cdn = CDN()
    cdn = CDN(zid="94866657860")

    database = cdn.database                       # current branch, resolved for you
    asset = database.assets.Lamborghini_AventadorLP7004_2011_loda
    data = cdn.download_asset(asset)

    blocks = cdn.get_metadata("CarFusionProfileData")

This project is not affiliated with, endorsed by or connected to Zynga,
NaturalMotion or any of their subsidiaries.
"""

from csr2cdn._naming import alias_for
from csr2cdn.branches import (
    BranchNames,
    base_branch_candidates,
    branch_names,
    probe_branches,
    resolve_branch,
)
from csr2cdn.cdn import DEFAULT_BASE_URL, SYNC_MANIFEST, CDN, SyncResult
from csr2cdn.hub import (
    DEFAULT_HUB_BASE_URL,
    HUB_BRAND_MAP,
    HUB_CATEGORIES,
    HUB_SYNC_MANIFEST,
    HubCDN,
    HubError,
    HubSyncResult,
)
from csr2cdn.database import (
    DEFAULT_ASSET_FIELDS,
    HEADER_FIELDS,
    Asset,
    AssetCollection,
    AssetDatabase,
    DatabaseDiff,
)
from csr2cdn.errors import (
    AssetNotFoundError,
    BranchNotFoundError,
    Csr2CdnError,
    DatabaseFormatError,
    MetadataError,
    MissingZidError,
    StoreVersionError,
)
from csr2cdn import patterns, store
from csr2cdn.patterns import BranchName as ParsedBranch, build_branch, parse_branch, successors
from csr2cdn.store import (
    APP_STORE_ID,
    PACKAGE_ID,
    AppIds,
    app_store_version,
    google_play_version,
    latest_store_version,
    normalize_release,
    store_versions,
)
from csr2cdn.metadata import (
    DEFAULT_METADATA_URL,
    KILLSWITCHES_BLOCK,
    MetadataBlock,
    MetadataCache,
    MetadataClient,
    metadata_block_ids,
)
from csr2cdn.snapshots import (
    SNAPSHOTS_BLOCK,
    SNAPSHOT_KINDS,
    SnapshotCDN,
    SnapshotError,
    SnapshotNotFoundError,
)

__version__ = "0.6.0"

__all__ = [
    "SnapshotCDN",
    "SnapshotError",
    "SnapshotNotFoundError",
    "SNAPSHOTS_BLOCK",
    "SNAPSHOT_KINDS",
    "metadata_block_ids",
    "CDN",
    "HubCDN",
    "HubError",
    "HubSyncResult",
    "DEFAULT_HUB_BASE_URL",
    "HUB_CATEGORIES",
    "HUB_BRAND_MAP",
    "HUB_SYNC_MANIFEST",
    "APP_STORE_ID",
    "PACKAGE_ID",
    "AppIds",
    "DEFAULT_BASE_URL",
    "DEFAULT_METADATA_URL",
    "DEFAULT_ASSET_FIELDS",
    "HEADER_FIELDS",
    "KILLSWITCHES_BLOCK",
    "Asset",
    "AssetCollection",
    "AssetDatabase",
    "AssetNotFoundError",
    "BranchNames",
    "BranchNotFoundError",
    "Csr2CdnError",
    "DatabaseDiff",
    "DatabaseFormatError",
    "MetadataBlock",
    "MetadataCache",
    "MetadataClient",
    "MetadataError",
    "MissingZidError",
    "SYNC_MANIFEST",
    "SyncResult",
    "StoreVersionError",
    "ParsedBranch",
    "alias_for",
    "app_store_version",
    "base_branch_candidates",
    "build_branch",
    "google_play_version",
    "branch_names",
    "latest_store_version",
    "normalize_release",
    "parse_branch",
    "patterns",
    "probe_branches",
    "resolve_branch",
    "store",
    "store_versions",
    "successors",
    "__version__",
]
