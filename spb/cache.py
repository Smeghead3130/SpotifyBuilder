"""A small on-disk cache so repeat runs do not re-read the whole library.

Playlist contents are keyed by Spotify's snapshot_id, which changes whenever
a playlist is edited - so a hit is exact rather than a guess, and no expiry
is needed. Search results have no such marker and expire on age instead.
"""

import json
import os
import time

DEFAULT_TTL = 7 * 24 * 3600


def _cache_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "spb", "cache.json")


class Cache:
    def __init__(self, path=None, enabled=True):
        self.path = path or _cache_path()
        self.enabled = enabled
        self.hits = 0
        self.misses = 0
        self._data = self._load() if enabled else {}
        self._dirty = False

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            # A corrupt or missing cache is not an error; start empty.
            return {}

    def get(self, key, ttl=None):
        if not self.enabled:
            return None
        entry = self._data.get(key)
        if not isinstance(entry, dict) or "value" not in entry:
            self.misses += 1
            return None
        if ttl is not None and time.time() - entry.get("at", 0) > ttl:
            self.misses += 1
            return None
        self.hits += 1
        return entry["value"]

    def set(self, key, value):
        if not self.enabled:
            return
        self._data[key] = {"at": time.time(), "value": value}
        self._dirty = True

    def save(self):
        if not self.enabled or not self._dirty:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh)
        os.replace(tmp, self.path)   # never leave a half-written cache
        self._dirty = False

    def clear(self):
        self._data = {}
        self._dirty = True
        self.save()
        try:
            os.remove(self.path)
        except OSError:
            pass

    def summary(self):
        total = self.hits + self.misses
        if not self.enabled or not total:
            return ""
        return "cache: %d hit(s), %d miss(es)" % (self.hits, self.misses)
