"""Dev36 public cosmetics: synthetic requests, no live game or CDN dependency."""
import hashlib
import json
from unittest.mock import patch

import pytest

from csr2cdn._research.dev36_latest_visual_ids import (
    _SOURCES, _CURRENT_BRANCH, CurrentSourceEvidence,
    fetch_current_visual_ids, catalog_ids_one_by_one,
    unmatched_ids_one_by_one, main, _write_private_new,
)
from csr2cdn._research.dev29_public_cdn_forensics import PublicCDNProbeError
from csr2cdn.game_labels import GameVisualLibrary, VisualCodeName
from test_dev071_dev29_public_cdn_forensics import Response, Session, ORIGIN
from test_dev071_dev25_offline_visual_forensics import inputs, CREW_SECRET


def fake_session():
    doc = [{'version':'77777'}, []]
    answers = {
        f'{ORIGIN}/asset_database_{_CURRENT_BRANCH}.version': Response(b'{"version":77777}'),
    }
    for i, library in enumerate(_SOURCES):
        raw = bytes([65+i])*256
        doc[1].append({'code':library, 'version':str(200+i), 'type':'31',
                       'sizes':{'ASTC':len(raw)}})
        answers[f'{ORIGIN}/ANDROID/ASTC/{library}.ASTC.{200+i}'] = Response(raw)
    answers[f'{ORIGIN}/asset_database.77777.json'] = Response(json.dumps(doc).encode())
    return Session(answers)


def stub_decoder(raw, *, library):
    i = _SOURCES.index(library)
    slot = 'calliper' if 'Calliper' in library else 'interior' if 'Interior' in library else 'paint'
    code = 1000001 if 'Tuner' in library else 5+i
    return GameVisualLibrary((VisualCodeName('*',slot,code, f'Fixture name {i}', library, names=(f'Fixture name {i}',)),))


def test_public_current_branch_six_sources_exact_eight_gets():
    sess = fake_session()
    with patch('csr2cdn._research.dev36_latest_visual_ids.decode_visual_unityfs', side_effect=stub_decoder):
        result = fetch_current_visual_ids(_CURRENT_BRANCH, session=sess)
    assert result.report['database_version']=='77777'
    assert result.report['network_requests'] == 8
    assert result.report['source_total_records'] == 6
    assert result.report['gameplay_read_count'] == 0
    assert result.report['roster_unresolved_ids_identifiable_from_public_sources_alone'] is False
    for u, kw in sess.calls:
        assert u.startswith(ORIGIN+'/')
        assert kw['stream'] is True and kw['allow_redirects'] is False
    cat = catalog_ids_one_by_one(result)
    assert len(cat['individual_source_ids']) == 6
    assert all(row['unresolved_roster_id']=='unknown_without_saved_roster' for row in cat['individual_source_ids'])
    assert all(row['vehicle_eligibility_verified'] is False for row in cat['individual_source_ids'])
    assert all('Fixture name' in row['source_label'] for row in cat['individual_source_ids'])
    assert 'Fixture name' not in json.dumps(result.report)


def test_source_asset_missing_fails_closed_after_index():
    s=fake_session()
    u=f'{ORIGIN}/asset_database.77777.json'
    d=json.loads(s.mapping[u].payload)
    d[1]=d[1][:-1]
    s.mapping[u]=Response(json.dumps(d).encode())
    with pytest.raises(PublicCDNProbeError):
        fetch_current_visual_ids(_CURRENT_BRANCH, session=s)
    assert len(s.calls)==2


def test_deny_redirect_and_wrong_sized_asset():
    s=fake_session()
    first=f'{ORIGIN}/asset_database_{_CURRENT_BRANCH}.version'
    s.mapping[first]=Response(b'',status=302)
    with pytest.raises(PublicCDNProbeError):
        fetch_current_visual_ids(_CURRENT_BRANCH,session=s)
    assert len(s.calls)==1
    s=fake_session()
    first_asset = f'{ORIGIN}/ANDROID/ASTC/{_SOURCES[0]}.ASTC.200'
    s.mapping[first_asset]=Response(b'Z'*255)
    with pytest.raises(PublicCDNProbeError):
        fetch_current_visual_ids(_CURRENT_BRANCH,session=s)
    assert len(s.calls)==3


@pytest.mark.parametrize('branch', ['../x','6_8_0_Release/extra','https://evil.example',''])
def test_branch_blocked_before_http(branch):
    s=fake_session()
    with pytest.raises(ValueError):
        fetch_current_visual_ids(branch,session=s)
    assert len(s.calls)==0


def test_unresolved_one_by_one_with_saved_fixtures_is_private():
    _,_,library,own,roster=inputs()
    out=unmatched_ids_one_by_one(own,roster,library,branch=_CURRENT_BRANCH,database_version='77777')
    entries=out['individual_unresolved_numeric_ids']
    assert sorted((r['slot'],r['numeric_id']) for r in entries) == [
       ('interior',3001111),('interior',3002222),('paint',88),('paint',777)]
    assert out['unresolved_numeric_occurrences']==4
    dumped=json.dumps(out)
    assert CREW_SECRET not in dumped and 'PRIVATE_' not in dumped and 'SECRET_' not in dumped
    assert 'Mazda' not in dumped and 'Normal_Car' not in dumped


def test_dry_run_and_fixture_guards(tmp_path,capsys,monkeypatch):
    monkeypatch.setattr('socket.socket.connect',lambda *args:pytest.fail('no network on dry run'))
    assert main(['--source-ids-output',str(tmp_path/'catalog.json')])==0
    assert json.loads(capsys.readouterr().out)['planned_public_gets']==8
    assert not (tmp_path/'catalog.json').exists()
    with pytest.raises(SystemExit):
        main(['--online','--unresolved-ids-output',str(tmp_path/'unresolved.json')])
    p=tmp_path/'existing.json'
    p.write_text('secret fixture')
    with pytest.raises(SystemExit):
        main(['--output',str(p)])
    assert p.read_text()=='secret fixture'


def test_private_output_is_exclusive_and_permissions(tmp_path):
    p=tmp_path/'private.json'
    _write_private_new(p,{'a':12})
    assert json.loads(p.read_text())=={'a':12}
    with pytest.raises(ValueError):
        _write_private_new(p,{'a':13})
    assert json.loads(p.read_text())=={'a':12}
    q=tmp_path/'link.json'
    try:
        q.symlink_to(p)
    except (OSError,NotImplementedError):
        pytest.skip('symlink creation blocked by platform')
    with pytest.raises(ValueError):
        _write_private_new(q,{'a':13})
