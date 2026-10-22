"""Dev39 palette overlap hypotheses: synthetic ASTC bytes and HTTP fixtures only."""
import json
import hashlib
from pathlib import Path

import pytest

from csr2cdn._research.dev39_color_palette_overlap import (
    parse_received_report, parse_palette, compare_paint_to_palette,
    fetch_current_palette, main,
)
from csr2cdn._research.dev29_public_cdn_forensics import PublicCDNProbeError
from test_dev071_dev14_native_calliper_color import _bundle
from test_dev071_dev29_public_cdn_forensics import ORIGIN, Session, Response, BRANCH


def report():
    return {'status':'received_roster_numeric_ids_absent_from_source_libraries',
            'source_branch':BRANCH,'source_database_version':'34011',
            'individual_absent_received_ids':[
                {'attribute':'paint','received_numeric_id':0,'occurrences':8,
                 'tnr_model_syntax_occurrences':1,'other_or_unknown_model_occurrences':7},
                {'attribute':'paint','received_numeric_id':15,'occurrences':1,
                 'tnr_model_syntax_occurrences':0,'other_or_unknown_model_occurrences':1}],
            'coverage_by_attribute':{'paint':{'absent_from_sources':9}},
            'total_absent_received_occurrences':9,
            'unique_attribute_id_pairs_absent':2,
            'secret':'PRIVATE_PLAYER_ID_DONT_EXPORT'}


def received(tmp_path):
    p=tmp_path/'received.json'
    p.write_text(json.dumps(report()))
    return p


def fake_session(raw=None):
    raw=raw or _bundle('CarColorLibrary',count=16)
    doc=[{'version':'34012'},[{'code':'CarColorLibrary','version':'777',
              'type':'31','sizes':{'ASTC':len(raw)}}]]
    return Session({f'{ORIGIN}/asset_database_{BRANCH}.version': Response(b'{"version":"34012"}'),
                    f'{ORIGIN}/asset_database.34012.json': Response(json.dumps(doc).encode()),
                    f'{ORIGIN}/ANDROID/ASTC/CarColorLibrary.ASTC.777': Response(raw)})


def test_one_paint_id_zero_and_fifteen_raw_color_overlap_does_not_become_paint_mapping(tmp_path):
    info=parse_received_report(received(tmp_path))
    raw=_bundle('CarColorLibrary',count=16)
    palette, sha=parse_palette(raw)
    assert len(palette)==16
    assert palette[0]=='Color 0'
    assert palette[15]==''
    result=compare_paint_to_palette(info, raw,
        evidence={'branch':BRANCH,'database_version':'34012','palette_asset_version':'777','network_requests':3})
    rows=result['individual_unmatched_received_paint_ids']
    assert [(r['received_paint_id'],r['present_in_color_palette']) for r in rows]==[(0,True),(15,True)]
    assert rows[1]['palette_name'] is None
    assert rows[1]['palette_record_is_unnamed'] is True
    assert rows[0]['palette_name']=='Color 0'
    assert result['same_database_version_as_roster_sources'] is False
    assert result['source_paint_library_absence_unchanged'] is True
    assert result['numeric_palette_overlap_is_not_paint_name_mapping'] is True
    assert result['id_zero_is_not_assumed_default'] is True
    assert result['mapping_promoted'] is False
    assert result['palette_sha256']==sha
    assert 'PRIVATE_PLAYER_ID' not in json.dumps(result)


def test_palette_id15_absent_in_shorter_library(tmp_path):
    raw=_bundle('CarColorLibrary',count=11)
    result=compare_paint_to_palette(parse_received_report(received(tmp_path)),raw,
                                     evidence={'branch':BRANCH, 'network_requests':0})
    a,b=result['individual_unmatched_received_paint_ids']
    assert a['present_in_color_palette'] is True
    assert b['present_in_color_palette'] is False
    assert b['palette_name'] is None
    assert result['same_database_version_as_roster_sources'] is None


def test_online_three_only_gets_and_validated_versions():
    s=fake_session()
    raw, metadata=fetch_current_palette(BRANCH,session=s)
    assert len(s.calls)==3
    assert metadata['database_version']=='34012'
    assert metadata['network_requests']==3
    assert len(raw)>100
    for url, kw in s.calls:
        assert url.startswith(ORIGIN+'/')
        assert kw['stream'] is True and kw['allow_redirects'] is False


def test_unexpected_source_fails_closed_after_two_reads():
    s=fake_session()
    p=f'{ORIGIN}/asset_database.34012.json'
    d=json.loads(s.mapping[p].payload)
    d[1]=[]
    s.mapping[p]=Response(json.dumps(d).encode())
    with pytest.raises(PublicCDNProbeError):
        fetch_current_palette(BRANCH,session=s)
    assert len(s.calls)==2


def test_wrong_size_fails_closed_at_third_read():
    s=fake_session()
    p=f'{ORIGIN}/ANDROID/ASTC/CarColorLibrary.ASTC.777'
    s.mapping[p]=Response(b'0'*100)
    with pytest.raises(PublicCDNProbeError):
        fetch_current_palette(BRANCH,session=s)
    assert len(s.calls)==3


@pytest.mark.parametrize('bad',['../not', '6_8_0_Release/abc','', 'http://example.com'])
def test_bad_branch_rejected_before_any_network(bad):
    s=fake_session()
    with pytest.raises(ValueError):
        fetch_current_palette(bad,session=s)
    assert s.calls == []


def test_report_malformed_zero_duplicate_broken_counts(tmp_path):
    doc=report()
    doc['individual_absent_received_ids'].append(dict(doc['individual_absent_received_ids'][0]))
    p=tmp_path/'bad.json'
    p.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        parse_received_report(p)
    doc=report()
    doc['individual_absent_received_ids'][0]['received_numeric_id']=True
    p.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        parse_received_report(p)
    doc=report()
    doc['coverage_by_attribute']['paint']['absent_from_sources']=10
    p.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        parse_received_report(p)


def test_dry_run_no_network_or_saved_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr('socket.socket.connect',lambda *args: pytest.fail('dry run attempted network'))
    outfile=tmp_path/'x.json'
    assert main(['--output',str(outfile)])==0
    assert not outfile.exists()
    assert json.loads(capsys.readouterr().out)['network_requests']==0


def test_offline_existing_color_bundle_and_private_output(tmp_path, capsys):
    f=tmp_path/'CarColorLibrary.ASTC.test'
    f.write_bytes(_bundle('CarColorLibrary',count=16))
    path=tmp_path/'results.json'
    assert main(['--color-bundle',str(f),'--received-report',str(received(tmp_path)),
                 '--output',str(path)])==0
    written=json.loads(path.read_text())
    assert written['network_requests']==0
    assert written['individual_unmatched_received_paint_ids'][0]['received_paint_id']==0
    assert 'PRIVATE_PLAYER_ID' not in path.read_text()
    with pytest.raises(SystemExit):
        main(['--color-bundle',str(f),'--received-report',str(tmp_path/'received.json'),
              '--output',str(path)])  # no clobber
    assert json.loads(capsys.readouterr().out)['status']=='received_paint_id_vs_separate_color_palette_checked'


def test_reject_unmatched_report_symlink(tmp_path):
    original=received(tmp_path)
    linked=tmp_path/'link.json'
    try:
        linked.symlink_to(original)
    except OSError:
        pytest.skip('symlink privilege unavailable')
    with pytest.raises(ValueError):
        parse_received_report(linked)
