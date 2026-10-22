"""Dev78: offline, conservative validation of optional non-mutating paint snapshots.

This tool never acquires gameplay state. A self-described passive capture is NOT
independently authenticated; synthetic inputs can never verify production paint.
The pinned Dev72-77 native audit runs first against the supplied local APK.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .dev77_gacha_config_validity import inspect as inspect_dev77, model_config_validity
from .dev75_gacha_eligibility import model_gacha_decision

_SCHEMA = 'csr2cdn.dev78.runtime-paint-snapshot.v1'
_CAR = 'Ford_Mustang302_1970'
_MAX_SNAPSHOT = 131072
_MAX_PAINTS = 4096
_MAX_INT32 = (1 << 31) - 1
_MIN_INT32 = -(1 << 31)


def _object(obj: Any, location: str, *, required: set[str], optional: set[str] = frozenset()) -> dict[str, Any]:
    if type(obj) is not dict:
        raise ValueError(location + ': expected JSON object')
    missing = required - obj.keys()
    extra = obj.keys() - required - optional
    if missing:
        raise ValueError(location + ': missing keys ' + ', '.join(sorted(missing)))
    if extra:
        raise ValueError(location + ': unrecognized keys ' + ', '.join(sorted(extra)))
    return obj


def _number(value: Any, location: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{location}: expected integer in [{low}, {high}]')
    return value


def _boolean(value: Any, location: str) -> bool:
    if type(value) is not bool:
        raise ValueError(location + ': expected boolean')
    return value


def _pair(values: Any, location: str, *, size: int, low: int, high: int) -> list[int]:
    if type(values) is not list or len(values) != size:
        raise ValueError(f'{location}: expected exactly {size} integers')
    return [_number(x, f'{location}[{i}]', low, high) for i, x in enumerate(values)]


def _parse_json(contents: str) -> Any:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        found: dict[str, Any] = {}
        for k, v in pairs:
            if k in found:
                raise ValueError('snapshot: duplicate JSON key ' + k)
            found[k] = v
        return found
    def bad_constant(value: str) -> Any:
        raise ValueError('snapshot: nonfinite numeric constant ' + value)
    return json.loads(contents, object_pairs_hook=unique_pairs, parse_constant=bad_constant)


def load_snapshot(path: Path) -> dict[str, Any]:
    """Bounded, UTF-8 strict, no-follow-input read; never reads a URL."""
    if path.is_symlink() or not path.is_file():
        raise ValueError('snapshot must be a regular local file, not a symlink')
    with path.open('rb') as stream:
        body = stream.read(_MAX_SNAPSHOT + 1)
    if len(body) > _MAX_SNAPSHOT:
        raise ValueError('snapshot exceeds 128 KiB')
    try:
        return _parse_json(body.decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('snapshot is not strict UTF-8 JSON') from exc


def _paint_stage(stage: Any, location: str) -> dict[str, Any]:
    stage = _object(stage, location,
        required={'ordered_paint_ids', 'selected_index'}, optional={'observed_paint_id'})
    ids = stage['ordered_paint_ids']
    if type(ids) is not list or not 0 < len(ids) <= _MAX_PAINTS:
        raise ValueError(location + ': expected 1-4096 ordered paint IDs')
    paints = [_number(x, f'{location}.ordered_paint_ids[{i}]', 0, _MAX_INT32)
              for i, x in enumerate(ids)]
    index = _number(stage['selected_index'], location + '.selected_index', _MIN_INT32, _MAX_INT32)
    selected = paints[index] if 0 <= index < len(paints) else None
    observed = stage.get('observed_paint_id')
    if observed is not None:
        _number(observed, location + '.observed_paint_id', 0, _MAX_INT32)
    # Preserve zero as a legitimate ID; None means unknown/unavailable.
    if observed is not None and selected != observed:
        raise ValueError(location + ': observed paint ID differs from indexed list ID')
    return {
        'count': len(paints), 'selected_index': index,
        'index_in_bounds': selected is not None, 'resolved_paint_id': selected,
        'observed_id_supplied': observed is not None,
        'observed_id_matches_index': observed == selected if observed is not None else None,
        'ordered_list_sha256': hashlib.sha256(
            json.dumps(paints, separators=(',', ':')).encode('ascii')).hexdigest(),
        'contains_duplicate_ids': len(set(paints)) != len(paints),
        'index_0_id': paints[0],
        'candidate_15_from_list': paints[15] if len(paints) > 15 else None,
    }


def _gacha(gacha: Any) -> dict[str, Any]:
    keys = {'delivery_tuple_low_high', 'flag_0x160', 'garage_word_0xb0',
            'config_fields_0x1c_0x20_0x24_0x28', 'secondary_filter_rejects',
            'config_count', 'config_entry_present', 'observed_apply_gacha_called'}
    gacha = _object(gacha, 'gacha', required=keys)
    low, high = _pair(gacha['delivery_tuple_low_high'], 'delivery_tuple_low_high',
                      size=2, low=_MIN_INT32, high=_MAX_INT32)
    fields = _pair(gacha['config_fields_0x1c_0x20_0x24_0x28'], 'config_fields',
                   size=4, low=_MIN_INT32, high=0xFFFFFFFF)
    flag = _boolean(gacha['flag_0x160'], 'flag_0x160')
    garage = _number(gacha['garage_word_0xb0'], 'garage_word_0xb0', _MIN_INT32, 0xFFFFFFFF)
    secondary = _boolean(gacha['secondary_filter_rejects'], 'secondary_filter_rejects')
    count = _number(gacha['config_count'], 'config_count', 0, 1_000_000)
    present = _boolean(gacha['config_entry_present'], 'config_entry_present')
    called = _boolean(gacha['observed_apply_gacha_called'], 'observed_apply_gacha_called')
    validity = model_config_validity(fields)
    packed = ((high & 0xFFFFFFFF) << 32) | (low & 0xFFFFFFFF)
    derived = model_gacha_decision(packed, flag_0x160=flag,
        config_is_valid=validity['is_valid'], garage_word_0xb0=garage,
        secondary_filter_rejects=secondary, config_count=count,
        config_entry_present=present)
    if called and not derived['can_reach_gacha_call_under_inputs']:
        raise ValueError('gacha: observed call contradicts modeled native guards')
    return {
        'four_field_config_valid': validity['is_valid'],
        'positive_delivery_result': derived['positive_pop_result'],
        'fallback_sentinel_gate': derived['fallback_sentinel_gate'],
        'eligibility_gate': derived['eligibility_gate'],
        'selected_gacha_config_index': derived['selected_gacha_config_index'],
        'predicted_native_gate': derived['normal_path_outcome'],
        'can_reach_call_under_observed_guards': derived['can_reach_gacha_call_under_inputs'],
        'reported_call_observed': called,
        'gate_call_consistent': (not called or derived['can_reach_gacha_call_under_inputs']),
        'method_is_mutating_and_must_not_be_reinvoked': 'PlayerProfile.PopCarIfInDeliveryWaitingList',
    }


def validate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Pure validation; never execute game APIs or promote a self-reported capture."""
    snapshot = _object(snapshot, 'snapshot', required={'schema', 'capture'},
                       optional={'gacha', 'paint'})
    if snapshot['schema'] != _SCHEMA:
        raise ValueError('snapshot: unsupported schema')
    capture = _object(snapshot['capture'], 'capture', required={
        'client', 'vehicle_key', 'source_id', 'kind', 'non_mutating'})
    if capture['client'] != 'CSR2 6.8.0' or capture['vehicle_key'] != _CAR or type(capture['source_id']) is not int or capture['source_id'] != 1:
        raise ValueError('capture: expected CSR2 6.8.0 Tutorial Ford_Mustang302_1970')
    if capture['kind'] not in ('synthetic', 'passive_runtime'):
        raise ValueError('capture.kind: expected synthetic or passive_runtime')
    _boolean(capture['non_mutating'], 'capture.non_mutating')
    if capture['kind'] == 'passive_runtime' and not capture['non_mutating']:
        raise ValueError('capture: passive runtime evidence must be non-mutating')
    gacha = _gacha(snapshot['gacha']) if 'gacha' in snapshot else None
    paint = snapshot.get('paint')
    if paint is not None:
        paint = _object(paint, 'paint', required=set(), optional={'lookup', 'post_refresh'})
        if not paint:
            raise ValueError('paint: empty paint object')
    at_lookup = _paint_stage(paint['lookup'], 'paint.lookup') if paint and 'lookup' in paint else None
    post = _paint_stage(paint['post_refresh'], 'paint.post_refresh') if paint and 'post_refresh' in paint else None
    if post is not None and at_lookup is None:
        raise ValueError('paint: post_refresh requires lookup for ordered comparison')
    same_list = (at_lookup['ordered_list_sha256'] == post['ordered_list_sha256']) if post and at_lookup else None
    same_index = (at_lookup['selected_index'] == post['selected_index']) if post and at_lookup else None
    same_id = (at_lookup['resolved_paint_id'] == post['resolved_paint_id']) if post and at_lookup else None
    # This is a self-reported snapshot. Its internal consistency may be tested,
    # but its actual origin, instrumentation, or target car cannot be established.
    fully_populated = bool(gacha and at_lookup and post and
        at_lookup['index_in_bounds'] and post['index_in_bounds'] and
        at_lookup['observed_id_supplied'] and post['observed_id_supplied'])
    if capture['kind'] == 'synthetic':
        status = 'synthetic_not_runtime_evidence'
    elif fully_populated:
        status = 'self_reported_runtime_snapshot_consistent_not_authenticated'
    else:
        status = 'partial_self_reported_runtime_snapshot'
    compact = json.dumps(snapshot, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return {
        'snapshot_schema': _SCHEMA,
        'snapshot_sha256': hashlib.sha256(compact.encode('ascii')).hexdigest(),
        'capture_claimed_kind': capture['kind'],
        'capture_claims_non_mutating': capture['non_mutating'],
        'external_capture_origin_independently_authenticated': False,
        'status': status,
        'gacha_assessment': gacha,
        'paint_lookup_assessment': at_lookup,
        'paint_post_refresh_assessment': post,
        'ordered_list_unchanged_after_refresh': same_list,
        'selected_index_unchanged_after_refresh': same_index,
        'resolved_id_unchanged_after_refresh': same_id,
        'paint_index_15_equals_conditional_1323_at_lookup': (
            at_lookup['candidate_15_from_list'] == 1323 if at_lookup and
            at_lookup['candidate_15_from_list'] is not None else None),
        'observed_selected_paint_id_at_lookup': at_lookup['resolved_paint_id'] if at_lookup else None,
        'production_paint_mapping_verified': False,
        'production_mappings_changed': False,
        'proof_limitation': 'Input JSON is self-reported; independent provenance and live execution are not verified.',
    }


def assess(apk: Path, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    static = inspect_dev77(apk)
    if static['production_mappings_changed'] or static['runtime_ordered_paint_list_captured']:
        raise ValueError('Dev77 static-only guard changed')
    assessment = validate_snapshot(snapshot) if snapshot is not None else None
    return {
        'status': 'dev78_offline_runtime_snapshot_validator',
        'client': 'CSR2 6.8.0',
        'previous_dev72_77_pinned_native_chain_passed': True,
        'dev77_config_validity_native_sha256': static['native_method']['sha256'],
        'snapshot_supplied': assessment is not None,
        'snapshot_assessment': assessment,
        'missing_runtime_evidence': (['non_mutating_gacha_guard_capture', 'paint_list_at_selected_lookup',
                                      'post_refresh_paint_state'] if assessment is None else []),
        'conditional_index_15_paint_candidate': 1323,
        'paint_index_0_runtime_mapping_verified': False,
        'production_paint_mapping_verified': False,
        'production_mappings_changed': False,
        'network_requests': 0, 'authenticated_gameplay_requests': 0,
        'gameplay_state_writes': 0, 'private_capture_echoed_to_report': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', required=True, type=Path,
                        help='Local CSR2 6.8.0 APK for the pinned native evidence chain')
    parser.add_argument('--snapshot', type=Path,
                        help='Optional externally captured JSON; see docs/DEV78_RUNTIME_SNAPSHOT_VALIDATOR.md')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        parser.error('refusing to overwrite existing evidence output')
    try:
        snapshot = load_snapshot(args.snapshot) if args.snapshot else None
        result = assess(args.apk, snapshot)
        body = json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True) + '\n'
        if len(body.encode('utf-8')) > 150_000:
            raise ValueError('oversized evidence report')
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(body)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print('Dev78: pinned native audit passed; no production paint mapping promoted.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
