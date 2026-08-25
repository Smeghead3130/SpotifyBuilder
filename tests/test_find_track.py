"""A loose search must not return a track by a different artist."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spb.client import Spotify, _same_artist  # noqa: E402
from test_client_migration import FakeResponse, FakeSession  # noqa: E402


class SearchSession(FakeSession):
    """Strict query finds nothing; the loose one returns `loose`."""

    def __init__(self, loose):
        super().__init__("new")
        self.loose = loose
        self.queries = []

    def request(self, method, url, **kwargs):
        query = (kwargs.get("params") or {}).get("q", "")
        self.queries.append(query)
        if query.startswith("track:"):
            return FakeResponse(200, {"tracks": {"items": []}})
        return FakeResponse(200, {"tracks": {"items": self.loose}})


def _track(name, *artists):
    return {"name": name, "uri": "spotify:track:x",
            "artists": [{"name": a} for a in artists]}


def test_a_loose_hit_by_the_wrong_artist_is_rejected():
    # The real failure: "Hotline TNT - Julia's War" matched Matt Corby.
    session = SearchSession([_track("War To Love - Acoustic", "Matt Corby")])
    assert Spotify("t", session=session).find_track("Hotline TNT",
                                                    "Julia's War") is None


def test_an_unreleased_album_reports_a_miss_rather_than_a_near_name():
    # Cindy Lee's Diamond Jubilee is not on Spotify; "Cindy" by Javier Lara is.
    session = SearchSession([_track("Cindy", "Javier Lara")])
    assert Spotify("t", session=session).find_track("Cindy Lee",
                                                    "Diamond Jubilee") is None


def test_a_loose_hit_by_the_right_artist_is_accepted():
    session = SearchSession([_track("Julia's War", "Hotline TNT")])
    found = Spotify("t", session=session).find_track("Hotline TNT",
                                                     "Julia's War")
    assert found["name"] == "Julia's War"


def test_a_featured_credit_still_counts_as_the_artist():
    session = SearchSession(
        [_track("Right Back to It", "Waxahatchee", "MJ Lenderman")]
    )
    found = Spotify("t", session=session).find_track("Waxahatchee",
                                                     "Right Back to It")
    assert found is not None


def test_same_artist_folds_case_accents_and_punctuation():
    assert _same_artist("Nilüfer Yanya", "Nilufer Yanya")
    assert _same_artist("Fontaines D.C.", "Fontaines DC")
    assert _same_artist("Model/Actriz", "Model Actriz")
    assert not _same_artist("Matt Corby", "Hotline TNT")
    assert not _same_artist("", "Anything")
