"""Separate protected runtime catalog and atomic device reader, never a legacy queue upgrader."""

import hashlib
import os
import uuid
from pathlib import Path

from .build_profile import check_storage_path
from .storage import load_config, save_config
from .windows import FileLock


def terminal_key(path):
    return hashlib.sha256(os.path.normcase(str(Path(path).resolve())).encode()).hexdigest()


class Catalog:
    def __init__(self, root, protector):
        self.path = Path(root) / "runtime-v3.dpapi"
        self.protector = protector
        self.lock = FileLock(Path(root) / "runtime-v3.lock")

    def get(self):
        return (
            load_config(self.path, self.protector)
            if self.path.exists()
            else {"accounts": {}, "terminals": {}, "legacy_paused": []}
        )

    def save(self, state):
        save_config(self.path, state, self.protector)

    def close(self):
        self.lock.close()


class DeviceReader:
    """Atomic replacement permits account children to read while one device worker rotates."""

    def __init__(self, root, protector):
        self.path = Path(root).parent / "device-v3" / "device.dpapi"
        check_storage_path(self.path)
        self.protector = protector

    def get(self):
        return load_config(self.path, self.protector) if self.path.exists() else {}


def account_path(root, binding):
    key = str(uuid.UUID(binding))
    directory = Path(root) / "device-accounts" / key
    check_storage_path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "queue-v2.sqlite"
