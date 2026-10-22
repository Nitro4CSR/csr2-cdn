"""Python client for the CSR2 asset CDN and metadata service.

Typical use::

    from csr2cdn import CDN

    cdn = CDN()
    cdn = CDN(zid="YOUR_PLAYER_ID")

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
from csr2cdn.services import CSR2Services, ServiceNetworkDisabled, ServiceHTTPError
from csr2cdn.service_events import EventCatalog, EventLeaderboard, EventResolutionError
from csr2cdn.service_discovery import ShowdownDiscovery, ShowdownCandidate, scan_showdowns, merge_modular_showdown_groups, modular_event_assets
from csr2cdn.service_models import (
    OwnCrew, CrewCar, CrewMember, CrewMembers, GCCCrewStanding, GCCCrewStandings,
    LeaderboardEntry, LeaderboardPage, LeaderboardScore, ServiceResponseError,
    GCCProgressCrewScore, GCCProgressCrewScores,
)
from csr2cdn.crew_optional_data import (CrewOptionalSnapshot, CrewOptionalStats, CrewMemberOptionalStats, CrewMemberVehicle, CrewVehicleGacha, CrewVehicleAppearance, CrewVehicleVisuals, CrewVisualSelection, InteriorDisplayName, CrewEmblem, CrewPresentation, CrewTournamentShape,
                                      CrewTournament, CrewTournamentEvent, CrewTournamentRival,
                                      TOURNAMENT_CADENCE_DAYS)
from csr2cdn.vehicle_catalog import VehicleCatalog, VehicleCatalogEntry, resolve_vehicle_report
from csr2cdn.customization_evidence import (CosmeticCandidateCatalog, CosmeticCandidate,
    inspect_customization_apk, cosmetic_coverage_report)
from csr2cdn.game_labels import (CarNameStyle, GameCarTranslations, GameCarName, CarDisplayName, GameVisualLibrary, VisualCodeName, game_label_report, metadata_library_inventory)
from csr2cdn.native_game_sources import (TranslationLayout, VisualJsonLayout, decode_translation_flatbuffer, decode_visual_metadata_cache, inspect_metadata_cache, load_translation_source, load_visual_source, SourceSchemaError)
from csr2cdn.car_body_parts import (BODY_PART_SLOTS, VARIANT_SLOTS, RETIRED_SLOTS, BodyPartSelection,
                                    CarBodyPartInventory, bodykit_asset_code,
                                    part_asset_code, resolve_body_parts)
from csr2cdn.localisation_bundle import (decode_localisation_unityfs, load_localisation_unityfs, LocalisationSourceError)
from csr2cdn.visual_library_bundle import (decode_visual_unityfs, load_visual_unityfs, load_visual_libraries_unityfs, VisualLibrarySourceError)
from csr2cdn.visual_asset_plan import (VisualAssetCandidate, VisualAssetPlan, VISUAL_ASSET_SLOTS, PENDING_VISUAL_ASSET_SLOTS, plan_visual_assets, plan_visual_assets_from_file)
from csr2cdn.visual_source_recon import (VisualArrayShape, VisualBlockShape, VisualSourceInventory, VISUAL_SOURCE_BLOCKS, inspect_visual_cache)
from csr2cdn.bulk_review import BulkUIReference, review_bulk_evidence
from csr2cdn.visual_gap_diagnostics import (VisualGapDiagnostics, VisualGapSlot, analyze_visual_gaps)
from csr2cdn.visual_asset_refresh import (VisualAssetRefreshSlot, VisualAssetRefreshReport, compare_visual_asset_plans, compare_visual_asset_databases)
from csr2cdn.visual_source_delta import (VisualSourceDelta, VisualSourceDeltaSlot, VisualMissingIDRecheck, VisualMissingIDSlot, compare_visual_sources, recheck_visual_missing_ids)
from csr2cdn.crew_rp import CrewRPSnapshot
from csr2cdn.crew_season import GCCSeasonTiming, CrewSeasonTransition
from csr2cdn._service_reads import StandingRange
from csr2cdn.snapshots import (
    SNAPSHOTS_BLOCK,
    SNAPSHOT_KINDS,
    SnapshotCDN,
    SnapshotError,
    SnapshotNotFoundError,
)

__version__ = "0.7.1"

__all__ = [
    "CSR2Services", "ServiceNetworkDisabled", "ServiceHTTPError",
    "EventCatalog", "EventLeaderboard", "EventResolutionError", "StandingRange",
    "ShowdownDiscovery", "ShowdownCandidate", "scan_showdowns", "merge_modular_showdown_groups", "modular_event_assets",
    "extract_modular_event_metadata", "load_modular_event_metadata",
    "OwnCrew", "CrewCar", "CrewMember", "CrewMembers", "GCCCrewStanding", "GCCCrewStandings",
    "LeaderboardEntry", "LeaderboardPage", "LeaderboardScore",
    "GCCProgressCrewScore", "GCCProgressCrewScores",
    "ServiceResponseError", "CrewOptionalSnapshot", "CrewOptionalStats", "CrewMemberOptionalStats",
    "CrewTournament", "CrewTournamentEvent", "CrewTournamentRival", "TOURNAMENT_CADENCE_DAYS",
    "CrewMemberVehicle", "CrewVehicleGacha", "CrewVehicleAppearance", "CrewVehicleVisuals", "CrewVisualSelection", "InteriorDisplayName", "CrewEmblem",
    "CrewPresentation", "CrewTournamentShape", "BulkUIReference", "review_bulk_evidence", "VisualGapDiagnostics", "VisualGapSlot", "analyze_visual_gaps", "VisualSourceDelta", "VisualSourceDeltaSlot", "VisualMissingIDRecheck", "VisualMissingIDSlot", "compare_visual_sources", "recheck_visual_missing_ids", "VehicleCatalog", "VehicleCatalogEntry",
    "resolve_vehicle_report", "CosmeticCandidateCatalog", "CosmeticCandidate",
    "CarNameStyle", "GameCarTranslations", "GameCarName", "CarDisplayName", "GameVisualLibrary", "VisualCodeName", "game_label_report", "metadata_library_inventory",
    "TranslationLayout", "VisualJsonLayout", "decode_translation_flatbuffer", "decode_visual_metadata_cache", "inspect_metadata_cache", "load_translation_source", "load_visual_source", "SourceSchemaError",
    "BODY_PART_SLOTS", "VARIANT_SLOTS", "RETIRED_SLOTS", "BodyPartSelection", "CarBodyPartInventory",
    "bodykit_asset_code", "part_asset_code", "resolve_body_parts",
    "decode_localisation_unityfs", "load_localisation_unityfs", "LocalisationSourceError",
    "decode_visual_unityfs", "load_visual_unityfs", "load_visual_libraries_unityfs", "VisualLibrarySourceError",
    "VisualAssetRefreshSlot", "VisualAssetRefreshReport", "compare_visual_asset_plans", "compare_visual_asset_databases",
    "VisualAssetCandidate", "VisualAssetPlan", "VISUAL_ASSET_SLOTS", "PENDING_VISUAL_ASSET_SLOTS", "plan_visual_assets", "plan_visual_assets_from_file",
    "inspect_customization_apk", "cosmetic_coverage_report", "CrewRPSnapshot", "GCCSeasonTiming", "CrewSeasonTransition", "SnapshotCDN",
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

from csr2cdn.service_modular_assets import extract_modular_event_metadata, load_modular_event_metadata

from csr2cdn.service_prestige import PrestigeCupDiscovery, PrestigeCupSelection
