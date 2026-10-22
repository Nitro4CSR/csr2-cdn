"""Dev41 provenance labels are evidence categories, not accepted game mappings."""
import copy
import json
import pytest

from csr2cdn._research.dev41_field_source_provenance import field_schema_inventory, make_audit, main
from csr2cdn.visual_asset_plan import VisualAssetCandidate


H = lambda n: chr(97+n)*64


def source():
    names = ('CarPaintLibrary','CarInteriorLibrary','CarCalliperLibrary',
             'CarTunerStarsPaintLibrary','CarTunerStarsInteriorLibrary',
             'CarTunerStarsCalliperLibrary')
    return dict(status='current_release_public_cosmetic_sources_validated',
                branch='6_8_0_Release', database_version='34011',
                source_sha256={n:H(i) for i,n in enumerate(names)},
                source_record_counts={n: 10+i for i,n in enumerate(names)})


def roster(src):
    return dict(status='received_roster_numeric_ids_absent_from_source_libraries',
                source_branch=src['branch'], source_database_version=src['database_version'],
                source_sha256=src['source_sha256'],
                coverage_by_attribute={
                    'paint': dict(received_numeric_occurrences=29, present_in_sources=20,
                                  absent_from_sources=9, field_missing_or_unparsed=0),
                    'interior': dict(received_numeric_occurrences=29,present_in_sources=29,
                                     absent_from_sources=0,field_missing_or_unparsed=0),
                    'calliper':dict(received_numeric_occurrences=29,present_in_sources=29,
                                    absent_from_sources=0,field_missing_or_unparsed=0),
                },
                individual_absent_received_ids=[
                    dict(attribute='paint',received_numeric_id=0,occurrences=8),
                    dict(attribute='paint',received_numeric_id=15,occurrences=1)])


def palette():
    return dict(status='received_paint_id_vs_separate_color_palette_checked',
                roster_source_branch='6_8_0_Release',palette_branch='6_8_0_Release',
                roster_source_database_version='34011', palette_database_version='34011',
                source_paint_library_absence_unchanged=True, numeric_palette_overlap_is_not_paint_name_mapping=True,
                same_database_version_as_roster_sources=True,
                individual_unmatched_received_paint_ids=[
                  dict(received_paint_id=0,occurrences=8,palette_name='Transparent',present_in_color_palette=True,
                       paint_to_color_namespace_join_verified=False),
                  dict(received_paint_id=15,occurrences=1,palette_name=None,present_in_color_palette=False,
                       paint_to_color_namespace_join_verified=False)])


def test_inventory_flags_do_not_infer_any_namespace_or_wheel_join():
    inv = field_schema_inventory()
    assert len(inv) == 14
    assert len(set(x['wire_field'] for x in inv)) == len(inv)
    assert all(not x['same_namespace_demonstrated'] and
               not x['vehicle_eligibility_verified'] for x in inv)
    paint = next(x for x in inv if x['wire_field']=='car_paint_id')
    assert [x['native_primary_array'] for x in paint['source_candidates']] == ['CarPaints','CarTNRPaints']
    wheel = next(x for x in inv if x['wire_field']=='car_wheel_name')
    assert wheel['wire_type']=='string'
    assert wheel['relationship']=='unverified_possible_source'
    assert wheel['source_candidates'][0]['native_primary_array']=='CarRims'
    assert not any('CarColorLibrary'==s['source_asset'] for s in paint['source_candidates'])
    tnr_liv = next(x for x in inv if x['wire_field']=='car_livery_id')
    assert tnr_liv['source_candidates'][0]['native_decoder_supported']
    assert not tnr_liv['source_candidates'][1]['native_decoder_supported']


def test_decode_is_not_name_mapping_verification():
    candidate = lambda join: VisualAssetCandidate('paint','CarPaintLibrary','1','ANDROID','ASTC',100,'https://test.invalid', 'decode_supported', join)
    assert candidate('observed_numeric_id').native_schema_decoded
    assert candidate('observed_numeric_id').roster_id_match_candidate
    assert not candidate('observed_numeric_id').name_mapping_verified
    assert not candidate('unverified_roster_join').roster_id_match_candidate
    assert not candidate('unverified_roster_join').name_mapping_verified
    assert candidate('verified_roster_join').name_mapping_verified


def test_actual_roster_like_counts_with_explicit_approved_alias():
    src=source()
    report=make_audit(source_summary=src,roster_report=roster(src),
                      palette_report=palette(),approve_transparent_zero=True)
    assert report['source_database_version']=='34011'
    assert report['network_requests']==0 and report['gameplay_read_count']==0
    assert report['reported_roster_exact_id_coverage']['paint']['id_present_in_candidate_source']==20
    assert [(x['received_numeric_id'],x['occurrences']) for x in report['unmatched_received_ids']] == [(0,8),(15,1)]
    assert not report['reported_roster_exact_id_coverage']['paint']['same_namespace_demonstrated']
    paint=next(x for x in report['wire_fields'] if x['wire_field']=='car_paint_id')
    assert paint['operator_display_alias']['label']=='Transparent'
    assert not paint['same_namespace_demonstrated']
    assert report['palette_comparison']['id_fifteen_present_in_palette'] is False
    assert not report['metadata_field_schema_decoded']


def test_zero_alias_requires_explicit_approval_and_real_palette_evidence():
    src=source()
    plain=make_audit(source_summary=src,roster_report=roster(src),palette_report=palette())
    assert next(x for x in plain['wire_fields'] if x['wire_field']=='car_paint_id')['operator_display_alias'] is None
    with pytest.raises(ValueError):
        make_audit(approve_transparent_zero=True)
    wrong=palette()
    wrong['individual_unmatched_received_paint_ids'][0]['palette_name']='Other'
    with pytest.raises(ValueError):
        make_audit(source_summary=src,roster_report=roster(src),palette_report=wrong,approve_transparent_zero=True)


@pytest.mark.parametrize('alter',[
    lambda src,r: r.update(source_database_version='99999'),
    lambda src,r: r['source_sha256'].update(CarPaintLibrary=H(12)),
    lambda src,r: r['coverage_by_attribute']['paint'].update(absent_from_sources=10),
    lambda src,r: r['individual_absent_received_ids'][1].update(received_numeric_id=0),
    lambda src,r: r['individual_absent_received_ids'][0].update(occurrences=7),
])
def test_reject_changed_or_contradictory_reports(alter):
    src=source(); r=roster(src); alter(src,r)
    with pytest.raises(ValueError):
        make_audit(source_summary=src,roster_report=r)


def test_cli_bounded_private_new_output(tmp_path, capsys):
    src=source(); r=roster(src)
    for name,content in [('src.json',src),('roster.json',r),('palette.json',palette())]:
        (tmp_path/name).write_text(json.dumps(content))
    output=tmp_path/'audit.json'
    args=['--source-summary',str(tmp_path/'src.json'),'--received-report',str(tmp_path/'roster.json'),
          '--palette-report',str(tmp_path/'palette.json'),'--approve-transparent-zero','--output',str(output)]
    assert main(args)==0
    report=json.loads(output.read_text())
    assert report['source_branch']=='6_8_0_Release'
    assert 'Transparent' not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(args)  # no overwrite
    assert report['network_requests']==0
