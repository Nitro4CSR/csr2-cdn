"""Typed, conservative decoders for CSR2 crew and leaderboard read responses.

The CSR2 6.8.0 response wrappers have not been validated against a live
session. Unknown fields are preserved **in memory**, not logged. Only
recognized wire field names are promoted to typed attributes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
import re
from typing import Any, Mapping, Optional, Tuple

from csr2cdn.errors import Csr2CdnError


class ServiceResponseError(Csr2CdnError):
    """Malformed/unrecognized response; optionally carries a key-free shape report."""

    def __init__(self, message: str, *, structure=None):
        super().__init__(message)
        self.structure = structure


def _mapping(data: Any) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise ServiceResponseError("service response must be a JSON object")
    return data


def _service_rejected(node: Mapping[str, Any]) -> bool:
    # The native response base has `isValid`, `clientOutOfDate`, `errorCode`
    # and `errorString` in addition to common HTTP/JSON envelope fields.
    return (node.get("success") is False or node.get("isValid") is False or
            node.get("clientOutOfDate") is True or bool(node.get("error")) or
            bool(node.get("errors")) or bool(node.get("errorString")) or
            node.get("errorCode") not in (None, "", 0, "0"))


def _payload(data: Any) -> Mapping[str, Any]:
    node = _mapping(data)
    if _service_rejected(node):
        raise ServiceResponseError("service returned a failure (details suppressed)")
    # Transport envelopes observed in the portal/download code; game-service
    # wrappers are still unverified. Never silently convert a server error to
    # an empty successful result.
    for name in ("responseData", "data", "result"):
        candidate = node.get(name)
        if isinstance(candidate, Mapping):
            node = candidate
            break
    if _service_rejected(node):
        raise ServiceResponseError("service returned a failure (details suppressed)")
    return node


def _field(obj: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in obj:
            return obj[name]
    return None


def _str(obj: Mapping[str, Any], *names: str) -> Optional[str]:
    v = _field(obj, *names)
    return None if v is None else str(v)


def _int(obj: Mapping[str, Any], *names: str) -> Optional[int]:
    v = _field(obj, *names)
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (ValueError, TypeError, OverflowError):
        return None


@dataclass(frozen=True)
class OwnCrew:
    """Own crew membership from the `CheckUserCrewResponse` model.

    `crew_uid=None` means no returned active crew identifier. Live success
    and negative/no-membership envelope semantics remain to be validated.
    Opaque reply fields are stored only in memory and excluded from repr.
    """
    crew_uid: Optional[str]
    name: Optional[str] = None
    member_count: Optional[int] = None
    player_role: Optional[str] = None
    extras: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def in_crew(self) -> bool:
        return self.crew_uid is not None

    @classmethod
    def from_response(cls, response: Any) -> "OwnCrew":
        node = _payload(response)
        # Do not turn a malformed or unexpected response into "no crew".
        marker_keys = ("crewUID", "crew_uid", "playerUID", "crewName",
                       "crew_name", "memberCount", "playerRole")
        if not any(key in node for key in marker_keys):
            raise ServiceResponseError("crew membership fields missing from response")
        raw_uid = _field(node, "crewUID", "crew_uid")
        uid = str(raw_uid).strip() if raw_uid is not None else None
        if uid == "":
            uid = None
        # Server identifiers are validated before they can form a URL.
        if uid is not None:
            from csr2cdn._service_reads import _identifier
            try:
                uid = _identifier(uid, name="crew_uid")
            except Exception:
                raise ServiceResponseError("invalid crew membership identifier") from None
        return cls(uid, _str(node, "crewName", "crew_name"),
                   _int(node, "memberCount", "membersTotal"),
                   _str(node, "playerRole", "player_role"), dict(node))


# The 6.8.0 PlayerCrewMember.FromJSONDict code (RVA 0x34a3d78) reads
# the *uppercase* literal "RP"; the lower-case "rp" key is from its
# separate compact FromJSONList overloads. Keep source provenance because
# the game's RP_allTime and RP_season are different native fields.
_CREW_RP_KEYS = ("RP_season", "rp_season", "seasonRP", "season_rp",
                 "crewRP", "crew_rp", "crewRp", "RP", "rp")
_NATIVE_CREW_ROLES = ("NEWBIE", "MEMBER", "SENIOR", "ADMIN", "LEADER")


def _member_rp(raw: Mapping[str, Any]) -> tuple[Optional[int], Optional[str]]:
    for key in _CREW_RP_KEYS:
        value = _int(raw, key)
        if value is not None:
            return value, key
    return None, None


def _season_rp_integer(value: Any) -> Optional[int]:
    """Strict candidate-only decoder for nonnegative seasonal RP counters.

    In contrast to the legacy ``_int`` helper, do not truncate floats or
    accept booleans. Bound the accepted integer size and never infer a value
    from a different RP statistic.
    """
    if type(value) is int:
        parsed = value
    elif isinstance(value, str):
        trimmed = value.strip()
        if not trimmed or len(trimmed) > 20 or not re.fullmatch(r"\+?[0-9]+", trimmed):
            return None
        parsed = int(trimmed)
    else:
        return None
    return parsed if 0 <= parsed <= 2**63 - 1 else None


def _native_season_contribution(raw: Mapping[str, Any]) -> tuple[Optional[int], Optional[str]]:
    """Mirror native PlayerCrewMember.FromJSONDict's season-key priority.

    6.8.0 reads ``score`` into RP_season, then reads ``cc_contrib`` into the
    *same* field. A present but malformed cc_contrib must not silently be
    substituted with score; the live source and season scope remain unverified.
    Compact (list) members have no native contribution field.
    """
    for key in ("cc_contrib", "score"):
        if key in raw:
            return _season_rp_integer(raw[key]), key
    return None, None


def _crew_role_name(value: Any) -> Optional[str]:
    """Normalize the native five-value CrewRole enum; preserve raw `role`."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int) or (isinstance(value, str) and value.strip().lstrip("+-").isdigit()):
        try:
            index = int(value)
            return _NATIVE_CREW_ROLES[index] if 0 <= index < len(_NATIVE_CREW_ROLES) else None
        except (ValueError, OverflowError):
            return None
    if isinstance(value, str):
        label = value.strip().upper()
        return label if label in _NATIVE_CREW_ROLES else None
    return None


def _crew_shape_summary(response: Any) -> Mapping[str, int]:
    """Bounded, value-free diagnostic. No field names, IDs, tokens or replies.

    Counts container types only. Useful for telling an error response from a
    roster envelope without accidentally emitting the authentication exchange.
    """
    counts = {"top_level_fields": 0, "nested_objects": 0,
              "array_fields": 0, "array_items": 0}
    if not isinstance(response, Mapping):
        return counts
    counts["top_level_fields"] = min(len(response), 100)
    visited = set()
    def walk(node, depth):
        if depth > 2 or id(node) in visited or len(visited) > 120:
            return
        visited.add(id(node))
        for val in list(node.values())[:100]:
            if isinstance(val, Mapping):
                counts["nested_objects"] += 1
                walk(val, depth+1)
            elif isinstance(val, list):
                counts["array_fields"] += 1
                counts["array_items"] += min(len(val), 100)
    walk(response, 0)
    return counts


def _crew_rows(node: Mapping[str, Any]):
    """Find explicit native member arrays in supported nested response wrappers.

    A single otherwise unrecognized list of member-like objects is admissible
    only when every nonempty record has a player identifier. Unknown empty
    arrays and ambiguous candidates never become a purported empty roster.
    """
    explicit = ("crewMembers", "crew_members", "memberList", "crewMemberList",
                "playerCrewMembers", "crew_member_list", "members")
    wrappers = ("responseData", "data", "result", "response", "payload",
                "crew", "roster", "crewData")
    queue = [(node, 0)]
    seen = set()
    inferred = []
    while queue:
        obj, depth = queue.pop(0)
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        if _service_rejected(obj):
            raise ServiceResponseError("service returned a failure (details suppressed)")
        for field in explicit:
            if field in obj:
                return obj, obj[field]
        if depth >= 2:
            continue
        for k, value in obj.items():
            if k in wrappers and isinstance(value, Mapping):
                queue.append((value, depth+1))
            elif isinstance(value, list) and value and len(value) <= 1000 and all(
                isinstance(r, Mapping) and any(key in r for key in
                ("player_uid", "playerUID", "zid")) for r in value):
                inferred.append((obj, value))
    if len(inferred) == 1:
        return inferred[0]
    return node, None


def _native_member_record(raw):
    if isinstance(raw, Mapping):
        return raw
    if isinstance(raw, list) and len(raw) in (10, 11):
        # Two native PlayerCrewMember.FromJSONList overloads; only applied
        # to *explicitly named* roster arrays, not arbitrary server lists.
        fields = (("player_uid", "name", "career_earnings", "garage_value",
                   "rp", "tier", "car_pp", "car_ep", "xp", "level", "message")
                  if len(raw) == 11 else
                  ("player_uid", "name", "crew_uid", "career_earnings", "rp",
                   "tier", "car_ep", "xp", "level", "last_sign_in_time"))
        return dict(zip(fields, raw))
    raise ServiceResponseError("crew member record has an unsupported type")



def _crew_wire_rp_diagnostics(rows: list) -> Mapping[str, int]:
    """Aggregate only schema shapes; NEVER return keys, values, IDs or raw rows.

    The live ``viewMembers`` format remains unconfirmed. These counters
    distinguish omitted RP from a naming/type mismatch without storing any
    member data in a validation report. No numeric field is accepted as RP
    merely because it occurs near a name or role.
    """
    counts = {k: 0 for k in (
        "dictionary_rows", "compact_10_rows", "compact_11_rows",
        "native_RP_key_present", "native_rp_key_present",
        "explicit_season_rp_key_present", "known_crew_rp_alias_present",
        "other_rp_labeled_key_present", "rp_labeled_null",
        "rp_labeled_unparseable", "rp_nested_labeled_rows",
        "compact_rp_slot_present", "compact_rp_slot_parseable",
        "role_source_text", "role_source_number",
        "cc_contrib_present", "cc_contrib_numeric", "cc_contrib_null",
        "cc_contrib_invalid", "score_present", "score_numeric",
        "score_null", "score_invalid", "cc_contrib_and_score_present",
        "native_season_candidate_numeric", "native_season_candidate_from_cc_contrib",
        "native_season_candidate_from_score",
    )}
    def rp_labeled(key: str) -> bool:
        # A deliberately broad *diagnostic* only, not a decoding alias.
        name = key.casefold().replace("-", "_")
        return ("rp" in name or "respectpoints" in name or
                "respect_points" in name)

    def has_nested_rp(obj, depth=0):
        if depth >= 2:
            return False
        if isinstance(obj, Mapping):
            for key, value in list(obj.items())[:128]:
                if isinstance(key, str) and rp_labeled(key):
                    return True
                if isinstance(value, (Mapping, list)) and has_nested_rp(value, depth + 1):
                    return True
        elif isinstance(obj, list):
            for value in obj[:32]:
                if isinstance(value, (Mapping, list)) and has_nested_rp(value, depth + 1):
                    return True
        return False

    for item in rows[:1000]:
        if isinstance(item, list):
            if len(item) not in (10, 11):
                continue
            counts[f"compact_{len(item)}_rows"] += 1
            rp = item[4]
            if rp is not None:
                counts["compact_rp_slot_present"] += 1
                if _int({"rp": rp}, "rp") is not None:
                    counts["compact_rp_slot_parseable"] += 1
            continue
        if not isinstance(item, Mapping):
            continue
        counts["dictionary_rows"] += 1
        for key in ("cc_contrib", "score"):
            if key in item:
                counts[f"{key}_present"] += 1
                if item[key] is None:
                    counts[f"{key}_null"] += 1
                elif _season_rp_integer(item[key]) is None:
                    counts[f"{key}_invalid"] += 1
                else:
                    counts[f"{key}_numeric"] += 1
        if "cc_contrib" in item and "score" in item:
            counts["cc_contrib_and_score_present"] += 1
        rp_value, rp_source = _native_season_contribution(item)
        if rp_value is not None:
            counts["native_season_candidate_numeric"] += 1
            counts[f"native_season_candidate_from_{rp_source}"] += 1
        role = _field(item, "role", "Role")
        if isinstance(role, str):
            counts["role_source_text"] += 1
        elif isinstance(role, (float, int)) and not isinstance(role, bool):
            counts["role_source_number"] += 1
        nested = False
        for key, value in list(item.items())[:128]:
            if not isinstance(key, str):
                continue
            if isinstance(value, (Mapping, list)):
                if has_nested_rp(value):
                    nested = True
                continue
            if not rp_labeled(key):
                continue
            if key == "RP":
                label = "native_RP_key_present"
            elif key == "rp":
                label = "native_rp_key_present"
            elif key in ("RP_season", "rp_season", "seasonRP", "season_rp"):
                label = "explicit_season_rp_key_present"
            elif key in ("crewRP", "crew_rp", "crewRp"):
                label = "known_crew_rp_alias_present"
            else:
                label = "other_rp_labeled_key_present"
            counts[label] += 1
            if value is None:
                counts["rp_labeled_null"] += 1
            elif _int({key: value}, key) is None:
                counts["rp_labeled_unparseable"] += 1
        if nested:
            counts["rp_nested_labeled_rows"] += 1
    return counts


# Explicitly opt-in *schema* diagnostics. These are names of repeated static
# wire keys only: no field values, player identifiers, nicknames or raw records.
# Candidate keys are never promoted to typed RP based on their spelling alone.
_SCHEMA_KEY_RE = re.compile(r"[A-Za-z_]{2,48}\Z")
_PRIVATE_KEY_PARTS = (
    "auth", "token", "secret", "passwd", "password", "session", "cookie",
    "nonce", "private", "playerid", "player_uid", "zid", "email",
    "address", "username", "nickname", "displayname", "userid",
)


def _crew_rp_schema_key_counts(rows: list) -> Mapping[str, int]:
    """Privacy-filtered census of repeated RP-looking *keys*, never values.

    Restrict to dictionary rows and ASCII protocol-like identifiers; omit
    singleton names, numeric/dynamic keys, sensitive-looking keys and unknown
    containers. This intentionally reveals only stable field names repeated
    across members, to allow native semantic tracing. It is opt-in for output.
    """
    counts = Counter()
    for row in rows[:1000]:
        if not isinstance(row, Mapping):
            continue
        for key in list(row)[:128]:
            if not isinstance(key, str) or not _SCHEMA_KEY_RE.fullmatch(key):
                continue
            norm = key.casefold()
            if ("rp" not in norm and "respectpoints" not in norm and
                    "respect_points" not in norm and key not in ("cc_contrib", "score")):
                continue
            if any(banned in norm for banned in _PRIVATE_KEY_PARTS):
                continue
            # Never inspect, stringify, or serialize values.
            counts[key] += 1
    # A repeated structural schema field, unlike a one-off dynamic key,
    # will occur in multiple independent member rows.
    return dict(sorted(((key, min(count, 1000)) for key, count in counts.items()
                        if count >= 2), key=lambda kv: (-kv[1], kv[0]))[:24])


def _crew_rp_name_families(key_counts: Mapping[str, int]) -> Mapping[str, int]:
    """Classify observed schema names without interpreting their values."""
    totals = {"car_performance_like": 0, "rp_boundary_like": 0,
              "other_substring_like": 0}
    for key, amount in key_counts.items():
        norm = key.casefold().replace("_", "")
        if ("carpp" in norm or "carparts" in norm or
                "carperformance" in norm or "carpower" in norm):
            label = "car_performance_like"
        elif (re.search(r"(?:^|_)rp(?:_|$)", key, re.I) or
              re.search(r"(?:crew|season|seasonal|lifetime|alltime)rp|rp(?:crew|season|total)", norm)):
            label = "rp_boundary_like"
        else:
            label = "other_substring_like"
        totals[label] += amount
    return totals


@dataclass(frozen=True)
class CrewCar:
    """Fields found in PlayerCrewMember.FromJSONDict, when present."""
    identifier: Optional[str] = None
    pp: Optional[int] = None
    ep: Optional[int] = None
    details: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class CrewMember:
    """One crew member from the read-only ``crews/viewMembers`` response.

    ``name`` is retained for compatibility and ``nickname`` is its explicit
    display-name alias. ``crew_rp`` reads a supplied roster RP field, including
    the native dictionary key ``RP`` (uppercase). The game stores the resulting
    RP in its ``RP_allTime`` field, *not* necessarily its separate seasonal
    ``RP_season`` field. Use ``crew_rp_source`` to audit that distinction; do
    not claim that a value from ``RP`` equals displayed seasonal Crew RP before
    an in-game comparison. ``player_rank`` is the game's
    player *level*, not crew roster position or leaderboard position.
    """
    player_uid: Optional[str]
    zid: Optional[str]
    name: Optional[str]
    role: Optional[str]
    car: Optional[CrewCar]
    extras: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)
    nickname: Optional[str] = None
    crew_rp: Optional[int] = None
    player_rank: Optional[int] = None
    # Optional, backwards-compatible fields appended after existing fields.
    crew_rp_source: Optional[str] = None
    rp_all_time: Optional[int] = None
    role_normalized: Optional[str] = None
    # PlayerProfile.get_RP published in UserManager.FillNonSecureBlobDict
    # under the exact 6.8.0 wire key `player_rp` (RVA 0x368b798).
    # This profile stat is NOT evidence of crew-season contribution.
    player_rp: Optional[int] = None
    # 6.8.0 PlayerCrewMember.FromJSONDict: cc_contrib overrides score.
    # A parser-supported candidate, NOT an in-game-verified 14-day value.
    season_crew_rp_candidate: Optional[int] = None
    season_crew_rp_source: Optional[str] = None
    # Verified for the tested 2026-10-16 game snapshot: only an explicit
    # cc_contrib wire field is eligible. This is the game's roster seasonal
    # counter, NOT proof of a backend season ID or rollover semantics.
    season_crew_rp: Optional[int] = None


@dataclass(frozen=True)
class CrewMembers:
    crew_uid: str
    members: Tuple[CrewMember, ...]
    extras: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)
    wire_rp_diagnostics: Mapping[str, int] = field(default_factory=dict, repr=False, compare=False)
    wire_rp_schema_keys: Mapping[str, int] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_response(cls, crew_uid: str, response: Any) -> "CrewMembers":
        node = _payload(response)
        node, rows = _crew_rows(node)
        if rows is None:
            raise ServiceResponseError("crew roster structure not recognized",
                                       structure=_crew_shape_summary(response))
        if not isinstance(rows, list):
            raise ServiceResponseError("crew roster field is not an array",
                                       structure=_crew_shape_summary(response))
        members = []
        for item in rows:
            raw = _native_member_record(item)
            car_value = _field(raw, "current_car", "currentCar")
            car_details = dict(car_value) if isinstance(car_value, Mapping) else {}
            car_id = (_str(car_details, "car_id", "carID", "car_uid", "carUID", "name")
                      if car_details else (str(car_value) if car_value is not None else None))
            pp = _int(raw, "car_pp", "carPP")
            ep = _int(raw, "car_ep", "carEP")
            car = CrewCar(car_id, pp, ep, car_details) if car_value is not None or pp is not None or ep is not None else None
            nickname = _str(raw, "name", "nickname", "nickName", "playerName",
                            "player_name", "displayName", "display_name")
            crew_rp, rp_source = _member_rp(raw)
            season_candidate, season_source = (
                _native_season_contribution(raw) if isinstance(item, Mapping) else (None, None))
            role_wire = _field(raw, "role", "Role")
            members.append(CrewMember(
                _str(raw, "player_uid", "playerUID"), _str(raw, "zid"),
                nickname, _str(raw, "role", "Role"), car, dict(raw),
                nickname=nickname,
                crew_rp=crew_rp,
                player_rank=_int(raw, "level", "playerLevel", "player_level", "playerRank"),
                crew_rp_source=rp_source,
                rp_all_time=_int(raw, "RP"),
                role_normalized=_crew_role_name(role_wire),
                player_rp=_int(raw, "player_rp"),
                season_crew_rp_candidate=season_candidate,
                season_crew_rp_source=season_source,
                season_crew_rp=season_candidate if season_source == "cc_contrib" else None,
            ))
        return cls(str(_field(node, "crewUID", "crew_uid") or crew_uid), tuple(members), dict(node),
                   _crew_wire_rp_diagnostics(rows), _crew_rp_schema_key_counts(rows))


@dataclass(frozen=True)
class GCCCrewStanding:
    """Unverified crew row decoded using native RemoteCrewInfo key meanings.

    ``cc_rp`` maps to CrewRP_season; ``rp`` maps to CrewRP_allTime. Native
    ``score`` is a fallback for both, but it is not a verified seasonal total.
    These fields are only populated from a *supplied* response; no speculative
    GCC URL or network contract is installed.
    """
    crew_uid: Optional[str]
    name: Optional[str]
    rank: Optional[int]
    season_crew_rp_candidate: Optional[int] = None
    season_crew_rp_source: Optional[str] = None
    rp_all_time: Optional[int] = None
    extras: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> "GCCCrewStanding":
        if not isinstance(raw, Mapping):
            raise ServiceResponseError("GCC crew row must be an object")
        # Explicit season key wins over generic fallback, even if invalid.
        source = "cc_rp" if "cc_rp" in raw else "score" if "score" in raw else None
        total = _season_rp_integer(raw[source]) if source is not None else None
        return cls(
            crew_uid=_str(raw, "uid", "UID", "crew_uid", "crewUID"),
            name=_str(raw, "name", "Name"),
            rank=_int(raw, "crew_rank"),
            season_crew_rp_candidate=total,
            season_crew_rp_source=source,
            rp_all_time=_int(raw, "rp", "score"),
            extras=dict(raw),
        )


@dataclass(frozen=True)
class GCCCrewStandings:
    """Offline-only decoder for candidate Grand Crew Championship crew rows.

    The actual response envelope and active-season URL require a live/native
    contract check; never interpret generic event leaderboard scores as GCC.
    """
    crews: Tuple[GCCCrewStanding, ...]
    extras: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_response(cls, response: Any) -> "GCCCrewStandings":
        node = _payload(response)
        rows = _field(node, "results", "Results")
        if rows is None:
            # The native FillFromJsonList decoder can accept a direct list
            # under a responseData envelope; do not infer unrelated arrays.
            rows = response.get("responseData") if isinstance(response, Mapping) else None
        if not isinstance(rows, list):
            raise ServiceResponseError("GCC crew results array missing")
        return cls(tuple(GCCCrewStanding.from_wire(raw) for raw in rows), dict(node))


@dataclass(frozen=True)
class GCCProgressCrewScore:
    """Observed 6.8.0 GCC progress `scores` row; units are NOT season-verified.

    This is not a RemoteCrewInfo/results row. `score` is a standalone
    leaderboard integer and is not silently mapped to `cc_rp` or all-time RP.
    """
    crew_id: str = field(repr=False)
    name: str
    rank: int
    score: int
    # The server returned a logo object for all 21 rows in the dev25 sample.
    # Preserve it (and any other row fields) in memory for future schema work;
    # do not infer logo format or print opaque values by default.
    logo: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)
    extras: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def crew_leaderboard_score(self) -> int:
        """GCC progress score; equal to crew contribution sum in dev27 live check.

        Source response has no independently confirmed active season identifier.
        """
        return self.score

    @property
    def crew_leaderboard_rank(self) -> int:
        """Backend-returned global rank, not a position in this 21-row window."""
        return self.rank

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> "GCCProgressCrewScore":
        if not isinstance(raw, Mapping):
            raise ServiceResponseError("GCC progress row must be an object")
        crew_id = raw.get("crew_id")
        name = raw.get("name")
        rank = raw.get("rank")
        score = raw.get("score")
        if not isinstance(crew_id, str) or not 0 < len(crew_id.strip()) <= 180:
            raise ServiceResponseError("GCC progress crew_id missing or malformed")
        if not isinstance(name, str) or len(name) > 512:
            raise ServiceResponseError("GCC progress name missing or malformed")
        if type(rank) is not int or rank <= 0 or rank >= 2**31:
            raise ServiceResponseError("GCC progress rank missing or malformed")
        if type(score) is not int or score < 0 or score >= 2**63:
            raise ServiceResponseError("GCC progress score missing or malformed")
        logo = raw.get("logo")
        return cls(crew_id=crew_id.strip(), name=name, rank=rank, score=score,
                   logo=dict(logo) if isinstance(logo, Mapping) else {},
                   extras=dict(raw))


@dataclass(frozen=True)
class GCCProgressCrewScores:
    """Current-progress `scores` response shape observed in dev25 live read.

    Rank and score are returned by the backend, but this type does NOT claim
    the active 14-day season or equivalence to in-game seasonal Crew RP.
    """
    crews: Tuple[GCCProgressCrewScore, ...]
    extras: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_response(cls, response: Any) -> "GCCProgressCrewScores":
        node = _payload(response)
        rows = node.get("scores")
        if not isinstance(rows, list) or not rows or len(rows) > 10000:
            raise ServiceResponseError("GCC progress scores array missing or invalid")
        parsed = tuple(GCCProgressCrewScore.from_wire(row) for row in rows)
        if len({r.crew_id for r in parsed}) != len(parsed):
            raise ServiceResponseError("GCC progress response has duplicate crew IDs")
        return cls(parsed, dict(node))


@dataclass(frozen=True)
class LeaderboardScore:
    """Typed score read; score units remain unknown unless provided."""
    leaderboard_name: str
    score: Optional[int] = None
    rank: Optional[int] = None
    period_offset: int = 0
    extras: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_response(cls, board: str, response: Any, *, period_offset: int = 0) -> "LeaderboardScore":
        payload = _payload(response)
        obj = _field(payload, "scoreData", "playerScore")
        if isinstance(obj, Mapping):
            payload = obj
        score = _int(payload, "score", "points", "trophies")
        rank = _int(payload, "rank", "position")
        if score is None and rank is None:
            raise ServiceResponseError("score/rank fields missing from leaderboard-score response")
        return cls(board, score, rank, period_offset, dict(payload))


@dataclass(frozen=True)
class LeaderboardEntry:
    rank: Optional[int]
    player_id: Optional[str]
    player_name: Optional[str]
    score: Optional[int]
    crew_id: Optional[str] = None
    extras: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class LeaderboardPage:
    leaderboard_name: str
    entries: Tuple[LeaderboardEntry, ...]
    player_rank: Optional[int] = None
    player_score: Optional[int] = None
    next_cursor: Optional[str] = None
    previous_cursor: Optional[str] = None
    score_unit: Optional[str] = None
    extras: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def find_player(self, player_id: str) -> Optional[LeaderboardEntry]:
        return next((row for row in self.entries if row.player_id == str(player_id)), None)

    @classmethod
    def from_response(cls, leaderboard_name: str, response: Any, *,
                      score_unit: Optional[str] = None) -> "LeaderboardPage":
        node = _payload(response)
        rows = _field(node, "scores", "entries", "records", "leaderboard", "results")
        if isinstance(rows, Mapping):
            # Some wrappers provide nested records and paging metadata.
            node = rows
            rows = _field(node, "scores", "entries", "records", "results")
        if rows is None or not isinstance(rows, list):
            raise ServiceResponseError("leaderboard entries missing or not an array")
        entries = []
        for raw in rows:
            if not isinstance(raw, Mapping):
                raise ServiceResponseError("leaderboard entry is not an object")
            entries.append(LeaderboardEntry(
                rank=_int(raw, "rank", "position", "place"),
                player_id=_str(raw, "player_uid", "playerUID", "zid", "player_id", "playerId"),
                player_name=_str(raw, "name", "player_name", "playerName"),
                score=_int(raw, "score", "points", "trophies"),
                crew_id=_str(raw, "crew_uid", "crewUID", "crew_id"), extras=dict(raw),
            ))
        player = _field(node, "player", "currentPlayer", "myRank")
        if not isinstance(player, Mapping):
            player = {}
        return cls(
            leaderboard_name, tuple(entries),
            _int(node, "player_rank", "playerRank") or _int(player, "rank"),
            _int(node, "player_score", "playerScore") or _int(player, "score"),
            _str(node, "next_cursor", "nextCursor"),
            _str(node, "previous_cursor", "previousCursor"),
            score_unit, dict(node),
        )


__all__ = ["OwnCrew", "CrewCar", "CrewMember", "CrewMembers", "GCCCrewStanding", "GCCCrewStandings", "LeaderboardEntry", "LeaderboardPage", "LeaderboardScore", "ServiceResponseError"]
