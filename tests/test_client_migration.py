"""The client must survive the 9 March 2026 playlist endpoint migration."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spb.client import Spotify, SpotifyError  # noqa: E402


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.headers = {}
        self.content = b"x"
        self.text = str(payload)

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._payload


class FakeSession:
    """Serves one of the two API shapes and records what was asked for."""

    def __init__(self, shape):
        self.shape = shape
        self.headers = {}
        self.paths = []

    def request(self, method, url, **kwargs):
        self.paths.append((method, url))
        if self.shape == "new" and url.endswith("/items"):
            return FakeResponse(
                200,
                {
                    "items": [
                        {"item": {"id": "t1", "name": "New Shape",
                                  "artists": [{"id": "a1", "name": "Ada"}]}},
                        {"item": None},                       # a removed track
                        {"item": {"id": None, "name": "Local file"}},
                    ],
                    "next": None,
                },
            )
        if self.shape == "old" and url.endswith("/tracks"):
            return FakeResponse(
                200,
                {
                    "items": [
                        {"track": {"id": "t9", "name": "Old Shape",
                                   "artists": [{"id": "a9", "name": "Bo"}]}}
                    ],
                    "next": None,
                },
            )
        if url.endswith("/items"):
            return FakeResponse(404, {"error": {"status": 404}})
        return FakeResponse(403, {"error": {"status": 403}})


def test_reads_the_post_migration_items_shape():
    session = FakeSession("new")
    client = Spotify("tok", session=session)
    tracks = client.playlist_tracks("p1")
    assert [t["name"] for t in tracks] == ["New Shape"]
    assert session.paths[0][1].endswith("/playlists/p1/items")


def test_falls_back_to_the_old_tracks_path_on_404():
    session = FakeSession("old")
    client = Spotify("tok", session=session)
    tracks = client.playlist_tracks("p1")
    assert [t["name"] for t in tracks] == ["Old Shape"]
    assert [p[1].rsplit("/", 1)[-1] for p in session.paths] == ["items", "tracks"]


def test_null_and_local_entries_are_skipped():
    client = Spotify("tok", session=FakeSession("new"))
    assert len(client.playlist_tracks("p1")) == 1


def test_add_tracks_posts_to_items():
    session = FakeSession("new")
    client = Spotify("tok", session=session)
    client.add_tracks("p1", ["spotify:track:1"])
    assert session.paths[-1] == ("POST", "https://api.spotify.com/v1/playlists/p1/items")


class CreateSession(FakeSession):
    """POST /me/playlists behaves per `me_status`; the legacy path succeeds."""

    def __init__(self, me_status):
        super().__init__("new")
        self.me_status = me_status

    def request(self, method, url, **kwargs):
        self.paths.append((method, url))
        if method == "POST" and url.endswith("/me/playlists"):
            if self.me_status == 200:
                return FakeResponse(200, {"id": "new1"})
            return FakeResponse(self.me_status, {"error": {"status": self.me_status}})
        if method == "POST" and url.endswith("/users/u1/playlists"):
            return FakeResponse(200, {"id": "legacy1"})
        return FakeResponse(200, {})


def test_create_playlist_uses_the_me_path():
    session = CreateSession(200)
    client = Spotify("tok", session=session)
    assert client.create_playlist("u1", "Mix")["id"] == "new1"
    assert session.paths[0][1].endswith("/me/playlists")


def test_create_playlist_falls_back_on_404():
    session = CreateSession(404)
    client = Spotify("tok", session=session)
    assert client.create_playlist("u1", "Mix")["id"] == "legacy1"
    assert [p[1].rsplit("/v1", 1)[-1] for p in session.paths] == [
        "/me/playlists",
        "/users/u1/playlists",
    ]


def test_a_403_on_create_is_not_retried_against_the_legacy_path():
    import pytest

    session = CreateSession(403)
    client = Spotify("tok", session=session)
    with pytest.raises(SpotifyError):
        client.create_playlist("u1", "Mix")
    assert len(session.paths) == 1
