"""Dev29 regression tests: offline redacted schema census and fixed read boundary."""
import json
from pathlib import Path

import pytest

from csr2cdn.crew_endpoint_inventory import (
    _kind, _rows_summary, build_endpoint_inventory, main,
)
from csr2cdn._service_reads import own_crew_contract, crew_members_contract, gcc_progress_contract
from csr2cdn.services import CSR2Services
from csr2cdn.service_models import ServiceResponseError


OWN = {
    'crewUID': 'TOP_SECRET_CREW_ID', 'crewName': 'private crew',
    'memberCount': 2, 'crewRP': 34567890, 'crewLevel': 2,
    'maximumMembers': 30, 'invitesCount': None,
    'crewMotto': 'MY TOP SECRET MOTTO',
    'accessToken': 'PRIVATE_ACCESS_TOKEN',
    'seasonIdentifier': 'interesting-secret-season-value',
}
ROSTER = {
    'responseData': {'members': [
        {'player_uid': 'PRIVATE_ID_ONE', 'name': 'Secret Name 1',
         'cc_contrib': 10, 'player_rp': 999, 'season_pass_rp_boost': 5,
         'TokenDonated_season': 3, 'current_car': {
             'car_id': 'PRIVATE_CAR', 'paint': 'PRIVATE_PAINT', 'car_pp': 650},
         'last_sign_in_time': '2026-10-15'},
        {'player_uid': 'PRIVATE_ID_TWO', 'name': 'Secret Name 2',
         'cc_contrib': 20, 'player_rp': 888, 'season_pass_rp_boost': None,
         'TokenDonated_season': 'bad', 'current_car': {'car_id': 'OTHER_SECRET_CAR'}},
    ], 'season_id': 'hidden-season'},
    'nonce': 'TOP_SECRET_NONCE',
}
GCC = {
    'scores': [
        {'crew_id': 'TOP_SECRET_CREW_ID', 'name': 'the private crew',
         'rank': 12, 'score': 30, 'logo': {'image': 'MY_SECRET_IMAGE_URL',
                                         'palette': 'MY_SECRET_COLOR'}},
        {'crew_id': 'another_id', 'name': 'second private crew',
         'rank': 13, 'score': 31, 'logo': {'image': 'OTHER_SECRET_IMAGE_URL'}},
    ],
    'currentSeasonId': 'MY_SECRET_SEASON',
    'nextCursor': 'MY_SECRET_CURSOR',
    'accessToken': 'MY_SECRET_ACCESS',
}


def test_schema_census_has_expected_member_gcc_and_logo_types():
    out = build_endpoint_inventory(OWN, ROSTER, GCC)
    assert out['source_contracts'] == ['crews/checkUserCrew', 'crews/viewMembers',
                                      'leaderboard/crew-champs-v2/viewcrew']
    assert out['roster']['member_rows']['row_count'] == 2
    assert out['roster']['member_rows']['fields']['cc_contrib'] == {'integer': 2}
    assert out['roster']['member_rows']['fields']['season_pass_rp_boost'] == {'integer': 1, 'null': 1}
    assert out['roster']['member_rows']['nested_object_fields']['current_car']['car_id'] == {'string': 2}
    assert out['gcc_progress']['score_rows']['fields']['score'] == {'integer': 2}
    assert out['gcc_progress']['score_rows']['nested_object_fields']['logo']['image'] == {'string': 2}
    assert out['gcc_progress']['scores_array_present']
    assert out['metadata_key_cues']['gcc_response'] == ['currentSeasonId', 'nextCursor']
    assert out['raw_replies_saved'] is False
    assert out['live_season_identity_verified'] is False


@pytest.mark.parametrize('opt_in', [False, True])
def test_no_private_values_or_secret_key_names_escape_even_with_numeric_preview(opt_in):
    out = json.dumps(build_endpoint_inventory(OWN, ROSTER, GCC, show_stat_candidates=opt_in))
    for private in ('TOP_SECRET_CREW_ID', 'PRIVATE_ID_ONE', 'PRIVATE_ID_TWO',
                    'Secret Name 1', 'TOP SECRET MOTTO', 'MY_SECRET_CURSOR',
                    'MY_SECRET_IMAGE_URL', 'hidden-season', 'accessToken',
                    'MY_SECRET_ACCESS', 'TOP_SECRET_NONCE'):
        assert private not in out
    assert 'currentSeasonId' in out  # name is fine, value is not
    assert 'cc_contrib' in out
    assert 'logo' in out


def test_optional_numeric_preview_separate_unverified_and_aggregate_only():
    safe = build_endpoint_inventory(OWN, ROSTER, GCC)
    assert safe['own_crew']['candidate_numeric']['crewRP']['numeric'] == 1
    assert 'own_crew_value_unverified' not in safe['own_crew']['candidate_numeric']['crewRP']
    assert safe['roster']['candidate_numeric']['TokenDonated_season']['invalid'] == 1
    assert safe['roster']['candidate_numeric']['season_pass_rp_boost']['null'] == 1
    out = build_endpoint_inventory(OWN, ROSTER, GCC, show_stat_candidates=True)
    assert out['own_crew']['candidate_numeric']['crewRP']['own_crew_value_unverified'] == 34567890
    assert out['roster']['candidate_numeric']['cc_contrib']['sum'] == 30
    assert out['roster']['candidate_numeric']['cc_contrib']['minimum'] == 10
    assert 'season_scope' not in out['roster']['candidate_numeric']['cc_contrib']
    assert out['roster']['candidate_numeric']['cc_contrib']['units_or_season_verified'] is False


def test_gcc_progress_unexpected_scores_structure_reports_envelope_but_no_ranks():
    o = build_endpoint_inventory(OWN, ROSTER, {'resultCount': 42, 'whatever': []})
    assert not o['gcc_progress']['scores_array_present']
    assert not o['gcc_progress']['score_rows']['fields']
    assert o['gcc_progress']['selected_payload']['fields']['resultCount'] == {'integer': 1}


def test_wrapped_responses_retained_and_metadata_cues_from_selected_payload():
    a = build_endpoint_inventory({'responseData': OWN}, ROSTER,
                                  {'responseData': GCC})
    assert a['own_crew']['raw_envelope']['fields']['responseData'] == {'object': 1}
    assert a['roster']['raw_envelope']['fields']['responseData'] == {'object': 1}
    assert 'season_id' in a['metadata_key_cues']['roster_response']
    assert a['gcc_progress']['score_rows']['row_count'] == 2


def test_protect_protocol_schema_keys_and_limit_unknown_fields():
    malformed = {f'k_{i}': 'NEVER_PRINT' for i in range(300)}
    malformed.update({'secret': 'NEVER_PRINT', 'myAccessToken': 'NEVER_PRINT',
                      'PRIVATE_12345': 'NEVER_PRINT', 'good_key': None})
    census = _rows_summary([malformed])
    assert census['suppressed_key_occurrences'] > 0
    assert len(census['fields']) <= 96
    assert 'myAccessToken' not in census['fields']
    assert 'PRIVATE_12345' not in census['fields']
    assert census['row_count'] == 1
    assert 'NEVER_PRINT' not in str(census)


def test_bounded_rows_and_types_boolean_not_integer():
    assert _kind(True) == 'boolean'
    census = _rows_summary([{'count': True}] * 1200)
    assert census['row_count'] == 1200
    assert census['inspected'] == 1000 and census['truncated_rows'] is True
    assert census['fields']['count'] == {'boolean': 1000}


def test_unsupported_roster_fails_closed_without_dumping_data():
    with pytest.raises(ServiceResponseError):
        build_endpoint_inventory(OWN, {'unrecognized': 'PRIVATE'}, GCC)
    with pytest.raises(ServiceResponseError):
        build_endpoint_inventory({'not_crew': 'private'}, ROSTER, GCC)


def test_service_uses_exact_existing_three_read_contracts(monkeypatch):
    svc = CSR2Services('PRIVATE_PLAYER_ID', allow_network=False)
    seen = []
    def fake_read(contract):
        seen.append((contract.route, tuple(contract.params)))
        return {'crews/checkUserCrew': OWN,
                'crews/viewMembers': ROSTER,
                'leaderboard/crew-champs-v2/viewcrew': GCC}[contract.route]
    monkeypatch.setattr(svc, '_read', fake_read)
    report = svc.get_crew_endpoint_inventory()
    assert [key for key, params in seen] == [
        'crews/checkUserCrew', 'crews/viewMembers', 'leaderboard/crew-champs-v2/viewcrew']
    assert seen[0][1] == ('app_ver',)
    assert seen[1][1] == ('crew_uid', 'app_ver')
    assert seen[2][1] == ('app_ver', 'top', 'after', 'before', 'offset')
    assert 'PRIVATE_PLAYER_ID' not in str(report)
    assert 'TOP_SECRET_CREW_ID' not in str(report)


def test_service_no_roster_or_gcc_request_without_valid_membership(monkeypatch):
    svc = CSR2Services('private', allow_network=False)
    calls = []
    def fake_read(contract):
        calls.append(contract.route)
        return {'playerUID': 'secret', 'crewUID': None}
    monkeypatch.setattr(svc, '_read', fake_read)
    with pytest.raises(Exception):
        svc.get_crew_endpoint_inventory()
    assert calls == ['crews/checkUserCrew']


def test_cli_dry_run_no_network(capsys):
    assert main([]) == 0
    text = capsys.readouterr().out
    assert json.loads(text)['network_requests'] == 0


def test_cli_requires_all_offline_files(capsys):
    with pytest.raises(SystemExit) as raised:
        main(['--own-json', 'anything.json'])
    assert raised.value.code == 2


def test_cli_offline_paths_support_schema_from_files_without_live_network(tmp_path, capsys):
    files = []
    for name, reply in [('own', OWN), ('roster', ROSTER), ('gcc', GCC)]:
        path = tmp_path / f'{name}.json'
        path.write_text(json.dumps(reply), encoding='utf-8')
        files.append(str(path))
    args = ['--own-json', files[0], '--members-json', files[1], '--gcc-json', files[2]]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['gcc_progress']['score_rows']['row_count'] == 2
    assert result['field_values_printed'] is False


def test_cli_refuses_oversize_raw_json(tmp_path, capsys):
    oversize = tmp_path / 'huge.json'
    oversize.write_bytes(b' ' * (8*1024*1024 + 1))
    small = tmp_path / 'small.json'
    small.write_text('{}')
    assert main(['--own-json', str(oversize), '--members-json', str(small),
                 '--gcc-json', str(small)]) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'inventory_unavailable'


def test_cli_execute_rejects_noninteractive_before_any_requests(monkeypatch, capsys):
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    assert main(['--execute']) == 2
    assert json.loads(capsys.readouterr().out)['network_requests'] == 0


def test_gcc_typed_model_retains_logo_and_metadata_in_memory_only():
    from csr2cdn.service_models import GCCProgressCrewScores
    rows = GCCProgressCrewScores.from_response(GCC)
    assert rows.crews[0].logo['image'] == 'MY_SECRET_IMAGE_URL'
    assert rows.extras['currentSeasonId'] == 'MY_SECRET_SEASON'
    # Dataclass repr of the object must never reveal arbitrary metadata.
    assert 'MY_SECRET_IMAGE_URL' not in repr(rows)
    assert 'MY_SECRET_SEASON' not in repr(rows)
    assert 'TOP_SECRET_CREW_ID' not in repr(rows)


def test_nested_season_metadata_field_names_no_values():
    wrapped = dict(GCC)
    wrapped['metadata'] = {'seasonId': 'SECRET_PERIOD_7',
                           'nextPage': 'SECRET_NEXT_PAGE',
                           'accessToken': 'VERY_SECRET'}
    o = build_endpoint_inventory(OWN, ROSTER, wrapped)
    assert 'metadata.seasonId' in o['metadata_key_cues']['gcc_response']
    assert 'metadata.nextPage' in o['metadata_key_cues']['gcc_response']
    assert 'metadata.accessToken' not in str(o)
    assert 'SECRET_PERIOD_7' not in str(o)
