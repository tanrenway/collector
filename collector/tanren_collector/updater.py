"""User-started update: reviewed origin and paths, no redirects, size and SHA-256 checked."""

import hashlib
import json
import os
import re
import subprocess  # noqa: S404 - runs only a file whose digest was verified just before.
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__
from .build_profile import profile_root, require_network
from .build_target import ORIGIN
from .client import NoRedirect

INFO_PATH = "/api/v1/collector/release"
MAX_BYTES = 200 * 1024 * 1024
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
_DIGEST = re.compile(r"[0-9a-f]{64}")


def _parts(version):
    return tuple(int(part) for part in version.split("."))


def validate(info):
    """Accept only a manifest that names exactly the fixed installer path for its own version."""
    try:
        version, name, digest, size, url = (
            info["version"],
            info["file"],
            info["sha256"],
            info["size_bytes"],
            info["url"],
        )
    except (KeyError, TypeError):
        raise RuntimeError("UPDATE_INVALID_MANIFEST") from None
    if (
        not isinstance(version, str)
        or not _VERSION.fullmatch(version)
        or name != f"TanrenCollectorSetup-{version}.exe"
        or not isinstance(digest, str)
        or not _DIGEST.fullmatch(digest)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or not 0 < size <= MAX_BYTES
        or url != f"{INFO_PATH}/download/{name}"
    ):
        raise RuntimeError("UPDATE_INVALID_MANIFEST")
    return {"version": version, "file": name, "sha256": digest, "size_bytes": size, "url": url}


def _is_windows():
    return os.name == "nt"


def _digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


class Updater:
    def __init__(self, directory=None, opener=None, origin=ORIGIN, current=__version__):
        self.directory = Path(directory) if directory else None
        self.opener = opener or urllib.request.build_opener(NoRedirect())
        self.origin, self.current = origin.rstrip("/"), current

    def folder(self):
        return self.directory or profile_root() / "updates"

    def check(self):
        """The manifest when a newer version is published, otherwise None. Never a downgrade."""
        require_network()
        try:
            with self.opener.open(self.origin + INFO_PATH, timeout=30) as response:
                info = json.loads(response.read(64 * 1024))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:  # Nothing is published yet.
                return None
            raise RuntimeError("UPDATE_CHECK_FAILED") from None
        except (OSError, ValueError):
            raise RuntimeError("UPDATE_CHECK_FAILED") from None
        info = validate(info)
        return info if _parts(info["version"]) > _parts(self.current) else None

    def download(self, info):
        """Store the installer only after its size and SHA-256 match; never keep a partial file."""
        require_network()
        info = validate(info)
        folder = self.folder()
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("TanrenCollectorSetup-*"):
            old.unlink(missing_ok=True)
        target = folder / info["file"]
        partial = target.with_name(info["file"] + ".part")
        hasher, received = hashlib.sha256(), 0
        try:
            with (
                self.opener.open(self.origin + info["url"], timeout=60) as response,
                partial.open("wb") as stream,
            ):
                while chunk := response.read(1024 * 1024):
                    received += len(chunk)
                    if received > info["size_bytes"]:
                        raise RuntimeError("UPDATE_FILE_MISMATCH")
                    hasher.update(chunk)
                    stream.write(chunk)
            if received != info["size_bytes"] or hasher.hexdigest() != info["sha256"]:
                raise RuntimeError("UPDATE_FILE_MISMATCH")
            os.replace(partial, target)
        except (OSError, urllib.error.URLError):
            raise RuntimeError("UPDATE_DOWNLOAD_FAILED") from None
        finally:
            partial.unlink(missing_ok=True)
        return target

    def launch(self, path, info):
        """Re-verify right before starting; the visible installer wizard does the rest."""
        info = validate(info)
        if not _is_windows():
            raise RuntimeError("UPDATE_WINDOWS_REQUIRED")
        if Path(path).name != info["file"] or _digest(path) != info["sha256"]:
            raise RuntimeError("UPDATE_FILE_MISMATCH")
        subprocess.Popen([str(path)], close_fds=True)  # noqa: S603 - digest verified above.
