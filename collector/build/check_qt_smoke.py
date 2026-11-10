"""Verify bounded frozen synthetic Qt evidence; does NOT certify native MT5 or Windows support."""

import argparse
import json
from pathlib import Path

LIMIT = 65536


def validate(path):
    with Path(path).open("rb") as stream:
        payload = stream.read(LIMIT + 1)
    if len(payload) > LIMIT:
        raise ValueError("Qt smoke evidence exceeds limit")
    report = json.loads(payload)
    if (
        report.get("schema") != 1
        or report.get("synthetic") is not True
        or report.get("frozen") is not True
        or report.get("checks_passed") is not True
        or report.get("spawn_bootstrap") is not True
        or report.get("qml_errors") != []
    ):
        raise ValueError("Successful frozen synthetic Qt evidence required")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    validate(parser.parse_args().report)
