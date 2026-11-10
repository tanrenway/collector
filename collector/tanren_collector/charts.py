"""Server-driven chart jobs: read broker candles for closed trades and upload them.

Read-only: the Collector never opens a chart, takes a screenshot or touches orders. The server
decides which closed trades need which timeframes (per-account opt-in) and keeps job state, so a
crash, reboot or offline period loses nothing: unfinished jobs are simply offered again. Uploading
the same candles twice is idempotent on the server.
"""

from datetime import datetime

# Failure codes the server understands; anything else is reported as a transient read failure.
PERMANENT = {"SYMBOL_NOT_FOUND", "NO_HISTORY"}
NEVER_REPORT = {"TERMINAL_BUSY", "TERMINAL_UNAVAILABLE"}  # Terminal not usable now: retry later.


def failure_code(exc):
    code = str(exc)
    if code in PERMANENT:
        return code
    return "READ_FAILED"


class ChartTurn:
    """One bounded turn: fetch up to a few jobs, read candles, upload. Never raises on a job."""

    def __init__(self, api, prefix, terminal):
        self.api, self.prefix, self.terminal = api, prefix, terminal

    def run(self):
        jobs = self.api.call(self.prefix + "/chart-jobs")["items"]
        done = failed = 0
        for job in jobs:
            try:
                self.terminal.connect()
            except Exception as exc:
                if str(exc) in NEVER_REPORT or str(exc).startswith("TERMINAL_"):
                    break  # Leave the jobs pending; report nothing about an unavailable terminal.
                raise
            try:
                digits, candles = self.terminal.rates(
                    job["symbol"],
                    job["timeframe"],
                    datetime.fromisoformat(job["from"]),
                    datetime.fromisoformat(job["to"]),
                )
            except Exception as exc:
                if str(exc).startswith("TERMINAL_"):
                    break
                self.api.call(
                    self.prefix + "/chart-jobs/" + job["id"] + "/failure",
                    {"code": failure_code(exc)},
                )
                failed += 1
                continue
            finally:
                self.terminal.close()
            self.api.call(
                self.prefix + "/chart-jobs/" + job["id"] + "/ohlc",
                {"digits": digits, "candles": candles},
            )
            done += 1
        return {"jobs": len(jobs), "uploaded": done, "failed": failed}
