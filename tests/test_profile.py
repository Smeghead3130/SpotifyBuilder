import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spb import profile  # noqa: E402
from test_recipes import FakeClient  # noqa: E402


def test_auto_source_matches_listened_to_playlists_newest_first():
    playlists = [
        {"id": "a", "name": "2024 - Music I Listened To"},
        {"id": "b", "name": "Discovery"},
        {"id": "c", "name": "2026 - Music I Listened To"},
        {"id": "d", "name": "songs i listened to in 2025"},
        {"id": "e", "name": "Hampus is a Tool"},
    ]
    got = profile.auto_source_playlists(playlists)
    assert [p["id"] for p in got] == ["c", "d", "a"]


def test_auto_source_returns_nothing_when_no_playlist_matches():
    assert profile.auto_source_playlists([{"id": "x", "name": "Chill"}]) == []


def test_parse_picks_handles_dashes_numbering_and_comments():
    text = """
    # a comment
    1. Ada - First Song
    Bo – Second Song
    Cy — Third Song
    Dee / Fourth Song
    nonsense line without a separator
    """
    pairs, skipped = profile.parse_picks(text)
    assert pairs == [
        ("Ada", "First Song"),
        ("Bo", "Second Song"),
        ("Cy", "Third Song"),
        ("Dee", "Fourth Song"),
    ]
    assert len(skipped) == 1


def test_resolve_picks_separates_hits_from_misses():
    class Client(FakeClient):
        def find_track(self, artist, title, market="from_token"):
            if artist == "Ghost":
                return None
            return {
                "uri": "spotify:track:%s" % title.replace(" ", ""),
                "name": title,
                "artists": [{"name": artist}],
                "album": {"release_date": "2026-01-01"},
            }

    found, missing = profile.resolve_picks(
        Client(), [("Ada", "Real Song"), ("Ghost", "Nope")]
    )
    assert [t["name"] for t in found] == ["Real Song"]
    assert missing == ["Ghost - Nope"]


def test_build_profile_collects_artists_genres_and_counts():
    client = FakeClient()
    data = profile.build_profile(client, [client.playlists[0]])
    assert data["playlists"][0]["name"] == "Core"
    assert sorted(data["playlists"][0]["artists"]) == ["Ada", "Bo"]
    assert data["genre_counts"]["shoegaze"] == 2
    assert data["followed"] == ["Followed"]
