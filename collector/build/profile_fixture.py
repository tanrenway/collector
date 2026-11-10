"""Synthetic retention fixture. CLI restricted to disposable GitHub-hosted Windows runner."""

import argparse
import hashlib
import json
import os
import secrets
import uuid
from pathlib import Path

from tanren_collector.protocol import batches
from tanren_collector.runtime_store import account_path
from tanren_collector.storage import DPAPI, Queue, save_config
from tanren_collector.v2_store import Store


def snapshot(root):
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def seed(root, protector):
    if root.exists():
        raise ValueError("Refuse existing profile")
    root.mkdir(parents=True)
    for directory in ["device-v3", "v2/registration-v3", "v2/bindings/synthetic-legacy"]:
        (root / directory).mkdir(parents=True)
    device = str(uuid.uuid4())
    save_config(
        root / "device-v3/device.dpapi",
        {
            "synthetic": True,
            "state": "paired",
            "device_id": device,
            "token": secrets.token_urlsafe(32),
        },
        protector,
    )
    save_config(root / "v2/settings.dpapi", {"palette": "forest", "locale": "uk"}, protector)
    binding = str(uuid.uuid4())
    account = str(uuid.uuid4())
    save_config(
        root / "v2/runtime-v3.dpapi",
        {
            "accounts": {
                binding: {
                    "account_id": account,
                    "device_id": device,
                    "terminal_key": "synthetic-terminal",
                    "enabled": False,
                }
            },
            "terminals": {},
            "legacy_paused": ["synthetic"],
        },
        protector,
    )
    save_config(
        root / "v2/registration-v3/registrations.dpapi",
        {
            "registration_results": {
                "synthetic-request": {
                    "binding_id": binding,
                    "account_id": account,
                    "state": "created",
                }
            }
        },
        protector,
    )
    identity = {
        "broker": "Synthetic",
        "server": "Synthetic",
        "login": "1",
        "currency": "USD",
        "mode": "hedging",
    }
    stamp = "2026-01-01T00:00:00+00:00"
    body = batches(identity, [], stamp, stamp)[0]
    queue = Queue(root / "legacy.sqlite", protector)
    try:
        queue.enqueue({"batch_id": body["batch_id"], "synthetic": True, "scanned_until": stamp})
    finally:
        queue.close()
    store = Store(root / "v2/bindings/synthetic-legacy/queue-v2.sqlite", protector)
    try:
        store.save("config", {"synthetic": True, "credential": secrets.token_urlsafe(32)})
        store.capture("synthetic-window", [body], "capture_cursor", stamp)
    finally:
        store.close()
    store = Store(account_path(root / "v2", binding), protector)
    try:
        store.save(
            "config",
            {
                "binding_id": binding,
                "account_id": account,
                "device_id": device,
                "identity": identity,
                "enabled": False,
            },
        )
        store.capture(
            "synthetic-v3-window",
            [body],
            "capture_cursor",
            stamp,
            provenance={
                "binding_id": binding,
                "epoch": 1,
                "window_id": "synthetic-v3-window",
                "fragment_count": 1,
            },
        )
        store.save("v3_lease_request", {"action": "acquire", "request_id": str(uuid.uuid4())})
    finally:
        store.close()
    return snapshot(root)


def verify(root, expected):
    if snapshot(root) != expected:
        raise ValueError("Protected synthetic profile changed during binary maintenance")
    return {"retained": True, "files": len(expected), "synthetic_only": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["seed", "verify"])
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    if (
        os.name != "nt"
        or os.getenv("GITHUB_ACTIONS") != "true"
        or os.getenv("RUNNER_ENVIRONMENT") != "github-hosted"
    ):
        raise RuntimeError("Disposable hosted Windows runner required; never real user profiles")
    root = Path(os.environ["LOCALAPPDATA"]) / "TanrenCollector"
    if args.action == "seed":
        if args.manifest.exists():
            raise ValueError("Fresh fixture manifest required")
        args.manifest.write_text(json.dumps(seed(root, DPAPI()), indent=2))
    else:
        print(json.dumps(verify(root, json.loads(args.manifest.read_text()))))
