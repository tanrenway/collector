"""Explicit inventory and delivery-only legacy transition. No capture/relabel/checkpoint reset."""

import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from .application_state import LegacyView, MigrationView
from .build_profile import check_storage_path, require_network
from .client import Api
from .protocol import ORIGIN, PREFIX, V2Api
from .rotation import refresh
from .runtime_store import Catalog, account_path
from .storage import DPAPI, Queue, load_config
from .v2_store import Store


def inventory(root, account_id, identity, protector):
    require_network()  # Engineering never inventories or drains legacy account bindings.
    check_storage_path(root)
    root = Path(root)
    result = []
    directories = sorted((root / "bindings").iterdir())
    if len(directories) > 1000:
        raise RuntimeError("LEGACY_INVENTORY_INCOMPLETE")
    for directory in directories:
        if not directory.is_dir():
            continue
        try:
            uuid.UUID(directory.name)
        except ValueError:
            continue
        path = directory / "queue-v2.sqlite"
        check_storage_path(path)
        if not path.is_file():
            raise RuntimeError("LEGACY_INVENTORY_INCOMPLETE")
        # Read-only SQLite snapshot; never constructs Store, changes schema or decrypts payloads.
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.1) as db:
            row = db.execute("SELECT payload FROM metadata WHERE key='config'").fetchone()
            pending_pair = db.execute("SELECT payload FROM metadata WHERE key='pairing'").fetchone()
            if pending_pair and json.loads(protector.open(pending_pair[0])):
                raise RuntimeError("LEGACY_ENROLLMENT_PENDING")
            if row is None:
                raise RuntimeError("LEGACY_INVENTORY_INCOMPLETE")
            config = json.loads(protector.open(row[0]))
            if config.get("account_id") == account_id:
                if config.get("identity") != identity:
                    raise RuntimeError("LEGACY_IDENTITY_REVIEW_REQUIRED")
                counts = dict(
                    db.execute("SELECT status,count(*) FROM deliveries GROUP BY status").fetchall()
                )
                result.append(
                    LegacyView(
                        directory.name,
                        "v2",
                        counts.get("pending", 0),
                        counts.get("received", 0),
                        sum(
                            counts.get(k, 0)
                            for k in ("partial", "needs_review", "paused", "cancelled")
                        ),
                    )
                )
            elif config.get("identity") == identity:
                raise RuntimeError("LEGACY_IDENTITY_REVIEW_REQUIRED")
    cli = root.parent
    if (cli / "config.dpapi").is_file() or (cli / "outbox.sqlite").is_file():
        if not (cli / "config.dpapi").is_file() or not (cli / "outbox.sqlite").is_file():
            raise RuntimeError("LEGACY_INVENTORY_INCOMPLETE")
        config = load_config(cli / "config.dpapi", protector)
        if config["identity"] == identity:
            with sqlite3.connect((cli / "outbox.sqlite").as_uri() + "?mode=ro", uri=True) as db:
                counts = dict(
                    db.execute("SELECT status,count(*) FROM outbox GROUP BY status").fetchall()
                )
            result.append(
                LegacyView("cli-v1", "v1", counts.get("pending", 0), 0, counts.get("received", 0))
            )
    return tuple(result)


def drain_one(root, item, protector, factory=V2Api, legacy_factory=Api, account_id=None):
    require_network()
    if item.protocol == "v1":
        directory = Path(root).parent
        config = load_config(directory / "config.dpapi", protector)
        if config["origin"].rstrip("/") != ORIGIN.rstrip("/"):
            raise RuntimeError("LEGACY_ORIGIN_REVIEW_REQUIRED")
        with closing(Queue(directory / "outbox.sqlite", protector)) as queue:
            pending = queue.pending()
            if pending:
                key, body = pending
                api = legacy_factory(config["origin"], config["token"])
                if api.call("/api/v1/mt5/collector/control")["account_id"] != account_id:
                    raise RuntimeError("CREDENTIAL_SCOPE_MISMATCH")
                result = api.call("/api/v1/mt5/collector/batches", body)
                queue.acknowledge(key, result, body["scanned_until"])
        return
    with closing(Store(Path(root) / "bindings" / item.key / "queue-v2.sqlite", protector)) as store:
        config = store.get("config")
        control = refresh(store, factory)
        if control["account_id"] != config["account_id"]:
            raise RuntimeError("CREDENTIAL_SCOPE_MISMATCH")
        api = factory(store.get("config")["token"])
        pending = store.due()
        if pending:
            key, body = pending
            store.received(key, api.call(PREFIX + "/batches", body))
        unsettled = store.unsettled()
        if unsettled:
            key, receipt = unsettled
            store.processed(key, api.call(PREFIX + "/jobs/" + receipt["job_id"])["state"])


def transition_turn(
    root,
    binding,
    action="inspect",
    confirmed=False,
    protector=None,
    factory=V2Api,
    legacy_factory=Api,
):
    protector = protector or DPAPI()
    with closing(Store(account_path(root, binding), protector)) as queue:
        config = queue.get("config")
    try:
        items = inventory(root, config["account_id"], config["identity"], protector)
    except (sqlite3.Error, OSError, ValueError, KeyError):
        raise RuntimeError("LEGACY_INVENTORY_INCOMPLETE") from None
    if action == "drain":
        if not confirmed:
            raise RuntimeError("EXPLICIT_MIGRATION_REQUIRED")
        for item in items:
            try:
                drain_one(root, item, protector, factory, legacy_factory, config["account_id"])
            except OSError:
                raise RuntimeError("LEGACY_QUEUE_BUSY") from None
        items = inventory(root, config["account_id"], config["identity"], protector)
    blocked = any(i.review for i in items)
    stage = (
        "blocked"
        if blocked
        else "draining"
        if any(i.pending or i.processing for i in items)
        else "awaiting_browser_confirmation"
    )
    with closing(Catalog(root, protector)) as catalog:
        state = catalog.get()
        state["migration"] = {
            "binding_id": binding,
            "stage": stage,
            "legacy_keys": [i.key for i in items],
            "confirmed": action == "drain" and confirmed,
        }
        if action == "drain":
            state["legacy_paused"] = sorted(
                set(state["legacy_paused"]) | {i.key for i in items if i.protocol == "v2"}
            )
        catalog.save(state)
    return MigrationView(binding, stage, items, "LEGACY_REVIEW_REQUIRED" if blocked else None)
