"""Short local trail of command codes for diagnosing silent failures. No payloads or paths."""

import re
import time

from .build_profile import profile_root

LIMIT = 256 * 1024
_SAFE = re.compile(r"[^A-Za-z0-9_.:=-]+")
_FOLDERS = re.compile(r"(?:[^\s\\/]*[\\/])+")


def write(event, code=""):
    """Best effort: logging never affects the application."""
    try:
        path = profile_root() / "diagnostics.log"
        if path.exists() and path.stat().st_size > LIMIT:
            path.replace(path.with_suffix(".old.log"))
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with path.open("a", encoding="ascii", errors="replace") as stream:
            stream.write(
                f"{stamp} {_SAFE.sub('_', event)[:60]} {_SAFE.sub('_', str(code))[:120]}\n"
            )
    except (OSError, RuntimeError, KeyError):
        pass


def qt_message(message):
    """A windowed build has no console, so QML errors are kept here without their folders."""
    write("qt_warning", _FOLDERS.sub("", str(message)))
