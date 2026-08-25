"""new-releases rebuilt on the search endpoint, since discographies are gone."""

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spb import recipes  # noqa: E402

TODAY = datetime.date(2026, 8, 25)


def _track(name, artist, album, released, album_id=None):
    return {
        "uri": "spotify:track:" + name.replace(" ", ""),
        "name": name,
        "artists": [{"name": artist}],
        "album": {"id": album_id or album, "name": album,
                  "release_date": released},
    }


class SearchClient:
    def __init__(self, by_query):
        self.by_query = by_query
        self.queries = []

    def my_playlists(self):
        return [{"id": "p1", "name": "2026 - Music I Listened To"}]

    def playlist_tracks(self, playlist_id):
        return [
            {"id": "t1", "artists": [{"id": "a1", "name": "Beth Gibbons"}]},
            {"id": "t2", "artists": [{"id": "a2", "name": "Nilüfer Yanya"}]},
        ]

    def search_tracks(self, query, limit=50):
        self.queries.append(query)
        for fragment, tracks in self.by_query.items():
            if fragment in query:
                return tracks
        return []


def _run(by_query, **kwargs):
    client = SearchClient(by_query)
    playlists = client.my_playlists()
    return client, recipes.releases_by_search(
        client, playlists, today=TODAY, **kwargs
    )


def test_the_query_spans_the_window_years():
    client, _ = _run({})
    assert all('year:2025-2026' in q for q in client.queries)
    assert 'artist:"Beth Gibbons"' in client.queries[0]


def test_only_releases_inside_the_window_are_kept():
    _, picked = _run({
        "Beth Gibbons": [
            _track("New One", "Beth Gibbons", "Fresh", "2026-05-01"),
            _track("Old One", "Beth Gibbons", "Ancient", "2019-01-01"),
        ]
    })
    assert [t["name"] for t in picked] == ["New One"]


def test_a_result_credited_to_a_different_artist_is_dropped():
    _, picked = _run({
        "Beth Gibbons": [_track("Not Hers", "Someone Else", "X", "2026-01-01")]
    })
    assert picked == []


def test_accented_names_still_match_their_own_results():
    _, picked = _run({
        "Yanya": [_track("Track", "Nilufer Yanya", "Album", "2026-02-02")]
    })
    assert [t["artist"] for t in picked] == ["Nilüfer Yanya"]


def test_per_artist_caps_the_take_and_one_album_counts_once():
    tracks = [
        _track("A", "Beth Gibbons", "Same Album", "2026-01-01", "alb1"),
        _track("B", "Beth Gibbons", "Same Album", "2026-01-01", "alb1"),
        _track("C", "Beth Gibbons", "Other", "2026-02-01", "alb2"),
        _track("D", "Beth Gibbons", "Third", "2026-03-01", "alb3"),
    ]
    _, picked = _run({"Beth Gibbons": tracks}, per_artist=2)
    assert [t["name"] for t in picked] == ["C", "A"]  # newest first, one/album


def test_reissues_are_skipped_unless_asked_for():
    tracks = [_track("Track", "Beth Gibbons", "Album (2026 Remaster)",
                     "2026-01-01")]
    _, picked = _run({"Beth Gibbons": tracks})
    assert picked == []
    _, kept = _run({"Beth Gibbons": tracks}, skip_reissues=False)
    assert len(kept) == 1


def test_a_failing_search_does_not_sink_the_whole_run():
    class Flaky(SearchClient):
        def search_tracks(self, query, limit=50):
            if "Beth" in query:
                raise RuntimeError("429 somewhere")
            return [_track("Fine", "Nilufer Yanya", "Album", "2026-04-01")]

    client = Flaky({})
    picked = recipes.releases_by_search(
        client, client.my_playlists(), today=TODAY
    )
    assert [t["name"] for t in picked] == ["Fine"]
