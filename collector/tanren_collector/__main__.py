"""One explicit binding/process; durable scan -> queue -> upload -> applied checkpoint."""

import argparse
import getpass
import json
import logging
import os
import random
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .build_profile import ENGINEERING, current
from .client import Api
from .storage import DPAPI, Queue, load_config, save_config
from .terminal import Terminal


def cycle(queue, terminal, api, config, full=False, replay_requested=False):
    pending = queue.pending()
    if pending:
        key, body = pending
        result = api.call("/api/v1/mt5/collector/batches", body)
        queue.acknowledge(key, result, body["scanned_until"])
        return
    # Periodic full replay also catches late old changes; no ticket-only or finite-overlap promise.
    initial = datetime.fromisoformat(config["history_start"]).astimezone(UTC)
    applied = queue.checkpoint("scan_cursor")
    caught_up = applied and datetime.fromisoformat(applied) >= datetime.now(UTC) - timedelta(
        minutes=2
    )
    start = (
        initial
        if replay_requested or (full and caught_up) or not applied
        else max(initial, datetime.fromisoformat(applied))
    )
    now = datetime.now(UTC)
    end = min(now, start + timedelta(days=1))
    records = terminal.read(start, end)
    # Atomic window only; never truncate broker responses or advance on oversized windows.
    while len(records) > 500 and (end - start).total_seconds() > 1:
        end = start + (end - start) / 2
        records = terminal.read(start, end)
    if len(records) > 500:
        raise RuntimeError("WINDOW_TOO_LARGE_REQUIRES_SMALLER_WINDOW")
    body = {
        "protocol": "mt5-v1",
        "batch_id": str(uuid.uuid4()),
        "identity": config["identity"],
        "history_start": start.isoformat(),
        "scanned_until": end.isoformat(),
        "collector_version": "0.1.0",
        "records": records,
    }
    queue.enqueue(body)
    key, body = queue.pending()
    result = api.call("/api/v1/mt5/collector/batches", body)
    queue.acknowledge(key, result, body["scanned_until"])


def main():
    if current() == ENGINEERING:
        raise RuntimeError("ENGINEERING_DESKTOP_ONLY")
    parser = argparse.ArgumentParser(description="Tanren read-only MT5 Collector")
    parser.add_argument("command", choices=["configure", "run"])
    parser.add_argument(
        "--directory", default=str(Path(os.environ.get("LOCALAPPDATA", ".")) / "TanrenCollector")
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    path = Path(args.directory)
    path.mkdir(parents=True, exist_ok=True)
    logging.getLogger().addHandler(
        RotatingFileHandler(
            path / "collector.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
    )
    protector = DPAPI()
    if args.command == "configure":
        if (path / "config.dpapi").exists():
            raise RuntimeError(
                "Use a separate directory for another binding; do not relabel a queue"
            )
        origin = input("Tanren HTTPS origin: ").strip()
        token = getpass.getpass("One-time displayed Collector token: ").strip()
        Api(origin, token)
        identity = json.loads(
            input("Exact approved identity JSON (broker/server/login/currency/mode): ")
        )
        terminal_path = input("Selected MT5 terminal64.exe absolute path: ").strip()
        if not Path(terminal_path).is_absolute() or not Path(terminal_path).is_file():
            raise ValueError("Select an existing absolute terminal path")
        history = datetime.fromisoformat(input("History start ISO8601 with UTC offset: ").strip())
        if history.tzinfo is None or history > datetime.now(UTC):
            raise ValueError("Aware historical start required")
        terminal = Terminal(terminal_path, identity)
        try:
            terminal.connect()
        finally:
            terminal.close()
        save_config(
            path / "config.dpapi",
            {
                "origin": origin,
                "token": token,
                "identity": identity,
                "terminal": terminal_path,
                "history_start": history.astimezone(UTC).isoformat(),
            },
            protector,
        )
        logging.info("Configuration protected for current Windows user")
        return
    config = load_config(path / "config.dpapi", protector)
    queue = Queue(path / "outbox.sqlite", protector)
    api = Api(config["origin"], config["token"])
    terminal = Terminal(config["terminal"], config["identity"])
    failures, last_full, last_request = 0, 0, None
    try:
        while True:
            try:
                terminal.connect()
                control = api.call("/api/v1/mt5/collector/control")
                requested = control["requested_at"] and control["requested_at"] != last_request
                full = bool(requested or time.monotonic() - last_full > 86400)
                cycle(queue, terminal, api, config, full=full, replay_requested=bool(requested))
                if full:
                    last_full = time.monotonic()
                last_request = control["requested_at"]
                failures = 0
                logging.info("Sync batch acknowledged; check server reconciliation status")
                time.sleep(60)
            except ConnectionError as exc:
                failures += 1
                logging.warning("Delivery deferred; durable batch retained")
                time.sleep(
                    max(getattr(exc, "retry_after", 0), min(300, 2 ** min(failures, 8)))
                    + random.SystemRandom().uniform(0, 5)
                )
            except RuntimeError as exc:
                # Our error codes contain no broker/credential payloads.
                code = str(exc)
                allowed = {
                    "TERMINAL_UNAVAILABLE",
                    "TERMINAL_DISCONNECTED",
                    "DEAL_READ_FAILED",
                    "ORDER_READ_FAILED",
                    "POSITION_READ_FAILED",
                }
                if code not in allowed:
                    safe_code = (
                        code if re.fullmatch(r"[A-Z0-9_]{1,80}", code) else "COLLECTOR_ERROR"
                    )
                    logging.error(
                        "Sync paused (%s); review configuration/reconciliation", safe_code
                    )
                    raise SystemExit(2) from None
                logging.warning("Terminal unavailable; history will backfill after recovery")
                time.sleep(60)
            finally:
                terminal.close()
    finally:
        queue.close()


if __name__ == "__main__":
    main()
