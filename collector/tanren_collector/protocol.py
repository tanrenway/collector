"""Fixed-origin v2 transport and deterministic batch fragmentation; no financial calculations."""

import hashlib
import json
import re
import uuid

from . import __version__
from .build_target import ORIGIN
from .client import Api

VERSION = __version__
PREFIX = "/api/v1/mt5/collector/v2"


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


class V2Api(Api):
    def __init__(self, token):
        super().__init__(ORIGIN, token)

    def allowed_path(self, path):
        return path in {
            PREFIX + suffix
            for suffix in (
                "/control",
                "/batches",
                "/heartbeat",
                "/sync-jobs",
                "/enrollment",
                "/enrollment/claim",
                "/credentials/rotate",
            )
        } or bool(re.fullmatch(re.escape(PREFIX) + r"/(?:jobs|sync-jobs)/[0-9a-f-]{36}", path))


def batches(identity, records, start, end, sync_id=None):
    """Only the LAST fragment certifies the window; send immutable fragments FIFO.

    Earlier fragments carry zero-length coverage at start, preventing premature server force-sync
    completion. All records are retained; no density-based truncation. Empty windows still get ACKs.
    """
    template = {
        "protocol": "mt5-v2",
        "identity": identity,
        "history_start": start,
        "scanned_until": start,
        "collector_version": VERSION,
        "sync_job_id": sync_id,
    }
    fragments, current = [], []
    for record in records:
        candidate = {**template, "batch_id": str(uuid.uuid4()), "records": current + [record]}
        if len(current) >= 500 or len(encoded(candidate)) > 1_400_000:
            if not current:
                raise RuntimeError("SOURCE_RECORD_TOO_LARGE")
            fragments.append(current)
            current = []
        current.append(record)
        if (
            len(encoded({**template, "batch_id": str(uuid.uuid4()), "records": current}))
            > 1_400_000
        ):
            raise RuntimeError("SOURCE_RECORD_TOO_LARGE")
    fragments.append(current)
    return [
        {
            **template,
            "batch_id": str(uuid.uuid4()),
            "records": part,
            "scanned_until": end if index == len(fragments) - 1 else start,
        }
        for index, part in enumerate(fragments)
    ]
