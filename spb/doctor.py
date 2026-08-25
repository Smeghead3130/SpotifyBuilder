"""Probe every endpoint the tool relies on and report what this app can do.

Spotify's Feb/Mar 2026 changes withdrew a lot of the Web API from apps in
Development mode, and the failures surface one 403 at a time. This asks the
whole question in one run.
"""

from .client import SpotifyError

# (label, callable, what breaks without it)


def _checks(client, sample_playlist, sample_artist, sample_track_uri):
    return [
        ("GET /me", lambda: client.me(), "everything"),
        ("GET /me/playlists", lambda: client.my_playlists(), "everything"),
        (
            "GET /playlists/{id}/items",
            lambda: client.playlist_tracks(sample_playlist),
            "export, new-releases, discover",
        ),
        (
            "GET /artists (batch)",
            lambda: client.artists([sample_artist]),
            "genre tags in export",
        ),
        (
            "GET /artists/{id}/albums",
            lambda: client.artist_albums(sample_artist),
            "new-releases",
        ),
        (
            "GET /artists/{id}/top-tracks",
            lambda: client.artist_top_tracks(sample_artist),
            "discover",
        ),
        (
            "GET /search (artist)",
            lambda: client.search_artists('genre:"rock"', limit=1),
            "discover",
        ),
        (
            "GET /search (track)",
            lambda: client.find_track("Radiohead", "Creep"),
            "build - the chat workflow",
        ),
        ("GET /me/top/artists", lambda: client.top_artists(cap=1), "genre inference"),
        ("GET /me/following", lambda: client.followed_artists(cap=1), "discover"),
    ]


def run(client, create_probe=False):
    """Returns (rows, ok_labels). Each row is (label, status, detail, breaks)."""
    me = None
    try:
        me = client.me()
    except SpotifyError as exc:
        print("GET /me failed outright - nothing else can work.\n  %s" % exc)
        return [], set()

    playlists = []
    try:
        playlists = client.my_playlists()
    except SpotifyError:
        pass

    sample_playlist = playlists[0]["id"] if playlists else "37i9dQZF1DXcBWIGoYBM5M"
    sample_artist = "4Z8W4fKeB5YxbusRsdQVPb"  # Radiohead
    sample_track = "spotify:track:6b2oQwSGFkzsMtQruIWm2p"

    rows = []
    ok = set()
    for label, call, breaks in _checks(
        client, sample_playlist, sample_artist, sample_track
    ):
        try:
            call()
        except SpotifyError as exc:
            first = str(exc).splitlines()[0]
            code = "403" if " 403 " in first else (
                "404" if " 404 " in first else "ERR"
            )
            rows.append((label, code, first[-90:], breaks))
        except Exception as exc:
            rows.append((label, "ERR", str(exc)[:90], breaks))
        else:
            rows.append((label, "OK", "", breaks))
            ok.add(label)

    if create_probe:
        label = "POST playlist + add items"
        try:
            created = client.create_playlist(
                me["id"], "spb connectivity probe", "Safe to delete.", public=False
            )
            client.add_tracks(created["id"], [sample_track])
            rows.append(
                (label, "OK",
                 "created %s - delete it in Spotify" % created["id"], "build")
            )
            ok.add(label)
        except SpotifyError as exc:
            rows.append((label, "403", str(exc).splitlines()[0][-90:], "build"))

    return rows, ok


def report(rows, ok):
    if not rows:
        return
    width = max(len(r[0]) for r in rows)
    print()
    for label, status, detail, breaks in rows:
        mark = "ok  " if status == "OK" else status.ljust(4)
        print("%s  %-*s  %s" % (mark, width, label, detail))

    broken = sorted({r[3] for r in rows if r[1] != "OK"})
    print()
    if not broken:
        print("Everything this tool needs is available.")
        return
    print("Unavailable, which breaks: " + "; ".join(broken))
    print(
        "\nSpotify withdrew much of the Web API from Development mode apps in\n"
        "the Feb/Mar 2026 changes. Quota Extension moves an app out of it:\n"
        "  https://developer.spotify.com/documentation/web-api/concepts/quota-modes"
    )
