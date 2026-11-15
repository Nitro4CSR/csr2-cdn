"""Dev87: the Showdown board ledger survives a catalogue rollover.

Observed 2026-11-15: the server rolled its modular event catalogue forward
and the bundles of showdowns that had already started left it, while those
showdowns kept running for days. Discovery from a fresh catalogue then
reported no current showdown at all. The ledger remembers what discovery
resolved, so a still-running board is carried forward.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import csr2cdn.service_discovery as sd
from csr2cdn.service_discovery import (LEDGER_VERSION, ShowdownBoardLedger,
                                       ShowdownCandidate, ShowdownDiscovery)

UTC = timezone.utc
T0 = datetime(2026, 11, 11, 16, tzinfo=UTC)          # SMP W2 opens
T_END = datetime(2026, 11, 18, 18, tzinfo=UTC)       # ... and closes
BOARD = "evnt-off-160-dur-170-hours-dsc---301176007"


def candidate(event_id="ev-w2", board=BOARD, start=T0, end=T_END, status="scheduled_now",
              **extra):
    return ShowdownCandidate(event_id=event_id, schedule_id="SMP_SHOWDOWN_279_W2",
                             leaderboard_name=board, starts_at=start, ends_at=end,
                             time_status=status, display_name="SMP_SHOWDOWN_279_W2",
                             leaderboard_template_id="LeaderboardChampionshipShowdown_DEFAULT",
                             **extra)


def discovery_with(monkeypatch, scans, ledger):
    """A discovery whose scan returns `scans[i]` on the i-th call."""
    calls = {"n": 0}

    def fake_scan(blocks, *, at=None):
        result = scans[min(calls["n"], len(scans) - 1)]
        calls["n"] += 1
        return tuple(result)

    monkeypatch.setattr(sd, "scan_showdowns", fake_scan)
    return ShowdownDiscovery(lambda: {"ShowdownEventsContainer": {}}, ttl=0, ledger=ledger)


def test_rollover_keeps_a_running_board(monkeypatch, tmp_path):
    ledger = ShowdownBoardLedger(tmp_path / "ledger.json")
    disc = discovery_with(monkeypatch, [[candidate()], []], ledger)
    first = disc.list_showdowns(at=T0 + timedelta(hours=1))
    assert [c.resolution_source for c in first] == [None]

    # the catalogue rolled: the scan no longer lists the board
    later = T0 + timedelta(days=4)
    second = disc.list_showdowns(at=later, refresh=True)
    assert len(second) == 1
    carried = second[0]
    assert carried.leaderboard_name == BOARD
    assert carried.resolution_source == "ledger"
    assert carried.time_status == "scheduled_now"
    assert carried.requestable


def test_carried_board_reports_elapsed_after_its_window(monkeypatch, tmp_path):
    ledger = ShowdownBoardLedger(tmp_path / "ledger.json")
    disc = discovery_with(monkeypatch, [[candidate()], []], ledger)
    disc.list_showdowns(at=T0)
    after = disc.list_showdowns(at=T_END + timedelta(minutes=1), refresh=True)
    assert after[0].time_status == "elapsed"


def test_ledger_persists_across_instances(tmp_path):
    path = tmp_path / "ledger.json"
    ShowdownBoardLedger(path).record([candidate()], at=T0)
    reloaded = ShowdownBoardLedger(path)
    assert len(reloaded) == 1
    out = reloaded.carried([], at=T0 + timedelta(days=1))
    assert out[0].leaderboard_name == BOARD


def test_board_still_listed_is_not_duplicated(tmp_path):
    ledger = ShowdownBoardLedger(tmp_path / "l.json")
    ledger.record([candidate()], at=T0)
    assert ledger.carried([candidate()], at=T0) == ()
    # also matched by board name when the event id changes between catalogues
    assert ledger.carried([candidate(event_id="new-id")], at=T0) == ()


def test_only_requestable_windowed_candidates_are_recorded(tmp_path):
    ledger = ShowdownBoardLedger(tmp_path / "l.json")
    ledger.record([candidate(board=None), candidate(event_id="x", start=None),
                   candidate(event_id="y", end=None)], at=T0)
    assert len(ledger) == 0


def test_ledger_candidates_are_never_re_recorded(tmp_path):
    ledger = ShowdownBoardLedger(tmp_path / "l.json")
    ledger.record([candidate()], at=T0)
    carried = ledger.carried([], at=T0)
    assert ledger.record(carried, at=T0) == 0


def test_old_entries_are_pruned(tmp_path):
    ledger = ShowdownBoardLedger(tmp_path / "l.json")
    ledger.record([candidate()], at=T0)
    ledger.record([], at=T_END + timedelta(days=31))
    assert len(ledger) == 0


def test_without_a_ledger_discovery_is_unchanged(monkeypatch):
    disc = discovery_with(monkeypatch, [[candidate()], []], None)
    disc.list_showdowns(at=T0)
    assert disc.list_showdowns(at=T0, refresh=True) == ()


def test_in_memory_ledger_writes_nothing(tmp_path):
    ledger = ShowdownBoardLedger()
    ledger.record([candidate()], at=T0)
    assert len(ledger) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("content", ["not json", json.dumps([1, 2]),
                                     json.dumps({"version": 999, "boards": {}}),
                                     json.dumps({"version": LEDGER_VERSION,
                                                 "boards": {"x": {"leaderboard_name": "b"}}})])
def test_unreadable_or_foreign_ledger_is_empty_not_a_crash(tmp_path, content):
    path = tmp_path / "l.json"
    path.write_text(content, encoding="utf-8")
    assert len(ShowdownBoardLedger(path)) == 0


def test_remember_adds_a_known_board(tmp_path):
    ledger = ShowdownBoardLedger(tmp_path / "l.json")
    ledger.remember("ev-w2", BOARD, T0, T_END, schedule_id="SMP_SHOWDOWN_279_W2")
    assert ledger.carried([], at=T0 + timedelta(hours=1))[0].time_status == "scheduled_now"


@pytest.mark.parametrize("kwargs", [
    {"event_id": ""}, {"leaderboard_name": ""},
    {"starts_at": datetime(2026, 11, 11)},          # naive
    {"starts_at": T_END, "ends_at": T0},             # reversed
])
def test_remember_validates(tmp_path, kwargs):
    args = {"event_id": "ev", "leaderboard_name": BOARD, "starts_at": T0, "ends_at": T_END}
    args.update(kwargs)
    with pytest.raises(ValueError):
        ShowdownBoardLedger().remember(args.pop("event_id"), args.pop("leaderboard_name"),
                                       args.pop("starts_at"), args.pop("ends_at"))


def test_ledger_file_holds_no_account_data(tmp_path):
    path = tmp_path / "l.json"
    ShowdownBoardLedger(path).record([candidate()], at=T0)
    stored = json.loads(path.read_text(encoding="utf-8"))
    entry = stored["boards"]["ev-w2"]
    assert set(entry) == {"leaderboard_name", "schedule_id", "display_name",
                          "leaderboard_template_id", "starts_at", "ends_at"}


def test_discovery_rejects_a_non_ledger():
    with pytest.raises(TypeError):
        ShowdownDiscovery(lambda: {}, ledger="ledger.json")


# --------------------------------------------------------------------------
# showdown rows: races and license_level (live boards, 2026-11-15)

def _row(**over):
    row = {"crewId": "C1", "facebook_id": "", "last_updated": 1794900000,
           "license_level": 412, "multiplier": "Monadic::Nothing", "name": "n",
           "races": "Monadic::Nothing", "rank": 269, "score": 2120,
           "sp_boost_data": {}, "zid": "11111111111"}
    row.update(over)
    return row


def test_event_showdown_row_sentinels_read_as_none():
    from csr2cdn.service_models import LeaderboardPage
    page = LeaderboardPage.from_response("b", {"error_code": 0, "scores": [_row()]})
    entry = page.entries[0]
    assert entry.races is None
    assert entry.multiplier is None
    assert entry.license_level == 412
    assert (entry.rank, entry.score, entry.crew_id) == (269, 2120, "C1")


def test_numeric_races_are_kept():
    from csr2cdn.service_models import LeaderboardPage
    page = LeaderboardPage.from_response("b", {"scores": [_row(races=37)]})
    assert page.entries[0].races == 37


def test_facebook_id_is_still_not_promoted():
    from csr2cdn.service_models import LeaderboardEntry
    assert "facebook_id" not in LeaderboardEntry.__dataclass_fields__
