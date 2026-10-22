"""Dev37 offline-only source-ID lookup and bounded library-numbering gap audit.

Input: independently exported Dev36 PUBLIC source-ID catalogue + summary.
Important: gaps in *source numbering* do not identify unresolved roster IDs.
No CDN, authentication, gameplay, imports of network clients, or mapping changes.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

SLOT_BY_LIBRARY = {
    'CarPaintLibrary': 'paint',
    'CarInteriorLibrary': 'interior',
    'CarCalliperLibrary': 'calliper',
    'CarTunerStarsPaintLibrary': 'paint',
    'CarTunerStarsInteriorLibrary': 'interior',
    'CarTunerStarsCalliperLibrary': 'calliper',
}
MAX_CATALOG_BYTES = 24 * 1024 * 1024
MAX_SUMMARY_BYTES = 256 * 1024
MAX_IDS_FILE_BYTES = 128 * 1024
MAX_QUERIES = 1000
MAX_RECORDS = 100_000
MAX_INTERNAL_GAPS = 250_000
MAX_ID = 2**32 - 1
HASH = re.compile(r'[0-9a-f]{64}\Z')
DECIMAL = re.compile(r'[0-9]+\Z')


class SourceCatalogueError(ValueError):
    """Input is not a consistent Dev36 source-ID catalogue and summary."""


def _read_json(path: Path, maximum: int) -> Any:
    if path.is_symlink() or not path.is_file() or not 2 <= path.stat().st_size <= maximum:
        raise SourceCatalogueError('invalid local input')
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise SourceCatalogueError('unreadable local input') from exc


def load_catalog(catalog_path: Path, summary_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Check source metadata/record counts. This is NOT a fresh byte-hash check.

    A catalogue/summary with matching hash *strings* is consistent with the
    previously reported Dev36 hashes, not cryptographic proof about the bytes
    without the source bundles.
    """
    cat = _read_json(catalog_path, MAX_CATALOG_BYTES)
    summary = _read_json(summary_path, MAX_SUMMARY_BYTES)
    if not isinstance(cat, dict) or not isinstance(summary, dict):
        raise SourceCatalogueError('invalid source document')
    if cat.get('status') != 'public_source_id_catalog_not_unresolved_roster_ids' or summary.get('status') != 'current_release_public_cosmetic_sources_validated':
        raise SourceCatalogueError('unexpected source type')
    if not (cat.get('branch') == summary.get('branch') and cat.get('database_version') == summary.get('database_version')):
        raise SourceCatalogueError('catalogue and summary release mismatch')
    if cat.get('contains_player_or_roster_data') is not False or cat.get('mapping_promoted') is not False:
        raise SourceCatalogueError('unexpected sensitive data or accepted mapping')
    if summary.get('gameplay_read_count') != 0 or summary.get('authentication_used') is not False:
        raise SourceCatalogueError('unexpected gameplay source')
    hashes = cat.get('source_sha256')
    counts = summary.get('source_record_counts')
    if not isinstance(hashes, dict) or not isinstance(counts, dict) or set(hashes) != set(SLOT_BY_LIBRARY) or set(counts) != set(SLOT_BY_LIBRARY):
        raise SourceCatalogueError('missing source metadata')
    if hashes != summary.get('source_sha256') or not all(isinstance(s, str) and HASH.fullmatch(s) for s in hashes.values()):
        raise SourceCatalogueError('source fingerprint metadata mismatch')
    rows = cat.get('individual_source_ids')
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_RECORDS:
        raise SourceCatalogueError('invalid source records')
    seen: set[tuple[str, int]] = set()
    computed = {k: 0 for k in SLOT_BY_LIBRARY}
    checked = []
    for r in rows:
        if not isinstance(r, dict):
            raise SourceCatalogueError('invalid source row')
        library, slot, num = r.get('source_library'), r.get('slot'), r.get('numeric_id')
        label, category, extra = r.get('source_label'), r.get('source_category'), r.get('additional_source_labels')
        if library not in SLOT_BY_LIBRARY or SLOT_BY_LIBRARY[library] != slot or type(num) is not int or not 0 <= num <= MAX_ID:
            raise SourceCatalogueError('invalid library/slot/ID')
        if (library, num) in seen:
            raise SourceCatalogueError('duplicate numeric ID within a library')
        if not isinstance(label, str) or not label or len(label) > 512 or not isinstance(category, str) or not category or len(category) > 512:
            raise SourceCatalogueError('invalid label/category')
        if not isinstance(extra, list) or len(extra) > 16 or not all(isinstance(v, str) and len(v) <= 512 for v in extra):
            raise SourceCatalogueError('invalid additional labels')
        if r.get('vehicle_eligibility_verified') is not False or r.get('unresolved_roster_id') != 'unknown_without_saved_roster':
            raise SourceCatalogueError('input incorrectly claims roster evidence')
        seen.add((library, num))
        computed[library] += 1
        checked.append(r)
    if computed != counts or sum(counts.values()) != len(checked) or summary.get('source_total_records') != len(checked):
        raise SourceCatalogueError('source record counts do not match')
    return {'branch': summary['branch'], 'database_version': summary['database_version'],
            'source_sha256': dict(hashes), 'source_record_counts': dict(computed)}, checked


def index_and_gaps(rows: list[dict[str, Any]]) -> tuple[dict[tuple[str, int], list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Only gaps *between occupied IDs of each individual source library*."""
    idx: dict[tuple[str, int], list[dict[str, Any]]] = {}
    grouped = {k: [] for k in SLOT_BY_LIBRARY}
    for r in rows:
        idx.setdefault((r['slot'], r['numeric_id']), []).append(r)
        grouped[r['source_library']].append(r['numeric_id'])
    gap_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for lib in SLOT_BY_LIBRARY:
        occupied = sorted(grouped[lib])
        if not occupied:
            raise SourceCatalogueError('required library is empty')
        missing = occupied[-1] - occupied[0] + 1 - len(occupied)
        if missing > MAX_INTERNAL_GAPS:
            raise SourceCatalogueError('source-ID span too large')
        for prev, curr in zip(occupied, occupied[1:]):
            for num in range(prev + 1, curr):
                gap_rows.append({'slot': SLOT_BY_LIBRARY[lib], 'source_library': lib,
                                 'numeric_id': num, 'classification': 'unoccupied_inside_library_range'})
        summary_rows.append({'slot': SLOT_BY_LIBRARY[lib], 'source_library': lib,
                             'source_records': len(occupied), 'minimum_numeric_id': occupied[0],
                             'maximum_numeric_id': occupied[-1], 'internal_unoccupied_numbers': missing,
                             'unresolved_roster_ids': 'unknown_without_saved_roster'})
    return idx, summary_rows, gap_rows


def look_up_id(idx: dict[tuple[str, int], list[dict[str, Any]]], number: int, slot: str = 'all') -> dict[str, Any]:
    if type(number) is not int or not 0 <= number <= MAX_ID or slot not in ('paint','interior','calliper','all'):
        raise ValueError('invalid ID or slot')
    attrs = ('paint','interior','calliper') if slot == 'all' else (slot,)
    matches = [r for s in attrs for r in idx.get((s, number), [])]
    matched_slots = sorted({r['slot'] for r in matches})
    same_slot_collision = any(sum(r['slot'] == s for r in matches) > 1 for s in matched_slots)
    if not matches:
        status = 'not_present_in_selected_source_libraries'
    elif same_slot_collision:
        status = 'multiple_records_within_same_attribute_no_trusted_selection'
    elif len(matched_slots) > 1:
        status = 'present_in_multiple_attributes_not_a_collision'
    else:
        status = 'present_in_source_library'
    return {
        'numeric_id': number, 'requested_attribute': slot, 'status': status,
        'matched_attributes': matched_slots,
        'source_matches': [{
            'attribute': r['slot'], 'source_library': r['source_library'],
            'source_label': r['source_label'], 'additional_source_labels': list(r['additional_source_labels']),
            'source_category': r['source_category'], 'vehicle_eligibility_verified': False,
        } for r in sorted(matches, key=lambda r: (r['slot'],r['source_library']))],
        'is_known_unresolved_roster_id': False,
        'historical_roster_membership': 'unknown_without_saved_roster',
    }


def analyze(meta: dict[str, Any], rows: list[dict[str, Any]], ids: Iterable[int] = (), slot: str = 'all') -> dict[str, Any]:
    if slot not in ('paint','interior','calliper','all'):
        raise ValueError('invalid attribute filter')
    ids = list(ids)
    if len(ids) > MAX_QUERIES or any(type(n) is not int or not 0 <= n <= MAX_ID for n in ids):
        raise ValueError('too many or invalid IDs')
    idx, sources, gaps = index_and_gaps(rows)
    by_slot_collision = sum(len(v) > 1 for v in idx.values())
    return {
        'status': 'offline_source_catalogue_lookup_not_roster_gap_diagnosis',
        'branch': meta['branch'], 'database_version': meta['database_version'],
        'source_record_count': len(rows),
        'source_fingerprint_metadata_consistent': True,
        'original_source_bundle_bytes_reverified': False,
        'source_library_ranges': sources,
        'internal_source_numbering_gaps_total': len(gaps),
        'same_attribute_multi_source_ID_collisions': by_slot_collision,
        'individual_queries': [look_up_id(idx, n, slot) for n in dict.fromkeys(ids)],
        'gaps_are_unresolved_roster_ids': False,
        'historical_unresolved_roster_numeric_ids': 'not_available_without_roster_snapshot',
        'authentication_used': False, 'gameplay_read_count': 0, 'network_requests': 0,
        'mapping_promoted': False,
    }


def _read_queries(path: Path) -> list[int]:
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= MAX_IDS_FILE_BYTES:
        raise SourceCatalogueError('invalid numeric ID list')
    ids: list[int] = []
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        part = line.strip()
        if not part or part.startswith('#'):
            continue
        if not DECIMAL.fullmatch(part):
            raise SourceCatalogueError('numeric ID list contains non-decimal values')
        ids.append(int(part))
        if len(ids) > MAX_QUERIES:
            raise SourceCatalogueError('too many numeric IDs')
    return ids


def _private_csv_safe(s: Any) -> Any:
    # Public catalogue names are still untrusted CSV cell contents.
    if isinstance(s, str) and s.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + s
    return s


def _csv_bytes(fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({k: _private_csv_safe(row.get(k,'')) for k in fieldnames})
    return stream.getvalue().encode('utf-8-sig')


def _write_new(path: Path, data: bytes) -> None:
    """Exclusive output creation; default owner-only permissions where supported."""
    if path.is_symlink() or path.exists() or not path.parent.is_dir() or path.parent.is_symlink():
        raise SourceCatalogueError('invalid output location')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Offline Dev37 catalogue ID lookup; NOT unresolved roster ID recovery')
    parser.add_argument('--catalog', type=Path, required=True, help='Dev36 source-IDs JSON')
    parser.add_argument('--summary', type=Path, required=True, help='Matching Dev36 summary JSON')
    parser.add_argument('--id', type=int, action='append', default=[], help='Suspected decimal ID; repeat')
    parser.add_argument('--ids-file', type=Path, help='Optional plain-text decimal IDs (one per line)')
    parser.add_argument('--slot', choices=['all', 'paint', 'interior', 'calliper'], default='all')
    parser.add_argument('--output', type=Path, help='New JSON result file; also prints a short summary')
    parser.add_argument('--gaps-csv', type=Path, help='New CSV listing *library numbering gaps*, NOT missing roster IDs')
    parser.add_argument('--catalog-csv', type=Path, help='New CSV listing occupied public source IDs and labels')
    args = parser.parse_args(argv)
    destinations = [p for p in [args.output, args.gaps_csv, args.catalog_csv] if p is not None]
    if len(set(destinations)) != len(destinations) or any(p.exists() or p.is_symlink() or not p.parent.is_dir() for p in destinations):
        parser.error('each output must be a distinct new file in an existing directory')
    try:
        all_queries = args.id + (_read_queries(args.ids_file) if args.ids_file else [])
        meta, rows = load_catalog(args.catalog, args.summary)
        result = analyze(meta, rows, all_queries, args.slot)
        _, _, gaps = index_and_gaps(rows)
        if args.output:
            _write_new(args.output, (json.dumps(result, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
        if args.gaps_csv:
            _write_new(args.gaps_csv, _csv_bytes(['slot','source_library','numeric_id','classification'], gaps))
        if args.catalog_csv:
            flattened = ({'slot':r['slot'],'numeric_id':r['numeric_id'],'source_library':r['source_library'],
                          'source_label':r['source_label'],'source_category':r['source_category']} for r in rows)
            _write_new(args.catalog_csv, _csv_bytes(['slot','numeric_id','source_library','source_label','source_category'], flattened))
        # Never dump 1000 unrequested names to stdout; queries stay in JSON when requested.
        print(json.dumps(result if not args.output else {
            'status': result['status'], 'database_version': result['database_version'],
            'source_records': result['source_record_count'],
            'source_numbering_gaps': result['internal_source_numbering_gaps_total'],
            'lookups': len(result['individual_queries']), 'network_requests': 0}, indent=2, ensure_ascii=False))
        return 0
    except (SourceCatalogueError, ValueError, OSError, UnicodeError):
        print(json.dumps({'status':'local_catalogue_analysis_unavailable', 'network_requests':0,
                          'no_partial_mapping_published': True}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
