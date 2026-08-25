"""Drive the build command itself, so a wrong module reference is caught."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spb import cli  # noqa: E402


class BuildClient:
    def __init__(self):
        self.created = None
        self.added = []

    def me(self):
        return {"id": "toohey"}

    def my_playlists(self):
        return [{"id": "p1", "name": "2026 - Music I Listened To",
                 "owner": {"id": "toohey"}}]

    def playlist_tracks(self, playlist_id):
        return [
            {"id": "t1", "name": "Let Down",
             "artists": [{"id": "a1", "name": "Radiohead"}]}
        ]

    def find_track(self, artist, title):
        return {
            "uri": "spotify:track:%s" % title.replace(" ", ""),
            "name": title,
            "artists": [{"name": artist}],
            "album": {"release_date": "2024-01-01"},
        }

    def create_playlist(self, user_id, name, description="", public=False):
        self.created = {"id": "new1", "name": name,
                        "external_urls": {"spotify": "https://x/new1"}}
        return self.created

    def add_tracks(self, playlist_id, uris):
        self.added.extend(uris)


@pytest.fixture
def picks(tmp_path):
    path = tmp_path / "picks.txt"
    path.write_text(
        "# comment\nRadiohead - Let Down\nDuster - Constellations\n",
        encoding="utf-8",
    )
    return str(path)


def test_build_dry_run_excludes_known_artists(monkeypatch, picks, capsys):
    client = BuildClient()
    monkeypatch.setattr(cli, "_connect", lambda: client)

    assert cli.main(["build", "--from", picks, "--exclude-known",
                     "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "Radiohead" in out and "Dropped" in out   # already in the playlist
    assert "Constellations" in out                    # kept
    assert client.created is None                     # dry run writes nothing


def test_build_creates_the_playlist_and_adds_only_kept_tracks(
    monkeypatch, picks
):
    client = BuildClient()
    monkeypatch.setattr(cli, "_connect", lambda: client)

    assert cli.main(["build", "--from", picks, "--exclude-known",
                     "--name", "Claude picks"]) == 0

    assert client.created["name"] == "Claude picks"
    assert client.added == ["spotify:track:Constellations"]


def test_build_without_exclude_known_keeps_everything(monkeypatch, picks):
    client = BuildClient()
    monkeypatch.setattr(cli, "_connect", lambda: client)

    assert cli.main(["build", "--from", picks]) == 0
    assert len(client.added) == 2
