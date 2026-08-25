"""Artist names with diacritics must survive a cp1252 Windows console."""

import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spb import profile  # noqa: E402

NAME = "Dvořák"  # U+0159 is the character that crashed on Windows


def test_profile_is_written_as_utf8_regardless_of_locale():
    path = os.path.join(tempfile.mkdtemp(), "profile.json")
    profile.write_profile({"artists": [{"name": NAME}]}, path)
    with open(path, encoding="utf-8") as fh:
        assert json.load(fh)["artists"][0]["name"] == NAME


def test_a_cp1252_stream_really_does_reject_the_name():
    """Guards the premise: without the fix this genuinely raises."""
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    try:
        stream.write(NAME)
        stream.flush()
    except UnicodeEncodeError:
        return
    raise AssertionError("expected cp1252 to reject U+0159")


def test_reconfigured_output_replaces_instead_of_crashing():
    from spb.cli import _use_utf8_output

    original = sys.stdout
    sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    try:
        _use_utf8_output()
        print(NAME)  # must not raise
        sys.stdout.flush()
    finally:
        sys.stdout = original
