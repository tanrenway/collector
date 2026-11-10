"""Real source spawned SQLite writer: shutdown drain must not terminate a transaction."""

import time
from contextlib import closing

from tanren_collector.processes import SpawnPool
from tanren_collector.v2_store import Store
from test_collector import TestProtector


def durable_write(path, entered, release):
    from pathlib import Path

    with closing(Store(path, TestProtector())) as store:
        with store.db:
            store.put("pending-write", {"checkpoint": "retained"})
            Path(entered).touch()
            deadline = time.monotonic() + 10
            while not Path(release).exists():
                if time.monotonic() > deadline:
                    raise RuntimeError("SYNTHETIC_RELEASE_TIMEOUT")
                time.sleep(0.01)
    return "committed"


def test_shutdown_drain_preserves_inflight_durable_write(tmp_path):
    path, entered, release = [tmp_path / name for name in ("queue.sqlite", "entered", "release")]
    pool = SpawnPool(max_workers=1, timeout=0.01)
    task = pool.submit(durable_write, str(path), str(entered), str(release))
    waiting = pool.submit(durable_write, str(path), str(entered), str(release))
    try:
        pool.tick()
        deadline = time.monotonic() + 10
        while not entered.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert entered.exists()
        # The ordinary worker deadline has expired while the real SQLite transaction is open.
        time.sleep(0.03)
        pool.tick(draining=True)
        assert task.process.is_alive() and not task.done()
        assert waiting.done() and not waiting.ok and not pool.waiting and pool.closed
        release.touch()
        while pool.active and time.monotonic() < deadline:
            pool.tick(draining=True)
            time.sleep(0.01)
        assert not pool.active and task.result() == "committed"
        with closing(Store(path, TestProtector())) as store:
            assert store.get("pending-write") == {"checkpoint": "retained"}
    finally:
        release.touch()
        # Cleanup only this disposable test pool; never terminate an active durable write.
        deadline = time.monotonic() + 10
        while pool.active and time.monotonic() < deadline:
            pool.tick(draining=True)
            time.sleep(0.01)
        assert not pool.active
        pool.shutdown()
