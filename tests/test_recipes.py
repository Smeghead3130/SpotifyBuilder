import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spb import recipes  # noqa: E402


def test_parse_release_date_handles_all_three_precisions():
    assert recipes.parse_release_date("2026") == datetime.date(2026, 1, 1)
    assert recipes.parse_release_date("2026-03") == datetime.date(2026, 3, 1)
    assert recipes.parse_release_date("2026-03-14") == datetime.date(2026, 3, 14)
    assert recipes.parse_release_date("") is None
    assert recipes.parse_release_date("March 2026") is None


def test_months_ago_walks_back_across_the_year_boundary():
    assert recipes.months_ago(12, datetime.date(2026, 8, 24)) == datetime.date(
        2025, 8, 24
    )
    assert recipes.months_ago(9, datetime.date(2026, 3, 31)) == datetime.date(
        2025, 6, 28
    )


def test_dedupe_keeps_first_occurrence_and_order():
    tracks = [
        {"uri": "a", "name": "one"},
        {"uri": "b", "name": "two"},
        {"uri": "a", "name": "one again"},
    ]
    assert [t["name"] for t in recipes._dedupe(tracks)] == ["one", "two"]


class FakeClient:
    """Stands in for Spotify with a tiny fixed catalogue."""

    def __init__(self):
        self.playlists = [
            {"id": "p1", "name": "Core", "tracks": {"total": 2}},
            {"id": "p2", "name": "Other", "tracks": {"total": 1}},
        ]
        self._tracks = {
            "p1": [
                {"id": "t1", "name": "Song", "artists": [{"id": "a1", "name": "Ada"}]},
                {"id": "t2", "name": "Tune", "artists": [{"id": "a2", "name": "Bo"}]},
            ],
            "p2": [
                {"id": "t3", "name": "Air", "artists": [{"id": "a3", "name": "Cy"}]}
            ],
        }
        self._albums = {
            "a1": [
                {
                    "id": "al1",
                    "name": "Fresh",
                    "release_date": "2026-06-01",
                    "artists": [{"id": "a1"}],
                },
                {
                    "id": "al2",
                    "name": "Old Thing",
                    "release_date": "2019-01-01",
                    "artists": [{"id": "a1"}],
                },
                {
                    "id": "al3",
                    "name": "Fresh (2026 Remaster)",
                    "release_date": "2026-05-01",
                    "artists": [{"id": "a1"}],
                },
                {
                    "id": "al4",
                    "name": "Various Artists Comp",
                    "release_date": "2026-07-01",
                    "artists": [{"id": "zz"}],
                },
            ],
            "a2": [
                {
                    "id": "al5",
                    "name": "Recent",
                    "release_date": "2026",
                    "artists": [{"id": "a2"}],
                }
            ],
        }

    def my_playlists(self):
        return self.playlists

    def playlist_tracks(self, playlist_id):
        return self._tracks[playlist_id]

    def artist_albums(self, artist_id, groups="album,single"):
        return self._albums.get(artist_id, [])

    def album_tracks(self, album_id):
        return [
            {"id": album_id + "-1", "uri": "spotify:track:" + album_id + "1",
             "name": album_id + " one"},
            {"id": album_id + "-2", "uri": "spotify:track:" + album_id + "2",
             "name": album_id + " two"},
        ]

    def followed_artists(self, cap=None):
        return [{"id": "a9", "name": "Followed"}]

    def top_artists(self, time_range="medium_term", cap=50):
        return [{"id": "a1", "name": "Ada", "genres": ["shoegaze", "dream pop"]}]

    def artists(self, ids):
        return [{"id": i, "genres": ["shoegaze"]} for i in ids]

    def search_artists(self, query, limit=50, offset=0):
        if offset:
            return []
        return [
            {"id": "a1", "name": "Ada", "popularity": 90},        # already known
            {"id": "a9", "name": "Followed", "popularity": 80},   # already followed
            {"id": "n1", "name": "New One", "popularity": 70},
            {"id": "n2", "name": "New Two", "popularity": 60},
        ]

    def artist_top_tracks(self, artist_id, market="from_token"):
        return [
            {"uri": "spotify:track:%s-%d" % (artist_id, n),
             "name": "%s hit %d" % (artist_id, n),
             "album": {"name": "Alb", "release_date": "2024-01-01"}}
            for n in range(1, 6)
        ]


def test_resolve_playlists_by_name_id_and_url():
    client = FakeClient()
    got = recipes.resolve_playlists(
        client, ["Core", "p2", "https://open.spotify.com/playlist/p1?si=x"]
    )
    assert [p["id"] for p in got] == ["p1", "p2", "p1"]


def test_resolve_playlists_rejects_an_unknown_name():
    with pytest.raises(SystemExit):
        recipes.resolve_playlists(FakeClient(), ["Nope"])


def test_new_releases_filters_window_reissues_and_uncredited():
    client = FakeClient()
    tracks = recipes.new_releases(client, [client.playlists[0]], months=12)
    albums = {t["album"] for t in tracks}
    assert albums == {"Fresh", "Recent"}        # al2 too old, al3 reissue, al4 not theirs
    assert len(tracks) == 4                      # two tracks from each kept album


def test_new_releases_respects_per_album_cap():
    client = FakeClient()
    tracks = recipes.new_releases(
        client, [client.playlists[0]], months=12, per_album=1
    )
    assert len(tracks) == 2


def test_include_reissues_flag_keeps_the_remaster():
    client = FakeClient()
    tracks = recipes.new_releases(
        client, [client.playlists[0]], months=12, skip_reissues=False
    )
    assert "Fresh (2026 Remaster)" in {t["album"] for t in tracks}


def test_discover_excludes_known_and_followed_artists():
    client = FakeClient()
    tracks, genres = recipes.discover(
        client, [client.playlists[0]], genres=["shoegaze"], artists_wanted=10, top_n=2
    )
    names = {t["artist"] for t in tracks}
    assert names == {"New One", "New Two"}   # Ada is in the playlist, Followed is followed
    assert len(tracks) == 4                  # top_n=2 each
    assert genres == ["shoegaze"]


def test_discover_infers_genres_when_none_are_given():
    client = FakeClient()
    _, genres = recipes.discover(client, [client.playlists[0]], artists_wanted=5)
    assert "shoegaze" in genres
