"""Offline Dev37 user-readable source ID lookups: no CDNs, no roster."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from csr2cdn._research.dev37_source_id_lookup import (
    SLOT_BY_LIBRARY, SourceCatalogueError, load_catalog, index_and_gaps,
    look_up_id, analyze, _private_csv_safe, main,
)


def fixture():
    rows=[]
    for i, (library, slot) in enumerate(SLOT_BY_LIBRARY.items()):
        # The same code in different attributes is not an ID collision.
        ids = (0, 2) if 'Tuner' not in library else (1000001, 1000003)
        for num in ids:
            rows.append({'slot': slot,'numeric_id':num,'source_library':library,
                         'source_label':f'Label {i}','additional_source_labels':[],
                         'source_category':'All','vehicle_eligibility_verified':False,
                         'unresolved_roster_id':'unknown_without_saved_roster'})
    digests={k:('a'*64) for k in SLOT_BY_LIBRARY}
    counts={k:2 for k in SLOT_BY_LIBRARY}
    c={'status':'public_source_id_catalog_not_unresolved_roster_ids',
       'branch':'6_8_0_Release','database_version':'34011',
       'source_sha256':dict(digests),'individual_source_ids':rows,
       'contains_player_or_roster_data':False,'mapping_promoted':False}
    s={'status':'current_release_public_cosmetic_sources_validated',
       'branch':'6_8_0_Release','database_version':'34011',
       'source_sha256':dict(digests),'source_record_counts':counts,
       'source_total_records':len(rows),'gameplay_read_count':0,'authentication_used':False}
    return c,s


def source_files(tmp_path):
    c,s=fixture()
    p=tmp_path/'catalog.json'; q=tmp_path/'summary.json'
    p.write_text(json.dumps(c)); q.write_text(json.dumps(s))
    return p,q


def test_load_analyze_and_cross_attribute_overlap(tmp_path):
    p,q=source_files(tmp_path)
    meta, rows = load_catalog(p,q)
    result=analyze(meta,rows,[0,1,1000001,3333])
    assert result['source_record_count']==12
    assert result['internal_source_numbering_gaps_total']==6
    assert result['same_attribute_multi_source_ID_collisions']==0
    assert result['network_requests']==0 and not result['gaps_are_unresolved_roster_ids']
    statuses={r['numeric_id']:r['status'] for r in result['individual_queries']}
    assert statuses[0]=='present_in_multiple_attributes_not_a_collision'
    assert statuses[1]=='not_present_in_selected_source_libraries'
    assert statuses[1000001]=='present_in_multiple_attributes_not_a_collision'
    assert statuses[3333]=='not_present_in_selected_source_libraries'
    assert result['source_fingerprint_metadata_consistent'] is True
    assert result['original_source_bundle_bytes_reverified'] is False
    assert all(r['historical_roster_membership']=='unknown_without_saved_roster' for r in result['individual_queries'])


def test_slot_specific_and_source_ambiguity():
    c,s=fixture()
    rows=c['individual_source_ids']
    idx,_,gaps=index_and_gaps(rows)
    assert len(gaps)==6 and all(row['classification']=='unoccupied_inside_library_range' for row in gaps)
    assert look_up_id(idx,0,'paint')['status']=='present_in_source_library'
    assert look_up_id(idx,0,'interior')['status']=='present_in_source_library'
    assert look_up_id(idx,0,'calliper')['status']=='present_in_source_library'
    assert look_up_id(idx,1,'paint')['status']=='not_present_in_selected_source_libraries'
    assert look_up_id(idx,1000001,'paint')['status']=='present_in_source_library'
    rows.append({'slot':'paint','numeric_id':0,'source_library':'CarTunerStarsPaintLibrary',
                 'source_label':'Overlap','additional_source_labels':[],'source_category':'All',
                 'vehicle_eligibility_verified':False,'unresolved_roster_id':'unknown_without_saved_roster'})
    idx[('paint', 0)].append(rows[-1])
    assert look_up_id(idx,0,'paint')['status']=='multiple_records_within_same_attribute_no_trusted_selection'


@pytest.mark.parametrize('change',[
    lambda c,s: c.update(database_version='1234'),
    lambda c,s: s['source_sha256'].update(CarPaintLibrary='0'*64),
    lambda c,s: c['individual_source_ids'].append(copy.deepcopy(c['individual_source_ids'][0])),
    lambda c,s: c['individual_source_ids'][0].update(slot='interior'),
    lambda c,s: c['individual_source_ids'][0].update(vehicle_eligibility_verified=True),
    lambda c,s: c['individual_source_ids'][0].update(numeric_id=True),
    lambda c,s: c['individual_source_ids'][0].update(source_label=''),
    lambda c,s: s.update(source_total_records=1),
    lambda c,s: c.update(contains_player_or_roster_data=True),
])
def test_inconsistent_catalogue_fails_closed(tmp_path, change):
    c,s=fixture(); change(c,s)
    p=tmp_path/'a.json';q=tmp_path/'b.json'
    p.write_text(json.dumps(c)); q.write_text(json.dumps(s))
    with pytest.raises(SourceCatalogueError):
        load_catalog(p,q)


def test_cli_outputs_are_new_and_offline(tmp_path,monkeypatch,capsys):
    p,q=source_files(tmp_path)
    out=tmp_path/'results.json'; gap=tmp_path/'gaps.csv'; cat=tmp_path/'catalogue.csv'
    monkeypatch.setattr('socket.socket.connect', lambda *a,**kw: pytest.fail('unexpected network'))
    assert main(['--catalog',str(p),'--summary',str(q),'--slot','paint',
                 '--id','0','--id','1','--id','0','--output',str(out),
                 '--gaps-csv',str(gap),'--catalog-csv',str(cat)])==0
    doc=json.loads(out.read_text())
    assert len(doc['individual_queries'])==2
    assert doc['individual_queries'][0]['source_matches'][0]['source_label']=='Label 0'
    assert len(gap.read_text(encoding='utf-8-sig').splitlines())==7
    assert len(cat.read_text(encoding='utf-8-sig').splitlines())==13
    assert json.loads(capsys.readouterr().out)['network_requests']==0
    with pytest.raises(SystemExit):
        main(['--catalog',str(p),'--summary',str(q),'--output',str(out)])
    assert json.loads(out.read_text())==doc


def test_list_file_and_no_partial_result_on_bad_input(tmp_path,capsys):
    p,q=source_files(tmp_path)
    listfile=tmp_path/'list.txt';listfile.write_text('# suspects\n0\n1000001\n')
    assert main(['--catalog',str(p),'--summary',str(q),'--ids-file',str(listfile)])==0
    assert len(json.loads(capsys.readouterr().out)['individual_queries'])==2
    listfile.write_text('0\nnot-a-number\n')
    assert main(['--catalog',str(p),'--summary',str(q),'--ids-file',str(listfile)])==3
    assert json.loads(capsys.readouterr().out)['status']=='local_catalogue_analysis_unavailable'


def test_csv_injection_guard():
    for expr in ('=cmd','-HYPERLINK()', '+formula', '@x', '\t=cmd'):
        assert _private_csv_safe(expr).startswith("'")
    assert _private_csv_safe('Ferrari Rosso')=='Ferrari Rosso'


def test_privacy_and_symlink_input_guard(tmp_path):
    p,q=source_files(tmp_path)
    link=tmp_path/'link.json'
    try:
        link.symlink_to(p)
    except (OSError,NotImplementedError):
        pytest.skip('symlinks unsupported')
    with pytest.raises(SourceCatalogueError):
        load_catalog(link,q)
