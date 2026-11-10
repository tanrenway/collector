"""Update checks with an in-memory transport; nothing here reaches a network or runs a file."""

import hashlib
import io
import json
import urllib.error

import pytest
from tanren_collector import updater as module
from tanren_collector.updater import INFO_PATH, Updater, validate

PAYLOAD = b"synthetic installer"


def manifest(version="0.7.0", payload=PAYLOAD, **values):
    name = f"TanrenCollectorSetup-{version}.exe"
    return {
        "version": version,
        "file": name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "url": f"{INFO_PATH}/download/{name}",
        **values,
    }


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Opener:
    def __init__(self, info=None, payload=PAYLOAD, error=None):
        self.info, self.payload, self.error, self.urls = info, payload, error, []

    def open(self, url, timeout):
        self.urls.append(url)
        if self.error:
            raise self.error
        if url.endswith(INFO_PATH):
            return Reply(json.dumps(self.info).encode())
        return Reply(self.payload)


def http(code):
    return urllib.error.HTTPError("https://x", code, "x", {}, None)


def updater(tmp_path, opener, current="0.6.2"):
    return Updater(tmp_path, opener, "https://app.example.test", current)


@pytest.mark.parametrize(
    ("version", "found"),
    [("0.7.0", True), ("0.6.10", True), ("0.6.2", False), ("0.6.1", False)],
)
def test_only_a_newer_version_is_offered(tmp_path, version, found):
    result = updater(tmp_path, Opener(manifest(version))).check()
    assert (result is not None) is found


def test_nothing_published_is_not_an_error(tmp_path):
    assert updater(tmp_path, Opener(error=http(404))).check() is None


@pytest.mark.parametrize("error", [http(500), http(403), OSError("offline")])
def test_failed_check_is_reported(tmp_path, error):
    with pytest.raises(RuntimeError, match="UPDATE_CHECK_FAILED"):
        updater(tmp_path, Opener(error=error)).check()


@pytest.mark.parametrize(
    "bad",
    [
        {"url": "https://evil.example/TanrenCollectorSetup-0.7.0.exe"},
        {"url": f"{INFO_PATH}/download/../../evil.exe"},
        {"file": "evil.exe"},
        {"file": "../TanrenCollectorSetup-0.7.0.exe"},
        {"sha256": "ABC"},
        {"size_bytes": 0},
        {"size_bytes": module.MAX_BYTES + 1},
        {"size_bytes": True},
        {"version": "1.0"},
    ],
)
def test_manifest_cannot_redirect_the_download(bad):
    with pytest.raises(RuntimeError, match="UPDATE_INVALID_MANIFEST"):
        validate(manifest(**bad))


def test_download_verifies_and_replaces_old_files(tmp_path):
    (tmp_path / "TanrenCollectorSetup-0.5.0.exe").write_bytes(b"old")
    path = updater(tmp_path, opener := Opener()).download(manifest())
    assert path.read_bytes() == PAYLOAD and sorted(p.name for p in tmp_path.iterdir()) == [
        path.name
    ]
    assert opener.urls == ["https://app.example.test" + manifest()["url"]]


@pytest.mark.parametrize("payload", [b"tampered installer!", b"short", PAYLOAD + b"x"])
def test_mismatched_file_is_never_kept(tmp_path, payload):
    with pytest.raises(RuntimeError, match="UPDATE_FILE_MISMATCH"):
        updater(tmp_path, Opener(payload=payload)).download(manifest())
    assert list(tmp_path.iterdir()) == []


def test_launch_rechecks_the_file_and_runs_only_on_windows(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(module.subprocess, "Popen", lambda args, close_fds: started.append(args))
    item = updater(tmp_path, Opener())
    path = item.download(manifest())
    monkeypatch.setattr(module, "_is_windows", lambda: False)
    with pytest.raises(RuntimeError, match="UPDATE_WINDOWS_REQUIRED"):
        item.launch(path, manifest())
    monkeypatch.setattr(module, "_is_windows", lambda: True)
    path.write_bytes(b"swapped after download")
    with pytest.raises(RuntimeError, match="UPDATE_FILE_MISMATCH"):
        item.launch(path, manifest())
    assert started == []
    path.write_bytes(PAYLOAD)
    item.launch(path, manifest())
    assert started == [[str(path)]]
