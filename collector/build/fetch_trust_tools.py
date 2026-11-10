"""Fetch pinned vendor NuGet tools, verifying archive and selected PE SHA256 before use."""

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Vendor tool redirects forbidden")


def fetch(lock, destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)  # Never merge stale/untrusted binaries.
    result = {}
    for name in ("sdk", "artifact_client"):
        item = lock[name]
        url = urllib.parse.urlsplit(item["url"])
        if (
            url.scheme != "https"
            or url.hostname != "api.nuget.org"
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.port not in (None, 443)
            or not url.path.startswith("/v3-flatcontainer/")
        ):
            raise ValueError("Official HTTPS NuGet source required")
        archive = destination / (name + ".zip")
        with (
            urllib.request.build_opener(NoRedirect()).open(item["url"], timeout=60) as response,
            archive.open("xb") as output,
        ):
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 100_000_000:
                    raise ValueError("Tool archive size exceeded")
                output.write(chunk)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Vendor tool archive hash mismatch")
        target = destination / name
        target.mkdir()
        with zipfile.ZipFile(archive) as package:
            for info in package.infolist():
                path = (target / info.filename).resolve()
                if (
                    not path.is_relative_to(target)
                    or "\\" in info.filename
                    or ":" in info.filename
                    or info.file_size > 100_000_000
                    or (info.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError("Unsafe vendor archive path/entry")
            package.extractall(target)
        binary = target / item["file"]
        if hashlib.sha256(binary.read_bytes()).hexdigest() != item["file_sha256"]:
            raise ValueError("Vendor PE hash mismatch")
        result[name] = str(binary)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    lock = json.loads(Path(__file__).with_name("toolchain.json").read_text())
    print(json.dumps(fetch(lock, args.destination)))
