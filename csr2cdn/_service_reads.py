"""UNRELEASED, internal offline read-contract reconstruction for CSR2 6.8.0.

Do not treat these prepared requests as demonstrated live compatibility.
ARM64 request construction and IL2CPP string literals establish operation names,
request types, routes and selected wire keys; server response schemas are not
verified. No network I/O, saved profile, upload or save download is supported.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from csr2cdn._service_auth import (
    PortalCredentials, PreparedRequest, ServiceAuthError, _prepare_signed_json,
)


class ReadContractError(ServiceAuthError):
    """Input is not admissible for a traced read-only game-service operation."""


@dataclass(frozen=True)
class ReadContract:
    """Inspectable, offline-only reconstruction of a single read operation.

    ``params`` preserves native insertion order for signing comparisons.
    ``request_type`` is the compiled ``WebRequestQueue.StartCall`` category.
    """

    route: str
    params: Mapping[str, Any]
    request_type: int
    operation: str


def _identifier(value: str, *, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", value):
        raise ReadContractError(f"{name} must be a nonempty URL-path-safe identifier")
    return value


def _version(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", value):
        raise ReadContractError("app_version must be a numeric dotted game version")
    return value


def _i32(value: int, *, name: str) -> int:
    # Python bool is an int but not a valid native 32-bit range selector.
    if type(value) is not int or not -(2**31) <= value < 2**31:
        raise ReadContractError(f"{name} must be a signed 32-bit integer")
    return value


@dataclass(frozen=True)
class StandingRange:
    """Four wire inputs observed in the native Showdown Leagues builder.

    Their integer domain is verified, but server-side cursor/range behavior
    and the right defaults are NOT; callers must choose the three parameters
    explicitly, rather than the library inventing paging values.
    """

    after: int
    before: int
    offset: int
    top: Optional[int] = None

    @classmethod
    def common(cls) -> "StandingRange":
        """Native `SetupWithCommonRange` (RVA 0x2bdc660)."""
        return cls(after=5, before=5, offset=0, top=10)

    @classmethod
    def preview(cls) -> "StandingRange":
        """Native `SetupWithPreviewRange` (RVA 0x2bdc674): omit INT_MIN top."""
        return cls(after=4, before=4, offset=0, top=None)

    @classmethod
    def top3_and_you(cls) -> "StandingRange":
        """Native `SetupWithTop3AndYouRange` (RVA 0x2bdc688)."""
        return cls(after=0, before=0, offset=0, top=3)

    @classmethod
    def prestige_ui_window(cls, *, offset: int = 0) -> "StandingRange":
        """Operator-observed Prestige UI scope: global top 20 plus +/-10.

        These numbers are admissible to the game's native generic range
        serializer, but its exact UI call-site has NOT been independently
        established. Treat this as an explicit opt-in validation range.
        """
        return cls(top=20, after=10, before=10, offset=_i32(offset, name="offset"))

    @classmethod
    def native_event_crew(cls, *, offset: int = 0) -> "StandingRange":
        """EventLeaderboard crew mode (0x33896f0 => 0x2be23a0, mode 2).

        The mode retains top=10 from the common initializer and writes 30
        into after/before. It is NOT the GCC viewcrew top-10+/-5 request.
        """
        return cls(top=10, after=30, before=30, offset=_i32(offset, name="offset"))

    def as_wire_params(self) -> Mapping[str, int]:
        after = _i32(self.after, name="after")
        before = _i32(self.before, name="before")
        offset = _i32(self.offset, name="offset")
        items = OrderedDict()
        if self.top is not None:
            top = _i32(self.top, name="top")
            # The native method omits the top key for INT_MIN.
            if top == -(2**31):
                raise ReadContractError("use top=None to omit the native INT_MIN sentinel")
            items["top"] = top
        items["after"] = after
        items["before"] = before
        items["offset"] = offset
        return items


def own_crew_contract(*, app_version: str = "6.8.0") -> ReadContract:
    """Read own crew: native PlayerCrewNetwork.CheckUserCrew, RVA 0x34ffd64.

    Its compiled builder sends only `app_ver` in the request dictionary,
    queues `crews/checkUserCrew` with category 3 and parses a response that
    declares `crewUID`. No PlayerID-to-crew mapping is bundled.
    """
    return ReadContract("crews/checkUserCrew",
                        OrderedDict([("app_ver", _version(app_version))]),
                        3, "Check User Crew")


def crew_members_contract(crew_uid: str, *, app_version: str = "6.8.0") -> ReadContract:
    """`PlayerCrewNetwork.FetchCrewMembers`, RVA 0x350203c, type 3.

    Native parameters are `crew_uid` then `app_ver`, using the GetAppID value.
    `app_ver` is the caller-selected version here rather than downloaded at runtime.
    """
    uid = _identifier(crew_uid, name="crew_uid")
    return ReadContract(
        "crews/viewMembers", OrderedDict([("crew_uid", uid), ("app_ver", _version(app_version))]),
        3, "Get Crew Member List",
    )


def showdown_standings_contract(
    leaderboard_name: str,
    ranges: StandingRange,
    *,
    preview: bool = False,
    score: Optional[int] = None,
    app_version: str = "6.8.0",
) -> ReadContract:
    """Showdown Leagues progress/preview, RVAs 0x2ead984 and 0x2eadd24.

    This is the *Showdown Leagues* provider, NOT a general Showdown event-
    trophies or Prestige Cup leaderboard implementation. `leaderboard_name`
    must already be resolved by authoritative game/event metadata.
    """
    board = _identifier(leaderboard_name, name="leaderboard_name")
    if not isinstance(ranges, StandingRange):
        raise ReadContractError("ranges must be StandingRange")
    if preview and score is None:
        raise ReadContractError("preview requires explicit score")
    if not preview and score is not None:
        raise ReadContractError("progress does not accept preview score")
    params = OrderedDict([("app_ver", _version(app_version))])
    params.update(ranges.as_wire_params())
    if preview:
        params["score"] = _i32(score, name="score")
    return ReadContract(
        f"leaderboard/{board}/{'preview' if preview else 'view'}",
        params, 5,
        "Fetches showdown leagues preview" if preview else
        "Fetches the single player leaderboard current progress",
    )



def event_standings_contract(
    leaderboard_name: str,
    ranges: StandingRange,
    *,
    app_version: str = "6.8.0",
    score: Optional[int] = None,
    show_default: Optional[bool] = None,
) -> ReadContract:
    """First-pass generic event-leaderboard read for Showdown and Prestige Cup.

    Native `PlayerCrewNetwork.FetchEventLeaderboardProgress` (0x35050a4)
    serializes app_ver, top/after/before/offset and optional score and
    show_default. Its `leaderboard_name` parameter is prepared upstream.
    We provisionally use the separately traced `leaderboard/{name}/view`
    read route. The binding of this route to classic Showdown and Prestige
    Cup is NOT verified until the final live test.
    """
    board = _identifier(leaderboard_name, name="leaderboard_name")
    if not isinstance(ranges, StandingRange):
        raise ReadContractError("ranges must be StandingRange")
    params = OrderedDict([("app_ver", _version(app_version))])
    params.update(ranges.as_wire_params())
    if score is not None:
        params["score"] = _i32(score, name="score")
    if show_default is not None:
        if type(show_default) is not bool:
            raise ReadContractError("show_default must be a boolean")
        params["show_default"] = show_default
    return ReadContract(f"leaderboard/{board}/view", params, 5,
                        "Fetches an Event leaderboard current progress")



def event_crew_standings_contract(
    leaderboard_name: str,
    ranges: Optional[StandingRange] = None,
    *,
    app_version: str = "6.8.0",
) -> ReadContract:
    """Read-only EventLeaderboard crew tab, **not** GCC seasonal RP.

    Native EventLeaderboard.RefreshCrewStandings (0x33896f0) calls
    GetLeaderboardURL(mode=1, 0x3389188), selecting
    ``leaderboard/{0}/scores/crewmembers``. It passes the native crew
    range mode 2 to EventLeaderboard's request helper (0x2be23a0), which
    delegates to FetchEventLeaderboardProgress (0x35050a4). The 6.8.0
    native wire keys are app_ver/top/after/before/offset, request type 5.

    No authenticated response from this route has yet been observed. The
    decoder must not infer the meaning of scores or completeness of rows.
    """
    board = _identifier(leaderboard_name, name="leaderboard_name")
    selected = ranges if ranges is not None else StandingRange.native_event_crew()
    if not isinstance(selected, StandingRange):
        raise ReadContractError("ranges must be StandingRange")
    params = OrderedDict([("app_ver", _version(app_version))])
    params.update(selected.as_wire_params())
    return ReadContract(f"leaderboard/{board}/scores/crewmembers", params, 5,
                        "Fetches event crew-member standings")


def showdown_leagues_score_contract(
    leaderboard_name: str, *, period_offset: int = 0,
    app_version: str = "6.8.0",
) -> ReadContract:
    """Native Showdown Leagues `leaderboard/{0}/score` read (0x2eae0f4).

    The compiled builder sets `signed=true` and `extra=true`; neither
    flag is caller-controlled. `period_offset` selects a time period, not
    a result-page cursor. Final wire behavior remains live-unverified.
    """
    board = _identifier(leaderboard_name, name="leaderboard_name")
    return ReadContract(f"leaderboard/{board}/score", OrderedDict([
        ("app_ver", _version(app_version)),
        ("offset", _i32(period_offset, name="period_offset")),
        ("signed", True), ("extra", True),
    ]), 5, "Fetches showdown leagues leaderboard score")



# 6.8.0 GCC rewards metadata carries this default endpoint prefix. The
# compiled GetLeaderboardURL (0x38aa8fc) string-concatenates its runtime
# configured prefix with `viewcrew`. The actual runtime prefix and season
# identity have NOT been checked on an authenticated session.
GCC_METADATA_DEFAULT_PREFIX = "leaderboard/crew-champs-v2/"


def gcc_progress_contract(*, endpoint_prefix: str = GCC_METADATA_DEFAULT_PREFIX,
                          app_version: str = "6.8.0") -> ReadContract:
    """Experimental GCC CURRENT progress read, with explicit opt-in only.

    GrandCrewChampionshipManager.RequestLBDataProgress (0x38a7dac)
    calls GetLeaderboardURL(..., false) => prefix + `viewcrew`, and
    PlayerCrewManager.FetchGrandCrewChampionshipProgress (0x34b83b8)
    calls PlayerCrewNetwork.FetchGrandCrewChampionshipProgress (0x3504770).
    The fetch writes `app_ver`, `top`, `after`, `before`, `offset` and queues
    request type 3. The caller uses SetupWithCommonRange (0x2bdc660).
    This route may depend on runtime metadata not packaged here.
    """
    if endpoint_prefix != GCC_METADATA_DEFAULT_PREFIX:
        raise ReadContractError("GCC endpoint prefix differs from the APK default; runtime overrides have not been verified")
    params = OrderedDict([("app_ver", _version(app_version))])
    params.update(StandingRange.common().as_wire_params())
    return ReadContract(endpoint_prefix + "viewcrew", params, 3,
                        "Fetches GCC current progress (experimental)")

# Bounded exploration of the SAME read-only GCC route. The 6.8.0 native
# generic standings serializer accepts these four integers, but the GCC UI
# call site was observed using common(); arbitrary ranges are NOT verified.
_GCC_RANGE_PROBE_OPERATION = "Fetches GCC current progress (bounded range probe; unverified)"


def gcc_progress_range_contract(ranges: StandingRange, *, app_version: str = "6.8.0",
                                exploratory: bool = False) -> ReadContract:
    """Explicitly opt in to one bounded GCC progress range, never crawling.

    No full pagination/offset semantics are inferred. Avoid the native signed
    32-bit domain's huge values until a server response establishes behavior.
    Keep the known common-range production method separate.
    """
    if exploratory is not True:
        raise ReadContractError("exploratory=True required for a GCC range probe")
    if not isinstance(ranges, StandingRange):
        raise ReadContractError("an explicit StandingRange is required")
    if (type(ranges.top) is not int or not 1 <= ranges.top <= 50 or
            type(ranges.after) is not int or not 0 <= ranges.after <= 30 or
            type(ranges.before) is not int or not 0 <= ranges.before <= 30 or
            type(ranges.offset) is not int or not 0 <= ranges.offset <= 1000 or
            ranges.top + ranges.before + ranges.after > 100):
        raise ReadContractError("GCC probe ranges must be bounded (top 1..50, before/after 0..30, offset 0..1000, total <=100)")
    params = OrderedDict([("app_ver", _version(app_version))])
    params.update(ranges.as_wire_params())
    return ReadContract(GCC_METADATA_DEFAULT_PREFIX + "viewcrew", params, 3,
                        _GCC_RANGE_PROBE_OPERATION)


# ---------------------------------------------------------------------------
# 0.7.2 additions, reconstructed from the 6.8.0 IL2CPP metadata rather than
# from ARM64 disassembly. Provenance differs from the contracts above and is
# weaker in one specific way: method *parameter* names are compiled into
# `global-metadata.dat` and are quoted verbatim below, but they are C#
# identifiers, not wire keys. Each wire key used here is additionally present
# as a string literal in the same metadata, and follows the spelling already
# proven for `crew_uid`/`app_ver`/`top`/`before`/`after`/`offset`. Parameter
# *order* within the request dictionary is NOT established for these routes.
# None of these has been answered by a live server.

def crew_event_progress_contract(crew_uid: str, event_id: str, series_id: str, *,
                                 app_version: str = "6.8.0") -> ReadContract:
    """Crew-aggregate progress for one event series.

    `PlayerCrewNetwork.FetchCrewEventProgress(crewUID, eventID, seriesID,
    completionDelegate)` is answered by `FetchCrewEventProgressResponse`,
    whose single field `crewEventProgress` carries `CrewEventProgress`
    {isValid, progress, participated}.

    The figure is a crew total. The client submits each race individually via
    `RaceInCrewEventRaceTransaction` {m_Reason, m_event_id, m_series_id,
    m_is_win, m_race_number, m_race_time}, but the server publishes no
    per-member breakdown on this route.

    Request type 4 is the `EWebRequestType.Events` ordinal, inferred from the
    enum's declaration order and the `events/` route prefix; it is carried for
    documentation only and nothing dispatches on it.
    """
    return ReadContract(
        "events/crewEventProgress",
        OrderedDict([("crew_uid", _identifier(crew_uid, name="crew_uid")),
                     ("event_id", _identifier(event_id, name="event_id")),
                     ("series_id", _identifier(series_id, name="series_id")),
                     ("app_ver", _version(app_version))]),
        4, "Fetches crew event progress")


def crew_rankings_contract(crew_uid: str, *, top: int, before: int, after: int,
                           app_version: str = "6.8.0") -> ReadContract:
    """Crew leaderboard standing with its immediate neighbours.

    `PlayerCrewNetwork.FetchCrewRankings(crewUID, top, before, after,
    completionDelegate)` is answered by `FetchCrewRankResponse` {crewUID,
    crewRank, topCrews, crewsJustAbove, crewsJustBelow}.

    Note the native signature takes no `offset`, so `StandingRange` does not
    apply: it always serializes one. The three selectors are bounded here to
    keep a single read from turning into a crawl.

    **Live status: HTTP 500.** Tried on 2026-11-06 in five shapes -- as built
    here, with an added `offset`, with only `crew_uid`/`app_ver`, without
    `crew_uid`, and with the keys reordered. All five returned 500, so the
    failure is not about these keys. `PlayerCrewNetwork` carries a
    `lastCrewLeaderboardNameFetched` field, which suggests the call also wants
    a leaderboard name that neither the method signature nor the literal table
    reveals. Until that is found this contract is not usable.
    """
    if not 1 <= _i32(top, name="top") <= 50:
        raise ReadContractError("top must be 1..50")
    if not 0 <= _i32(before, name="before") <= 30:
        raise ReadContractError("before must be 0..30")
    if not 0 <= _i32(after, name="after") <= 30:
        raise ReadContractError("after must be 0..30")
    return ReadContract(
        "crews/showCrewsRanks",
        OrderedDict([("crew_uid", _identifier(crew_uid, name="crew_uid")),
                     ("app_ver", _version(app_version)),
                     ("top", top), ("before", before), ("after", after)]),
        3, "Fetches crew rankings")




#: Both spellings exist as string literals in 6.8.0. Live, 2026-11-06: the
#: plural answers with the wildcard state and the singular with something that
#: is not JSON, so the plural comes first and is the default.
WILDCARD_ROUTES = ("wildcards/status", "wildcard/status")


def wildcard_status_contract(*, route: str = WILDCARD_ROUTES[0],
                             app_version: str = "6.8.0") -> ReadContract:
    """Crew wildcard season state.

    `PlayerCrewNetwork.FetchWildcardStatus(completionDelegate)` takes no
    inputs beyond the app version, and is answered by
    `FetchWildcardStatusResponse` {seasonEndTime, token, wildcardDataList,
    lastmessage_ID}. Each `WildcardData` declares 17 fields including
    rarity, rpBonus, duration, cost, paid, activated, endTime and zid.
    """
    if route not in WILDCARD_ROUTES:
        raise ReadContractError("route must be one of the two traced wildcard spellings")
    return ReadContract(route, OrderedDict([("app_ver", _version(app_version))]),
                        3, "Fetches wildcard status")


def crew_perks_contract(crew_uid: str, *, app_version: str = "6.8.0") -> ReadContract:
    """Crew perk milestones and unlocks.

    `PlayerCrewNetwork.FetchCrewPerks(crewUID, completionDelegate)` feeds
    `PlayerCrewPerks.FromJSONDict`, whose fields are m_milestoneList,
    CurrentMilestone, PerkGroupsUnlocked, PerksUnlocked, CrewRespectRank
    and CrewCash.
    """
    return ReadContract(
        "crews/checkCrewPerks",
        OrderedDict([("crew_uid", _identifier(crew_uid, name="crew_uid")),
                     ("app_ver", _version(app_version))]),
        3, "Fetches crew perks")


# ---------------------------------------------------------------------------
# Account-state reads, verified live 2026-11-15. Each is a read of the
# authenticated player's own server-side state over prod-web, and takes only
# the app version. `request_type` is a documentary category and is not used in
# signing; 1 groups these account/game-state reads, as 3 groups crew and 5
# leaderboard. None involves a write.

def season_pass_contract(*, app_version: str = "6.8.0") -> ReadContract:
    """`season_pass/season_pass_info` -> season, points, rewards, tasks."""
    return ReadContract("season_pass/season_pass_info",
                        OrderedDict([("app_ver", _version(app_version))]),
                        1, "Fetches season pass info")


def collections_blob_contract(*, app_version: str = "6.8.0") -> ReadContract:
    """`collections/get_collections_blob_data` -> Car Credits wallet."""
    return ReadContract("collections/get_collections_blob_data",
                        OrderedDict([("app_ver", _version(app_version))]),
                        1, "Fetches the collections blob")


#: A Grand Tour schedule id, e.g. ``GRAND_TOUR_SEASON_4_SEG_0``.
_GRAND_TOUR_SCHEDULE = re.compile(r"GRAND_TOUR_SEASON_\d{1,4}_SEG_\d{1,2}")


def grand_tour_contract(active_schedule_id: str, *, app_version: str = "6.8.0") -> ReadContract:
    """`grand_tour/get_season_details`, with the id nested under `extra`.

    `GrandTourWebRequestBase.TriggerRequest` carries the feature's params in an
    `extra` object, so the body is
    ``{"app_ver": ..., "extra": {"activeScheduleId": <id>}}``. `active_schedule_id`
    is a live `GRAND_TOUR_SEASON_<n>_SEG_<m>` from `EventSchedule`; the server
    answers with the player's own segment whichever is sent.
    """
    if not isinstance(active_schedule_id, str) or not _GRAND_TOUR_SCHEDULE.fullmatch(active_schedule_id):
        raise ReadContractError("active_schedule_id must be a GRAND_TOUR_SEASON_<n>_SEG_<m> id")
    return ReadContract("grand_tour/get_season_details",
                        OrderedDict([("app_ver", _version(app_version)),
                                     ("extra", {"activeScheduleId": active_schedule_id})]),
                        1, "Fetches grand tour season details")


#: Prefix of a Collections Tournament race board (the triple dash is literal).
_TOURNAMENT_BOARD = re.compile(
    r"csr2-collections-tournament(?:-debug)?---[0-9]{1,9}-"
    r"[0-9]{1,12}(?:_[0-9]{1,12}){1,7}-Day[0-9]{1,2}_Race[0-9]{1,2}")


def tournament_race_contract(board: str, ranges: StandingRange, *,
                             app_version: str = "6.8.0") -> ReadContract:
    """`leaderboard/{board}/top` for a Collections Tournament race board.

    `board` is composed by `csr2cdn.collections_tournament.board_id` (or
    `standard_board_ids`); this contract will not invent one. The reply decodes
    with `service_models.LeaderboardPage` (score = best time ms, races =
    attempts), request type 5, with `extra: true` as the native builder sets.
    """
    if not isinstance(board, str) or not _TOURNAMENT_BOARD.fullmatch(board):
        raise ReadContractError("not a Collections Tournament race board id")
    if not isinstance(ranges, StandingRange):
        raise ReadContractError("ranges must be StandingRange")
    params = OrderedDict([("app_ver", _version(app_version))])
    params.update(ranges.as_wire_params())
    params["extra"] = True
    return ReadContract(f"leaderboard/{board}/top", params, 5,
                        "Fetches collections tournament standings")


#: The weekly leaderboards reachable with a clean (non-injected) board name.
#: `rp-earned` is verified live; `cash-earned-` needs an injected id and is not
#: offered here.
WEEKLY_LEADERBOARDS = ("rp-earned",)


def weekly_leaderboard_contract(board: str, ranges: StandingRange, *,
                                app_version: str = "6.8.0") -> ReadContract:
    """`leaderboard/{board}/view` for a weekly board such as `rp-earned`.

    Same board shape as the Showdown reads (request type 5); decode the reply
    with `service_models.LeaderboardPage`.
    """
    if board not in WEEKLY_LEADERBOARDS:
        raise ReadContractError("unknown weekly leaderboard")
    if not isinstance(ranges, StandingRange):
        raise ReadContractError("ranges must be StandingRange")
    params = OrderedDict([("app_ver", _version(app_version))])
    params.update(ranges.as_wire_params())
    return ReadContract(f"leaderboard/{board}/view", params, 5,
                        "Fetches a weekly leaderboard")


def prepare_read_contract(
    credentials: PortalCredentials, contract: ReadContract,
    *, web_api_url: str = "https://prod-web.csr2.zynga.com",
    unix_time: Optional[int] = None, nonce: Optional[int] = None,
) -> PreparedRequest:
    """Sign ONLY one of the statically traced read-only request contracts.

    The package never sends this request; a separate, explicit opt-in test
    harness can use it for owned-account compatibility checks.
    """
    if not isinstance(contract, ReadContract):
        raise ReadContractError("a traced ReadContract is required")
    if contract.route == "crews/checkUserCrew" and contract.request_type == 3:
        if tuple(contract.params) != ("app_ver",):
            raise ReadContractError("unexpected own-crew request fields")
        canonical = own_crew_contract(app_version=contract.params["app_ver"])
    elif contract.route == "crews/viewMembers" and contract.request_type == 3:
        if tuple(contract.params) != ("crew_uid", "app_ver"):
            raise ReadContractError("unexpected crew request fields")
        canonical = crew_members_contract(contract.params["crew_uid"], app_version=contract.params["app_ver"])
    elif (contract.route == GCC_METADATA_DEFAULT_PREFIX + "viewcrew" and
          contract.request_type == 3 and
          contract.operation in ("Fetches GCC current progress (experimental)",
                                 _GCC_RANGE_PROBE_OPERATION)):
        if tuple(contract.params) != ("app_ver", "top", "after", "before", "offset"):
            raise ReadContractError("unexpected GCC progress range fields")
        if contract.operation == _GCC_RANGE_PROBE_OPERATION:
            range_fields = StandingRange(
                after=contract.params["after"], before=contract.params["before"],
                offset=contract.params["offset"], top=contract.params["top"])
            canonical = gcc_progress_range_contract(
                range_fields, app_version=contract.params["app_ver"], exploratory=True)
        else:
            canonical = gcc_progress_contract(app_version=contract.params["app_ver"])
    elif (contract.route.startswith("leaderboard/") and
          contract.route.endswith("/scores/crewmembers") and contract.request_type == 5 and
          contract.operation == "Fetches event crew-member standings"):
        parts = contract.route.split("/")
        if len(parts) != 4 or parts[-2:] != ["scores", "crewmembers"]:
            raise ReadContractError("invalid event crew standings route")
        expected = (("app_ver", "top", "after", "before", "offset")
                    if "top" in contract.params else ("app_ver", "after", "before", "offset"))
        if tuple(contract.params) != expected:
            raise ReadContractError("unexpected event crew standings request fields")
        ranges = StandingRange(after=contract.params["after"], before=contract.params["before"],
                               offset=contract.params["offset"], top=contract.params.get("top"))
        canonical = event_crew_standings_contract(
            parts[1], ranges, app_version=contract.params["app_ver"])
    elif (contract.route.startswith("leaderboard/") and contract.request_type == 5
          and contract.route.endswith("/view")
          and contract.route.split("/")[1] in WEEKLY_LEADERBOARDS):
        parts = contract.route.split("/")
        expected = (("app_ver", "top", "after", "before", "offset")
                    if "top" in contract.params else ("app_ver", "after", "before", "offset"))
        if tuple(contract.params) != expected:
            raise ReadContractError("unexpected weekly leaderboard request fields")
        ranges = StandingRange(after=contract.params["after"], before=contract.params["before"],
                               offset=contract.params["offset"], top=contract.params.get("top"))
        canonical = weekly_leaderboard_contract(parts[1], ranges,
                                                app_version=contract.params["app_ver"])
    elif (contract.route.startswith("leaderboard/") and contract.request_type == 5
          and contract.route.endswith("/top")):
        parts = contract.route.split("/")
        if len(parts) != 3:
            raise ReadContractError("invalid tournament board route")
        expected = (("app_ver", "top", "after", "before", "offset", "extra")
                    if "top" in contract.params
                    else ("app_ver", "after", "before", "offset", "extra"))
        if tuple(contract.params) != expected:
            raise ReadContractError("unexpected tournament standings request fields")
        ranges = StandingRange(after=contract.params["after"], before=contract.params["before"],
                               offset=contract.params["offset"], top=contract.params.get("top"))
        canonical = tournament_race_contract(parts[1], ranges,
                                             app_version=contract.params["app_ver"])
    elif contract.route.startswith("leaderboard/") and contract.request_type == 5 and contract.route.endswith("/score"):
        parts = contract.route.split("/")
        if len(parts) != 3 or tuple(contract.params) != ("app_ver", "offset", "signed", "extra"):
            raise ReadContractError("invalid score read contract")
        canonical = showdown_leagues_score_contract(parts[1], period_offset=contract.params["offset"],
                                                    app_version=contract.params["app_ver"])
    elif contract.route.startswith("leaderboard/") and contract.request_type == 5:
        parts = contract.route.split("/")
        if len(parts) != 3 or parts[2] not in {"view", "preview"}:
            raise ReadContractError("not a supported standings read route")
        keys = tuple(contract.params)
        expected = ("app_ver", "top", "after", "before", "offset") if "top" in contract.params else ("app_ver", "after", "before", "offset")
        preview = parts[2] == "preview"
        if preview: expected += ("score",)
        generic = contract.operation == "Fetches an Event leaderboard current progress"
        if generic and preview:
            raise ReadContractError("event progress cannot use a preview route")
        if generic:
            if "score" in contract.params:
                expected += ("score",)
            if "show_default" in contract.params:
                expected += ("show_default",)
        if keys != expected:
            raise ReadContractError("unexpected standings request fields")
        ranges = StandingRange(
            after=contract.params["after"], before=contract.params["before"],
            offset=contract.params["offset"], top=contract.params.get("top"),
        )
        if generic:
            canonical = event_standings_contract(
                parts[1], ranges, app_version=contract.params["app_ver"],
                score=contract.params.get("score"),
                show_default=contract.params.get("show_default"),
            )
        else:
            canonical = showdown_standings_contract(
                parts[1], ranges, preview=preview,
                score=contract.params["score"] if preview else None,
                app_version=contract.params["app_ver"],
            )
    elif contract.route == "events/crewEventProgress" and contract.request_type == 4:
        if tuple(contract.params) != ("crew_uid", "event_id", "series_id", "app_ver"):
            raise ReadContractError("unexpected crew event progress request fields")
        canonical = crew_event_progress_contract(
            contract.params["crew_uid"], contract.params["event_id"],
            contract.params["series_id"], app_version=contract.params["app_ver"])
    elif contract.route == "crews/showCrewsRanks" and contract.request_type == 3:
        if tuple(contract.params) != ("crew_uid", "app_ver", "top", "before", "after"):
            raise ReadContractError("unexpected crew rankings request fields")
        canonical = crew_rankings_contract(
            contract.params["crew_uid"], top=contract.params["top"],
            before=contract.params["before"], after=contract.params["after"],
            app_version=contract.params["app_ver"])
    elif contract.route in WILDCARD_ROUTES and contract.request_type == 3:
        if tuple(contract.params) != ("app_ver",):
            raise ReadContractError("unexpected wildcard status request fields")
        canonical = wildcard_status_contract(route=contract.route,
                                             app_version=contract.params["app_ver"])
    elif contract.route == "crews/checkCrewPerks" and contract.request_type == 3:
        if tuple(contract.params) != ("crew_uid", "app_ver"):
            raise ReadContractError("unexpected crew perks request fields")
        canonical = crew_perks_contract(contract.params["crew_uid"],
                                        app_version=contract.params["app_ver"])
    elif contract.route == "season_pass/season_pass_info" and contract.request_type == 1:
        if tuple(contract.params) != ("app_ver",):
            raise ReadContractError("unexpected season pass request fields")
        canonical = season_pass_contract(app_version=contract.params["app_ver"])
    elif contract.route == "collections/get_collections_blob_data" and contract.request_type == 1:
        if tuple(contract.params) != ("app_ver",):
            raise ReadContractError("unexpected collections blob request fields")
        canonical = collections_blob_contract(app_version=contract.params["app_ver"])
    elif contract.route == "grand_tour/get_season_details" and contract.request_type == 1:
        if tuple(contract.params) != ("app_ver", "extra"):
            raise ReadContractError("unexpected grand tour request fields")
        extra = contract.params["extra"]
        if not isinstance(extra, Mapping) or tuple(extra) != ("activeScheduleId",):
            raise ReadContractError("grand tour extra must carry only activeScheduleId")
        canonical = grand_tour_contract(extra["activeScheduleId"],
                                        app_version=contract.params["app_ver"])
    else:
        raise ReadContractError("operation is not on the traced read-only allowlist")
    # Do not accept hand-built or mutated request fields that bypass validation.
    if tuple(canonical.params.items()) != tuple(contract.params.items()):
        raise ReadContractError("request differs from the reconstructed native contract")
    return _prepare_signed_json(credentials, canonical.route, canonical.params,
                                web_api_url=web_api_url, unix_time=unix_time, nonce=nonce)


__all__ = [
    "ReadContract", "ReadContractError", "StandingRange",
    "own_crew_contract", "crew_members_contract", "GCC_METADATA_DEFAULT_PREFIX", "gcc_progress_contract", "gcc_progress_range_contract", "showdown_standings_contract", "event_standings_contract", "event_crew_standings_contract", "showdown_leagues_score_contract", "prepare_read_contract",
    "crew_event_progress_contract", "crew_rankings_contract",
    "season_pass_contract", "collections_blob_contract", "grand_tour_contract",
    "tournament_race_contract",
    "weekly_leaderboard_contract", "WEEKLY_LEADERBOARDS",
    "WILDCARD_ROUTES", "wildcard_status_contract", "crew_perks_contract",
]
