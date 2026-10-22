"""Dev38: per-received-ID source-membership diagnosis, all network simulated."""
import json
from types import SimpleNamespace

import pytest

from csr2cdn._research.dev38_received_unmatched_ids import (
    compare_received_to_library_ids, compare_from_responses, main)
from csr2cdn._research.dev36_latest_visual_ids import CurrentSourceEvidence
from csr2cdn.game_labels import GameVisualLibrary, VisualCodeName
from test_dev071_dev25_offline_visual_forensics import inputs, CREW_SECRET

LIBRARIES = {
    'paint': ('CarPaintLibrary', 'CarTunerStarsPaintLibrary'),
    'interior': ('CarInteriorLibrary', 'CarTunerStarsInteriorLibrary'),
    'calliper': ('CarCalliperLibrary', 'CarTunerStarsCalliperLibrary'),
}
META = {'branch':'6_8_0_Release', 'database_version':'34011',
        'source_sha256': {x:'a'*64 for v in LIBRARIES.values() for x in v}}


def rows():
    return [{'slot': slot, 'numeric_id': n, 'source_library': lib,
             'source_label':'SENSITIVE_SOURCE_LABEL', 'source_category':'All'}
            for slot, pair in LIBRARIES.items()
            for lib,n in zip(pair, {'paint':(42,1000001),
                                    'interior':(7,1000001),
                                    'calliper':(8,1000001)}[slot])]


def test_exact_roster_id_by_slot_not_heuristic_and_no_member_identity():
    snap, *_ = inputs()
    result = compare_received_to_library_ids(snap, rows(), branch=META['branch'],database_version=META['database_version'],source_hashes=META['source_sha256'])
    assert [(r['attribute'],r['received_numeric_id'],r['occurrences'])
            for r in result['individual_absent_received_ids']] == [
            ('paint',88,1), ('paint',777,1), ('interior',3001111,1), ('interior',3002222,1)]
    assert result['unique_attribute_id_pairs_absent'] == 4
    assert result['total_absent_received_occurrences'] == 4
    assert result['coverage_by_attribute']['paint']['present_in_sources']==1
    assert result['coverage_by_attribute']['calliper']['absent_from_sources']==0
    assert result['historical_dev24_roster_reproduced'] is False
    text=json.dumps(result)
    for token in (CREW_SECRET, 'PRIVATE_', 'SECRET_', 'Mazda_', 'Honda_', 'Normal_Car'):
        assert token not in text


def test_cross_attribute_same_number_does_not_resolve_miss():
    snap, *_ = inputs()
    candidate = rows()
    candidate.append({'slot':'calliper','numeric_id':777})
    result=compare_received_to_library_ids(snap,candidate,branch=META['branch'],database_version=META['database_version'],source_hashes=META['source_sha256'])
    assert any(r['attribute']=='paint' and r['received_numeric_id']==777
               for r in result['individual_absent_received_ids'])


def test_distinct_rows_merge_occurrences_and_zero_is_valid():
    snap, _, _, _, _ = inputs()
    from dataclasses import replace
    members=list(snap.members)
    a=replace(members[0].vehicle.appearance, paint_id=0)
    b=replace(members[1].vehicle.appearance, paint_id=0)
    members[0]=replace(members[0],vehicle=replace(members[0].vehicle, appearance=a))
    members[1]=replace(members[1],vehicle=replace(members[1].vehicle, appearance=b))
    snap=replace(snap,members=tuple(members))
    result=compare_received_to_library_ids(snap, rows(), branch=META['branch'],database_version=META['database_version'],source_hashes=META['source_sha256'])
    found=next(r for r in result['individual_absent_received_ids'] if r['attribute']=='paint' and r['received_numeric_id']==0)
    assert found['occurrences']==2
    assert found['tnr_model_syntax_occurrences']==1
    assert found['other_or_unknown_model_occurrences']==1


def test_invalid_roster_and_catalog_fail_closed():
    snap, *_ = inputs()
    with pytest.raises(ValueError):
        compare_received_to_library_ids(replace_members(snap, ()),rows(),branch=META['branch'],database_version=META['database_version'],source_hashes=META['source_sha256'])
    with pytest.raises(ValueError):
        compare_received_to_library_ids(snap, [{'slot':'paint','numeric_id':True}],branch=META['branch'],database_version=META['database_version'],source_hashes=META['source_sha256'])


def replace_members(snap, members):
    from dataclasses import replace
    return replace(snap, members=tuple(members))


class FakeService:
    calls=[]
    def __init__(self, player_id, *, allow_network=False):
        assert player_id == 'PRIVATE_PLAYER_ID'
        assert allow_network is True
        self.calls=[]
        FakeService.calls.append(self.calls)
        self.own=inputs()[3]
        self.members=inputs()[4]
    def __enter__(self): return self
    def __exit__(self,*exc): pass
    def prepare_my_crew(self): return 'my_crew'
    def prepare_crew_members(self,crew_uid):
        assert crew_uid == CREW_SECRET
        return 'crew_members'
    def _read(self,contract):
        self.calls.append(contract)
        if len(self.calls)>2: raise AssertionError('more than two operations')
        return self.own if contract=='my_crew' else self.members


def fake_fetch(branch, *, session):
    assert branch=='6_8_0_Release'
    records=tuple(VisualCodeName('*',r['slot'],r['numeric_id'],'TEST_LABEL',r['source_library']) for r in rows())
    return CurrentSourceEvidence({'branch':branch,'database_version':'34011',
                'source_sha256':META['source_sha256'],
                'source_record_counts':{name:1 for name in META['source_sha256']},
                'network_requests':8}, GameVisualLibrary(records))


def test_work_live_simulated_exact_two_reads_only(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('CSR2_PLAYER_ID', 'PRIVATE_PLAYER_ID')
    result_file=tmp_path/'ids.json'
    rc=main(['--refresh-public','--execute','--output',str(result_file)],
            services_factory=FakeService,source_fetch=fake_fetch)
    assert rc==0
    assert FakeService.calls[-1]==['my_crew','crew_members']
    result=json.loads(result_file.read_text())
    assert result['game_service_read_operations']==2
    assert result['public_cdn_get_count']==8
    assert result['unique_attribute_id_pairs_absent']==4
    printed=capsys.readouterr().out
    assert 'received_numeric_id' in printed
    assert '3001111' in printed and '3002222' in printed
    for private in ('PRIVATE_PLAYER_ID',CREW_SECRET,'PRIVATE_', 'TEST_LABEL'):
        assert private not in printed and private not in result_file.read_text()


def test_live_not_possible_without_own_secret_and_no_requests(monkeypatch, tmp_path,capsys):
    monkeypatch.delenv('CSR2_PLAYER_ID', raising=False)
    monkeypatch.setattr('sys.stdin', SimpleNamespace(isatty=lambda:False))
    def should_not_fetch(*args, **kwargs):
        raise AssertionError('should not reach HTTP')
    rc=main(['--refresh-public','--execute','--output',str(tmp_path/'ids.json')],
            services_factory=FakeService,source_fetch=should_not_fetch)
    assert rc==3
    assert not (tmp_path/'ids.json').exists()
    assert json.loads(capsys.readouterr().out)['status']=='dev38_diagnostic_unavailable'


def test_dry_run_does_not_access_network(monkeypatch, tmp_path,capsys):
    monkeypatch.delenv('CSR2_PLAYER_ID', raising=False)
    assert main(['--refresh-public','--output',str(tmp_path/'ids.json')])==0
    output=json.loads(capsys.readouterr().out)
    assert output['status']=='dry_run_zero_requests'
    assert not (tmp_path/'ids.json').exists()


def test_existing_output_rejected_before_live_actions(monkeypatch,tmp_path):
    import sys
    outfile=tmp_path/'ids.json'
    outfile.write_text('never overwrite')
    with pytest.raises(SystemExit):
        main(['--refresh-public','--execute','--output',str(outfile)],
             services_factory=FakeService, source_fetch=fake_fetch)
    assert outfile.read_text()=='never overwrite'


def test_from_response_parses_typed_roster_and_no_raw_keys():
    *_,own,members=inputs()
    out=compare_from_responses(own,members,rows(),META,capture_mode='saved_roster_offline_replay')
    assert out['total_absent_received_occurrences']==4
    assert out['crew_member_rows']==3
    assert 'player_uid' not in json.dumps(out)
