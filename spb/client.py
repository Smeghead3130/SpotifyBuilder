"""Thin Spotify Web API client: pagination, rate-limit backoff, batching."""

import re
import time
import unicodedata

import requests

API = "https://api.spotify.com/v1"


def _same_artist(a, b):
    """Compare artist names ignoring case, accents and punctuation."""
    def fold(name):
        folded = unicodedata.normalize("NFKD", name or "")
        folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
        return re.sub(r"[^a-z0-9]+", "", folded.casefold())

    left, right = fold(a), fold(b)
    if not left or not right:
        return False
    # One may carry a suffix the other lacks, e.g. "Waxahatchee" against
    # "Waxahatchee, MJ Lenderman" once Spotify splits the credit.
    return left == right or left.startswith(right) or right.startswith(left)


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
                message = "%s %s -> %s %s" % (
                    method, url, response.status_code, response.text[:400],
                )
                if response.status_code == 403:
                    message += (
                        "\n\nA 403 here usually means the app is in Development "
                        "mode and Spotify is refusing this endpoint, or the "
                        "playlist is not yours. Check the app at "
                        "https://developer.spotify.com/dashboard."
                    )
                if response.status_code == 401:
                    message += (
                        "\n\nA 401 means the saved login has expired or lacks a "
                        "scope. Delete ~/.config/spb/token.json and run again to "
                        "re-authorize."
                    )
                raise SpotifyError(message)
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
        """Full track objects for a playlist, skipping local files and podcasts.

        The 9 March 2026 API migration replaced /playlists/{id}/tracks with
        /playlists/{id}/items and renamed the per-entry "track" key to "item".
        The old path now 403s for Development Mode apps. Try the new one and
        fall back, so this keeps working either side of the migration.
        """
        out = []
        for entry in self._playlist_entries(playlist_id):
            # "item" post-migration, "track" before it.
            track = entry.get("item") or entry.get("track") or {}
            if track.get("id"):
                out.append(track)
        return out

    def _playlist_entries(self, playlist_id):
        try:
            return list(
                self.paginate("/playlists/%s/items" % playlist_id, limit=100)
            )
        except SpotifyError as exc:
            if " 404 " not in str(exc):
                raise
            return list(
                self.paginate("/playlists/%s/tracks" % playlist_id, limit=100)
            )

    def artists(self, artist_ids):
        """Hydrate artist objects (for genres/popularity) in batches of 50."""
        ids = list(dict.fromkeys(artist_ids))
        out = []
        for start in range(0, len(ids), 50):
            chunk = ids[start : start + 50]
            out.extend(self.get("/artists", ids=",".join(chunk)).get("artists") or [])
        return out

    # Development mode apps have no catalog access to this endpoint since the
    # 2026 changes. It reports that as 400 "Invalid limit" rather than 403,
    # which is misleading - no page size makes it work.
    ALBUM_PAGE = 20

    def artist_albums(self, artist_id, groups="album,single"):
        return list(
            self.paginate(
                "/artists/%s/albums" % artist_id,
                limit=self.ALBUM_PAGE,
                include_groups=groups,
            )
        )

    def album_tracks(self, album_id):
        return list(self.paginate("/albums/%s/tracks" % album_id, limit=50))

    def artist_top_tracks(self, artist_id, market=None):
        params = {"market": market} if market else {}
        return self.get(
            "/artists/%s/top-tracks" % artist_id, **params
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

    def search_tracks(self, query, limit=50):
        page = self.get("/search", q=query, type="track", limit=limit)
        return (page.get("tracks") or {}).get("items") or []

    def search_artists(self, query, limit=50, offset=0):
        page = self.get(
            "/search", q=query, type="artist", limit=limit, offset=offset
        )
        return (page.get("artists") or {}).get("items") or []

    def create_playlist(self, user_id, name, description="", public=False):
        """Create a playlist for the current user.

        The 2026 migration moved creation to /me/playlists; the old
        /users/{id}/playlists path 403s for Development mode apps.
        """
        body = {"name": name, "description": description, "public": public}
        try:
            return self.post("/me/playlists", body)
        except SpotifyError as exc:
            first = str(exc).splitlines()[0]
            if " 404 " not in first and " 405 " not in first:
                raise
            return self.post("/users/%s/playlists" % user_id, body)

    def add_tracks(self, playlist_id, uris):
        """Add tracks in batches of 100, via the post-migration /items path."""
        for start in range(0, len(uris), 100):
            batch = {"uris": uris[start : start + 100]}
            try:
                self.post("/playlists/%s/items" % playlist_id, batch)
            except SpotifyError as exc:
                if " 404 " not in str(exc):
                    raise
                self.post("/playlists/%s/tracks" % playlist_id, batch)

    def find_track(self, artist, title, market=None):
        """Resolve an 'artist / title' pair to a track URI. None if no match."""
        query = 'track:"%s" artist:"%s"' % (title.replace('"', ""),
                                            artist.replace('"', ""))
        page = self.get("/search", q=query, type="track", limit=5)
        items = (page.get("tracks") or {}).get("items") or []
        if items:
            return items[0]

        # Fall back to a loose query; the quoted field search misses remixes,
        # featured credits and punctuation differences. But a loose search
        # will happily return something by a completely different artist, so
        # only accept a result that actually credits the artist asked for.
        page = self.get(
            "/search", q="%s %s" % (artist, title), type="track", limit=5,
        )
        for track in (page.get("tracks") or {}).get("items") or []:
            credited = [a.get("name", "") for a in track.get("artists") or []]
            if any(_same_artist(name, artist) for name in credited):
                return track
        return None
