"""Windows can report a closed worker pipe from poll(), before recv() is called."""

import time
from types import SimpleNamespace

import pytest
from tanren_collector.processes import SpawnPool, Task


@pytest.mark.parametrize("break_on", [1, 2])
@pytest.mark.parametrize("draining", [False, True])
def test_broken_poll_is_harvested_as_child_exit(break_on, draining):
    closed = []

    class Receiver:
        calls = 0

        def poll(self):
            self.calls += 1
            if self.calls == break_on:
                raise BrokenPipeError(109, "synthetic closed pipe")
            return False

        def close(self):
            closed.append("receiver")

    pool = SpawnPool(max_workers=1)
    task = Task(None, ())
    task.receiver = Receiver()
    task.process = SimpleNamespace(
        is_alive=lambda: False,
        exitcode=37,
        pid=123,
        close=lambda: closed.append("process"),
    )
    task.started = time.monotonic()
    pool.active.append(task)

    pool.tick(draining=draining)

    assert task.done() and not pool.active
    with pytest.raises(RuntimeError, match="CHILD_PROCESS_EXITED") as caught:
        task.result()
    assert caught.value.collector_diagnostic["exit_code"] == 37
    assert closed == ["receiver", "process"]
