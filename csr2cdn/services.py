"""Experimental CSR2 0.7.0 crew and leaderboard read API (offline-first).

The public API and CLI are usable with sanitized local fixtures today. Live
requests require explicit `allow_network=True`; no live compatibility is
claimed before release validation. This module never downloads or uploads
save games and never persists game credentials.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

import requests

from csr2cdn._service_auth import (
    DEFAULT_NMCLIENT_ID, PORTAL_URL, WEB_API_URL, PortalCredentials,
    PreparedRequest, ServiceAuthError, _https_url, _player_id,
    prepare_portal_request,
)
from csr2cdn._service_reads import (
    ReadContract, ReadContractError, StandingRange, _identifier,
    own_crew_contract, crew_members_contract, gcc_progress_contract, gcc_progress_range_contract, event_standings_contract, event_crew_standings_contract,
    prepare_read_contract, showdown_standings_contract, showdown_leagues_score_contract,
)
from csr2cdn.service_events import EventCatalog, EventResolutionError
from csr2cdn.service_discovery import ShowdownDiscovery
from csr2cdn.service_models import OwnCrew, CrewMembers, LeaderboardPage, LeaderboardScore, ServiceResponseError
from csr2cdn.errors import Csr2CdnError


class ServiceNetworkDisabled(Csr2CdnError):
    """Live game-service calls require explicit allow_network=True."""


class ServiceHTTPError(Csr2CdnError):
    """HTTP error without credential, URL-query, or response-body disclosure."""

    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"CSR2 service returned HTTP {status_code} (response suppressed)")


class PrestigeCrewSchemaError(ServiceResponseError):
    """Crew-filtered event response was returned but does not fit typed rows."""


def _prestige_crew_safe_shape(response: Any) -> dict:
    """Bounded, names/values-free diagnostic for an unknown crew-tab reply.

    Never return raw keys, account identifiers, or payload values: only
    explicitly known leaderboard field names and their primitive types.
    """
    allow = {"scores", "entries", "records", "results", "rank", "score", "name",
             "player_uid", "player_id", "crew_uid", "responseData", "data", "result"}
    def typename(value):
        if isinstance(value, list):
            return "array"
        if isinstance(value, Mapping):
            return "object"
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if type(value) is int:
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        return "other"
    if not isinstance(response, Mapping):
        return {"response_type": typename(response)}
    node = response
    for wrapper in ("responseData", "data", "result"):
        if isinstance(node.get(wrapper), Mapping):
            node = node[wrapper]
            break
    result = {"known_top_level_types": {k: typename(v) for k, v in node.items() if k in allow}}
    for key in ("scores", "entries", "records", "results"):
        rows = node.get(key)
        if isinstance(rows, list):
            result["rows"] = len(rows)
            result["inspected"] = min(len(rows), 50)
            known = {}
            for record in rows[:50]:
                if isinstance(record, Mapping):
                    for k, v in record.items():
                        if k in allow:
                            kind = typename(v)
                            known.setdefault(k, {})[kind] = known.get(k, {}).get(kind, 0) + 1
            result["known_row_types"] = known
            break
    return result


class CSR2Services:
    """Experimental crew and leaderboard reader using a PlayerID and NM portal.

    Authentication is lazy, memory-only, and bound to the caller-provided
    PlayerID. Registered `nm_client_id` is NOT an account secret. `events` is
    a dynamically reloadable mapping source; no event catalog ships here.

    Pass a `requests.Session` (or compatible test double) for dependency
    injection. Constructors and `prepare_*` / `decode_*` never issue requests.
    """

    def __init__(self, player_id: str, *, app_version: str = "6.8.0",
                 nm_client_id: str = DEFAULT_NMCLIENT_ID,
                 portal_url: str = PORTAL_URL, web_api_url: str = WEB_API_URL,
                 endpoint_source: Optional[Callable[[], str]] = None,
                 events: Optional[EventCatalog] = None,
                 allow_network: bool = False, timeout: float = 20.0,
                 session: Optional[Any] = None,
                 credentials: Optional[PortalCredentials] = None):
        self.player_id = _player_id(player_id)
        self.app_version = app_version
        self.nm_client_id = nm_client_id
        self.portal_url = _https_url(portal_url)
        self.web_api_url = _https_url(web_api_url)
        self.endpoint_source = endpoint_source
        self.events = events
        self.allow_network = bool(allow_network)
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = timeout
        if credentials is not None and credentials.player_id != self.player_id:
            raise ServiceAuthError("session does not match selected PlayerID")
        self._credentials = credentials
        self._own_crew = None
        self._own_crew_obtained_at = None
        self._session = session
        self._owns_session = session is None

    @property
    def session(self):
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def close(self) -> None:
        self._credentials = None
        self._own_crew = None
        self._own_crew_obtained_at = None
        if self._owns_session and self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self) -> "CSR2Services":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def refresh_endpoint(self) -> str:
        """Refresh service origin from externally supplied current configuration."""
        if self.endpoint_source is not None:
            new = _https_url(self.endpoint_source())
            self.web_api_url = new
        return self.web_api_url

    def authenticate(self, *, force: bool = False) -> PortalCredentials:
        current = int(time.time())
        if not force and self._credentials is not None and (
                not self._credentials.expires_at or self._credentials.expires_at > current + 30):
            return self._credentials
        if not self.allow_network:
            raise ServiceNetworkDisabled("live portal authentication is disabled; use allow_network=True only for final validation")
        try:
            request = prepare_portal_request(
                self.player_id, nm_client_id=self.nm_client_id,
                app_version=self.app_version, portal_url=self.portal_url,
            )
            doc = self._post(request, max_bytes=1024 * 1024)
            # The portal authorization token identifies an NM-side principal;
            # the selected game PlayerID is supplied separately and is bound
            # into every signed read and PID-validation header. In particular,
            # comparing the NM claim against PlayerID falsely rejected the
            # working reference flow for registered cross-account clients.
            self._credentials = PortalCredentials.from_response(self.player_id, doc)
            return self._credentials
        except ServiceAuthError:
            # Public exceptions must never narrate private session mechanics.
            raise ServiceAuthError("game-service session unavailable") from None

    def _post(self, prepared: PreparedRequest, *, max_bytes: int = 8 * 1024 * 1024) -> Any:
        if not self.allow_network:
            raise ServiceNetworkDisabled("live requests are disabled; use allow_network=True only for final validation")
        # POST only to approved HTTPS origins; no redirect, no response logging.
        try:
            with self.session.post(
                prepared.url, data=prepared.body, headers=dict(prepared.headers),
                timeout=(self.timeout, self.timeout), stream=True, allow_redirects=False,
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise ServiceHTTPError(response.status_code)
                data = bytearray()
                for part in response.iter_content(chunk_size=16384):
                    data.extend(part)
                    if len(data) > max_bytes:
                        raise ServiceResponseError("service response exceeds size limit")
        except requests.RequestException as exc:
            raise ServiceResponseError("CSR2 game-service network request failed (details suppressed)") from None
        try:
            return json.loads(data)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ServiceResponseError("service did not return valid JSON") from exc

    def prepare(self, contract: ReadContract, *, unix_time: Optional[int] = None,
                nonce: Optional[int] = None) -> PreparedRequest:
        """Sign a validated read contract; never send it. Requires a session."""
        if self._credentials is None:
            raise ServiceAuthError("game-service session unavailable")
        return prepare_read_contract(self._credentials, contract,
                                     web_api_url=self.web_api_url,
                                     unix_time=unix_time, nonce=nonce)

    def _read(self, contract: ReadContract) -> Any:
        credentials = self.authenticate()
        prepared = prepare_read_contract(credentials, contract, web_api_url=self.refresh_endpoint())
        try:
            return self._post(prepared)
        except ServiceHTTPError as exc:
            # A single re-authentication on 401 is safe for allowlisted reads.
            if exc.status_code != 401:
                raise
            credentials = self.authenticate(force=True)
            return self._post(prepare_read_contract(credentials, contract, web_api_url=self.web_api_url))

    def prepare_my_crew(self) -> ReadContract:
        """Offline preview of own membership lookup; needs no crew UID."""
        return own_crew_contract(app_version=self.app_version)

    @staticmethod
    def decode_my_crew(response: Any) -> OwnCrew:
        return OwnCrew.from_response(response)

    def get_my_crew(self, *, refresh: bool = False) -> OwnCrew:
        """Discover the authenticated account's crew, with short in-memory cache.

        Never downloads a save/profile or guesses a crew ID from a PlayerID.
        `refresh=True` checks for changes in membership.
        """
        now = time.monotonic()
        if (not refresh and self._own_crew is not None and
                self._own_crew_obtained_at is not None and
                now - self._own_crew_obtained_at < 300):
            return self._own_crew
        record = self.decode_my_crew(self._read(self.prepare_my_crew()))
        self._own_crew, self._own_crew_obtained_at = record, now
        return record

    def prepare_crew_members(self, crew_uid: Optional[str] = None) -> ReadContract:
        """Offline crew-member request: explicit ID or previously discovered ID.

        This method does no network I/O, even if `allow_network=True`.
        Call `get_crew_members()` for automatic network discovery.
        """
        if crew_uid is None:
            crew_uid = self._own_crew.crew_uid if self._own_crew else None
            if not crew_uid:
                raise ReadContractError("crew is not resolved; use get_my_crew() or pass crew_uid")
        return crew_members_contract(crew_uid, app_version=self.app_version)

    @staticmethod
    def decode_crew_members(crew_uid: str, response: Any) -> CrewMembers:
        return CrewMembers.from_response(crew_uid, response)

    @staticmethod
    def decode_gcc_crew_standings(response: Any):
        """Decode supplied GCC results offline; does NOT issue any read.

        The native GCC viewcrew route's complete signed request and active
        season selection have not been verified. Do not use a generic event
        board as a substitute.
        """
        from csr2cdn.service_models import GCCCrewStandings
        return GCCCrewStandings.from_response(response)

    def prepare_gcc_progress(self) -> ReadContract:
        """Offline native 6.8.0 GCC CURRENT progress read (experimental route)."""
        return gcc_progress_contract(app_version=self.app_version)

    def get_gcc_progress_response(self) -> Any:
        """Explicit opt-in current GCC read. Return in-memory JSON for cautious inspection.

        Uses the APK's metadata-default route prefix, not a verified current
        runtime override/season selector. No saved response or account writes.
        """
        return self._read(self.prepare_gcc_progress())

    def prepare_gcc_progress_range(self, ranges: StandingRange, *,
                                   exploratory: bool = False) -> ReadContract:
        """Prepare an unverified, bounded GCC range without I/O.

        The published default `prepare_gcc_progress` remains unchanged.
        Native generic range serialization is known; expanded GCC server
        behavior (including offset) is not. No automatic paging is provided.
        """
        return gcc_progress_range_contract(ranges, app_version=self.app_version,
                                           exploratory=exploratory)

    def get_gcc_progress_range_response(self, ranges: StandingRange, *,
                                        exploratory: bool = False) -> Any:
        """One experimental read from the established GCC route, opt-in only."""
        return self._read(self.prepare_gcc_progress_range(
            ranges, exploratory=exploratory))

    def get_gcc_progress_range(self, ranges: StandingRange, *,
                               exploratory: bool = False):
        """Decode one opt-in GCC progress range into typed crew standings.

        The server's treatment of non-common ranges and offsets is not yet
        validated. This method does not page, cache or claim completeness.
        """
        from .service_models import GCCProgressCrewScores
        response = self.get_gcc_progress_range_response(
            ranges, exploratory=exploratory)
        return GCCProgressCrewScores.from_response(response)

    def get_crew_rp_snapshot(self, *, expected_member_count: Optional[int] = None,
                             previous=None, season_marker: Optional[str] = None,
                             now_utc: Optional[datetime] = None,
                             max_age_seconds: float = 300,
                             max_read_gap_seconds: float = 30):
        """Read own-crew contributions and GCC standings as a guarded snapshot.

        Makes exactly three authorized read-only calls in order: fresh own-crew
        membership, its member roster, and the observed GCC progress endpoint.
        Caller must explicitly construct this service with allow_network=True.
        The scores are a tested data-source pairing, *not* server-certified
        14-day season identity; requests are sequential, not atomic. Roster
        count is derived from the own-crew memberCount if the server supplies
        one, unless the caller explicitly overrides it.
        """
        from .crew_rp import CrewRPSnapshot
        from .crew_season import _nonnegative_int
        from .service_models import GCCProgressCrewScores

        own = self.get_my_crew(refresh=True)
        if not own.crew_uid:
            raise ReadContractError("account has no resolved crew membership")
        roster = self.get_crew_members(crew_uid=own.crew_uid)
        member_read_at = datetime.now(timezone.utc)
        board = GCCProgressCrewScores.from_response(self.get_gcc_progress_response())
        gcc_read_at = datetime.now(timezone.utc)
        inferred = (own.member_count if type(own.member_count) is int
                    and 1 <= own.member_count <= 30 else None)
        return CrewRPSnapshot.from_reads(
            roster, board, own_crew_id=own.crew_uid,
            member_read_utc=member_read_at, gcc_read_utc=gcc_read_at,
            expected_member_count=(expected_member_count if expected_member_count is not None
                                   else inferred),
            previous=previous, season_marker=season_marker, now_utc=now_utc,
            own_crew_rp_unverified=_nonnegative_int(own.extras.get("crew_rp")),
            own_crew_garage_value_unverified=_nonnegative_int(own.extras.get("crew_garage_value")),
            max_age_seconds=max_age_seconds, max_read_gap_seconds=max_read_gap_seconds,
        )

    def get_crew_endpoint_inventory(self, *, show_stat_candidates: bool = False,
                                    show_gcc_metadata: bool = False):
        """Audit exactly three existing read-only responses without storing JSON.

        The ordinary typed getters lose the original response envelope. This
        separate opt-in flow inspects it in memory, using the same validated
        own-crew, members and GCC progress read contracts. An explicit
        allow_network=True service is still required for any network access.
        No new URL, pagination variant or write action is introduced.
        """
        from .crew_endpoint_inventory import build_endpoint_inventory
        own_response = self._read(self.prepare_my_crew())
        own = self.decode_my_crew(own_response)
        if not own.crew_uid:
            raise ReadContractError("account has no resolved crew membership")
        members_response = self._read(self.prepare_crew_members(own.crew_uid))
        member_read_at = datetime.now(timezone.utc)
        gcc_response = self.get_gcc_progress_response()
        gcc_read_at = datetime.now(timezone.utc)
        return build_endpoint_inventory(
            own_response, members_response, gcc_response,
            show_stat_candidates=show_stat_candidates,
            show_gcc_metadata=show_gcc_metadata,
            member_read_utc=member_read_at, gcc_read_utc=gcc_read_at,
        )

    def get_crew_optional_snapshot(self):
        """Opt-in optional crew/member/vehicle details from exactly two reads.

        This does not request GCC or any car-specific endpoint. All optional
        field values are unverified, and ordinary repr excludes member IDs.
        Live access still requires the service's allow_network=True guard.
        """
        from .crew_optional_data import CrewOptionalSnapshot
        own = self.get_my_crew(refresh=True)
        if not own.crew_uid:
            raise ReadContractError("account has no resolved crew membership")
        roster = self.get_crew_members(crew_uid=own.crew_uid)
        return CrewOptionalSnapshot.from_reads(own, roster)

    def get_crew_members(self, crew_uid: Optional[str] = None, *, refresh_crew: bool = False) -> CrewMembers:
        """Get own crew members by default; optional ID selects a known crew.

        Own-crew discovery happens once per cache window; no save API involved.
        """
        if crew_uid is None:
            crew_uid = self.get_my_crew(refresh=refresh_crew).crew_uid
            if crew_uid is None:
                raise ReadContractError("account has no resolved crew membership")
        return self.decode_crew_members(crew_uid, self._read(self.prepare_crew_members(crew_uid)))

    def _board(self, kind: str, event_id: Optional[str], leaderboard_name: Optional[str],
               *, season: Optional[str] = None, segment: Optional[str] = None,
               instance: Optional[str] = None, crew_id: Optional[str] = None,
               refresh: bool = False) -> tuple[str, Optional[str]]:
        if leaderboard_name is not None:
            # Explicit board is a user supplied identifier, never inferred by
            # treating the event ID as a URL segment.
            return _identifier(leaderboard_name, name="leaderboard_name"), None
        if not event_id or self.events is None:
            raise EventResolutionError("pass leaderboard_name or configure EventCatalog for event ID discovery")
        entry = self.events.resolve(event_id, kind, season=season, segment=segment,
                                    instance=instance, crew_id=crew_id, refresh=refresh)
        return entry.leaderboard_name, entry.score_unit

    def _standings_contract(self, kind: str, *, event_id: Optional[str] = None,
                            leaderboard_name: Optional[str] = None,
                            ranges: Optional[StandingRange] = None,
                            season: Optional[str] = None, segment: Optional[str] = None,
                            instance: Optional[str] = None, crew_id: Optional[str] = None,
                            refresh: bool = False, score: Optional[int] = None,
                            show_default: Optional[bool] = None) -> tuple[ReadContract, Optional[str]]:
        board, unit = self._board(kind, event_id, leaderboard_name, season=season,
                                 segment=segment, instance=instance, crew_id=crew_id,
                                 refresh=refresh)
        ranges = ranges if ranges is not None else StandingRange.common()
        if kind == "showdown_leagues":
            if score is not None or show_default is not None:
                raise ReadContractError("Showdown Leagues standings do not accept event-only options")
            contract = showdown_standings_contract(board, ranges, app_version=self.app_version)
        else:
            contract = event_standings_contract(board, ranges, app_version=self.app_version,
                                                score=score, show_default=show_default)
        return contract, unit

    @staticmethod
    def decode_leaderboard(leaderboard_name: str, response: Any, *,
                           score_unit: Optional[str] = None) -> LeaderboardPage:
        return LeaderboardPage.from_response(leaderboard_name, response, score_unit=score_unit)

    def prepare_current_showdown(self, discovery: ShowdownDiscovery, *, at=None,
                                 refresh: bool = False, ranges: Optional[StandingRange] = None) -> ReadContract:
        """Offline-only: resolve a scheduled Showdown to a *known* server board ID.

        The schedule preflight cannot establish player-specific eligibility or
        actual service availability. No network calls occur in this method.
        """
        if not isinstance(discovery, ShowdownDiscovery):
            raise TypeError("discovery must be ShowdownDiscovery")
        board = discovery.resolve_current_board(at=at, refresh=refresh)
        return self.prepare_showdown(leaderboard_name=board, ranges=ranges)

    def get_current_showdown_leaderboard(self, discovery: ShowdownDiscovery, *, at=None,
                                        refresh: bool = False,
                                        ranges: Optional[StandingRange] = None) -> LeaderboardPage:
        """Use a discovered board for a read (requires allow_network=True)."""
        contract = self.prepare_current_showdown(discovery, at=at, refresh=refresh, ranges=ranges)
        return self.decode_leaderboard(contract.route.split("/")[1], self._read(contract),
                                       score_unit=None)

    def _resolve_named_showdown(self, showdown_name: str,
                                discovery: Optional[ShowdownDiscovery] = None,
                                *, at=None, refresh: bool = False) -> str:
        """Resolve an active board without taking raw event IDs from the user.

        With a supplied ShowdownDiscovery, this is an offline lookup. Without
        one, it retrieves current metadata using the existing CDN facilities.
        This is the only place that performs implicit metadata network I/O.
        """
        if discovery is not None:
            return discovery.resolve_named(showdown_name, at=at, refresh=refresh).leaderboard_name
        if not self.allow_network:
            raise ServiceNetworkDisabled("automatic Showdown discovery requires allow_network=True or an offline metadata source")
        from csr2cdn.cdn import CDN
        from csr2cdn.metadata import MetadataClient
        with CDN(zid=self.player_id, release_version=self.app_version, probe=False) as cdn:
            product_version = cdn.product_version
            with MetadataClient(timeout=self.timeout) as metadata:
                lookup = ShowdownDiscovery.from_metadata(metadata, player_id=self.player_id,
                                                         product_version=product_version,
                                                         asset_cdn=cdn if hasattr(cdn, "get_database") else None)
                return lookup.resolve_named(showdown_name, at=at, refresh=refresh).leaderboard_name

    def prepare_showdown(self, *, showdown_name: Optional[str] = None,
                         discovery: Optional[ShowdownDiscovery] = None, at=None,
                         **options: Any) -> ReadContract:
        """Prepare an event standings read by visible Showdown name.

        A caller may provide a local/fixture discovery source for fully offline
        preparation. Without it, request preparation remains offline by default.
        """
        if showdown_name is not None:
            if options.get("event_id") or options.get("leaderboard_name"):
                raise EventResolutionError("choose showdown_name or explicit identifiers")
            options["leaderboard_name"] = self._resolve_named_showdown(
                showdown_name, discovery, at=at, refresh=bool(options.get("refresh", False)))
        elif discovery is not None:
            raise EventResolutionError("discovery requires showdown_name")
        return self._standings_contract("showdown", **options)[0]

    def prepare_prestige_cup(self, **options: Any) -> ReadContract:
        options.setdefault("show_default", True)
        return self._standings_contract("prestige_cup", **options)[0]

    def prepare_current_prestige_cup(self, discovery, *, at=None, refresh=False, ranges=None) -> ReadContract:
        """Build a read for the currently resolved cup; never guess an absent ID."""
        from csr2cdn.service_prestige import PrestigeCupDiscovery
        if not isinstance(discovery, PrestigeCupDiscovery):
            raise TypeError("discovery must be PrestigeCupDiscovery")
        selected = discovery.resolve_current(at=at, refresh=refresh)
        default_range = ranges or StandingRange.common()
        rng = StandingRange(top=default_range.top, after=default_range.after,
                            before=default_range.before, offset=selected.offset)
        return self.prepare_prestige_cup(leaderboard_name=selected.leaderboard_name, ranges=rng)

    def _resolve_current_prestige(self, *, at=None, season=None, prestige_car_tier=None,
                                  prestige_car_key=None):
        """Return only a verified metadata-derived board and its range offset.

        Sources are the standalone cup-series metadata plus current common
        event bundles, not the Showdown group-name filter. No game-service
        requests are made until the complete identity has been resolved.
        """
        if not self.allow_network:
            raise ServiceNetworkDisabled("automatic Prestige Cup discovery requires allow_network=True")
        from csr2cdn.cdn import CDN
        from csr2cdn.metadata import MetadataClient
        from csr2cdn.service_prestige import PrestigeCupDiscovery
        with CDN(zid=self.player_id, release_version=self.app_version, probe=False) as cdn:
            with MetadataClient(timeout=self.timeout) as metadata:
                lookup = PrestigeCupDiscovery.from_metadata(
                    metadata, player_id=self.player_id,
                    product_version=cdn.product_version, asset_cdn=cdn,
                    native_season=season, native_car_tier=prestige_car_tier,
                    native_car_key=prestige_car_key)
                return lookup.resolve_current(at=at)

    def get_current_prestige_cup_leaderboard(self, discovery=None, *, at=None, refresh=False,
                                            ranges=None, season=None, prestige_car_tier=None,
                                            prestige_car_key=None) -> LeaderboardPage:
        """Current Prestige Cup standings using only PlayerID when network enabled.

        Supplying a discovery object retains fully offline fixture support.
        """
        if discovery is None:
            selected = self._resolve_current_prestige(
                at=at, season=season, prestige_car_tier=prestige_car_tier,
                prestige_car_key=prestige_car_key)
            default = ranges or StandingRange.common()
            current_range = StandingRange(top=default.top, after=default.after,
                                          before=default.before, offset=selected.offset)
            return self.get_prestige_cup_leaderboard(
                leaderboard_name=selected.leaderboard_name, ranges=current_range)
        contract = self.prepare_current_prestige_cup(discovery, at=at, refresh=refresh, ranges=ranges)
        return self.decode_leaderboard(contract.route.split("/")[1], self._read(contract))

    def prepare_showdown_leagues(self, **options: Any) -> ReadContract:
        return self._standings_contract("showdown_leagues", **options)[0]

    def get_showdown_leaderboard(self, *, showdown_name: Optional[str] = None,
                                 discovery: Optional[ShowdownDiscovery] = None, at=None,
                                 **options: Any) -> LeaderboardPage:
        """Read standings by Showdown name and PlayerID (network opt-in).

        If no `discovery` was supplied, current game metadata is fetched
        automatically. Player-specific entitlement is only verified by the
        live server; this method never asserts that a schedule alone grants it.
        """
        if showdown_name is not None:
            if options.get("event_id") or options.get("leaderboard_name"):
                raise EventResolutionError("choose showdown_name or explicit identifiers")
            options["leaderboard_name"] = self._resolve_named_showdown(
                showdown_name, discovery, at=at, refresh=bool(options.get("refresh", False)))
        elif discovery is not None:
            raise EventResolutionError("discovery requires showdown_name")
        contract, unit = self._standings_contract("showdown", **options)
        return self.decode_leaderboard(contract.route.split("/")[1], self._read(contract), score_unit=unit)

    def prepare_prestige_cup_crew_leaderboard(
            self, *, leaderboard_name: str,
            ranges: Optional[StandingRange] = None) -> ReadContract:
        """Prepare native event Crew tab read without a network request.

        This requests **Prestige players from the authenticated crew**, not
        Grand Crew Championship crew RP standings. The board identity must
        have been resolved independently; do not infer it from the crew UID.
        """
        return event_crew_standings_contract(
            leaderboard_name, ranges=ranges, app_version=self.app_version)

    def get_prestige_cup_crew_leaderboard(
            self, *, leaderboard_name: str,
            ranges: Optional[StandingRange] = None) -> LeaderboardPage:
        """Read the native crew-filtered Prestige tab; live schema pending.

        Caller opts into network access through ``allow_network=True``.
        Unlike a global leaderboard filtered locally, this sends the game's
        separate ``scores/crewmembers`` operation to the authenticated server.
        """
        contract = self.prepare_prestige_cup_crew_leaderboard(
            leaderboard_name=leaderboard_name, ranges=ranges)
        response = self._read(contract)
        try:
            return self.decode_leaderboard(leaderboard_name, response,
                                           score_unit="microseconds")
        except ServiceResponseError:
            raise PrestigeCrewSchemaError(
                "crew-filtered Prestige response schema not yet recognized",
                structure=_prestige_crew_safe_shape(response)) from None

    def get_current_prestige_cup_crew_leaderboard(
            self, discovery=None, *, at=None, refresh=False, ranges=None,
            season=None, prestige_car_tier=None,
            prestige_car_key=None) -> LeaderboardPage:
        """Read crew-filtered standings for a resolved current Prestige Cup.

        Uses the same native resolver as the global view. No guessed season,
        board, or crew list is used. The selected event range offset is
        preserved for the native crew-tab range. Response/UI equivalence
        still requires the next operator-authorized live check.
        """
        if discovery is None:
            selected = self._resolve_current_prestige(
                at=at, season=season, prestige_car_tier=prestige_car_tier,
                prestige_car_key=prestige_car_key)
        else:
            from csr2cdn.service_prestige import PrestigeCupDiscovery
            if not isinstance(discovery, PrestigeCupDiscovery):
                raise TypeError("discovery must be PrestigeCupDiscovery")
            selected = discovery.resolve_current(at=at, refresh=refresh)
        rng = ranges if ranges is not None else StandingRange.native_event_crew()
        final_range = StandingRange(top=rng.top, after=rng.after,
                                    before=rng.before, offset=selected.offset)
        return self.get_prestige_cup_crew_leaderboard(
            leaderboard_name=selected.leaderboard_name, ranges=final_range)

    def get_prestige_cup_leaderboard(self, **options: Any) -> LeaderboardPage:
        if not options:
            return self.get_current_prestige_cup_leaderboard()
        options.setdefault("show_default", True)
        contract, unit = self._standings_contract("prestige_cup", **options)
        return self.decode_leaderboard(contract.route.split("/")[1], self._read(contract), score_unit=unit)

    def get_showdown_leagues_leaderboard(self, **options: Any) -> LeaderboardPage:
        contract, unit = self._standings_contract("showdown_leagues", **options)
        return self.decode_leaderboard(contract.route.split("/")[1], self._read(contract), score_unit=unit)

    def prepare_showdown_leagues_score(self, leaderboard_name: str, *, period_offset: int = 0) -> ReadContract:
        return showdown_leagues_score_contract(leaderboard_name, period_offset=period_offset,
                                                app_version=self.app_version)

    def get_showdown_leagues_score(self, leaderboard_name: str, *, period_offset: int = 0) -> LeaderboardScore:
        contract = self.prepare_showdown_leagues_score(leaderboard_name, period_offset=period_offset)
        return LeaderboardScore.from_response(leaderboard_name, self._read(contract),
                                              period_offset=period_offset)

    def prepare_showdown_leagues_preview(self, leaderboard_name: str, *, score: int,
                                        ranges: Optional[StandingRange] = None) -> ReadContract:
        return showdown_standings_contract(leaderboard_name, ranges or StandingRange.preview(),
                                            preview=True, score=score, app_version=self.app_version)

    def get_showdown_leagues_preview(self, leaderboard_name: str, *, score: int,
                                    ranges: Optional[StandingRange] = None) -> LeaderboardPage:
        contract = self.prepare_showdown_leagues_preview(leaderboard_name, score=score, ranges=ranges)
        return self.decode_leaderboard(leaderboard_name, self._read(contract))


__all__ = ["CSR2Services", "ServiceNetworkDisabled", "ServiceHTTPError"]
