"""Command line entry point: spb new-releases | discover | playlists."""

import argparse
import datetime
import sys

from . import auth, recipes
from .client import Spotify


def _connect():
    return Spotify(auth.get_access_token())


def _emit(tracks, args, client, default_name, description):
    if not tracks:
        print("Nothing matched. Try widening the window or the genre list.")
        return 0

    if args.limit:
        tracks = tracks[: args.limit]

    for track in tracks:
        print(
            "%-38.38s  %-28.28s  %s"
            % (track["name"], track["artist"], track.get("released", ""))
        )
    print("\n%d track(s)." % len(tracks))

    if args.dry_run:
        print("Dry run - nothing written to Spotify.")
        return 0

    name = args.name or default_name
    playlist = client.create_playlist(
        client.me()["id"], name, description, public=args.public
    )
    client.add_tracks(playlist["id"], [t["uri"] for t in tracks])
    print("Created: " + playlist["external_urls"]["spotify"])
    return 0


def cmd_playlists(args):
    client = _connect()
    for playlist in client.my_playlists():
        print("%-40.40s %s  (%d tracks)"
              % (playlist["name"], playlist["id"], playlist["tracks"]["total"]))
    return 0


def cmd_new_releases(args):
    client = _connect()
    seeds = recipes.resolve_playlists(client, args.source)
    tracks = recipes.new_releases(
        client,
        seeds,
        months=args.months,
        per_album=args.per_album,
        skip_reissues=not args.include_reissues,
    )
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
    excluded = recipes.resolve_playlists(client, args.exclude)
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

    subparsers.add_parser("playlists", help="list your playlists and their ids")

    new = subparsers.add_parser(
        "new-releases", parents=[shared], help="recent releases by artists you have"
    )
    new.add_argument(
        "--source", action="append", required=True,
        help="seed playlist by name, id, or URL (repeatable)",
    )
    new.add_argument("--months", type=int, default=12, help="window (default 12)")
    new.add_argument(
        "--per-album", type=int, help="cap tracks taken from each album"
    )
    new.add_argument(
        "--include-reissues", action="store_true",
        help="keep remasters, anniversary and deluxe editions",
    )

    disc = subparsers.add_parser(
        "discover", parents=[shared], help="in-genre artists you do not have yet"
    )
    disc.add_argument(
        "--exclude", action="append", required=True,
        help="playlist whose artists are already known (repeatable)",
    )
    disc.add_argument(
        "--genre", action="append",
        help="genre to mine; inferred from your taste if omitted (repeatable)",
    )
    disc.add_argument("--artists", type=int, default=15, help="how many artists")
    disc.add_argument("--top", type=int, default=3, help="top tracks each")

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    handlers = {
        "playlists": cmd_playlists,
        "new-releases": cmd_new_releases,
        "discover": cmd_discover,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
