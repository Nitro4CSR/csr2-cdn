"""Opt-in, read-only *value-printing* investigation for GCC 14-day Crew RP.

Unlike live_validation (privacy-safe aggregates), this tool intentionally prints
member names and selected RP counters for comparison with the game's member
stats. NEVER paste its output without checking names and contributions first.

Authenticated network reads are limited to known read-only 6.8.0 crew
calls and (with separate --gcc-live opt-in) one reconstructed GCC progress
request. The APK's default route prefix is NOT verified runtime season
configuration. No write APIs or automatic file output are used. Without
--execute there is zero network traffic.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import json
import re
from pathlib import Path
import sys
import unicodedata
from typing import Any, Callable, Mapping, Optional

from csr2cdn.service_models import CrewMembers, GCCCrewStandings, GCCProgressCrewScores, ServiceResponseError
from csr2cdn.crew_rp import CrewRPSnapshot
from csr2cdn.services import CSR2Services, ServiceHTTPError


# Terminal-safe, legible nicknames: avoid control sequences in output. Do not
# reinterpret names or assume case/normalization uniqueness as member identity.
def _printable(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    return "".join(ch if unicodedata.category(ch)[0] != "C" else "?" for ch in s)[:120]


def _num(value: Optional[int]) -> str:
    return "—" if value is None else f"{value:,}"


def _field_values(raw: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Inspect only exact, source-backed score keys; never dump raw replies."""
    result = {}
    for key in fields:
        if key not in raw:
            continue
        value = raw[key]
        if type(value) is int and value >= 0:
            result[key] = value
        elif isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 20:
            result[key] = int(value)
    return result


def make_member_report(
    roster: CrewMembers, *, reference_total: Optional[int] = None,
    reference_rank: Optional[int] = None, expected_members: Optional[int] = None,
    season_note: str = "",
) -> dict[str, Any]:
    """Pure report construction from a decoded roster, no HTTP or I/O."""
    members = sorted(roster.members,
                     key=lambda m: (m.season_crew_rp_candidate is not None,
                                    m.season_crew_rp_candidate if m.season_crew_rp_candidate is not None else -1),
                     reverse=True)
    rows = []
    for position, member in enumerate(members, 1):
        raw = member.extras
        rows.append({
            "position_by_candidate": position,
            "member_name": _printable(member.nickname or member.name) or "(no name)",
            "player_level": member.player_rank,
            "cc_contrib": member.season_crew_rp_candidate if member.season_crew_rp_source == "cc_contrib" else None,
            "score_fallback": member.season_crew_rp_candidate if member.season_crew_rp_source == "score" else None,
            "candidate_source": member.season_crew_rp_source,
            "player_rp": member.player_rp,
            "rp_all_time": member.rp_all_time,
            # Names and numbers are deliberately printed; player IDs and the
            # original response dictionaries remain excluded from stdout.
        })
    ids = [m.player_uid or m.zid for m in members]
    identifiers = [uid for uid in ids if uid]
    contributions = [m.season_crew_rp_candidate for m in members]
    complete = bool(members) and all(n is not None for n in contributions)
    contribution_sum = sum(n for n in contributions if n is not None)
    report: dict[str, Any] = {
        "season_context_from_user": _printable(season_note),
        "season_scope_confirmed_by_server": False,
        "server_route": "crews/viewMembers",
        "roster_count": len(members),
        "expected_roster_count": expected_members,
        "expected_roster_count_matches": expected_members == len(members) if expected_members is not None else None,
        "distinct_preferred_identifiers": len(set(identifiers)),
        "all_identifiers_distinct_and_present": len(identifiers) == len(set(identifiers)) == len(members),
        "cc_contrib_numeric_rows": sum(r["cc_contrib"] is not None for r in rows),
        "score_fallback_numeric_rows": sum(r["score_fallback"] is not None for r in rows),
        "complete_numeric_contribution_coverage": complete,
        "sum_of_available_member_candidates": contribution_sum,
        "sum_is_complete": complete,
        "ui_reference_crew_total": reference_total,
        "ui_reference_crew_rank": reference_rank,
        "delta_member_sum_minus_ui_total": contribution_sum - reference_total if complete and reference_total is not None else None,
        "reference_is_a_snapshot_not_a_server_verified_season": True,
        "rows": rows,
    }
    return report


def make_gcc_report(
    response: Any, *, own_crew_uid: Optional[str] = None,
    reference_total: Optional[int] = None, reference_rank: Optional[int] = None,
) -> dict[str, Any]:
    """Decode native GCC JSON from an offline or explicitly authorized read."""
    standings = GCCCrewStandings.from_response(response)
    rows = []
    for entry in standings.crews:
        rows.append({
            "crew_name": _printable(entry.name) or "(unnamed)",
            "rank": entry.rank,
            "cc_rp": entry.season_crew_rp_candidate if entry.season_crew_rp_source == "cc_rp" else None,
            "score_fallback": entry.season_crew_rp_candidate if entry.season_crew_rp_source == "score" else None,
            "candidate_source": entry.season_crew_rp_source,
            "rp_all_time": entry.rp_all_time,
            "matches_own_crew_id": bool(own_crew_uid and entry.crew_uid == own_crew_uid),
        })
    own_rows = [row for row in rows if row["matches_own_crew_id"]]
    own = own_rows[0] if len(own_rows) == 1 else None
    return {
        "source": "supplied_local_gcc_response_not_live_request",
        "active_season_verified": False,
        "result_count": len(rows),
        "matched_own_crew_records": len(own_rows),
        "own_crew_cc_rp_minus_ui_total": own["cc_rp"] - reference_total if own and own["cc_rp"] is not None and reference_total is not None else None,
        "own_crew_rank_matches_ui": own["rank"] == reference_rank if own and own["rank"] is not None and reference_rank is not None else None,
        "rows": rows,
    }



def make_gcc_progress_report(
    response: Any, *, own_crew_uid: Optional[str] = None,
    reference_total: Optional[int] = None, reference_rank: Optional[int] = None,
    print_rows: bool = False,
) -> dict[str, Any]:
    """Join an observed GCC progress board to own crew using *only* crew_id.

    No fuzzy name/rank/score matching: ranks can change since a UI snapshot.
    Crew IDs and raw JSON never appear in the report; the full name/score
    listing is opt-in to preserve the dev25 diagnostic privacy boundary.
    """
    decoded = GCCProgressCrewScores.from_response(response)
    matches = [x for x in decoded.crews if own_crew_uid and x.crew_id == own_crew_uid]
    own = matches[0] if len(matches) == 1 else None
    result: dict[str, Any] = {
        "status": "gcc_progress_rows_decoded_season_unverified",
        "source": "gcc_current_progress_scores_wire_keys",
        "active_season_verified": False,
        "score_is_confirmed_season_crew_rp": False,
        "rank_is_server_returned": True,
        "result_count": len(decoded.crews),
        "unique_crew_ids": len(decoded.crews),
        "own_crew_id_available": bool(own_crew_uid),
        "matched_own_crew_records": len(matches),
        "own_crew_score_candidate": own.score if own else None,
        "own_crew_rank_returned": own.rank if own else None,
        "own_crew_name": _printable(own.name) if own and print_rows else None,
        "own_crew_score_minus_ui_snapshot": own.score - reference_total if own and reference_total is not None else None,
        "own_crew_rank_change_since_ui_snapshot": own.rank - reference_rank if own and reference_rank is not None else None,
        "ui_snapshot_total": reference_total,
        "ui_snapshot_rank": reference_rank,
        "standings_printed_by_opt_in": print_rows,
        "rows": [
            {"rank": x.rank, "crew_name": _printable(x.name), "score_candidate": x.score,
             "matches_own_crew_id": bool(own_crew_uid and x.crew_id == own_crew_uid)}
            for x in sorted(decoded.crews, key=lambda r: (r.rank, -r.score))
        ] if print_rows else [],
    }
    return result


def compare_sequential_crew_reads(
    member: Mapping[str, Any], gcc: Mapping[str, Any],
    *, member_read_utc: str, gcc_read_utc: str,
) -> dict[str, Any]:
    """Compare two sequential read-only responses; never imply atomic/season scope.

    Only a complete, distinct roster and a unique exact-ID GCC match are
    eligible. Missing/ambiguous data is reported as unavailable, not zero.
    """
    complete = (member.get("sum_is_complete") is True
                and member.get("all_identifiers_distinct_and_present") is True
                and member.get("expected_roster_count_matches") is not False
                and member.get("cc_contrib_numeric_rows") == member.get("roster_count")
                and member.get("roster_count", 0) > 0)
    matched = (gcc.get("status") == "gcc_progress_rows_decoded_season_unverified"
               and gcc.get("matched_own_crew_records") == 1)
    candidate = gcc.get("own_crew_score_candidate") if matched else None
    total = member.get("sum_of_available_member_candidates") if complete else None
    available = (type(candidate) is int and candidate >= 0
                 and type(total) is int and total >= 0)
    return {
        "status": "sequential_read_candidates_compared" if available else "comparison_unavailable",
        "member_read_utc": member_read_utc,
        "gcc_read_utc": gcc_read_utc,
        "not_an_atomic_snapshot": True,
        "season_scope_verified": False,
        "score_semantics_verified": False,
        "complete_cc_contrib_roster": complete,
        "exact_own_crew_id_match": matched,
        "member_cc_contrib_sum": total,
        "matched_gcc_score": candidate if type(candidate) is int else None,
        "member_sum_minus_gcc_score": total - candidate if available else None,
        "absolute_difference": abs(total - candidate) if available else None,
    }


def gcc_safe_schema(response: Any) -> dict[str, Any]:
    """Bounded list/known-field coverage if GCC response does not decode.

    Never returns arbitrary keys, IDs, nicknames, payloads, or error strings.
    """
    if not isinstance(response, Mapping):
        return {"envelope_type": type(response).__name__}
    permitted = ("results", "Results", "responseData", "data", "result",
                 "scores", "entries", "records", "crew_rank", "cc_rp")
    present = [k for k in permitted if k in response]
    types = {k: "array" if isinstance(response[k], list) else
             "object" if isinstance(response[k], Mapping) else "scalar"
             for k in present}
    nested = {}
    for k in present:
        v = response[k]
        if isinstance(v, Mapping):
            nested[k] = [name for name in permitted if name in v]
        elif isinstance(v, list):
            nested[k] = {"rows": min(len(v), 100000),
                         "dictionary_rows": sum(isinstance(e, Mapping) for e in v[:1000]),
                         "cc_rp_rows": sum(isinstance(e, Mapping) and "cc_rp" in e for e in v[:1000])}
    return {"recognized_fields": types, "recognized_nested_fields": nested}

# GCC progress payload seen in dev24: ``scores`` with 21 objects, none
# containing ``cc_rp`` at the top level. The native GCC *results* decoder
# takes RemoteCrewInfo records, but does not establish that *progress*
# score rows have the same schema or RP units. This deliberately reports only
# bounded structural evidence and, if opted in, strictly whitelisted values.
_GCC_ROW_KEYS = (
    "score", "cc_rp", "rp", "rank", "crew_rank", "position", "place", "pos",
    "name", "crew_name", "crewName", "id", "uid", "crew_uid", "crewUID",
    "value", "points", "result", "crew", "entity", "user", "profile",
    "player", "metadata", "season_id", "season", "seasonId", "tier",
    "bucket", "leaderboard", "total", "displayName", "nickname",
)
_GCC_NESTED_OBJECTS = ("crew", "entity", "user", "profile", "player", "result", "score", "metadata")
_GCC_PREVIEW_NUMERIC = ("score", "value", "points", "cc_rp", "rank", "crew_rank", "position", "place", "pos")
_GCC_PREVIEW_NAME = ("crew_name", "crewName", "name", "displayName")


def _shape_type(value: Any) -> str:
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    return "other"


def _score_int(value: Any) -> Optional[int]:
    if type(value) is int and 0 <= value <= 2**63 - 1:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 19:
        n = int(value)
        return n if n <= 2**63 - 1 else None
    return None


def gcc_scores_shape(response: Any, *, print_candidates: bool = False, show_schema_keys: bool = False) -> dict[str, Any]:
    """Inspect native GCC progress ``scores`` shape, not inferred standings.

    Never serialize raw mappings, unknown keys or IDs. A value-printing opt-in
    allows bounded display of whitelisted score/rank/name hints; these are NOT
    mapped to RemoteCrewInfo and cannot verify a 14-day season or leader rank.
    """
    node = response
    if isinstance(response, Mapping) and isinstance(response.get("responseData"), Mapping):
        node = response["responseData"]
    if not isinstance(node, Mapping) or not isinstance(node.get("scores"), list):
        raise ValueError("No recognized scores array")
    scores = node["scores"]
    rows = scores[:1000]
    counts: dict[str, dict[str, int]] = {}
    nested: dict[str, dict[str, dict[str, int]]] = {}
    schema_keys: dict[str, dict[str, int]] = {}
    previews = []
    for i, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        if show_schema_keys:
            for key, value in row.items():
                # Schema *names* only, never values. Reject unusual dynamic or
                # sensitive-looking field names; cap total exposure/size.
                if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", key):
                    continue
                if any(part in key.lower() for part in ("token", "secret", "auth", "password", "credential", "session", "cookie", "bearer", "jwt", "private")):
                    continue
                if key not in schema_keys and len(schema_keys) >= 64:
                    continue
                kind = _shape_type(value)
                kinds = schema_keys.setdefault(key, {})
                kinds[kind] = kinds.get(kind, 0) + 1
        for key in _GCC_ROW_KEYS:
            if key not in row:
                continue
            shape = _shape_type(row[key])
            kinds = counts.setdefault(key, {})
            kinds[shape] = kinds.get(shape, 0) + 1
        for key in _GCC_NESTED_OBJECTS:
            obj = row.get(key)
            if not isinstance(obj, Mapping):
                continue
            values = nested.setdefault(key, {})
            for sub in _GCC_ROW_KEYS:
                if sub in obj:
                    kinds = values.setdefault(sub, {})
                    shape = _shape_type(obj[sub])
                    kinds[shape] = kinds.get(shape, 0) + 1
        if print_candidates and len(previews) < 50:
            # Only recognize exact, vetted paths and printable labels. No IDs,
            # raw dictionaries, arbitrary properties or credential-bearing strings.
            preview: dict[str, Any] = {"response_row_index": i + 1}
            for key in _GCC_PREVIEW_NUMERIC:
                if key in row:
                    n = _score_int(row[key])
                    if n is not None:
                        preview[key + "_unverified"] = n
            for key in _GCC_PREVIEW_NAME:
                if isinstance(row.get(key), str):
                    preview["name_hint_unverified"] = _printable(row[key])
                    break
            for parent in ("crew", "entity", "score"):
                obj = row.get(parent)
                if not isinstance(obj, Mapping):
                    continue
                for key in _GCC_PREVIEW_NUMERIC:
                    if key in obj:
                        n = _score_int(obj[key])
                        if n is not None:
                            preview[parent + "." + key + "_unverified"] = n
                if "name_hint_unverified" not in preview:
                    for key in _GCC_PREVIEW_NAME:
                        if isinstance(obj.get(key), str):
                            preview["name_hint_unverified"] = _printable(obj[key])
                            break
            if len(preview) > 1:
                previews.append(preview)
    # Iteration is deliberately bounded; 21 expected entries were observed,
    # but no code here asserts 21 crews or global leaderboard coverage.
    return {
        "status": "unverified_gcc_progress_scores_shape",
        "not_a_decoded_crew_leaderboard": True,
        "active_season_verified": False,
        "row_count": len(scores),
        "inspected_rows": len(rows),
        "dictionary_rows": sum(isinstance(r, Mapping) for r in rows),
        "known_row_fields_by_type": counts,
        "known_nested_fields_by_type": nested,
        "schema_key_names_opted_in": show_schema_keys,
        "schema_key_type_counts": schema_keys if show_schema_keys else {},
        "cc_rp_top_level_rows": counts.get("cc_rp", {}).get("integer", 0) + counts.get("cc_rp", {}).get("string", 0),
        "candidate_value_preview_opted_in": print_candidates,
        "candidate_value_preview_limit": 50,
        "candidate_rows": previews if print_candidates else [],
        "warning": "Scores/positions are not mapped to Crew RP or crew ranks; no season ID confirmed",
    }


def _load_json(path: str) -> Any:
    source = Path(path)
    if source.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("GCC response file exceeds 8 MiB")
    return json.loads(source.read_text(encoding="utf-8-sig"))


def _table(report: dict[str, Any]) -> str:
    lines = [
        "Crew RP read-only comparison — USER-SUPPLIED UI SNAPSHOT, NOT A VERIFIED SEASON",
        f"UTC snapshot: {report['at_utc']}",
    ]
    member = report.get("member_response")
    if member and "rows" not in member:
        lines.append(f"CREW: {member.get('status', 'unavailable')}")
    elif member:
        lines.extend([
            f"Season clue (provided by operator): {member['season_context_from_user'] or '(none)'}",
            f"Roster: {member['roster_count']} / expected {member['expected_roster_count'] or 'unspecified'}; "
            f"distinct IDs: {member['distinct_preferred_identifiers']}; cc_contrib: {member['cc_contrib_numeric_rows']}",
            "Rank here is sort order by candidate, not crew leaderboard rank.",
            " #  Member name                         Level  cc_contrib    score fallback      player_rp     all-time RP",
            "--  ----------------------------------- ------  ------------  --------------  ------------  ------------",
        ])
        for row in member["rows"]:
            lines.append(f"{row['position_by_candidate']:>2}  {row['member_name'][:35]:35} "
                         f"{_num(row['player_level']):>6}  {_num(row['cc_contrib']):>12}  "
                         f"{_num(row['score_fallback']):>14}  "
                         f"{_num(row['player_rp']):>12}  {_num(row['rp_all_time']):>12}")
        lines.extend([
            f"SUM member candidate RP: {_num(member['sum_of_available_member_candidates'])}" +
            (" (complete)" if member["sum_is_complete"] else " (INCOMPLETE)"),
            f"UI CREW TOTAL (operator snapshot): {_num(member['ui_reference_crew_total'])}; "
            f"UI CREW RANK (operator snapshot): {_num(member['ui_reference_crew_rank'])}",
            f"MEMBER SUM MINUS UI TOTAL: {_num(member['delta_member_sum_minus_ui_total'])}",
        ])
        if report.get("own_crew_field_candidates"):
            lines.append(f"Own-crew response candidate fields: {report['own_crew_field_candidates']}")
    snapshot = report.get("crew_rp_snapshot")
    if snapshot:
        lines.append("TYPED CREW RP SNAPSHOT (READ-ONLY; NOT ATOMIC):")
        if snapshot.get("status") == "snapshot_unavailable":
            lines.append("Snapshot unavailable (suppressed details)")
        else:
            lines.append(
                f"Returned members: {snapshot['members_returned']}; "
                f"leaderboard score: {_num(snapshot['leaderboard_score'])}; "
                f"rank: {_num(snapshot['leaderboard_rank'])}; "
                f"comparable: {snapshot['comparable']}; "
                f"delta: {_num(snapshot['member_sum_minus_leaderboard'])}")
            if snapshot["warnings"]:
                lines.append("Snapshot checks: " + ", ".join(snapshot["warnings"]))
    comparison = report.get("sequential_roster_gcc_comparison")
    if comparison:
        lines.extend([
            "SEQUENTIAL ROSTER ↔ GCC SCORE COMPARISON (NOT ATOMIC / SEASON UNVERIFIED):",
            f"Member read at UTC: {comparison['member_read_utc']}; GCC read at UTC: {comparison['gcc_read_utc']}",
            f"Coverage: complete cc_contrib roster={comparison['complete_cc_contrib_roster']}; "
            f"exact own-crew ID match={comparison['exact_own_crew_id_match']}",
            f"Roster cc_contrib sum: {_num(comparison['member_cc_contrib_sum'])}; "
            f"matched GCC score: {_num(comparison['matched_gcc_score'])}; "
            f"sum minus score: {_num(comparison['member_sum_minus_gcc_score'])}",
        ])
    gcc = report.get("gcc_live_response") or report.get("gcc_supplied_response")
    if gcc and "rows" in gcc and gcc.get("status") != "gcc_progress_rows_decoded_season_unverified":
        lines.extend([
            "GCC leaderboard (LIVE experimental progress)" if report.get("gcc_live_response")
            else "GCC leaderboard (SUPPLIED JSON; not fetched by this command):",
            "Rank   Crew name                            cc_rp          all-time RP     Own crew?",
            "------ ----------------------------------- -------------- --------------- ----------",
        ])
        for row in gcc["rows"]:
            lines.append(f"{_num(row['rank']):>6} {row['crew_name'][:35]:35} "
                         f"{_num(row['cc_rp']):>14} {_num(row['rp_all_time']):>15} "
                         f"{'yes' if row['matches_own_crew_id'] else 'no'}")
        lines.append(f"OWN CREW GCC CC_RP MINUS UI TOTAL: {_num(gcc['own_crew_cc_rp_minus_ui_total'])}")
        lines.append(f"OWN CREW GCC RANK MATCHES UI: {gcc['own_crew_rank_matches_ui']}")
    elif gcc and gcc.get("status") == "gcc_progress_rows_decoded_season_unverified":
        lines.extend([
            "GCC PROGRESS: SERVER RANK/SCORE ROWS DECODED; ACTIVE-SEASON RP NOT VERIFIED",
            f"Rows: {gcc['result_count']}; distinct crew IDs: {gcc['unique_crew_ids']}",
            f"OWN CREW ID MATCH COUNT: {gcc['matched_own_crew_records']}",
            f"OWN CREW SCORE CANDIDATE: {_num(gcc['own_crew_score_candidate'])}; "
            f"SERVER RANK: {_num(gcc['own_crew_rank_returned'])}",
            f"SCORE MINUS UI SNAPSHOT: {_num(gcc['own_crew_score_minus_ui_snapshot'])}; "
            f"RANK CHANGE SINCE UI SNAPSHOT: {_num(gcc['own_crew_rank_change_since_ui_snapshot'])}",
        ])
        if gcc['standings_printed_by_opt_in']:
            lines.extend(["SERVER GCC PROGRESS (score units / season unverified):",
                          " Rank  Crew name                              score          Own crew?",
                          "------ ------------------------------------ -------------- ----------"])
            for row in gcc['rows']:
                lines.append(f"{row['rank']:>5}  {row['crew_name'][:36]:36} "
                             f"{_num(row['score_candidate']):>14} "
                             f"{'yes' if row['matches_own_crew_id'] else 'no'}")
        lines.append("GCC progress score is not yet proven identical to current-season Crew RP; season metadata absent.")
    elif gcc and gcc.get("status") == "unverified_gcc_progress_scores_shape":
        lines.extend([
            "GCC PROGRESS SCORES: RESPONSE SHAPE IDENTIFIED, CREW STANDINGS NOT DECODED",
            f"Rows: {gcc['row_count']}; objects: {gcc['dictionary_rows']}; inspected: {gcc['inspected_rows']}",
            "Row field types (presence only): " + json.dumps(gcc["known_row_fields_by_type"], ensure_ascii=False, sort_keys=True),
            "Nested field types (presence only): " + json.dumps(gcc["known_nested_fields_by_type"], ensure_ascii=False, sort_keys=True),
        ])
        if gcc["schema_key_names_opted_in"]:
            lines.append("Sanitized row key names and types (no values): " +
                         json.dumps(gcc["schema_key_type_counts"], ensure_ascii=False, sort_keys=True))
        if gcc["candidate_value_preview_opted_in"]:
            lines.append("UNVERIFIED SCORE/RANK HINTS (not seasonal RP / crew rank):")
            for candidate in gcc["candidate_rows"]:
                lines.append(json.dumps(candidate, ensure_ascii=False))
        lines.append("GCC crew totals, ranks and active-season scope: NOT VERIFIED")
    elif gcc:
        lines.append(f"GCC LIVE RESPONSE SCHEMA NOT RECOGNIZED: {json.dumps(gcc, ensure_ascii=False)}")
    else:
        lines.append("GCC LEADERBOARD: NOT QUERIED — add --gcc-live to explicitly probe the APK default GCC progress route.")
    lines.append("IMPORTANT: no claim of 14-day season scope or in-game equivalence is made by this test.")
    return "\n".join(lines)


def verify(
    *, player_id: Optional[str] = None, execute: bool = False, gcc_response: Any = None,
    reference_total: Optional[int] = None, reference_rank: Optional[int] = None,
    expected_members: Optional[int] = None, season_note: str = "",
    gcc_live: bool = False, gcc_only: bool = False, gcc_print_score_candidates: bool = False,
    gcc_show_schema_keys: bool = False,
    services_factory: Callable[..., Any] = CSR2Services,
) -> dict[str, Any]:
    """Only allowlisted read operations; GCC is an explicit extra opt-in."""
    result: dict[str, Any] = {
        "at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "read_only_crew_rp_verification",
        "network_requests_allowed": bool(execute),
        "gcc_live_requested": bool(gcc_live),
    }
    own_uid: Optional[str] = None
    decoded_roster: Optional[CrewMembers] = None
    if execute:
        if not player_id:
            raise ValueError("PlayerID required for executed read")
        with services_factory(player_id, app_version="6.8.0", allow_network=True) as svc:
            own = svc.get_my_crew()
            if not own.in_crew:
                result["member_response"] = {"status": "not_in_crew"}
            else:
                own_uid = own.crew_uid
                # Only source-confirmed keys and scalar values; NEVER raw response.
                result["own_crew_field_candidates"] = _field_values(
                    own.extras, ("cc_rp", "score", "rp", "crew_rank"))
                if not gcc_only:
                    roster = svc.get_crew_members()
                    decoded_roster = roster
                    # Occupied member count is not hardcoded to 29. Trust an
                    # explicit operator count, otherwise use own-crew's returned
                    # memberCount when the backend supplies a plausible value.
                    inferred_count = (own.member_count if type(own.member_count) is int
                                      and 1 <= own.member_count <= 30 else None)
                    actual_expected = expected_members if expected_members is not None else inferred_count
                    result["roster_count_reference_source"] = (
                        "operator" if expected_members is not None else
                        "own_crew_memberCount" if inferred_count is not None else "not_available")
                    result["member_response"] = make_member_report(
                        roster, reference_total=reference_total,
                        reference_rank=reference_rank, expected_members=actual_expected,
                        season_note=season_note)
                    result["member_read_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if gcc_live:
                # One request, no replay, no catch-all fallback to other boards.
                response = svc.get_gcc_progress_response()
                result["gcc_read_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                try:
                    gcc = make_gcc_progress_report(
                        response, own_crew_uid=own_uid,
                        reference_total=reference_total, reference_rank=reference_rank,
                        print_rows=gcc_print_score_candidates)
                    result["gcc_live_response"] = gcc
                except (ValueError, TypeError, ServiceResponseError):
                    try:
                        gcc = make_gcc_report(response, own_crew_uid=own_uid,
                                          reference_total=reference_total,
                                          reference_rank=reference_rank)
                        gcc["source"] = "live_gcc_progress_apk_default_route_unverified_season"
                        result["gcc_live_response"] = gcc
                    except (ValueError, TypeError, ServiceResponseError):
                        try:
                            result["gcc_live_response"] = gcc_scores_shape(
                                response, print_candidates=gcc_print_score_candidates,
                                show_schema_keys=gcc_show_schema_keys)
                        except (ValueError, TypeError, ServiceResponseError):
                            result["gcc_live_response"] = {"status": "unrecognized_native_gcc_schema",
                                                           "fields": gcc_safe_schema(response)}
                if (decoded_roster is not None and own_uid
                        and gcc.get("status") == "gcc_progress_rows_decoded_season_unverified"):
                    try:
                        overview = CrewRPSnapshot.from_reads(
                            decoded_roster, GCCProgressCrewScores.from_response(response),
                            own_crew_id=own_uid,
                            member_read_utc=datetime.fromisoformat(result["member_read_utc"]),
                            gcc_read_utc=datetime.fromisoformat(result["gcc_read_utc"]),
                            expected_member_count=result["member_response"].get("expected_roster_count"),
                            season_marker=season_note or None)
                        result["crew_rp_snapshot"] = overview.public_summary()
                    except (ValueError, TypeError, ServiceResponseError):
                        result["crew_rp_snapshot"] = {"status": "snapshot_unavailable"}
                if "rows" in result.get("member_response", {}):
                    legacy_comparison = compare_sequential_crew_reads(
                        result["member_response"], result["gcc_live_response"],
                        member_read_utc=result["member_read_utc"], gcc_read_utc=result["gcc_read_utc"])
                    # The old diagnostic did not check timestamps. Do not print
                    # a seemingly valid delta when the stricter typed snapshot
                    # has rejected stale, incomplete or skewed reads.
                    guarded = result.get("crew_rp_snapshot")
                    if guarded is not None and guarded.get("comparable") is not True:
                        legacy_comparison["status"] = "comparison_unavailable"
                        legacy_comparison["member_sum_minus_gcc_score"] = None
                        legacy_comparison["absolute_difference"] = None
                        legacy_comparison["guarded_by_typed_snapshot"] = True
                    result["sequential_roster_gcc_comparison"] = legacy_comparison
    if gcc_response is not None:
        try:
            result["gcc_supplied_response"] = make_gcc_progress_report(
                gcc_response, own_crew_uid=own_uid,
                reference_total=reference_total, reference_rank=reference_rank,
                print_rows=gcc_print_score_candidates)
        except (ValueError, TypeError, ServiceResponseError):
            try:
                result["gcc_supplied_response"] = make_gcc_report(
                    gcc_response, own_crew_uid=own_uid,
                    reference_total=reference_total, reference_rank=reference_rank)
            except (ValueError, TypeError, ServiceResponseError):
                try:
                    result["gcc_supplied_response"] = gcc_scores_shape(
                        gcc_response, print_candidates=gcc_print_score_candidates,
                        show_schema_keys=gcc_show_schema_keys)
                except (ValueError, TypeError, ServiceResponseError):
                    result["gcc_supplied_response"] = {"status": "unrecognized_native_gcc_schema",
                                                        "fields": gcc_safe_schema(gcc_response)}
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Print live own-crew contribution candidates and compare a user-supplied UI snapshot")
    parser.add_argument("--execute", action="store_true", help="authorize authenticated read-only calls (prompts privately for PlayerID)")
    parser.add_argument("--gcc-live", action="store_true", help="also query one EXPERIMENTAL GCC current-progress read using the APK-default route (runtime season unverified)")
    parser.add_argument("--gcc-only", action="store_true", help="with --gcc-live, skip member roster request; look up own crew for matching and query GCC")
    parser.add_argument("--gcc-print-score-candidates", action="store_true", help="print all structurally decoded crew name/rank/score rows (season units unverified); otherwise limit to safe diagnostics")
    parser.add_argument("--gcc-show-schema-keys", action="store_true", help="show bounded, sanitized score-row key names and value types (never raw payload values)")
    parser.add_argument("--print-member-values", action="store_true", help="explicitly acknowledge that nicknames, player levels and RP values will be printed")
    parser.add_argument("--reference-total", type=int, help="crew leaderboard RP seen in-game (operator snapshot)")
    parser.add_argument("--reference-rank", type=int, help="crew leaderboard rank seen in-game (operator snapshot)")
    parser.add_argument("--expected-members", type=int, help="optional occupied member count; otherwise use server memberCount when present")
    parser.add_argument("--season-note", default="", help="operator-known season clue; NOT proof of server season scope")
    parser.add_argument("--gcc-response-json", help="optional already-captured local GCC JSON results; NEVER triggers a guessed leaderboard request")
    parser.add_argument("--format", choices=("table", "json"), default="table")
    args = parser.parse_args(argv)
    for key in ("reference_total", "reference_rank", "expected_members"):
        value = getattr(args, key)
        if value is not None and value < 0:
            parser.error(f"--{key.replace('_','-')} must be nonnegative")
    if args.execute and not args.print_member_values:
        parser.error("--execute requires --print-member-values (this command intentionally prints personal crew statistics)")
    if args.gcc_live and not args.execute:
        parser.error("--gcc-live requires --execute")
    if args.gcc_only and not args.gcc_live:
        parser.error("--gcc-only requires --gcc-live")
    if (args.gcc_print_score_candidates or args.gcc_show_schema_keys) and not (args.gcc_live or args.gcc_response_json):
        parser.error("--gcc-print-score-candidates and --gcc-show-schema-keys require --gcc-live or --gcc-response-json")
    if not args.execute and not args.gcc_response_json:
        print(json.dumps({"mode": "dry_run", "network_requests": 0,
                          "member_values_printed": False, "gcc_live_request_supported": "experimental_opt_in_only"}, indent=2))
        return 0
    if args.execute and not sys.stdin.isatty():
        print(json.dumps({"status": "interactive_terminal_required", "network_requests": 0}))
        return 2
    try:
        gcc_response = _load_json(args.gcc_response_json) if args.gcc_response_json else None
        player_id = getpass.getpass("Your own PlayerID (input hidden): ").strip() if args.execute else None
        result = verify(
            player_id=player_id, execute=args.execute, gcc_response=gcc_response,
            reference_total=args.reference_total, reference_rank=args.reference_rank,
            expected_members=args.expected_members, season_note=args.season_note,
            gcc_live=args.gcc_live, gcc_only=args.gcc_only,
            gcc_print_score_candidates=args.gcc_print_score_candidates,
            gcc_show_schema_keys=args.gcc_show_schema_keys)
    except ServiceHTTPError as exc:
        # HTTP status is useful for distinguishing an unconfigured GCC route
        # from a recognized response. No URI, headers or response body printed.
        print(json.dumps({"status": "read_http_error", "http_status": exc.status_code,
                          "details": "suppressed"}))
        return 1
    except (Exception, KeyboardInterrupt):
        # Network exceptions can contain account material; never echo or dump.
        print(json.dumps({"status": "validation_unavailable", "details": "suppressed"}))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.format == "json" else _table(result))
    # Exit 0 only if the requested JSON shape was actually recognized.
    # Partial/no GCC decoding remains diagnostic and NOT a successful standings read.
    gcc = result.get("gcc_live_response") or result.get("gcc_supplied_response")
    return 3 if gcc and gcc.get("status") in (
        "unrecognized_native_gcc_schema", "unverified_gcc_progress_scores_shape") else 0


if __name__ == "__main__":
    raise SystemExit(main())
