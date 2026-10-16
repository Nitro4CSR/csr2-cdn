"""Dev30: bounded privacy-filtered inventory for three established CSR2 crew reads.

Pure analysis of caller-supplied replies; no network, raw response persistence,
account identifiers, crew names, RP values or secrets in default output.
A user must explicitly opt into *selected aggregate* numerical previews.
This is schema discovery, not evidence that any field has verified semantics.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import getpass
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Optional

from .service_models import OwnCrew, CrewMembers, ServiceResponseError, _payload, _crew_rows

_MAX_BYTES = 8 * 1024 * 1024
_MAX_KEYS = 128
_MAX_FIELDS = 96
_MAX_ROWS = 1000
_SAFE_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,47}\Z")
_PRIVATE_BITS = (
    "token", "secret", "password", "passwd", "auth", "cookie", "session",
    "credential", "private", "bearer", "jwt", "nonce", "email", "phone",
    "address", "accesskey", "apikey", "refresh", "signature", "sigkey",
)
_NESTED = frozenset({
    "logo", "current_car", "currentCar", "car", "CarInfo", "profile",
    "SPBoostData", "metadata", "season", "paging", "pagination",
    "TournamentCrewData", "crewEmblem", "crewData", "data", "result",
    "tournament", "crew_logo", "car_gacha_config", "car_tnr_setup",
})
_OWN_NUMERIC = (
    # Actual snake_case names observed in the Dev29 authorized inventory.
    "crew_rp", "crew_level", "crew_level_base", "crew_level_threshold",
    "crew_garage_value", "crew_career_earning", "crew_rr_point",
    "members", "max_members", "total_invites", "total_requests",
    # Preserve earlier synthetic / native-name candidates for compatibility.
    "crewRP", "crewLevel", "crewLevelProgress", "crewCash",
    "crewGarageValue", "crewCareerEarning", "maximumMembers",
    "memberCount", "invitesCount", "requestsCount",
)
_MEMBER_NUMERIC = (
    "cc_contrib", "season_pass_rp_boost", "seasonPassRPBoost",
    "TokenDonated_season", "token_donated_season", "tokenDonatedSeason",
    "garage_value", "garageValue", "career_earning", "career_earnings",
    "careerEarning", "cash_donated", "collections_rank", "car_pp", "car_ep",
    "pp", "ep", "races", "Races",
)
_METADATA_PATTERN = re.compile(r"season|period|epoch|start|end|timestamp|updated|server.?time|cursor|page|offset|count|total|next|previous|duration|time_left|bucket|tier|cardinality", re.I)


def _kind(value: Any) -> str:
    if value is None: return "null"
    if isinstance(value, bool): return "boolean"
    if isinstance(value, Mapping): return "object"
    if isinstance(value, list): return "array"
    if type(value) is int: return "integer"
    if type(value) is float: return "float"
    if isinstance(value, str): return "string"
    return "other"


def _safe_key(key: Any) -> bool:
    """Require protocol-like names, excluding suspicious/high-entropy keys.

    This is a best-effort safety filter, not a promise that a malformed schema
    key can never contain user information. No field VALUES are ever copied.
    """
    return (isinstance(key, str) and bool(_SAFE_KEY.fullmatch(key)) and
            (key in ("TokenDonated_season", "token_donated_season", "tokenDonatedSeason")
             or not any(bit in key.casefold() for bit in _PRIVATE_BITS)) and
            not key.isupper() and
            sum(c.isdigit() for c in key) <= 5)


def _rows_summary(rows: Any, *, nested: bool = True) -> dict[str, Any]:
    """Bounded census of field names/types; no names, IDs, or response values."""
    if not isinstance(rows, list):
        return {"container_type": _kind(rows), "row_count": 0, "inspected": 0,
                "dictionary_rows": 0, "fields": {}, "suppressed_key_occurrences": 0}
    selected = rows[:_MAX_ROWS]
    fields: dict[str, Counter] = defaultdict(Counter)
    nested_fields: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    hidden = 0
    dictionaries = 0
    for row in selected:
        if not isinstance(row, Mapping):
            continue
        dictionaries += 1
        for index, (key, value) in enumerate(row.items()):
            if index >= _MAX_KEYS:
                hidden += max(0, len(row) - _MAX_KEYS)
                break
            if not _safe_key(key) or (key not in fields and len(fields) >= _MAX_FIELDS):
                hidden += 1
                continue
            fields[key][_kind(value)] += 1
            if nested and key in _NESTED and isinstance(value, Mapping):
                for subindex, (subkey, subval) in enumerate(value.items()):
                    if subindex >= _MAX_KEYS:
                        hidden += max(0, len(value) - _MAX_KEYS)
                        break
                    if not _safe_key(subkey) or (subkey not in nested_fields[key] and
                                                len(nested_fields[key]) >= _MAX_FIELDS):
                        hidden += 1
                        continue
                    nested_fields[key][subkey][_kind(subval)] += 1
    return {
        "row_count": len(rows), "inspected": len(selected),
        "dictionary_rows": dictionaries,
        "truncated_rows": len(rows) > len(selected),
        "fields": {key: dict(sorted(types.items())) for key, types in sorted(fields.items())},
        "nested_object_fields": {
            parent: {sub: dict(sorted(types.items())) for sub, types in sorted(subitems.items())}
            for parent, subitems in sorted(nested_fields.items())},
        "suppressed_key_occurrences": hidden,
    }


def _mapping_summary(value: Any) -> dict[str, Any]:
    return _rows_summary([value] if isinstance(value, Mapping) else value)


def _payload_container(response: Any) -> Mapping[str, Any]:
    node = _payload(response)  # failures cannot be silently treated as empty
    return node


def _strict_counter(value: Any) -> Optional[int]:
    if type(value) is int and 0 <= value < 2**63:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,19}", value, re.ASCII):
        x = int(value)
        return x if x < 2**63 else None
    return None


def _numeric_census(rows: list[Any], keys: tuple[str, ...], *, show_values: bool) -> dict[str, Any]:
    results = {}
    for key in keys:
        present = [row[key] for row in rows if isinstance(row, Mapping) and key in row]
        if not present:
            continue
        valid = [_strict_counter(value) for value in present]
        numeric = [v for v in valid if v is not None]
        stats = {"present": len(present), "numeric": len(numeric),
                 "null": sum(v is None for v in present),
                 "invalid": len(present) - len(numeric) - sum(v is None for v in present),
                 "units_or_season_verified": False}
        if show_values and numeric:
            # Aggregate member stats, not per-member values or identifiers.
            # For own-crew there is a single record, whose numeric values were
            # explicitly requested by the opt-in switch.
            stats["minimum"] = min(numeric)
            stats["maximum"] = max(numeric)
            stats["sum"] = sum(numeric) if len(rows) > 1 else None
            if len(rows) == 1:
                stats["own_crew_value_unverified"] = numeric[0]
        results[key] = stats
    return results


def _gcc_timing_metadata(
    node: Mapping[str, Any], *, show_values: bool, read_utc: Optional[datetime],
) -> dict[str, Any]:
    """Only known GCC keys; opt-in values are *unverified* wire scalars.

    Unix-epoch and seconds interpretations are hypotheses checked against the
    local read timestamp, never asserted as server-certified season identity.
    """
    fields = ("end_time", "time_left", "cardinality", "bucket", "tier")
    out: dict[str, Any] = {"candidate_only": True, "verified_season_id": False,
                           "fields": {key: {"present": key in node, "type": _kind(node.get(key))
                                            if key in node else "absent"}
                                      for key in fields}}
    if not show_values:
        return out
    for key in ("end_time", "time_left", "cardinality"):
        val = _strict_counter(node.get(key))
        if val is not None:
            out["fields"][key]["value_unverified"] = val
    for key in ("bucket", "tier"):
        val = node.get(key)
        # Never render arbitrary or very long text from a response. These are
        # only the two explicitly requested metadata values, not name/IDs.
        if (isinstance(val, str) and 1 <= len(val) <= 48
                and re.fullmatch(r"[A-Za-z0-9_./:-]+", val, re.ASCII)
                and not any(bit in val.casefold() for bit in _PRIVATE_BITS)):
            out["fields"][key]["value_unverified"] = val
        elif key in node:
            out["fields"][key]["value_suppressed"] = True
    end = _strict_counter(node.get("end_time"))
    left = _strict_counter(node.get("time_left"))
    if end is not None and left is not None:
        # Common Unix seconds range and a conservative maximum time-left.
        plausible = 946684800 <= end <= 4102444800 and left <= 90 * 86400
        hint: dict[str, Any] = {
            "end_time_unix_seconds_plausible": plausible,
            "duration_seconds_hypothesis": True,
            "time_left_is_seconds_verified": False,
        }
        if plausible:
            hint["candidate_end_utc"] = datetime.fromtimestamp(end, timezone.utc).isoformat()
            implied = end - left
            hint["candidate_implied_server_time_utc"] = datetime.fromtimestamp(implied, timezone.utc).isoformat()
            if isinstance(read_utc, datetime) and read_utc.tzinfo is not None:
                delta = implied - read_utc.timestamp()
                hint["candidate_implied_time_minus_read_seconds"] = round(delta, 3)
                hint["near_read_time_if_seconds"] = abs(delta) <= 900
        out["timing_hypothesis"] = hint
    return out


def _rp_cross_read_candidates(
    own: Mapping[str, Any], roster: CrewMembers, gcc: Mapping[str, Any],
    *, show_values: bool, member_read_utc: Optional[datetime],
    gcc_read_utc: Optional[datetime],
) -> dict[str, Any]:
    """Compare three separately named statistics; no semantic equivalence claim."""
    own_id = own.get("crew_uid", own.get("crewUID"))
    members = roster.members
    identities = [m.player_uid or m.zid for m in members]
    ids_ok = bool(identities) and all(identities) and len(set(identities)) == len(identities)
    vals = [m.season_crew_rp for m in members]
    vals_ok = bool(vals) and all(type(v) is int and v >= 0 for v in vals)
    expected = own.get("members", own.get("memberCount"))
    expected_n = _strict_counter(expected)
    count_ok = expected_n is not None and expected_n == len(members) and 1 <= len(members) <= 30
    matched = []
    scores_valid = False
    try:
        from .service_models import GCCProgressCrewScores
        decoded = GCCProgressCrewScores.from_response(gcc)
        scores_valid = True
        matched = [row for row in decoded.crews if row.crew_id == own_id]
    except (ValueError, TypeError, ServiceResponseError):
        pass
    match_ok = len(matched) == 1
    gap = None
    if member_read_utc is not None and gcc_read_utc is not None:
        if (not isinstance(member_read_utc, datetime) or member_read_utc.tzinfo is None
                or not isinstance(gcc_read_utc, datetime) or gcc_read_utc.tzinfo is None):
            raise ValueError("read timestamps must be timezone-aware")
        gap = (gcc_read_utc - member_read_utc).total_seconds()
    # Old snapshots or unexpectedly slow/reordered reads must not be called a
    # comparable same-run RP snapshot. No clock means offline structural only.
    acceptable_gap = gap is None or 0 <= gap <= 30
    reliable = bool(ids_ok and vals_ok and count_ok and match_ok and scores_valid
                    and acceptable_gap)
    current_crew_rp = _strict_counter(own.get("crew_rp", own.get("crewRP")))
    out: dict[str, Any] = {
        "status": "candidate_comparison_not_season_verified",
        "sequential_non_atomic": True,
        "member_count": len(members),
        "own_crew_member_count": expected_n,
        "complete_roster": bool(ids_ok and vals_ok and count_ok),
        "exact_own_crew_id_matches": len(matched),
        "gcc_rows_decoded": scores_valid,
        "comparable": reliable,
        "read_gap_acceptable_if_known": acceptable_gap,
        "own_crew_rp_present_numeric": current_crew_rp is not None,
        "all_three_statistics_same_meaning_verified": False,
    }
    if member_read_utc is not None and gcc_read_utc is not None:
        out["member_read_utc"] = member_read_utc.isoformat()
        out["gcc_read_utc"] = gcc_read_utc.isoformat()
        out["read_gap_seconds"] = round(gap, 3)
    if not show_values:
        return out
    total = sum(vals) if ids_ok and vals_ok and count_ok else None
    matched_score = matched[0].score if match_ok else None
    out["own_crew_crew_rp_unverified"] = current_crew_rp
    out["complete_roster_cc_contrib_sum"] = total
    out["exact_id_matched_gcc_score"] = matched_score
    # Protect against comparing a partial roster or unmatched crew.
    out["member_sum_minus_gcc_score"] = (total - matched_score if reliable else None)
    out["own_crew_rp_minus_gcc_score"] = (
        current_crew_rp - matched_score if reliable and current_crew_rp is not None else None)
    out["own_crew_rp_minus_member_sum"] = (
        current_crew_rp - total if reliable and current_crew_rp is not None else None)
    return out


def _metadata_cues(*locations: tuple[str, Mapping[str, Any]]) -> dict[str, list[str]]:
    """Only matching *schema keys*, never their values; no inferred season ID."""
    result = {}
    for label, mapping in locations:
        found = [key for key in list(mapping)[:_MAX_KEYS]
                 if _safe_key(key) and _METADATA_PATTERN.search(key)]
        # The selected response may nest season or pagination information in
        # a metadata object. Report a *path*, never a corresponding value.
        for parent in ("metadata", "season", "paging", "pagination", "progress"):
            obj = mapping.get(parent)
            if isinstance(obj, Mapping):
                found.extend(parent + "." + key for key in list(obj)[:_MAX_KEYS]
                             if _safe_key(key) and _METADATA_PATTERN.search(key))
        result[label] = sorted(set(found))[:48]
    return result


def build_endpoint_inventory(
    own_response: Any, members_response: Any, gcc_response: Any,
    *, show_stat_candidates: bool = False, show_gcc_metadata: bool = False,
    member_read_utc: Optional[datetime] = None,
    gcc_read_utc: Optional[datetime] = None,
) -> dict[str, Any]:
    """Inventory exactly three already-obtained replies without logging them.

    May raise ServiceResponseError for unusable membership/roster structure.
    No values are exposed except explicitly opted-in numeric summaries of
    narrowly selected fields. GCC rank/score semantics remain independent.
    """
    own = OwnCrew.from_response(own_response)
    if not own.crew_uid:
        raise ServiceResponseError("account has no resolved crew")
    roster = CrewMembers.from_response(own.crew_uid, members_response)
    # Examine original wrappers instead of relying on decoded-model extras.
    own_payload = _payload_container(own_response)
    members_payload = _payload_container(members_response)
    roster_container, wire_rows = _crew_rows(members_payload)
    if not isinstance(wire_rows, list):
        raise ServiceResponseError("roster schema unavailable")
    gcc_payload = _payload_container(gcc_response)
    gcc_rows = gcc_payload.get("scores")
    if not isinstance(gcc_rows, list):
        # The progress endpoint may return an unfamiliar shape. Preserve a
        # safe census of the envelope and report no decoded leaderboard.
        gcc_rows = None
    member_rows = [member.extras for member in roster.members]
    known_row_count = len(member_rows)
    # Avoid exposing hidden nested data from the decoded model.
    gcc_census = _rows_summary(gcc_rows)
    return {
        "status": "read_only_endpoint_schema_inventory",
        "live_season_identity_verified": False,
        "source_contracts": ["crews/checkUserCrew", "crews/viewMembers",
                             "leaderboard/crew-champs-v2/viewcrew"],
        "raw_replies_saved": False,
        "field_values_printed": bool(show_stat_candidates or show_gcc_metadata),
        "own_crew": {
            "raw_envelope": _mapping_summary(own_response),
            "selected_payload": _mapping_summary(own_payload),
            "candidate_numeric": _numeric_census([own_payload], _OWN_NUMERIC,
                                                 show_values=show_stat_candidates),
        },
        "roster": {
            "raw_envelope": _mapping_summary(members_response),
            "selected_payload": _mapping_summary(members_payload),
            "member_array_container": _mapping_summary(roster_container),
            "member_rows": _rows_summary(member_rows),
            "wire_rows": known_row_count,
            "candidate_numeric": _numeric_census(member_rows, _MEMBER_NUMERIC,
                                                 show_values=show_stat_candidates),
        },
        "gcc_progress": {
            "raw_envelope": _mapping_summary(gcc_response),
            "selected_payload": _mapping_summary(gcc_payload),
            "scores_array_present": isinstance(gcc_rows, list),
            "score_rows": gcc_census,
            "timing_and_scope": _gcc_timing_metadata(
                gcc_payload, show_values=show_gcc_metadata, read_utc=gcc_read_utc),
            "season_identity_verified": False,
            "rank_score_units_confirmed_by_schema": False,
        },
        "rp_cross_read_comparison": _rp_cross_read_candidates(
            own_payload, roster, gcc_payload, show_values=show_stat_candidates,
            member_read_utc=member_read_utc, gcc_read_utc=gcc_read_utc),
        "metadata_key_cues": _metadata_cues(
            ("own_response", own_payload),
            ("roster_response", roster_container),
            ("gcc_response", gcc_payload),
        ),
        "notes": [
            "Reported schema keys are not evidence that fields have populated values or validated meaning.",
            "Numeric previews are candidates only, not validated currency/RP/season measurements.",
            "GCC logo and nested car/tournament fields are types only; no object values are printed.",
            "GCC timing interpretations and own-crew crew_rp are unverified candidates.",
            "Cross-endpoint RP comparisons are sequential and not a season validation.",
            "The census is capped to 1000 rows and 128 keys per object.",
        ],
    }


def _load_json(path: str) -> Any:
    file = Path(path)
    if file.stat().st_size > _MAX_BYTES:
        raise ValueError("input exceeds 8 MiB")
    return json.loads(file.read_text(encoding="utf-8-sig"))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Redacted census of three existing CSR2 crew read replies")
    parser.add_argument("--execute", action="store_true", help="prompt privately and authorize exactly the three established read-only endpoints")
    parser.add_argument("--own-json", help="offline own-crew JSON response")
    parser.add_argument("--members-json", help="offline crew-members JSON response")
    parser.add_argument("--gcc-json", help="offline GCC-progress JSON response")
    parser.add_argument("--show-stat-candidates", action="store_true", help="print selected own-crew numeric fields, aggregate member fields and cautious RP deltas; semantics unverified")
    parser.add_argument("--show-gcc-metadata", action="store_true", help="print strictly limited GCC timing, tier and bucket candidates; season meaning unverified")
    args = parser.parse_args(argv)
    offline = [args.own_json, args.members_json, args.gcc_json]
    if args.execute and any(offline):
        parser.error("--execute cannot be combined with offline response files")
    if any(offline) and not all(offline):
        parser.error("offline mode requires all three JSON files")
    if not args.execute and not all(offline):
        print(json.dumps({"mode": "dry_run", "network_requests": 0,
                          "raw_replies_saved": False, "schema_census_available": True}, indent=2))
        return 0
    if args.execute and not sys.stdin.isatty():
        print(json.dumps({"status": "interactive_terminal_required", "network_requests": 0}))
        return 2
    try:
        if args.execute:
            from .services import CSR2Services
            pid = getpass.getpass("Your own PlayerID (input hidden): ").strip()
            if not pid:
                raise ValueError("PlayerID required")
            with CSR2Services(pid, app_version="6.8.0", allow_network=True) as service:
                report = service.get_crew_endpoint_inventory(
                    show_stat_candidates=args.show_stat_candidates,
                    show_gcc_metadata=args.show_gcc_metadata)
        else:
            report = build_endpoint_inventory(
                _load_json(args.own_json), _load_json(args.members_json),
                _load_json(args.gcc_json),
                show_stat_candidates=args.show_stat_candidates,
                show_gcc_metadata=args.show_gcc_metadata)
    except (Exception, KeyboardInterrupt):
        # Exceptions may contain raw service, session, or file details.
        print(json.dumps({"status": "inventory_unavailable", "details": "suppressed"}))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
