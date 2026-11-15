"""The cars a Grand Crew Championship season awards, including the Prestige Cup car.

Each season names up to three cars: the Prestige Cup car, and a primary and
secondary crew-leaderboard prize car. They live in two places, and which one
holds a given season depends on how old it is.

``CrewLeaderboardRewardDefinitions.SeasonalRewardCars``
    Historical seasons. On 2026-11-06 it held 222 entries covering 5..227,
    with 217 missing, and nothing at or beyond the live season.

``assets_client_metadata_<N>``
    The current and upcoming seasons, one numbered bundle each. Its TextAsset
    is JSON shaped ``{"<N>": {"CrewLeaderboardRewardDefinitions":
    {"SeasonalRewardCars": {"<N>": {...}}}, ...}}`` -- the season id appears
    both as the outer key and again inside. Those bundles also carry
    per-season ``CupInvitationalRaceSeries``, ``EventSchedule``,
    ``GachaEventsCalendar``, ``GachaRewardPools``, ``GachaVariants`` and
    ``ShowroomCollections`` overrides.

So a lookup tries the season's own bundle first and falls back to the block,
and reports which answered. Verified against the live service::

    279  PrestigeCupCar  Chevrolet_LBCamaroIROCZRewardRecycled_1987
         primary         Hennessey_VenomF5RevRReward_2025
         secondary       Hennessey_VenomF5RevRRewardRecycled_2025
    280  PrestigeCupCar  Bentley_SupersportsRewardRecycled_2026
    282  PrestigeCupCar  Honda_VarisS2000RewardRecycled_2005

Car names are returned exactly as the service spells them, which is the
database key other parts of this package already use as a model key.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

#: Section inside both the base block and a numbered bundle.
SECTION = "CrewLeaderboardRewardDefinitions"
#: The map of season id to reward cars, inside that section.
CARS_KEY = "SeasonalRewardCars"
#: Asset code pattern for a season's own bundle.
SEASON_BUNDLE_PREFIX = "assets_client_metadata_"


def season_bundle_code(season: int) -> str:
    """The CDN asset code holding one season's definitions."""
    if isinstance(season, bool) or not isinstance(season, int) or season < 0:
        raise ValueError("season must be a non-negative integer")
    return "%s%d" % (SEASON_BUNDLE_PREFIX, season)


def _car(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


@dataclass(frozen=True)
class SeasonalRewardCar:
    """One season's reward cars, as published."""
    season: int
    prestige_cup_car: Optional[str] = None
    primary_prize_car: Optional[str] = None
    secondary_prize_car: Optional[str] = None
    allow_primary_prize_car_test_run: Optional[bool] = None
    #: ``"season_bundle"`` or ``"crew_leaderboard_block"``.
    source: Optional[str] = None

    @property
    def resolved(self) -> bool:
        return self.prestige_cup_car is not None

    @classmethod
    def from_record(cls, season: int, record: Any,
                    *, source: Optional[str] = None) -> "SeasonalRewardCar":
        if not isinstance(record, Mapping):
            return cls(season, source=source)
        test_run = record.get("allowPrimaryPrizeCarTestRun")
        return cls(
            season,
            _car(record.get("PrestigeCupCar")),
            _car(record.get("primaryPrizeCarDBid")),
            _car(record.get("secondaryPrizeCarDBid")),
            test_run if isinstance(test_run, bool) else None,
            source,
        )

    def as_dict(self) -> dict:
        return {
            "season": self.season,
            "prestige_cup_car": self.prestige_cup_car,
            "primary_prize_car": self.primary_prize_car,
            "secondary_prize_car": self.secondary_prize_car,
            "allow_primary_prize_car_test_run": self.allow_primary_prize_car_test_run,
            "source": self.source,
        }


def _cars_map(node: Any) -> Optional[Mapping[str, Any]]:
    if not isinstance(node, Mapping):
        return None
    section = node.get(SECTION)
    if isinstance(section, Mapping):
        cars = section.get(CARS_KEY)
        if isinstance(cars, Mapping):
            return cars
    cars = node.get(CARS_KEY)
    return cars if isinstance(cars, Mapping) else None


@dataclass(frozen=True)
class SeasonalRewardCarIndex:
    """Seasons read out of the historical block."""
    records: Mapping[int, SeasonalRewardCar] = field(default_factory=dict, repr=False)
    source: str = "crew_leaderboard_block"

    def __len__(self) -> int:
        return len(self.records)

    @classmethod
    def from_block(cls, block: Any) -> "SeasonalRewardCarIndex":
        cars = _cars_map(block)
        if cars is None:
            raise ValueError("block holds no %s.%s map" % (SECTION, CARS_KEY))
        out: Dict[int, SeasonalRewardCar] = {}
        for key, record in cars.items():
            if isinstance(key, bool):
                continue
            if isinstance(key, int):
                season = key
            elif isinstance(key, str) and key.isdecimal():
                season = int(key)
            else:
                continue
            out[season] = SeasonalRewardCar.from_record(
                season, record, source="crew_leaderboard_block")
        return cls(out)

    @property
    def seasons(self) -> Tuple[int, ...]:
        return tuple(sorted(self.records))

    @property
    def gaps(self) -> Tuple[int, ...]:
        seasons = self.seasons
        if not seasons:
            return ()
        return tuple(s for s in range(seasons[0], seasons[-1] + 1)
                     if s not in self.records)

    def get(self, season: int) -> Optional[SeasonalRewardCar]:
        return self.records.get(season)


def from_season_bundle(document: Any, season: int) -> SeasonalRewardCar:
    """Read one season's cars from its own numbered bundle's decoded JSON.

    Accepts the document whether the season id wraps it or not, since the
    bundle nests the id both outside and inside.
    """
    if isinstance(season, bool) or not isinstance(season, int):
        raise ValueError("season must be an integer")
    node = document
    if isinstance(document, Mapping):
        inner = document.get(str(season), document.get(season))
        if isinstance(inner, Mapping):
            node = inner
    cars = _cars_map(node)
    record = None
    if cars is not None:
        record = cars.get(str(season), cars.get(season))
        if record is None and len(cars) == 1:
            # The bundle carries exactly its own season; accept a key that
            # disagrees rather than silently reporting nothing.
            record = next(iter(cars.values()))
    return SeasonalRewardCar.from_record(season, record, source="season_bundle")


def resolve_seasonal_reward_car(season: int, *, bundle_document: Any = None,
                                index: Optional[SeasonalRewardCarIndex] = None
                                ) -> SeasonalRewardCar:
    """The season's cars, preferring its own bundle over the historical block."""
    if bundle_document is not None:
        found = from_season_bundle(bundle_document, season)
        if found.resolved:
            return found
    if index is not None:
        found = index.get(season)
        if found is not None and found.resolved:
            return found
    return SeasonalRewardCar(season, source=None)


class SeasonBundleError(Exception):
    """A season's numbered bundle is absent or does not decode."""


def decode_season_bundle(blob: bytes, season: int) -> SeasonalRewardCar:
    """Decode a numbered bundle's bytes, which hold one JSON TextAsset."""
    try:
        import UnityPy
    except ImportError as exc:                       # pragma: no cover
        raise SeasonBundleError("UnityPy is required to read a season bundle; "
                                "install the 'images' extra") from exc
    try:
        env = UnityPy.load(blob)
        objects = list(env.objects)
    except Exception as exc:
        raise SeasonBundleError("season bundle is not a readable UnityFS "
                                "container") from exc
    for obj in objects:
        if obj.type.name != "TextAsset":
            continue
        try:
            data = obj.read()
        except Exception:
            continue
        raw = getattr(data, "m_Script", None) or getattr(data, "script", None) or b""
        if isinstance(raw, str):
            raw = raw.encode("utf-8", "replace")
        try:
            document = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        return from_season_bundle(document, season)
    raise SeasonBundleError("season bundle holds no JSON TextAsset")


def load_season_reward_cars(cdn: Any, season: int) -> SeasonalRewardCar:
    """Download and decode a season's own bundle through a ``CDN``.

    Mirrors ``car_visuals_data.load_index_space``. Raises
    :class:`SeasonBundleError` when the season has no bundle published, which
    is the normal answer for a season older than the numbered series.
    """
    code = season_bundle_code(season)
    asset = cdn.database.assets.get(code)
    if asset is None:
        raise SeasonBundleError("no bundle published for season %d (%s)"
                                % (season, code))
    return decode_season_bundle(cdn.download_asset(asset), season)


def active_prestige_cup_car(cdn: Any, crew_leaderboard_block: Any,
                            *, now: Any = None) -> dict:
    """The current season's Prestige Cup car, start to finish.

    Composes what was previously four manual steps, and what
    ``seasonal_prestige_car`` used to require a hand-supplied season for:
    read the championship constants, compute the active season, fetch that
    season's bundle, fall back to the historical block if it has none.

    Returns the car alongside the season and window, and records which source
    answered, so nothing is implied to be verified that was not.
    """
    from csr2cdn.crew_season_schedule import GrandCrewChampionshipSchedule
    schedule = GrandCrewChampionshipSchedule.from_block(crew_leaderboard_block)
    season = schedule.active_season(now=now)
    start, end = schedule.window(season)
    car, error = None, None
    try:
        car = load_season_reward_cars(cdn, season)
    except SeasonBundleError as exc:
        error = str(exc)
    if car is None or not car.resolved:
        try:
            index = SeasonalRewardCarIndex.from_block(crew_leaderboard_block)
        except ValueError:
            index = None
        if index is not None:
            fallback = index.get(season)
            if fallback is not None and fallback.resolved:
                car = fallback
    out = {
        "season": season,
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "cars": (car or SeasonalRewardCar(season)).as_dict(),
        "bundle_error": error,
    }
    return out
