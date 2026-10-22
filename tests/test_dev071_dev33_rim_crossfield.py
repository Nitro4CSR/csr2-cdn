"""Dev33 cross-field and baseline honesty regressions, synthetic sources only."""
from __future__ import annotations

import json

import pytest

from csr2cdn._research.dev33_rim_crossfield import audit_rim_crossfield_structure
from csr2cdn._research.dev27_native_wheel_forensics import audit_tuner_rim_source
from csr2cdn._research.dev30_public_source_replay import capture_public_sources, replay_public_cache
from csr2cdn.visual_library_bundle import VisualLibrarySourceError
from test_dev16_native_visual_extensions import _synthetic
from test_dev071_dev29_public_cdn_forensics import BRANCH, session_for


def test_shared_reference_across_native_brand_category_groups_is_not_eligibility():
    r = audit_rim_crossfield_structure(
        [('Ref_A', 'Ref_B'), ('Ref_A',), ('Ref_C',), (), ('Ref_A', 'Ref_B')],
        ['Brand_A', 'Brand_A', 'Brand_A', 'Brand_B', 'Brand_C'],
        ['Sport', 'Sport', 'Luxury', 'Sport', 'Sport'])
    assert r['rim_records'] == 5
    assert r['distinct_brand_category_pairs'] == 4
    assert r['brand_category_pairs_with_nonempty_compatibility'] == 3
    assert r['brand_category_pairs_without_nonempty_compatibility'] == 1
    assert r['distinct_nonempty_compatible_references'] == 3
    assert r['compatible_references_in_one_brand_category_pair'] == 1
    assert r['compatible_references_in_multiple_brand_category_pairs'] == 2
    assert r['max_brand_category_pairs_per_reference'] == 2
    assert r['reference_sets_shared_across_brand_category_pairs'] == 1
    assert r['brand_category_pairs_per_reference_bucket_counts'] == {'1': 1, '2-4': 2}
    assert not r['field_relationships_are_eligibility']
    assert r['network_requests'] == 0
    dump = json.dumps(r)
    assert all(private not in dump for private in (
        'Ref_A', 'Ref_B', 'Ref_C', 'Brand_A', 'Brand_B', 'Sport', 'Luxury'))


def test_blank_and_duplicate_references_do_not_create_fictitious_links():
    r = audit_rim_crossfield_structure(
        [('A', 'A', ''), ('',), ()], ['', 'Brand', 'Brand'], ['', '', ''])
    assert r['rims_with_blank_brand_or_category'] == 3
    assert r['distinct_nonempty_compatible_references'] == 1
    assert r['compatible_references_in_multiple_brand_category_pairs'] == 0
    assert r['brand_category_pairs_without_nonempty_compatibility'] == 1


@pytest.mark.parametrize('rows,brands,categories', [
    ([('A',)], ['Brand'], []),
    ([('A',)], [], ['Cat']),
    (['invalid'], ['Brand'], ['Cat']),
    ([('A',)], [None], ['Cat']),
    ([('A',) * 1001], ['Brand'], ['Cat']),
    ([('A' * 4097,)], ['Brand'], ['Cat']),
])
def test_crossfield_rejects_bad_or_oversized_source_inputs(rows, brands, categories):
    with pytest.raises(VisualLibrarySourceError):
        audit_rim_crossfield_structure(rows, brands, categories)


def test_crossfield_is_in_original_native_rim_audit():
    r = audit_tuner_rim_source(_synthetic('CarTunerStarsRimLibrary',
                                         rim_compatible=('Private_Ref',)))
    fields = r['source_crossfield_relationships']
    assert fields['rim_records'] == 100
    assert fields['brand_category_pairs_with_nonempty_compatibility'] == 1
    assert fields['compatible_references_in_one_brand_category_pair'] == 1
    assert not fields['references_are_roster_wheel_names']
    assert 'Private_Ref' not in json.dumps(fields)


def test_baseline_comparison_truth_gated_by_all_hashes_and_index(tmp_path):
    cache = tmp_path / 'sources'
    result = capture_public_sources(BRANCH, ('rim',), cache, session=session_for())
    audit = result['validation']
    replay = replay_public_cache(cache, baseline_audit=audit)
    same = replay['dev29_baseline_comparison']
    assert same['all_reported_source_bytes_and_index_match_baseline'] is True
    assert same['matching_source_hashes_confirm_same_bytes_not_eligibility'] is True
    assert same['baseline_is_validated_public_audit'] is True
    assert same['same_source_slot_coverage'] is True

    changed_index = {**audit, 'public_index_sha256': '0'*64}
    result = replay_public_cache(cache, baseline_audit=changed_index)['dev29_baseline_comparison']
    assert result['same_source_sha256_by_slot']['rim'] is True
    assert result['same_public_index_sha256'] is False
    assert result['matching_source_hashes_confirm_same_bytes_not_eligibility'] is False

    bad_hash = {**audit, 'validated_source_sha256': {'rim': '0'*64}}
    result = replay_public_cache(cache, baseline_audit=bad_hash)['dev29_baseline_comparison']
    assert not result['all_reported_source_bytes_and_index_match_baseline']

    missing_slot = {**audit, 'validated_source_sha256': {}}
    result = replay_public_cache(cache, baseline_audit=missing_slot)['dev29_baseline_comparison']
    assert not result['same_source_slot_coverage']
    assert not result['matching_source_hashes_confirm_same_bytes_not_eligibility']

    invented_status = {**audit, 'status': 'not_validated'}
    result = replay_public_cache(cache, baseline_audit=invented_status)['dev29_baseline_comparison']
    assert not result['baseline_is_validated_public_audit']
    assert not result['all_reported_source_bytes_and_index_match_baseline']
