"""Small persisted settings, so nothing has to be re-typed each session.

The client id is not a secret - it is designed to be visible in browser apps -
so it lives here in plain JSON rather than being re-exported into every new
terminal.
"""

import json
import os

ENV_CLIENT_ID = "SPOTIFY_CLIENT_ID"


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "spb")


def config_path():
    return os.path.join(config_dir(), "config.json")


def load():
    try:
        with open(config_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(settings):
    os.makedirs(config_dir(), exist_ok=True)
    tmp = config_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
    os.replace(tmp, config_path())


def get_client_id():
    """The environment wins, so a one-off override is still possible."""
    return os.environ.get(ENV_CLIENT_ID) or load().get("client_id")


def set_client_id(client_id):
    settings = load()
    settings["client_id"] = client_id.strip()
    save(settings)
    return settings["client_id"]
