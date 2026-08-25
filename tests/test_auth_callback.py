"""The local redirect listener must ignore everything but the real callback."""

import os
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spb import auth  # noqa: E402


def _hit(path):
    """Returns the status code, or None if the listener already closed.

    Requests made after the real redirect race the server shutdown, so a
    refused connection there is expected rather than a failure.
    """
    try:
        urllib.request.urlopen("http://127.0.0.1:8731" + path, timeout=3).read()
        return 200
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return None


def _listen_in_background(box, timeout=15):
    def run():
        try:
            box["result"] = auth._listen_once(timeout=timeout)
        except Exception as exc:  # surfaced by the assertions below
            box["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.6)
    return thread


def test_favicon_requests_do_not_clobber_the_redirect():
    """Browsers fetch /favicon.ico around the redirect; it has no state."""
    box = {}
    thread = _listen_in_background(box)

    assert _hit("/favicon.ico") == 404
    assert _hit("/callback?code=REALCODE&state=REALSTATE") == 200
    _hit("/favicon.ico")

    thread.join()
    assert "error" not in box, box.get("error")
    assert box["result"]["state"] == ["REALSTATE"]
    assert box["result"]["code"] == ["REALCODE"]


def test_a_bare_callback_without_a_code_is_not_accepted():
    box = {}
    thread = _listen_in_background(box)

    assert _hit("/callback") == 404
    assert _hit("/callback?code=C&state=S") == 200

    thread.join()
    assert box["result"]["code"] == ["C"]


def test_the_first_real_redirect_wins():
    box = {}
    thread = _listen_in_background(box)

    assert _hit("/callback?code=FIRST&state=S1") == 200
    _hit("/callback?code=SECOND&state=S2")

    thread.join()
    assert box["result"]["code"] == ["FIRST"]


def test_an_error_redirect_is_passed_through():
    box = {}
    thread = _listen_in_background(box)

    assert _hit("/callback?error=access_denied&state=S") == 200

    thread.join()
    assert box["result"]["error"] == ["access_denied"]
