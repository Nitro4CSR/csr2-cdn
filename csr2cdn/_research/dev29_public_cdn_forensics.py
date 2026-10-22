"""Dev29 public-CDN-only, explicitly opted-in, bounded source verification.

No authentication, player/crew identifiers, gameplay requests, filesystem
asset exports, source labels or new trusted mappings. The only outbound
operations are at most six allowlisted HTTPS GETs to the public asset CDN.
Offline/dry-run is the default. Original bundle bytes stay in memory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional, Callable

from ..cdn import DEFAULT_BASE_URL
from ..database import AssetDatabase
from .dev25_visual_forensics import audit_tnr_eligibility_source
from .dev27_native_wheel_forensics import audit_tuner_rim_source
from ..tnr_visual_probe import plan_tnr_assets

_CDN_ORIGIN = 'https://csr2.cdn.zynga.com'
# Unlike older probes, do not discover branches by guessing multiple names.
_BRANCH = re.compile(r'[0-9]{1,2}_[0-9]{1,2}_[0-9]{1,2}_Release(?:_OTA_[0-9]{1,3})?\Z', re.ASCII)
_VERSION = re.compile(r'[0-9]{1,12}\Z', re.ASCII)
_ALLOWED = {
    'paint': 'CarTunerStarsPaintLibrary',
    'interior': 'CarTunerStarsInteriorLibrary',
    'calliper': 'CarTunerStarsCalliperLibrary',
    'rim': 'CarTunerStarsRimLibrary',
}
_MAX_VERSION_BYTES = 128 * 1024
_MAX_DATABASE_BYTES = 32 * 1024 * 1024
_MAX_ASSET_BYTES = 8 * 1024 * 1024
_TIMEOUT = (5, 12)


class PublicCDNProbeError(ValueError):
    """Unverified or disallowed public response; details are not user-visible."""


def _bounded_get(session: Any, url: str, max_bytes: int) -> bytes:
    """Read a single allowlisted CDN object; reject redirects and oversized replies.

    The caller constructs the URL exclusively from validated fixed templates.
    Never accept a URL from remote JSON, user input or third-party redirects.
    """
    if not (type(url) is str and url.startswith(_CDN_ORIGIN + '/') and
            '?' not in url and '#' not in url and '\\' not in url):
        raise PublicCDNProbeError('non-CDN URL rejected')
    # Fixed response-limit and redirect policy independent of the session.
    response = session.get(url, stream=True, allow_redirects=False, timeout=_TIMEOUT,
                           headers={'Accept': 'application/json, application/octet-stream'})
    try:
        if response.status_code != 200:
            raise PublicCDNProbeError('public CDN response not successful')
        announced = response.headers.get('Content-Length')
        if announced is not None:
            if not announced.isascii() or not announced.isdecimal() or int(announced) > max_bytes:
                raise PublicCDNProbeError('public CDN object too large')
        payload = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            if not isinstance(chunk, bytes):
                raise PublicCDNProbeError('invalid public response chunk')
            if len(payload) + len(chunk) > max_bytes:
                raise PublicCDNProbeError('public CDN object exceeds cap')
            payload.extend(chunk)
        if not payload:
            raise PublicCDNProbeError('empty public CDN response')
        return bytes(payload)
    finally:
        response.close()


def _json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode('utf-8-sig'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PublicCDNProbeError('invalid public JSON') from exc


def validate_public_tnr_sources(branch: str, *, slots: tuple[str, ...] = (),
                                session: Any,
                                validated_asset_sink: Optional[Callable[[str, bytes], None]] = None) -> dict[str, Any]:
    """Validate exact source bytes from public CDN. 2..6 GETs, no credentials.

    Optional callback receives exact validated source bytes for the explicit
    Dev30 opt-in local cache, never by default. Callback cannot change trust.
    `session` is required so the network boundary is explicit and easy to
    replace with synthetic responses. No HTTP happens on import or dry-run.
    Returns only aggregate evidence; never bundles, IDs, category strings,
    roster values or player identifiers. Raises on any failed source audit.
    """
    if type(branch) is not str or not _BRANCH.fullmatch(branch):
        raise ValueError('invalid explicit release branch')
    if type(slots) is not tuple or len(slots) > 4 or any(type(s) is not str or s not in _ALLOWED for s in slots) or len(set(slots)) != len(slots):
        raise ValueError('invalid or duplicate requested visual slot')
    if DEFAULT_BASE_URL.rstrip('/') != _CDN_ORIGIN:
        raise PublicCDNProbeError('unexpected package CDN origin')
    requests_made = 0

    def fetch(url: str, cap: int) -> bytes:
        nonlocal requests_made
        requests_made += 1
        return _bounded_get(session, url, cap)

    # The only two discovery GETs; no store, metadata, HUB, login or gameplay.
    version_reply = _json(fetch(f'{_CDN_ORIGIN}/asset_database_{branch}.version', _MAX_VERSION_BYTES))
    if not isinstance(version_reply, dict):
        raise PublicCDNProbeError('unexpected version format')
    db_version = str(version_reply.get('version', ''))
    if not _VERSION.fullmatch(db_version):
        raise PublicCDNProbeError('invalid public database version')
    raw_db = fetch(f'{_CDN_ORIGIN}/asset_database.{db_version}.json', _MAX_DATABASE_BYTES)
    try:
        db = AssetDatabase.from_json(_json(raw_db))
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise PublicCDNProbeError('invalid public database') from exc
    if str(db.version) != db_version:
        raise PublicCDNProbeError('database header/version disagreement')
    index_sha256 = hashlib.sha256(raw_db).hexdigest()
    plan = plan_tnr_assets(db)
    entries = {entry.code: entry for entry in plan.entries}
    audits: dict[str, dict[str, Any]] = {}
    unavailable: list[str] = []
    source_sha256: dict[str, str] = {}
    for slot in slots:
        code = _ALLOWED[slot]
        entry = entries.get(code)
        if entry is None or not entry.available or not entry.url or not entry.size_bytes:
            unavailable.append(slot)
            continue
        # Fixed known code/path derived solely from a validated index row.
        expected_url = f'{_CDN_ORIGIN}/ANDROID/ASTC/{code}.ASTC.{entry.version}'
        if entry.url != expected_url or entry.size_bytes > _MAX_ASSET_BYTES:
            raise PublicCDNProbeError('untrusted candidate URL or source size')
        raw = fetch(expected_url, min(entry.size_bytes + 1, _MAX_ASSET_BYTES))
        if len(raw) != entry.size_bytes:
            raise PublicCDNProbeError('source bundle size disagrees with public index')
        try:
            audit = (audit_tuner_rim_source(raw) if slot == 'rim' else
                     audit_tnr_eligibility_source(raw, library=code))
        except (ValueError, UnicodeError, IndexError) as exc:
            raise PublicCDNProbeError('public source did not validate') from exc
        # Source decoder returns aggregate counts/booleans, no raw labels.
        audits[slot] = audit
        source_sha256[slot] = hashlib.sha256(raw).hexdigest()
        if validated_asset_sink is not None:
            validated_asset_sink(slot, raw)
    return {
        'status': 'public_cdn_source_validation_completed',
        'mode': 'read_only_public_cdn',
        'branch': branch,
        'database_version': db_version,
        'public_index_sha256': index_sha256,
        'validated_source_sha256': source_sha256,
        'network_requests': requests_made,
        'max_requests': 2 + len(slots),
        'public_index_tuner_assets_found': plan.found,
        'requested_slots': list(slots),
        'audited_slots': audits,
        'unavailable_slots': unavailable,
        'authentication_used': False,
        'gameplay_read_count': 0,
        'raw_bundles_saved': False,
        'player_roster_used': False,
        'source_numeric_ids_exposed': False,
        'candidate_names_trusted': False,
        'wheel_mappings_accepted': False,
        'color_mappings_accepted': False,
        'ui_appearance_verified': False,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description='Bounded public-CDN source audit; explicit --online required')
    parser.add_argument('--online', action='store_true', help='opt in to up to two public CDN index GETs plus one per requested slot')
    parser.add_argument('--branch', help='explicit release branch, e.g. 6_8_0_Release; no discovery')
    parser.add_argument('--slot', action='append', choices=tuple(_ALLOWED), default=[],
                        help='optional exact TNR source to fetch and audit; repeat up to four')
    parser.add_argument('--output', help='write sanitized report to NEW local JSON path; never saves bundles')
    args = parser.parse_args(argv)
    if (args.output and (Path(args.output).exists() or not Path(args.output).parent.is_dir())):
        parser.error('output must be a new path in an existing directory')
    if len(set(args.slot)) != len(args.slot):
        parser.error('duplicate slots not permitted')
    if args.branch is not None and not _BRANCH.fullmatch(args.branch):
        parser.error('invalid release branch')
    if args.online and not args.branch:
        parser.error('--online requires --branch')
    if not args.online:
        report = {'status': 'dry_run_no_requests', 'mode': 'offline',
                  'network_requests': 0, 'planned_max_requests': 2 + len(args.slot),
                  'requested_slots': args.slot, 'explicit_online_opt_in_required': True,
                  'gameplay_read_count': 0, 'authentication_used': False}
    else:
        import requests  # defer connection capability until explicit opt-in
        try:
            with requests.Session() as session:
                # Prevent ambient netrc credentials, cookies and env proxy auth.
                session.trust_env = False
                report = validate_public_tnr_sources(args.branch, slots=tuple(args.slot), session=session)
        except (Exception, KeyboardInterrupt):
            # No URI, credentials, raw JSON, player data or failed bundle bytes.
            report = {'status': 'public_cdn_validation_unavailable',
                      'details': 'suppressed; no mappings were changed',
                      'authentication_used': False, 'gameplay_read_count': 0,
                      'candidate_names_trusted': False}
            print(json.dumps(report))
            return 3
    if args.output:
        try:
            with Path(args.output).open('x', encoding='utf-8') as stream:
                json.dump(report, stream, indent=2)
        except OSError:
            print(json.dumps({'status': 'output_unavailable', 'details': 'suppressed'}))
            return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
