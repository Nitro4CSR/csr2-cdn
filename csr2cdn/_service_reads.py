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
]
