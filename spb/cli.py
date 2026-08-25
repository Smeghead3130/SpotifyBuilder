"""Command line entry point: spb new-releases | discover | playlists."""

import argparse
import datetime
import sys
import time

from . import auth, doctor, profile, recipes
from .cache import Cache
from .client import SpotifyError
from .errors import SpbError
from . import config
from .client import Spotify


def _use_utf8_output():
    """Console output must not die on an artist name.

    Windows terminals default to cp1252, so printing a name like Sigur Ros
    with its real spelling raises UnicodeEncodeError. Replace what the
    terminal cannot show rather than crashing.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _connect(on_rate_limit=None):
    return Spotify(auth.get_access_token(), on_rate_limit=on_rate_limit)


def _cache(args, playlists=None):
    """One cache per run; saved on the way out so a crash cannot corrupt it."""
    cache = Cache(enabled=not getattr(args, "no_cache", False))
    # Caching hangs entirely off snapshot_id. If Spotify stops returning it,
    # say so rather than silently re-reading everything every run.
    if cache.enabled and playlists and not any(
        p.get("snapshot_id") for p in playlists
    ):
        print("Note: Spotify returned no snapshot_id, so playlists cannot be "
              "cached and will be re-read each run.")
    return cache


def _table(tracks):
    """One consistent tracklist layout everywhere, sized to the content."""
    if not tracks:
        return
    width_name = min(max(len(t["name"]) for t in tracks), 44)
    width_artist = min(max(len(t["artist"]) for t in tracks), 30)
    for track in tracks:
        print(
            "  %-*.*s  %-*.*s  %s"
            % (width_name, width_name, track["name"],
               width_artist, width_artist, track["artist"],
               (track.get("released") or "")[:10])
        )


def _emit(tracks, args, client, default_name, description):
    if not tracks:
        print("Nothing matched. Try a wider window or a longer list.")
        return 0

    if args.limit:
        tracks = tracks[: args.limit]

    _table(tracks)
    print("\n%d track(s)." % len(tracks))

    if args.dry_run:
        print("Dry run - nothing written. Re-run without --dry-run to create it.")
        return 0

    name = args.name or default_name
    playlist = client.create_playlist(
        client.me()["id"], name, description, public=args.public
    )
    client.add_tracks(playlist["id"], [t["uri"] for t in tracks])
    print("\nCreated \"%s\"\n  %s"
          % (name, playlist["external_urls"]["spotify"]))
    return 0


def _sources(client, given, flag):
    """Explicit playlists if given, else the 'listened to' ones."""
    if given:
        return recipes.resolve_playlists(client, given)
    found = profile.auto_source_playlists(client.my_playlists())
    if not found:
        raise SpbError(
            "No playlists matching 'listened to' were found, so there is "
            "nothing to work from. Name them explicitly with %s, or run "
            "'spb playlists' to see what you have." % flag
        )
    print("Using: " + ", ".join(p["name"] for p in found) + "\n")
    return found


def cmd_playlists(args):
    client = _connect()
    playlists = client.my_playlists()
    width = min(max((len(p["name"]) for p in playlists), default=10), 44)
    for playlist in playlists:
        print("  %-*.*s  %5d tracks  %s"
              % (width, width, playlist["name"],
                 (playlist.get("tracks") or {}).get("total", 0),
                 playlist["id"]))
    print("\n%d playlist(s)." % len(playlists))
    return 0


class _Progress:
    """A live progress line with an ETA, plus visible rate-limit waits.

    One search per artist over a large library is minutes of work, and a
    silent Retry-After sleep is indistinguishable from a hang.
    """

    def __init__(self):
        self.started = time.time()
        self.waited = 0.0

    def _line(self, text):
        sys.stdout.write("\r\033[K" + text)
        sys.stdout.flush()

    def rate_limited(self, seconds):
        self.waited += seconds
        self._line("  rate limited by Spotify, waiting %ds..." % round(seconds))

    def __call__(self, done, total, name):
        elapsed = time.time() - self.started
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        note = "  (%ds waiting on rate limits)" % round(self.waited) \
            if self.waited >= 1 else ""
        self._line(
            "  %d/%d artists  %s left%s  %-24.24s"
            % (done, total, _mmss(eta), note, name)
        )
        if done == total:
            sys.stdout.write(
                "\r\033[K  %d artists searched in %s%s\n\n"
                % (total, _mmss(elapsed), note)
            )


def _mmss(seconds):
    seconds = int(max(seconds, 0))
    return "%d:%02d" % (seconds // 60, seconds % 60)


def cmd_new_releases(args):
    progress = None if args.quiet else _Progress()
    client = _connect(on_rate_limit=progress.rate_limited if progress else None)
    seeds = _sources(client, args.source, "--source")
    if args.via_discography:
        tracks = recipes.new_releases(
            client,
            seeds,
            months=args.months,
            per_album=args.per_album,
            skip_reissues=not args.include_reissues,
        )
    else:
        cache = _cache(args, seeds)
        tracks = recipes.releases_by_search(
            client,
            seeds,
            months=args.months,
            per_artist=args.per_artist,
            skip_reissues=not args.include_reissues,
            progress=progress,
            cache=cache,
            search_ttl=args.search_ttl * 3600 if args.search_ttl else None,
        )
        cache.save()
        if cache.summary():
            print(cache.summary() + "\n")
    stamp = datetime.date.today().isoformat()
    return _emit(
        tracks,
        args,
        client,
        "New releases - %s" % stamp,
        "Releases from the last %d months by artists in: %s"
        % (args.months, ", ".join(p["name"] for p in seeds)),
    )


def cmd_discover(args):
    client = _connect()
    try:
        client.artist_top_tracks("4Z8W4fKeB5YxbusRsdQVPb")
    except SpotifyError:
        raise SpbError(
            "discover needs /artists/{id}/top-tracks, which Spotify closed to "
            "Development mode apps in 2026.\n\n"
            "Use build instead - ask Claude for an 'Artist - Title' list and:\n"
            "    spb build --from picks.txt --exclude-known\n\n"
            "Run 'spb doctor' to see everything your app can and cannot do."
        )
    excluded = _sources(client, args.exclude, "--exclude")
    tracks, genres = recipes.discover(
        client,
        excluded,
        genres=args.genre,
        artists_wanted=args.artists,
        top_n=args.top,
    )
    print("Genres used: " + ", ".join(genres) + "\n")
    return _emit(
        tracks,
        args,
        client,
        "Discovery - %s" % datetime.date.today().isoformat(),
        "Top %d tracks from %d artists in %s, none already in: %s"
        % (args.top, args.artists, "/".join(genres), ", ".join(
            p["name"] for p in excluded)),
    )


def cmd_login(args):
    if args.client_id:
        saved = config.set_client_id(args.client_id)
        print("Saved client id %s to %s" % (saved, config.config_path()))
    elif not config.get_client_id():
        raise SpbError(
            "Pass --client-id the first time:\n\n"
            "    spb login --client-id YOUR_ID\n\n"
            "Create a free app at https://developer.spotify.com/dashboard, "
            "tick Web API, and add this redirect URI:\n\n"
            "    " + auth.REDIRECT_URI
        )

    client = _connect()
    me = client.me()
    print("Logged in as %s." % (me.get("display_name") or me.get("id")))
    print("Try:  spb doctor")
    return 0


def cmd_clear_cache(args):
    cache = Cache()
    path = cache.path
    cache.clear()
    print("Cleared " + path)
    return 0


def cmd_doctor(args):
    client = _connect()
    rows, ok = doctor.run(client, create_probe=args.write_test)
    doctor.report(rows, ok)
    return 0


def cmd_export(args):
    client = _connect()
    if args.source:
        chosen = recipes.resolve_playlists(client, args.source)
    else:
        chosen = profile.auto_source_playlists(client.my_playlists())
        if not chosen:
            raise SystemExit(
                "No 'listened to' playlists found. Pass --source explicitly."
            )
        print("Auto-selected: " + ", ".join(p["name"] for p in chosen))

    cache = _cache(args, chosen)
    data = profile.build_profile(client, chosen, cache)
    cache.save()
    if cache.summary():
        print(cache.summary())
    profile.write_profile(data, args.out)
    print(
        "Wrote %s - %d playlists, %d artists, %d genres."
        % (
            args.out,
            len(data["playlists"]),
            len(data["artists"]),
            len(data["genre_counts"]),
        )
    )
    top = list(data["genre_counts"].items())[:10]
    if top:
        print("Top genres: " + ", ".join("%s (%d)" % g for g in top))
    return 0


def cmd_build(args):
    client = _connect()
    with open(args.from_file) as fh:
        pairs, skipped = profile.parse_picks(fh.read())
    if skipped:
        print("Ignored %d unparseable line(s):" % len(skipped))
        for line in skipped[:5]:
            print("  " + line.strip())
    if not pairs:
        raise SystemExit("No 'Artist - Title' lines found in " + args.from_file)

    found, missing = profile.resolve_picks(client, pairs)

    if args.exclude_known:
        seeds = _sources(client, args.exclude, "--exclude")
        cache = _cache(args, seeds)
        known = recipes.artists_in_playlists(client, seeds, cache)
        cache.save()
        found, dropped = profile.drop_known_artists(found, known.values())
        if dropped:
            print("Dropped %d pick(s) by artists already in your playlists:"
                  % len(dropped))
            for pick in dropped:
                print("  %s - %s" % (pick["artist"], pick["name"]))
            print()
    if missing:
        print("\nNot found on Spotify (%d):" % len(missing))
        for line in missing:
            print("  " + line)
    print()
    return _emit(
        found,
        args,
        client,
        "Built from picks - %s" % datetime.date.today().isoformat(),
        "Assembled from a curated tracklist.",
    )


def build_parser():
    parser = argparse.ArgumentParser(prog="spb", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--name", help="playlist name (default: dated)")
    shared.add_argument("--limit", type=int, help="cap the track count")
    shared.add_argument("--public", action="store_true", help="make it public")
    shared.add_argument(
        "--dry-run", action="store_true", help="print the tracks, write nothing"
    )
    shared.add_argument(
        "--no-cache", action="store_true",
        help="ignore the cache and re-read everything from Spotify",
    )

    subparsers.add_parser("playlists", help="list your playlists and their ids")

    log = subparsers.add_parser(
        "login", help="save your Spotify client id and authorize once"
    )
    log.add_argument("--client-id", help="from developer.spotify.com/dashboard")

    subparsers.add_parser(
        "clear-cache", help="delete the cached playlist and search data"
    )

    doc = subparsers.add_parser(
        "doctor", help="probe which Spotify endpoints this app can still use"
    )
    doc.add_argument(
        "--write-test", action="store_true",
        help="also create a throwaway playlist to test write access",
    )

    new = subparsers.add_parser(
        "new-releases", parents=[shared], help="recent releases by artists you have"
    )
    new.add_argument(
        "--source", action="append",
        help="seed playlist by name, id, or URL (repeatable); "
             "defaults to your 'listened to' playlists",
    )
    new.add_argument("--months", type=int, default=12, help="window (default 12)")
    new.add_argument(
        "--per-album", type=int, help="cap tracks taken from each album"
    )
    new.add_argument(
        "--per-artist", type=int, default=3,
        help="how many recent tracks to take per artist (default 3)",
    )
    new.add_argument(
        "--via-discography", action="store_true",
        help="use /artists/{id}/albums instead of search; needs catalog "
             "access, which Development mode apps do not have",
    )
    new.add_argument(
        "--quiet", action="store_true", help="no progress line"
    )
    new.add_argument(
        "--search-ttl", type=int, metavar="HOURS",
        help="how long cached searches stay fresh (default 168 = 7 days)",
    )
    new.add_argument(
        "--include-reissues", action="store_true",
        help="keep remasters, anniversary and deluxe editions",
    )

    disc = subparsers.add_parser(
        "discover", parents=[shared], help="in-genre artists you do not have yet"
    )
    disc.add_argument(
        "--exclude", action="append",
        help="playlist whose artists are already known (repeatable); "
             "defaults to your 'listened to' playlists",
    )
    disc.add_argument(
        "--genre", action="append",
        help="genre to mine; inferred from your taste if omitted (repeatable)",
    )
    disc.add_argument("--artists", type=int, default=15, help="how many artists")
    disc.add_argument("--top", type=int, default=3, help="top tracks each")

    exp = subparsers.add_parser(
        "export", help="dump a listening profile as JSON, to share with Claude"
    )
    exp.add_argument(
        "--source", action="append",
        help="playlist to profile; defaults to your 'listened to' playlists",
    )
    exp.add_argument("--out", default="profile.json", help="output path")
    exp.add_argument(
        "--no-cache", action="store_true",
        help="ignore the cache and re-read everything from Spotify",
    )

    bld = subparsers.add_parser(
        "build", parents=[shared], help="create a playlist from an 'Artist - Title' list"
    )
    bld.add_argument(
        "--from", dest="from_file", required=True,
        help="text file of 'Artist - Title' lines",
    )
    bld.add_argument(
        "--exclude-known", action="store_true",
        help="drop picks by artists already in your playlists",
    )
    bld.add_argument(
        "--exclude", action="append",
        help="playlists defining 'already known'; defaults to your "
             "'listened to' playlists",
    )

    return parser


def main(argv=None):
    _use_utf8_output()
    args = build_parser().parse_args(argv)
    handlers = {
        "playlists": cmd_playlists,
        "new-releases": cmd_new_releases,
        "discover": cmd_discover,
        "login": cmd_login,
        "clear-cache": cmd_clear_cache,
        "doctor": cmd_doctor,
        "export": cmd_export,
        "build": cmd_build,
    }
    return handlers[args.command](args)


def run():
    """Entry point: report expected problems as messages, not tracebacks."""
    try:
        return main()
    except SpbError as exc:
        print("\n" + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped. Work done so far is cached.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(run())
