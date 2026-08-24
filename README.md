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

Spotify won't let a random program touch your account. You have to register
the program with them once and get an ID for it. It's free, takes about two
minutes, and you never have to do it again.

1. Go to <https://developer.spotify.com/dashboard> and log in with your normal
   Spotify account.
2. Click **Create app**. Name and description can be anything ("spb" is fine).
3. In the **Redirect URI** box, paste exactly:
   `http://127.0.0.1:8731/callback` — then click **Add**.
   *(This is the address on your own computer that Spotify sends you back to
   after you approve. Nothing is published anywhere.)*
4. Save. On the app's page, copy the **Client ID** — a long string of letters
   and numbers. There is also a Client Secret; you do not need it.
5. In a terminal:

   ```bash
   pip install -r requirements.txt
   export SPOTIFY_CLIENT_ID=paste_the_client_id_here
   ```

The first command you run pops open a browser asking you to approve access to
your own account. Approve it once. After that a login token is saved to
`~/.config/spb/token.json` (readable only by you) and renewed automatically,
so you never see that screen again.

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

## Using it through a chat with Claude

Claude has no network route to the Spotify API — the connector can't read
playlists, and a sandboxed session is firewalled off from `api.spotify.com`
outright. So the pattern is: **your machine talks to Spotify, Claude does the
thinking in between.**

```bash
python -m spb.cli export
```

That finds your "Music I Listened To <year>" playlists automatically, and
writes `profile.json` — every artist in them, each artist's genre tags, the
ranked genre counts, your followed artists, and your top artists over three
time windows. No listening data leaves your machine unless you send the file.

Hand that file to Claude and ask for whatever you actually want:

> *"Here's my profile. Find me artists in the genres I lean on that I haven't
> heard, skew toward the last few years, nothing too mainstream — give me 30
> tracks."*

Claude answers with a plain list:

```
Duster - Constellations
Hovvdy - Runner
...
```

Save it as `picks.txt` and push it to Spotify:

```bash
python -m spb.cli build --from picks.txt --name "Claude picks"
```

`build` looks each line up on Spotify, tells you which ones it couldn't find,
and creates the playlist. `Artist - Title` per line; en/em dashes, slashes,
numbered lists and `#` comments are all tolerated.

The two rule-based recipes above stay useful for the things that are pure
bookkeeping — "what came out this year by people I already listen to" needs
no taste, just an API. Use the chat loop for the judgement calls.

## Tests

```bash
python -m pytest tests -q
```

Fifteen tests covering date precision, the month window across year
boundaries, reissue and uncredited-compilation filtering, the exclusion set,
playlist resolution, "listened to" auto-detection, and tracklist parsing —
all against a fake client, so no credentials are needed.

Worth being straight about: the tests exercise the *logic*, using a stand-in
for Spotify. Nothing in `auth.py` or `client.py` has run against the real
Spotify API yet, because the machine this was written on can't reach it. The
filtering and parsing are verified; the network and login paths are not.
Expect a rough edge on first run and send the error text.
