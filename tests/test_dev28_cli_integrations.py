"""End-to-end synthetic dev28 CLI behavior; no network or private records."""
from datetime import datetime

from csr2cdn.crew_rp_verification import verify, _table
from csr2cdn.service_models import OwnCrew, CrewMembers


class Stub:
    def __init__(self, *args, **kwargs):
        assert kwargs['allow_network'] is True
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def get_my_crew(self): return OwnCrew('private_crew', member_count=30)
    def get_crew_members(self):
        return CrewMembers.from_response('private_crew', {'crewMembers': [
            {'player_uid': f'PRIVATE_{i}', 'name': f'Name{i}', 'cc_contrib': i}
            for i in range(30)
        ]})
    def get_gcc_progress_response(self):
        return {'scores': [{'crew_id':'private_crew', 'name':'Some Crew', 'rank':4,
                            'score':sum(range(30))}]}


def test_verify_auto_server_occupancy_and_redacted_typed_summary():
    report = verify(player_id='MY_PRIVATE_ID', execute=True, gcc_live=True,
                    services_factory=Stub)
    assert report['roster_count_reference_source'] == 'own_crew_memberCount'
    assert report['member_response']['roster_count'] == 30
    snapshot = report['crew_rp_snapshot']
    assert snapshot['comparable'] and snapshot['member_sum_minus_leaderboard'] == 0
    assert snapshot['expected_member_count'] == 30
    assert snapshot['active_season_verified'] is False
    assert 'private_crew' not in str(snapshot)
    assert 'MY_PRIVATE_ID' not in str(snapshot)
    assert 'TYPED CREW RP SNAPSHOT' in _table(report)


def test_explicit_member_override_fails_closed_when_different():
    report = verify(player_id='MY_PRIVATE_ID', execute=True, gcc_live=True,
                    services_factory=Stub, expected_members=29)
    assert report['roster_count_reference_source'] == 'operator'
    assert not report['crew_rp_snapshot']['comparable']
    assert report['crew_rp_snapshot']['member_sum_minus_leaderboard'] is None
    assert report['sequential_roster_gcc_comparison']['member_sum_minus_gcc_score'] is None
    assert report['sequential_roster_gcc_comparison']['status'] == 'comparison_unavailable'
