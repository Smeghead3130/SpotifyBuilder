# spb — Spotify playlist builder

A small CLI that builds playlists from rules, using the Spotify Web API
directly. Two recipes to start with:

- **new-releases** — everything released in the last N months by artists that
  appear in playlists you name.
- **discover** — artists you *don't* already have, in genres drawn from your
  taste, represented by their top few tracks.

## Why not the Spotify connector

The Claude Spotify connector exposes three tools: a natural-language search
capped at five results, a `create_playlist` that takes a *sentence* and lets
Spotify's own engine choose the tracks, and "what's playing". It cannot read
the contents of a playlist, so neither recipe above is expressible — the first
needs the artist list out of a playlist, the second needs a set difference
against one. The Web API has all of it, hence this.

## Setup

1. Create an app at <https://developer.spotify.com/dashboard> (free).
2. Add `http://127.0.0.1:8731/callback` to that app's **Redirect URIs**.
3. Export the client ID (no secret needed — this uses PKCE):

   ```bash
   export SPOTIFY_CLIENT_ID=xxxxxxxxxxxxxxxxxxxx
   pip install -r requirements.txt
   ```

The first command you run opens a browser once to authorize. The token bundle
is cached at `~/.config/spb/token.json` (mode 0600) and refreshed silently
after that.

## Usage

```bash
python -m spb.cli playlists          # names + ids of everything you own
```

### Recipe 1 — new releases from artists in a playlist

> *"New released albums of artists I have added to this playlist, released in
> the last 12 months."*

```bash
python -m spb.cli new-releases --source "2026 - Music I Listened To" --months 12
```

Seed playlists are given by name, id, or `open.spotify.com` URL, and `--source`
repeats. Useful flags:

| Flag | Effect |
|---|---|
| `--months N` | release window, default 12 |
| `--per-album N` | take only the first N tracks of each album |
| `--include-reissues` | keep remasters, deluxe and anniversary editions (dropped by default) |
| `--dry-run` | print the tracks, write nothing |
| `--limit N` | cap the final playlist |
| `--name` / `--public` | name it yourself / make it public |

Filtering notes: albums where the seed artist is only a *featured* credit on a
compilation are dropped. Spotify's `release_date` comes at year, month, or day
precision; the coarse ones anchor to the start of the period, so a `2026`-only
album counts as 2026-01-01.

### Recipe 2 — artists you don't have yet

> *"Artists that are not in my playlists as defined by X, within genres I may
> like — play their top few songs."*

```bash
python -m spb.cli discover --exclude "2026 - Music I Listened To" \
                           --exclude Discovery \
                           --artists 15 --top 3
```

Everything appearing in the `--exclude` playlists, plus every artist you
follow, is removed from the candidate pool. Genres are inferred from your top
artists and the seed playlists unless you pass `--genre` (repeatable):

```bash
python -m spb.cli discover --exclude Discovery --genre shoegaze --genre "dream pop"
```

**A real constraint:** Spotify closed `/recommendations` and
`/artists/{id}/related-artists` to new apps in November 2024. "Genres you may
like" therefore works by ranking the genre tags on your top artists and then
mining `search?q=genre:"..."`, ordered by artist popularity. It's a coarser
instrument than the old recommender — expect to steer it with `--genre`.

## Tests

```bash
python -m pytest tests -q
```

Ten tests covering date precision, the month window across year boundaries,
reissue and uncredited-compilation filtering, the exclusion set, and playlist
resolution — all against a fake client, so no credentials are needed.
