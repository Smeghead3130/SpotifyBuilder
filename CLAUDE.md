# Notes for Claude working in this repo

A CLI that builds Spotify playlists. Read `README.md` for the commands; this
file is the context that is expensive to rediscover.

## How to run it

```bash
spb <command>            # or .\spb.ps1 <command> on Windows, or python -m spb
```

The client id and token are already saved under `~/.config/spb/`. If a command
says no client id is saved, the user needs to run `spb login --client-id ...`
with an id from developer.spotify.com/dashboard — do not guess one.

Run `spb doctor` before assuming an endpoint works. Its output is the ground
truth for that machine, and it takes seconds.

## What Spotify blocks, and why it matters

The app is in **Development mode**, which Spotify gutted in Feb/Mar 2026.
Blocked: batch `/artists` (so no genre tags), `/artists/{id}/albums` (no
discographies), `/artists/{id}/top-tracks`. Working: `/me/*`, playlist read
and write on the user's own playlists, and `/search`.

Consequences worth remembering:

- A blocked catalog endpoint returns **400 "Invalid limit"**, not 403. That
  message means "not allowed", not "bad parameter". Do not tune the page size.
- Reading a playlist the user does not own returns 403 by design.
- `new-releases` was rebuilt on `/search` because discographies are gone. It
  is one request per artist, so a full run over ~1350 artists takes several
  minutes. Cached afterwards.
- `discover` cannot work at all and says so.

## The workflow that works

1. `spb export` → `profile.json`, the user's full artist list.
2. Read it, pick tracks, write `picks.txt` as `Artist - Title` per line.
3. `spb build --from picks.txt --exclude-known --dry-run`, then without
   `--dry-run`.

`--exclude-known` is what enforces "artists I don't already have", against the
real library. Over-supply picks by ~30%: a third typically get dropped as
already owned.

**Always `--dry-run` first.** A wrong track in a real playlist has to be
deleted by hand.

## What is known about this user's taste

Confirmed in their library (each one was dropped by `--exclude-known`, so this
is measured, not guessed):

Radiohead, Djo, My Morning Jacket, The Last Dinner Party, Alex Warren,
Unknown Mortal Orchestra, Crumb, Pond, Nation of Language, Big Thief,
Kevin Morby, Wet Leg, Squid, Hozier, Noah Kahan, Gigi Perez, The Cure,
Perfume Genius, Geese, Lorde, HAIM, Matt Corby, Blood Orange.

Shape: melodic, guitar-forward, atmospheric rock with a psych streak, plus an
appetite for current buzzy acts. Eight playlists named "<year> - Music I
Listened To", 2016 to 2026, ~1350 artists.

Saturated — do not lead with these: psych-pop, current British indie.
Room to work with: early-90s British art rock (Talk Talk, Bark Psychosis,
Doves, Elbow), reverb-heavy americana.

Prefer `profile.json` over this list. This is 23 artists; that file is all of
them.

## Conventions

- Tests use fakes, never the network: `python -m pytest tests -q`.
- `python -m flake8 .` must be clean.
- Anything the user can act on raises `SpbError`, which prints as a message
  with the next command rather than a traceback. Keep it that way.
