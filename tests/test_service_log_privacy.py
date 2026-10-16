"""No auth-specific log output and no network I/O in previews."""
import json

from csr2cdn.cli import main


def test_cli_crews_never_posts(monkeypatch, capsys):
    import requests
    def fail(*args, **kwargs):
        raise AssertionError("network use in offline mode")
    monkeypatch.setattr(requests.Session, "post", fail)
    assert main(["services", "crew", "CREW_FIXTURE"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["route"] == "crews/viewMembers"


def test_cli_showdown_never_posts(monkeypatch, capsys):
    import requests
    def fail(*args, **kwargs):
        raise AssertionError("network use in offline mode")
    monkeypatch.setattr(requests.Session, "post", fail)
    assert main(["services", "showdown", "--leaderboard-name", "BOARD_FIXTURE"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["route"] == "leaderboard/BOARD_FIXTURE/view"


def test_invalid_path_does_not_echo_path(capsys):
    private = "/no_such_file/private_account_reference_9872.json"
    assert main(["services", "--events-file", private, "events"]) == 1
    output = capsys.readouterr().err
    assert "private_account_reference" not in output
    assert "portal" not in output.lower()


def test_no_chat_api():
    from csr2cdn.services import CSR2Services
    methods = [x for x in dir(CSR2Services) if not x.startswith("_")]
    assert not any("chat" in item for item in methods)
