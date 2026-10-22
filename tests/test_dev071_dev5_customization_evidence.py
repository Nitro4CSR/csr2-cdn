"""Dev5 offline APK inventory, exact candidate mapping, and privacy gates."""
import hashlib
import json
from zipfile import ZipFile

import pytest

from csr2cdn.customization_evidence import (
    CUSTOMIZATION_BLOCKS, CosmeticCandidateCatalog, cosmetic_coverage_report,
    inspect_customization_apk, main as evidence_main,
)
from csr2cdn.crew_optional_data import CrewOptionalSnapshot, optional_report
from csr2cdn.crew_bulk_validation import bulk_report, main as bulk_main
from csr2cdn._service_reads import StandingRange
from csr2cdn.service_models import CrewMembers, OwnCrew

RAW = b"\x00$Nmg\x11\x22\x33\x44"
SHA = hashlib.sha256(RAW).hexdigest()
SECRET = "SECRET_LABEL_CANARY"


def apk(tmp_path, *, with_nmg=True):
    file = tmp_path / 'csr2.apk'
    with ZipFile(file, 'w') as zip:
        zip.writestr('assets/Media/Metadata/CarCustomizationParameters.metadata',
                     RAW if with_nmg else b'plain?')
        zip.writestr('assets/Media/Metadata/CarPresets.metadata', b'?????')
    return file


def manifest(*, records=None):
    return {'format': 'csr2cdn.cosmetic-candidates.v1', 'records': [
        {'car_db_name': 'Abarth_500_2014', 'slot': 'paint', 'id': 7,
         'label': SECRET, 'source_block': 'CarCustomizationParameters',
         'source_sha256': SHA, 'source_record_path': 'example/explicit/paint/7'},
        {'car_db_name': 'Abarth_500_2014', 'slot': 'wheel', 'id': 'Wheel_W1',
         'label': 'WHEEL CANDIDATE', 'source_block': 'CarCustomizationParameters',
         'source_sha256': SHA, 'source_record_path': 'example/explicit/wheel/W1'},
    ] if records is None else records}


def wire():
    own = {'crew_uid': 'SECRET_CREW_ID', 'members': 2}
    roster = {'crew_uid': 'SECRET_CREW_ID', 'scores': [
        {'player_uid': 'PLAYER_PRIVATE', 'name': 'SECRET_MEMBER_NAME',
         'current_car': 'Abarth_500_2014', 'car_paint_id': 7,
         'car_wheel_name': 'Wheel_W1', 'car_livery_id': 0, 'cc_contrib': 7},
        {'player_uid': 'PLAYER_PRIVATE_2', 'name': 'OTHER_SECRET_MEMBER',
         'current_car': 'Abarth_500_2014', 'car_paint_id': 8,
         'car_wheel_name': 'Wheel_W2', 'cc_contrib': 10},
    ]}
    common = {'scores': [{'crew_id': 'SECRET_CREW_ID', 'name': 'SECRET_CREW_NAME', 'rank': 45, 'score': 17}]}
    expanded = {'scores': [{'crew_id': 'SECRET_CREW_ID', 'name': 'SECRET_CREW_NAME', 'rank': 45, 'score': 17}]}
    return own, roster, common, expanded


def snapshot():
    own, roster, _, _ = wire()
    return CrewOptionalSnapshot.from_reads(OwnCrew.from_response(own),
        CrewMembers.from_response('SECRET_CREW_ID', roster))


def test_apk_metadata_block_inventory_is_binary_only(tmp_path):
    result = inspect_customization_apk(apk(tmp_path))
    assert result['network_requests'] == 0
    assert result['semantic_mappings_verified'] is False
    assert list(result['blocks']) == list(CUSTOMIZATION_BLOCKS)
    assert result['blocks']['CarCustomizationParameters'] == {
        'present': True, 'size_bytes': len(RAW), 'sha256': SHA,
        'format': 'binary_nmg_unparsed'}
    assert result['blocks']['CarPresets']['format'] == 'unknown_unparsed'
    assert result['blocks']['CarLiveriesMatrix'] == {'present': False}
    assert SECRET not in repr(result)


def test_apk_inspection_rejects_corrupt_or_oversized_zip(tmp_path):
    bad = tmp_path/'bad.apk';bad.write_text('not-a-zip')
    with pytest.raises(ValueError, match='cannot be inspected'):
        inspect_customization_apk(bad)
    huge = tmp_path/'huge.apk'
    with ZipFile(huge, 'w') as f:
        f.writestr('assets/Media/Metadata/CarCustomizationParameters.metadata', b'A'*(8*1024*1024 + 1))
    with pytest.raises(ValueError, match='bounds'):
        inspect_customization_apk(huge)
    with pytest.raises(ValueError, match='bounded regular file'):
        inspect_customization_apk(tmp_path/'missing.apk')


def test_manifest_requires_exact_apk_source_digest(tmp_path):
    inv = inspect_customization_apk(apk(tmp_path))
    c = CosmeticCandidateCatalog.from_manifest(manifest(), apk_inventory=inv)
    assert c.apk_block_digests_confirmed is True
    assert len(c.records) == 2
    assert c.match('Abarth_500_2014', 'paint', 7).label_candidate == SECRET
    assert c.match('Abarth_500_2014', 'wheel', 'Wheel_W1') is not None
    assert c.match('Abarth_500_2014', 'paint', 8) is None
    assert c.match('abarth_500_2014', 'paint', 7) is None
    assert c.match('Abarth_500_2014', 'paint', True) is None
    assert c.match('Abarth_500_2014 ', 'paint', 7) is None
    assert SECRET not in repr(c)
    assert SECRET not in repr(c.records[0])


def test_manifest_without_apk_is_still_unverified_candidate():
    c = CosmeticCandidateCatalog.from_manifest(manifest())
    assert c.apk_block_digests_confirmed is False
    assert c.match('Abarth_500_2014', 'paint', 7).label_candidate == SECRET


def test_rejects_false_provenance_and_malformed_manifest(tmp_path):
    inv = inspect_customization_apk(apk(tmp_path))
    import copy
    bad = copy.deepcopy(manifest())
    bad['records'][0]['source_sha256'] = 'a'*64
    with pytest.raises(ValueError, match='SHA256'):
        CosmeticCandidateCatalog.from_manifest(bad, apk_inventory=inv)
    bad = copy.deepcopy(manifest())
    bad['records'][0]['source_block'] = 'GameAccountTokens'
    with pytest.raises(ValueError): CosmeticCandidateCatalog.from_manifest(bad)
    for candidate in [None, [], {}, {'format':'bad','records':[]},
                      {'format':'csr2cdn.cosmetic-candidates.v1','records':{}}]:
        with pytest.raises(ValueError): CosmeticCandidateCatalog.from_manifest(candidate)


@pytest.mark.parametrize('field,value', [
    ('car_db_name',''), ('car_db_name','A\nsecret'), ('slot','paint_id'),
    ('id',-1), ('id',True), ('id','7'), ('id',2**31),
    ('label','\nsecret'), ('label','a'*121),
    ('source_sha256','A'*64), ('source_sha256','0'*63),
    ('source_record_path','\nsecret'),
])
def test_rejects_invalid_candidates(field, value):
    m = manifest(records=[dict(manifest()['records'][0], **{field:value})])
    with pytest.raises(ValueError): CosmeticCandidateCatalog.from_manifest(m)


def test_rejects_duplicate_and_wrong_wheel_value_type():
    row = manifest()['records'][0]
    with pytest.raises(ValueError, match='duplicate'):
        CosmeticCandidateCatalog.from_manifest(manifest(records=[row,row]))
    bad = dict(manifest()['records'][1], id=1)
    with pytest.raises(ValueError, match='wheel'):
        CosmeticCandidateCatalog.from_manifest(manifest(records=[bad]))


def test_default_coverage_never_reveals_ids_or_candidate_labels(tmp_path):
    c = CosmeticCandidateCatalog.from_manifest(manifest(), apk_inventory=inspect_customization_apk(apk(tmp_path)))
    result = cosmetic_coverage_report(snapshot(), c)
    assert result['slot_present']['paint'] == 2
    assert result['slot_present']['wheel'] == 2
    assert result['slot_exact_candidate_matches']['paint'] == 1
    assert result['slot_exact_candidate_matches']['wheel'] == 1
    assert result['slot_present']['livery'] == 1
    assert result['slot_exact_candidate_matches']['livery'] == 0
    assert result['apk_block_digests_confirmed'] is True
    assert result['labels_verified_in_game'] is False
    assert result['source_record_semantics_verified'] is False
    output = json.dumps(result)
    for private in [SECRET, 'SECRET_MEMBER_NAME', 'PLAYER_PRIVATE', 'SECRET_CREW_ID', 'Abarth_500_2014', 'Wheel_W1']:
        assert private not in output
    details = cosmetic_coverage_report(snapshot(), c, show_members=True)
    assert details['member_label_candidates'][0]['paint']['label_candidate'] == SECRET
    assert details['member_label_candidates'][1] == {}
    assert 'PLAYER_PRIVATE' not in json.dumps(details)


def test_optional_bulk_integration_zero_new_requests(tmp_path):
    c = CosmeticCandidateCatalog.from_manifest(manifest(), apk_inventory=inspect_customization_apk(apk(tmp_path)))
    snap = snapshot()
    baseline = optional_report(snap)
    updated = optional_report(snap, cosmetic_catalog=c)
    assert updated.pop('cosmetic_candidates')['slot_exact_candidate_matches']['paint'] == 1
    assert updated == baseline
    own, roster, common, expanded = wire()
    result = bulk_report(own, roster, common, expanded,
                         ranges=StandingRange(top=20, before=10, after=10, offset=0),
                         cosmetic_catalog=c)
    assert result['optional']['cosmetic_candidates']['slot_present']['paint'] == 2
    assert result['feature_decisions']['cosmetic_labels'] == 'unverified_manifest_candidate'
    assert result['network_requests_for_offline_decoder'] == 0
    assert SECRET not in json.dumps(result)
    assert result['status'] == 'bulk_candidate_evidence_not_yet_live_verified'


def test_bulk_cli_offline_files_manifest_and_apk(tmp_path, capsys):
    paths = []
    for name, data in zip(('own','members','gcc1','gcc2'), wire()):
        p = tmp_path/(name+'.json');p.write_text(json.dumps(data), encoding='utf8');paths.append(str(p))
    manifest_path = tmp_path/'cosmetics.json';manifest_path.write_text(json.dumps(manifest()), encoding='utf8')
    apk_path = apk(tmp_path)
    args = ['--own-json',paths[0], '--members-json',paths[1],
            '--gcc-common-json',paths[2], '--gcc-experimental-json',paths[3],
            '--cosmetic-manifest-json',str(manifest_path), '--cosmetic-apk',str(apk_path)]
    assert bulk_main(args) == 0
    result=json.loads(capsys.readouterr().out)
    assert result['optional']['cosmetic_candidates']['apk_block_digests_confirmed']
    assert SECRET not in json.dumps(result)
    assert bulk_main(args+['--show-members']) == 0
    detailed=json.loads(capsys.readouterr().out)
    assert detailed['optional']['cosmetic_candidates']['member_label_candidates'][0]['paint']['label_candidate'] == SECRET
    assert 'PLAYER_PRIVATE' not in json.dumps(detailed)
    assert bulk_main(args[:-4]+['--cosmetic-apk',str(apk_path)]) == 3
    assert json.loads(capsys.readouterr().out)['details']=='suppressed'


def test_dry_run_never_opens_files(tmp_path, capsys):
    nonexist = str(tmp_path/'missing.apk')
    assert bulk_main(['--cosmetic-apk',nonexist]) == 0
    assert json.loads(capsys.readouterr().out)['network_requests'] == 0
    assert evidence_main([]) == 0
    assert json.loads(capsys.readouterr().out)['network_requests'] == 0
    assert evidence_main(['--apk', nonexist]) == 2
    assert json.loads(capsys.readouterr().out)['details'] == 'suppressed'


def test_evidence_cli_reports_only_allowed_blocks(tmp_path, capsys):
    assert evidence_main(['--apk',str(apk(tmp_path))]) == 0
    out=json.loads(capsys.readouterr().out)
    assert out['status'] == 'apk_binary_inventory_only'
    assert out['blocks']['CarCustomizationParameters']['format'] == 'binary_nmg_unparsed'
