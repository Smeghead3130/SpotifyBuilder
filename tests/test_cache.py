"""Playlist caching keyed on snapshot_id, and expiring search caching."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spb import recipes  # noqa: E402
from spb.cache import Cache  # noqa: E402


class CountingClient:
    """Counts how many times each playlist is actually read."""

    def __init__(self):
        self.reads = {}
        self.contents = {
            "p2025": [{"artists": [{"id": "a1", "name": "Radiohead"}]}],
            "p2026": [{"artists": [{"id": "a2", "name": "Djo"}]}],
        }

    def playlist_tracks(self, playlist_id):
        self.reads[playlist_id] = self.reads.get(playlist_id, 0) + 1
        return self.contents[playlist_id]


def _playlists(snapshot_2026="snapA"):
    return [
        {"id": "p2025", "name": "2025", "snapshot_id": "finished"},
        {"id": "p2026", "name": "2026", "snapshot_id": snapshot_2026},
    ]


def test_a_second_run_reads_nothing(tmp_path):
    cache = Cache(path=str(tmp_path / "c.json"))
    client = CountingClient()

    recipes.artists_in_playlists(client, _playlists(), cache)
    assert client.reads == {"p2025": 1, "p2026": 1}

    recipes.artists_in_playlists(client, _playlists(), cache)
    assert client.reads == {"p2025": 1, "p2026": 1}   # no new reads
    assert cache.hits == 2


def test_only_the_edited_playlist_is_re_read(tmp_path):
    """The finished years stay cached; the current year refreshes itself."""
    cache = Cache(path=str(tmp_path / "c.json"))
    client = CountingClient()

    recipes.artists_in_playlists(client, _playlists("snapA"), cache)
    # The user adds a track to the 2026 playlist; Spotify changes its snapshot.
    recipes.artists_in_playlists(client, _playlists("snapB"), cache)

    assert client.reads == {"p2025": 1, "p2026": 2}


def test_the_cache_survives_a_restart(tmp_path):
    path = str(tmp_path / "c.json")
    client = CountingClient()

    first = Cache(path=path)
    recipes.artists_in_playlists(client, _playlists(), first)
    first.save()

    second = Cache(path=path)          # a fresh process
    recipes.artists_in_playlists(client, _playlists(), second)
    assert client.reads == {"p2025": 1, "p2026": 1}
    assert second.hits == 2


def test_no_cache_always_reads(tmp_path):
    cache = Cache(path=str(tmp_path / "c.json"), enabled=False)
    client = CountingClient()
    recipes.artists_in_playlists(client, _playlists(), cache)
    recipes.artists_in_playlists(client, _playlists(), cache)
    assert client.reads == {"p2025": 2, "p2026": 2}


def test_a_playlist_without_a_snapshot_is_not_cached(tmp_path):
    cache = Cache(path=str(tmp_path / "c.json"))
    client = CountingClient()
    bare = [{"id": "p2026", "name": "2026"}]
    recipes.artists_in_playlists(client, bare, cache)
    recipes.artists_in_playlists(client, bare, cache)
    assert client.reads == {"p2026": 2}


def test_search_entries_expire_on_age(tmp_path):
    cache = Cache(path=str(tmp_path / "c.json"))
    cache.set("search:x", ["stale"])
    assert cache.get("search:x", ttl=3600) == ["stale"]

    cache._data["search:x"]["at"] = time.time() - 7200
    assert cache.get("search:x", ttl=3600) is None


def test_a_corrupt_cache_file_is_ignored(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{not json", encoding="utf-8")
    cache = Cache(path=str(path))
    assert cache.get("anything") is None
    cache.set("k", 1)
    cache.save()
    assert Cache(path=str(path)).get("k") == 1


def test_clear_removes_the_file(tmp_path):
    path = tmp_path / "c.json"
    cache = Cache(path=str(path))
    cache.set("k", 1)
    cache.save()
    assert path.exists()
    cache.clear()
    assert not path.exists()
