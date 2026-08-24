"""Thin Spotify Web API client: pagination, rate-limit backoff, batching."""

import time

import requests

API = "https://api.spotify.com/v1"


class SpotifyError(RuntimeError):
    pass


class Spotify:
    def __init__(self, access_token, session=None):
        self.session = session or requests.Session()
        self.session.headers["Authorization"] = "Bearer " + access_token

    # ---- transport -------------------------------------------------

    def _request(self, method, path, **kwargs):
        url = path if path.startswith("http") else API + path
        for attempt in range(6):
            response = self.session.request(method, url, timeout=30, **kwargs)
            if response.status_code == 429:
                # Retry-After is in seconds and Spotify means it.
                time.sleep(float(response.headers.get("Retry-After", 2)) + 0.5)
                continue
            if response.status_code >= 500 and attempt < 5:
                time.sleep(2**attempt)
                continue
            if response.status_code == 204 or not response.content:
                return {}
            if not response.ok:
                raise SpotifyError(
                    "%s %s -> %s %s"
                    % (method, url, response.status_code, response.text[:400])
                )
            return response.json()
        raise SpotifyError("gave up after repeated rate limiting on " + url)

    def get(self, path, **params):
        return self._request("GET", path, params=params or None)

    def post(self, path, payload):
        return self._request("POST", path, json=payload)

    def paginate(self, path, limit=50, cap=None, **params):
        """Yield items across a paged endpoint, stopping after `cap` items."""
        params = dict(params, limit=limit)
        page = self.get(path, **params)
        seen = 0
        while page:
            # Some endpoints nest the page one level down (search does).
            items = page.get("items", [])
            for item in items:
                yield item
                seen += 1
                if cap and seen >= cap:
                    return
            nxt = page.get("next")
            if not nxt:
                return
            page = self.get(nxt)

    # ---- endpoints -------------------------------------------------

    def me(self):
        return self.get("/me")

    def my_playlists(self):
        return list(self.paginate("/me/playlists"))

    def playlist_tracks(self, playlist_id):
        """Full track objects for a playlist, skipping local files and podcasts."""
        fields = (
            "next,items(track(id,name,artists(id,name),"
            "album(id,name,release_date)))"
        )
        out = []
        for item in self.paginate(
            "/playlists/%s/tracks" % playlist_id, limit=100, fields=fields
        ):
            track = item.get("track") or {}
            if track.get("id"):
                out.append(track)
        return out

    def artists(self, artist_ids):
        """Hydrate artist objects (for genres/popularity) in batches of 50."""
        ids = list(dict.fromkeys(artist_ids))
        out = []
        for start in range(0, len(ids), 50):
            chunk = ids[start : start + 50]
            out.extend(self.get("/artists", ids=",".join(chunk)).get("artists") or [])
        return out

    def artist_albums(self, artist_id, groups="album,single"):
        return list(
            self.paginate(
                "/artists/%s/albums" % artist_id,
                limit=50,
                include_groups=groups,
                market="from_token",
            )
        )

    def album_tracks(self, album_id):
        return list(self.paginate("/albums/%s/tracks" % album_id, limit=50))

    def artist_top_tracks(self, artist_id, market="from_token"):
        return self.get(
            "/artists/%s/top-tracks" % artist_id, market=market
        ).get("tracks") or []

    def top_artists(self, time_range="medium_term", cap=50):
        return list(
            self.paginate("/me/top/artists", cap=cap, time_range=time_range)
        )

    def followed_artists(self, cap=None):
        """/me/following is cursor-paged and nests under `artists`."""
        out = []
        page = self.get("/me/following", type="artist", limit=50).get("artists") or {}
        while page:
            out.extend(page.get("items", []))
            if cap and len(out) >= cap:
                return out[:cap]
            nxt = page.get("next")
            if not nxt:
                return out
            page = self.get(nxt).get("artists") or {}
        return out

    def search_artists(self, query, limit=50, offset=0):
        page = self.get(
            "/search", q=query, type="artist", limit=limit, offset=offset
        )
        return (page.get("artists") or {}).get("items") or []

    def create_playlist(self, user_id, name, description="", public=False):
        return self.post(
            "/users/%s/playlists" % user_id,
            {"name": name, "description": description, "public": public},
        )

    def add_tracks(self, playlist_id, uris):
        for start in range(0, len(uris), 100):
            self.post(
                "/playlists/%s/tracks" % playlist_id,
                {"uris": uris[start : start + 100]},
            )

    def find_track(self, artist, title, market="from_token"):
        """Resolve an 'artist / title' pair to a track URI. None if no match."""
        query = 'track:"%s" artist:"%s"' % (title.replace('"', ""),
                                            artist.replace('"', ""))
        page = self.get("/search", q=query, type="track", limit=5, market=market)
        items = (page.get("tracks") or {}).get("items") or []
        if not items:
            # Fall back to a loose query; quoted field search misses remixes,
            # featured credits and punctuation differences.
            page = self.get(
                "/search", q="%s %s" % (artist, title), type="track",
                limit=5, market=market,
            )
            items = (page.get("tracks") or {}).get("items") or []
        return items[0] if items else None
