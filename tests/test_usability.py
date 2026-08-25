"""The surfaces a person actually touches: config, errors, help, output."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spb import cli, config  # noqa: E402
from spb.errors import SpbError  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv(config.ENV_CLIENT_ID, raising=False)


def test_a_saved_client_id_survives_a_new_session():
    config.set_client_id("abc123")
    assert config.get_client_id() == "abc123"


def test_the_environment_overrides_the_saved_id(monkeypatch):
    config.set_client_id("saved")
    monkeypatch.setenv(config.ENV_CLIENT_ID, "override")
    assert config.get_client_id() == "override"


def test_client_id_is_stripped():
    assert config.set_client_id("  spaced  ") == "spaced"


def test_a_missing_config_file_is_not_an_error():
    assert config.get_client_id() is None
    assert config.load() == {}


def test_running_without_a_client_id_prints_a_message_not_a_traceback(
    monkeypatch, capsys
):
    monkeypatch.setattr(sys, "argv", ["spb", "playlists"])
    assert cli.run() == 1
    err = capsys.readouterr().err
    assert "spb login --client-id" in err
    assert "Traceback" not in err


def test_an_interrupt_is_reported_calmly(monkeypatch, capsys):
    monkeypatch.setattr(cli, "main", lambda: (_ for _ in ()).throw(
        KeyboardInterrupt))
    assert cli.run() == 130
    assert "cached" in capsys.readouterr().err


def test_every_command_and_flag_parses():
    parser = cli.build_parser()
    for argv in (
        ["playlists"],
        ["login", "--client-id", "x"],
        ["doctor"],
        ["doctor", "--write-test"],
        ["clear-cache"],
        ["export"],
        ["export", "--no-cache", "--out", "p.json"],
        ["new-releases", "--months", "6", "--per-artist", "2", "--dry-run"],
        ["new-releases", "--search-ttl", "24", "--quiet", "--no-cache"],
        ["discover", "--genre", "shoegaze", "--artists", "5"],
        ["build", "--from", "x.txt", "--exclude-known", "--limit", "10"],
    ):
        parser.parse_args(argv)


def test_the_tracklist_table_lines_up_and_truncates(capsys):
    cli._table([
        {"name": "Short", "artist": "A", "released": "2026-01-01"},
        {"name": "A very long track title " * 3, "artist": "B" * 60,
         "released": "2025-12-31"},
    ])
    lines = capsys.readouterr().out.rstrip("\n").split("\n")
    assert len({len(line) for line in lines}) == 1   # same width
    assert all(line.endswith(("2026-01-01", "2025-12-31")) for line in lines)


def test_an_empty_tracklist_prints_nothing(capsys):
    cli._table([])
    assert capsys.readouterr().out == ""


def test_spb_error_carries_the_next_step():
    with pytest.raises(SpbError) as caught:
        raise SpbError("do the thing:\n\n    spb login")
    assert "spb login" in str(caught.value)
