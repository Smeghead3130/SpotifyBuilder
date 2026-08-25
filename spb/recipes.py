"""The two playlist recipes, plus the shared helpers they lean on."""

import datetime
import re
import unicodedata

# Spotify release_date has three precisions: "2026", "2026-03", "2026-03-14".
_DATE_FORMATS = {4: "%Y", 7: "%Y-%m", 10: "%Y-%m-%d"}

# Anything whose title says it is a rerun rather than new work.
_REISSUE = re.compile(
    r"\b(remaster(ed)?|anniversary|deluxe|re-?issue|live at|live in|"
    r"karaoke|instrumental version|commentary)\b",
    re.I,
)


def parse_release_date(value):
    """Return a date for any of Spotify's three precisions, or None."""
    if not value:
        return None
    fmt = _DATE_FORMATS.get(len(value))
    if not fmt:
        return None
    try:
        parsed = datetime.datetime.strptime(value, fmt).date()
    except ValueError:
        return None
    # Year- and month-only dates anchor to the start of the period, which is
    # the conservative reading for a "released since X" filter.
    return parsed


def months_ago(months, today=None):
    today = today or datetime.date.today()
    year = today.year
    month = today.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(today.day, 28)
    return datetime.date(year, month, day)


def resolve_playlists(client, selectors):
    """Map names, ids, or open.spotify.com URLs onto the user's playlists."""
    owned = client.my_playlists()
    by_id = {p["id"]: p for p in owned}
    by_name = {}
    for playlist in owned:
        by_name.setdefault(playlist["name"].strip().lower(), playlist)

    resolved = []
    for selector in selectors:
        selector = selector.strip()
        match = re.search(r"playlist[/:]([A-Za-z0-9]+)", selector)
        key = match.group(1) if match else selector
        found = by_id.get(key) or by_name.get(selector.lower())
        if not found:
            known = ", ".join(sorted(p["name"] for p in owned)) or "(none)"
            raise SystemExit(
                "No playlist matched %r.\nYour playlists: %s" % (selector, known)
            )
        resolved.append(found)
    return resolved


def playlist_artists(client, playlist, cache=None):
    """{artist_id: name} for one playlist, cached against its snapshot_id.

    Spotify changes snapshot_id whenever a playlist is edited, so a cached
    entry under the current snapshot is exact and never needs expiring. A
    finished year playlist hits cache forever; the one still being added to
    re-reads itself only once it actually changes.
    """
    snapshot = playlist.get("snapshot_id")
    key = "pl-artists:%s:%s" % (playlist["id"], snapshot) if snapshot else None

    if key and cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return dict(hit)

    artists = {}
    for track in client.playlist_tracks(playlist["id"]):
        for artist in track.get("artists") or []:
            if artist.get("id"):
                artists[artist["id"]] = artist.get("name", "")

    if key and cache is not None:
        cache.set(key, artists)
    return artists


def artists_in_playlists(client, playlists, cache=None):
    """{artist_id: name} across every track of every given playlist."""
    artists = {}
    for playlist in playlists:
        artists.update(playlist_artists(client, playlist, cache))
    return artists


# ---- recipe 1: new releases -----------------------------------------


def new_releases(client, playlists, months=12, per_album=None,
                 skip_reissues=True, cache=None):
    """Tracks from albums/singles released in the window by the seed artists."""
    cutoff = months_ago(months)
    seeds = artists_in_playlists(client, playlists, cache)
    if not seeds:
        raise SystemExit("Those playlists contain no resolvable artists.")

    picked = []
    seen_albums = set()
    for artist_id, artist_name in seeds.items():
        for album in client.artist_albums(artist_id):
            if album["id"] in seen_albums:
                continue
            released = parse_release_date(album.get("release_date"))
            if not released or released < cutoff:
                continue
            if skip_reissues and _REISSUE.search(album.get("name", "")):
                continue
            # `include_groups` still returns compilations the artist merely
            # appears on; require them to be a credited album artist.
            credited = {a.get("id") for a in album.get("artists") or []}
            if artist_id not in credited:
                continue
            seen_albums.add(album["id"])

            tracks = client.album_tracks(album["id"])
            if per_album:
                tracks = tracks[:per_album]
            for track in tracks:
                if track.get("id"):
                    picked.append(
                        {
                            "uri": track["uri"],
                            "name": track["name"],
                            "artist": artist_name,
                            "album": album["name"],
                            "released": album.get("release_date"),
                        }
                    )

    picked.sort(key=lambda t: t["released"] or "", reverse=True)
    return _dedupe(picked)


# ---- recipe 2: discovery --------------------------------------------


def discover(client, exclude_playlists, genres=None, artists_wanted=15, top_n=3):
    """Top tracks from in-genre artists absent from the excluded playlists."""
    known = set(artists_in_playlists(client, exclude_playlists))
    known |= {a["id"] for a in client.followed_artists()}

    if genres:
        pool_genres = [g.strip().lower() for g in genres if g.strip()]
    else:
        pool_genres = _genres_from_taste(client, exclude_playlists)
    if not pool_genres:
        raise SystemExit(
            "Could not infer any genres. Pass --genre explicitly (repeatable)."
        )

    candidates = {}
    for genre in pool_genres:
        # Spotify's related-artists and recommendations endpoints were closed
        # to new apps in Nov 2024, so genre search is how we widen the net.
        for offset in (0, 50):
            for artist in client.search_artists(
                'genre:"%s"' % genre, limit=50, offset=offset
            ):
                if artist["id"] in known or artist["id"] in candidates:
                    continue
                candidates[artist["id"]] = artist

    ranked = sorted(
        candidates.values(), key=lambda a: a.get("popularity", 0), reverse=True
    )[:artists_wanted]

    picked = []
    for artist in ranked:
        for track in client.artist_top_tracks(artist["id"])[:top_n]:
            picked.append(
                {
                    "uri": track["uri"],
                    "name": track["name"],
                    "artist": artist["name"],
                    "album": (track.get("album") or {}).get("name", ""),
                    "released": (track.get("album") or {}).get("release_date", ""),
                }
            )
    return _dedupe(picked), pool_genres


def _genres_from_taste(client, playlists, top_k=6):
    """Rank genres by how often they appear across top artists + seed artists."""
    counts = {}
    pool = list(client.top_artists())
    seed_ids = list(artists_in_playlists(client, playlists))
    pool += client.artists(seed_ids[:150])
    for artist in pool:
        for genre in artist.get("genres") or []:
            counts[genre] = counts.get(genre, 0) + 1
    return [g for g, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:top_k]]


def _dedupe(tracks):
    seen = set()
    out = []
    for track in tracks:
        if track["uri"] in seen:
            continue
        seen.add(track["uri"])
        out.append(track)
    return out


def releases_by_search(client, playlists, months=12, per_artist=3,
                       skip_reissues=True, progress=None, today=None,
                       cache=None, search_ttl=None):
    """New releases by artists you already have, found via track search.

    The discography endpoint (/artists/{id}/albums) is closed to Development
    mode apps, so this asks the search endpoint - which is not - for recent
    tracks credited to each artist, one query per artist.
    """
    today = today or datetime.date.today()
    cutoff = months_ago(months, today)
    years = sorted({cutoff.year, today.year})
    span = str(years[0]) if len(years) == 1 else "%d-%d" % (years[0], years[-1])

    seeds = artists_in_playlists(client, playlists, cache)
    if not seeds:
        raise SystemExit("Those playlists contain no resolvable artists.")

    from .cache import DEFAULT_TTL
    ttl = DEFAULT_TTL if search_ttl is None else search_ttl
    picked = []
    for index, name in enumerate(sorted(set(seeds.values())), start=1):
        if progress:
            progress(index, len(set(seeds.values())), name)
        if not name:
            continue
        query = 'artist:"%s" year:%s' % (name.replace('"', ""), span)
        # Unlike playlists, a search has no snapshot to key on - new music
        # appears constantly - so these entries expire on age.
        key = "search:" + query
        tracks = cache.get(key, ttl=ttl) if cache is not None else None
        if tracks is None:
            try:
                tracks = client.search_tracks(query)
            except Exception:
                continue
            if cache is not None:
                cache.set(key, tracks)

        seen_albums = set()
        taken = 0
        for track in tracks:
            if taken >= per_artist:
                break
            album = track.get("album") or {}
            released = parse_release_date(album.get("release_date"))
            if not released or released < cutoff:
                continue
            if skip_reissues and _REISSUE.search(album.get("name", "")):
                continue
            credited = [a.get("name", "") for a in track.get("artists") or []]
            if not any(_fold_name(c) == _fold_name(name) for c in credited):
                continue
            if album.get("id") in seen_albums:
                continue
            seen_albums.add(album.get("id"))
            taken += 1
            picked.append(
                {
                    "uri": track["uri"],
                    "name": track["name"],
                    "artist": name,
                    "album": album.get("name", ""),
                    "released": album.get("release_date", ""),
                }
            )

    picked.sort(key=lambda t: t["released"] or "", reverse=True)
    return _dedupe(picked)


def _fold_name(name):
    folded = unicodedata.normalize("NFKD", name or "")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", folded.casefold())
