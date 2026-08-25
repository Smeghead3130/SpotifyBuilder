# spb — Spotify playlist builder

Build Spotify playlists from rules, or from a tracklist you worked out with
Claude. Reads your library, filters against what you already own, writes a
real playlist.

## Quickstart

```bash
pip install -r requirements.txt
spb login --client-id YOUR_CLIENT_ID     # once, ever
spb doctor                                # what your app can do
```

On Windows, use `.\spb.ps1` instead of `spb` — it finds Python for you:

```powershell
.\spb.ps1 login --client-id YOUR_CLIENT_ID
.\spb.ps1 doctor
```

Getting a client id takes two minutes and is free:

1. <https://developer.spotify.com/dashboard> → **Create app**
2. Name it anything, tick **Web API**
3. Redirect URI — paste exactly, then click **Add**:
   `http://127.0.0.1:8731/callback`
4. Copy the **Client ID** (ignore the secret; this uses PKCE)

`spb login` opens a browser once. After that the token is cached at
`~/.config/spb/` and refreshes itself.

## The commands

| Command | What it does |
|---|---|
| `spb playlists` | your playlists and their ids |
| `spb doctor` | probe which Spotify endpoints your app can use |
| `spb new-releases` | recent releases by artists you already have |
| `spb build --from picks.txt` | make a playlist from an `Artist - Title` list |
| `spb export` | dump your library as JSON, to hand to Claude |
| `spb clear-cache` | throw away cached playlist and search data |

Every command that writes takes `--dry-run` (show it, write nothing),
`--name`, `--limit` and `--public`.

Playlists are found by name, id, or URL via `--source` / `--exclude`. Given
none, `spb` uses playlists whose names contain "listened to", newest first.

### Recent releases by artists you have

```bash
spb new-releases --months 12 --per-artist 2 --dry-run
```

The first run over a large library takes several minutes — it is one search
per artist — and shows progress with an ETA. Later runs are near-instant.

### A playlist from a tracklist

```bash
spb build --from picks.txt --exclude-known --name "Claude picks"
```

`picks.txt` is one `Artist - Title` per line; `#` comments, numbered lists and
en/em dashes are all fine. `--exclude-known` drops anything by an artist
already in your playlists — which is how "artists I don't already have" is
enforced, against your real library rather than a guess.

### Working with Claude

Claude cannot reach the Spotify API, so the split is: your machine talks to
Spotify, Claude does the thinking.

```bash
spb export            # writes profile.json
```

Hand `profile.json` to Claude, ask for what you want, save the reply as
`picks.txt`, then `spb build`. See `picks.txt` and `picks-recent.txt` in this
repo for worked examples.

## What a Development mode app can do

Spotify's Feb/Mar 2026 changes withdrew most catalog access from
self-registered apps. Measured with `spb doctor`:

| Endpoint | State | Used by |
|---|---|---|
| `/me`, `/me/playlists` | works | everything |
| `/playlists/{id}/items` (your own) | works | export, build |
| `/search` (artist and track) | works | build, new-releases |
| `/me/top/artists`, `/me/following` | works | genre inference |
| `/artists` (batch) | **blocked** | genre tags in export |
| `/artists/{id}/albums` | **blocked** | new-releases — rebuilt on search |
| `/artists/{id}/top-tracks` | **blocked** | discover |

So `export`, `build` and `new-releases` work. `discover` does not, and says so
rather than failing obscurely.

Two traps: reading a playlist you do not own returns 403 by design, and
blocked catalog endpoints report a misleading 400 "Invalid limit" rather than
a 403 — that means "not allowed", not "bad parameter".

A [Quota Extension](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
moves an app out of Development mode and restores the blocked endpoints.

## Caching

Playlist contents are cached under Spotify's `snapshot_id`, which changes
whenever a playlist is edited — so a hit is exact and never expires. Finished
year playlists are read once ever; the year you are still adding to re-reads
itself only when it actually changes, and nothing else does.

Searches have no such marker, so they expire after 7 days
(`--search-ttl HOURS`). `--no-cache` skips the cache for one run;
`spb clear-cache` discards it.

## Files it writes

| Path | What |
|---|---|
| `~/.config/spb/config.json` | your client id |
| `~/.config/spb/token.json` | the login token, mode 0600 |
| `~/.config/spb/cache.json` | cached playlists and searches |
| `./profile.json` | only when you run `export` |

## Tests

```bash
python -m pytest tests -q
```

65 tests, all against fakes, so no credentials or network are needed. They
cover the date window, reissue and wrong-artist filtering, the exclusion set,
snapshot-keyed caching, the OAuth callback listener, cp1252 encoding, and the
CLI's own error handling.
