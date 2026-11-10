"""Bounded spawn turns with hard timeouts; GUI never waits on MT5/network or an orphaned pool."""

import multiprocessing
import time
from collections import deque

from . import diagnostics_log
from .observability import DiagnosticFailure, capture, remember, set_sink, stage


def invoke(sender, function, args):
    set_sink(lambda report: sender.send(("diagnostic", report)))
    try:
        capture("child_start")
        with stage("child_call"):
            value = function(*args)
        result = (True, value)
    except Exception as exc:
        name = getattr(function, "__name__", "unknown")
        diagnostics_log.write("child_failed:" + name, type(exc).__name__)
        report = getattr(exc, "collector_diagnostic", None) or capture("child_call", exc)
        result = (False, {"code": report["code"], "diagnostic": report})
    try:
        sender.send(result)
    finally:
        set_sink(None)
        sender.close()


class Task:
    def __init__(self, function, args):
        self.function, self.args = function, args
        self.finished = False
        self.value = None
        self.ok = False
        self.process = None
        self.diagnostics = []

    def done(self):
        return self.finished

    def result(self):
        if not self.finished or not self.ok:
            if isinstance(self.value, dict):
                raise DiagnosticFailure(self.value["code"], self.value.get("diagnostic"))
            raise DiagnosticFailure(
                self.value
                if self.finished and isinstance(self.value, str)
                else "WORKER_OPERATION_FAILED",
                self.diagnostics[-1] if self.diagnostics else None,
            )
        return self.value


class SpawnPool:
    def __init__(self, max_workers=4, timeout=120, context=None):
        self.context = context or multiprocessing.get_context("spawn")
        self.limit = max_workers
        self.timeout = timeout
        self.waiting = deque()
        self.active = []
        self.closed = False

    def submit(self, function, *args):
        if self.closed:
            raise RuntimeError("WORKERS_CLOSED")
        task = Task(function, args)
        self.waiting.append(task)
        return task

    def tick(self, *, draining=False):
        if draining:
            # Shutdown cannot interrupt a durable write. Reject new turns and cancel only work
            # that has not started; keep harvesting active children without hard timeouts.
            self.closed = True
            for task in list(self.waiting):
                self.cancel(task)
        for task in list(self.active):
            eof = False
            # Drain bounded technical events before the final existing success/error result.
            for _ in range(40):
                try:
                    if not task.receiver.poll():
                        break
                    kind, value = task.receiver.recv()
                except (EOFError, OSError):
                    eof = True
                    break
                if kind == "diagnostic":
                    remember(value)
                    task.diagnostics = (task.diagnostics + [value])[-32:]
                else:
                    task.ok, task.value = kind, value
                    task.finished = True
                    break
            if not task.finished and (
                not task.process.is_alive()
                or (not draining and time.monotonic() - task.started > self.timeout)
            ):
                timeout = task.process.is_alive()
                if not timeout and not eof:
                    try:
                        if task.receiver.poll():
                            # A result arrived between the initial poll and process exit check.
                            continue
                    except (EOFError, OSError):
                        eof = True
                code = "CHILD_PROCESS_TIMEOUT" if timeout else "CHILD_PROCESS_EXITED"
                report = capture(
                    "child_timeout" if timeout else "child_exit",
                    code=code,
                    exit_code=task.process.exitcode,
                )
                report["child_pid"] = task.process.pid
                if task.diagnostics:
                    report["last_stage"] = task.diagnostics[-1]["stage"]
                task.value = {"code": code, "diagnostic": report}
                task.finished = True
                task.ok = False
            if task.finished:
                if draining and task.process.is_alive():
                    continue
                self.stop(task)
                self.active.remove(task)
                task.args = ()
        while self.waiting and len(self.active) < self.limit:
            task = self.waiting.popleft()
            receiver, sender = self.context.Pipe(duplex=False)
            task.receiver = receiver
            task.process = self.context.Process(
                target=invoke, args=(sender, task.function, task.args), daemon=True
            )
            try:
                with stage("child_start"):
                    task.process.start()
            except Exception as exc:
                report = getattr(exc, "collector_diagnostic", None) or capture("child_start", exc)
                report["code"] = "CHILD_START_FAILED"
                task.value = {"code": "CHILD_START_FAILED", "diagnostic": report}
                task.finished = True
                receiver.close()
                sender.close()
                task.process.close()
                continue
            sender.close()
            task.started = time.monotonic()
            self.active.append(task)

    def stop(self, task):
        if task.process.is_alive():
            task.process.join(timeout=0.1)
        if task.process.is_alive():
            task.process.terminate()
            task.process.join(timeout=1)
        task.receiver.close()
        task.process.close()

    def cancel(self, task):
        if task in self.active:
            self.stop(task)
            self.active.remove(task)
        elif task in self.waiting:
            self.waiting.remove(task)
        task.finished, task.ok, task.args = True, False, ()

    def shutdown(self):
        self.closed = True
        for task in self.active:
            self.stop(task)
            task.finished = True
            task.ok = False
        for task in self.waiting:
            task.finished = True
            task.ok = False
        self.active.clear()
        self.waiting.clear()
