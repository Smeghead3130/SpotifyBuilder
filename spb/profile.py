"""Export a listening profile, and build a playlist from a chosen tracklist.

These two commands exist so the interesting half of the work can happen in a
chat with Claude, which has no route to the Spotify API: `export` writes a
JSON profile you hand over, `build` takes back a plain "Artist - Title" list
and turns it into a real playlist.
"""

import json
import re
import unicodedata

# Matches "2026 - Music I Listened To", "Music I Listened To 2024",
# "songs i listened to in 2023", and similar.
YEAR_PLAYLIST = re.compile(r"listen(ed|ing)?\s+to", re.I)
YEAR_IN_NAME = re.compile(r"(19|20)\d{2}")

# Accepts "Artist - Title", "Artist – Title", "Artist — Title", "Artist / Title".
PICK_LINE = re.compile(r"^\s*(?P<artist>.+?)\s+[-–—/]\s+(?P<title>.+?)\s*$")


def auto_source_playlists(playlists):
    """The user's own year-by-year 'music I listened to' playlists, newest first."""
    hits = [p for p in playlists if YEAR_PLAYLIST.search(p.get("name", ""))]

    def year_of(playlist):
        found = YEAR_IN_NAME.search(playlist.get("name", ""))
        return int(found.group(0)) if found else 0

    return sorted(hits, key=year_of, reverse=True)


def build_profile(client, playlists, cache=None):
    """Everything Claude needs to reason about taste, as plain JSON."""
    seen_artists = {}
    playlist_blocks = []

    from .recipes import playlist_artists

    for playlist in playlists:
        names = playlist_artists(client, playlist, cache)
        seen_artists.update(names)
        playlist_blocks.append(
            {
                "name": playlist["name"],
                "id": playlist["id"],
                "artists": sorted(names.values()),
            }
        )

    # Batch /artists was withdrawn from Development Mode apps in the
    # Feb/Mar 2026 API changes, and it is the only source of genre tags.
    # Without it the profile is still useful - names carry a lot.
    notes = []
    try:
        hydrated = client.artists(list(seen_artists))
    except Exception as exc:
        notes.append("artist genres unavailable: %s" % _short(exc))
        hydrated = [
            {"id": aid, "name": name, "genres": []}
            for aid, name in sorted(seen_artists.items(), key=lambda kv: kv[1])
        ]

    genre_counts = {}
    artist_rows = []
    for artist in hydrated:
        genres = artist.get("genres") or []
        for genre in genres:
            genre_counts[genre] = genre_counts.get(genre, 0) + 1
        artist_rows.append(
            {
                "name": artist.get("name", ""),
                "id": artist.get("id"),
                "genres": genres,
                "popularity": artist.get("popularity"),
            }
        )

    top = []
    for window in ("short_term", "medium_term", "long_term"):
        try:
            top.append(
                {
                    "range": window,
                    "artists": [a.get("name") for a in client.top_artists(window)],
                }
            )
        except Exception as exc:  # a missing scope should not sink the export
            top.append({"range": window, "error": _short(exc)})
            notes.append("top artists (%s) unavailable" % window)

    try:
        followed = sorted(a.get("name", "") for a in client.followed_artists())
    except Exception as exc:
        followed = []
        notes.append("followed artists unavailable: %s" % _short(exc))

    return {
        "notes": notes,
        "playlists": playlist_blocks,
        "artists": sorted(artist_rows, key=lambda a: a["name"].lower()),
        "genre_counts": dict(
            sorted(genre_counts.items(), key=lambda kv: -kv[1])
        ),
        "followed": followed,
        "top_artists": top,
    }


def parse_picks(text):
    """Parse a 'Artist - Title' tracklist. Returns (pairs, skipped_lines)."""
    pairs = []
    skipped = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Tolerate numbered lists: "1. Artist - Title".
        line = re.sub(r"^\s*\d+[.)]\s*", "", line)
        match = PICK_LINE.match(line)
        if match:
            pairs.append((match.group("artist"), match.group("title")))
        else:
            skipped.append(raw)
    return pairs, skipped


def resolve_picks(client, pairs):
    """Look each pair up on Spotify. Returns (found, missing)."""
    found = []
    missing = []
    for artist, title in pairs:
        track = client.find_track(artist, title)
        if track:
            found.append(
                {
                    "uri": track["uri"],
                    "name": track["name"],
                    "artist": ", ".join(
                        a["name"] for a in track.get("artists") or []
                    ),
                    "released": (track.get("album") or {}).get("release_date", ""),
                }
            )
        else:
            missing.append("%s - %s" % (artist, title))
    return found, missing


def _short(exc):
    """First line of an exception, so notes stay readable."""
    return str(exc).splitlines()[0][:200]


def write_profile(profile, path):
    # Windows defaults to cp1252, which cannot hold most artist names with
    # diacritics; the file is JSON, so it must be UTF-8 regardless of locale.
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2, ensure_ascii=False)


def drop_known_artists(picks, known_names):
    """Remove picks whose artist you already have.

    Claude proposes from a partial view of your taste, so the "not already in
    my playlists" rule is enforced here, against the real library.
    """
    known = {_fold(n) for n in known_names}
    kept, dropped = [], []
    for pick in picks:
        # A pick's artist string may carry featured credits; judge the lead.
        lead = re.split(r"\s*(?:,|&| feat\.| featuring| with )\s*",
                        pick["artist"], maxsplit=1)[0]
        if _fold(lead) in known:
            dropped.append(pick)
        else:
            kept.append(pick)
    return kept, dropped


def _fold(name):
    """Compare artist names ignoring case, accents and a leading 'the'."""
    folded = unicodedata.normalize("NFKD", name or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = folded.casefold().strip()
    folded = re.sub(r"^the\s+", "", folded)
    return re.sub(r"[^a-z0-9]+", "", folded)
