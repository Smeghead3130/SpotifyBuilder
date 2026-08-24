"""Authorization Code flow with PKCE, plus on-disk token caching.

PKCE rather than the client-secret flow so the builder can run from a laptop
without a secret sitting on disk. The only thing cached is the token bundle,
under 0600.
"""

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser

import requests

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
REDIRECT_URI = "http://127.0.0.1:8731/callback"

# Read the playlists we diff against, write the playlist we build, and read
# the top artists the discovery recipe derives genres from.
SCOPES = [
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-follow-read",
    "user-top-read",
]


def _token_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "spb", "token.json")


def _save(tokens):
    path = _token_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(tokens, fh)


def _load():
    try:
        with open(_token_path()) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result = None

    def do_GET(self):
        query = urllib.parse.urlparse(self.path).query
        _CallbackHandler.result = urllib.parse.parse_qs(query)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<h2>Authorized. You can close this tab.</h2>")

    def log_message(self, *args):
        pass


def _listen_once(timeout=180):
    server = http.server.HTTPServer(("127.0.0.1", 8731), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.time() + timeout
    while _CallbackHandler.result is None and time.time() < deadline:
        time.sleep(0.2)
    server.shutdown()
    result = _CallbackHandler.result
    _CallbackHandler.result = None
    if result is None:
        raise TimeoutError("timed out waiting for the Spotify redirect")
    return result


def _authorize(client_id):
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    state = secrets.token_urlsafe(16)

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    print("Opening Spotify authorization in your browser.")
    print("If it does not open, visit:\n  " + url)
    webbrowser.open(url)

    returned = _listen_once()
    if "error" in returned:
        raise RuntimeError("Spotify denied authorization: " + returned["error"][0])
    if returned.get("state", [None])[0] != state:
        raise RuntimeError("state mismatch on the Spotify redirect")

    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": returned["code"][0],
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _refresh(client_id, refresh_token):
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
        timeout=30,
    )
    response.raise_for_status()
    tokens = response.json()
    # Spotify does not always return a fresh refresh token; keep the old one.
    tokens.setdefault("refresh_token", refresh_token)
    return tokens


def get_access_token(client_id=None):
    """Return a usable access token, authorizing or refreshing as needed."""
    client_id = client_id or os.environ.get("SPOTIFY_CLIENT_ID")
    if not client_id:
        raise RuntimeError(
            "Set SPOTIFY_CLIENT_ID (from https://developer.spotify.com/dashboard) "
            "and add " + REDIRECT_URI + " as a redirect URI on that app."
        )

    tokens = _load()
    if tokens and tokens.get("expires_at", 0) > time.time() + 60:
        return tokens["access_token"]

    if tokens and tokens.get("refresh_token"):
        try:
            tokens = _refresh(client_id, tokens["refresh_token"])
        except requests.HTTPError:
            tokens = _authorize(client_id)
    else:
        tokens = _authorize(client_id)

    tokens["expires_at"] = time.time() + tokens.get("expires_in", 3600)
    _save(tokens)
    return tokens["access_token"]
