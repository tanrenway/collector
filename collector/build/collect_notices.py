"""Collect wheel and bundled Python/Tcl/Tk license notices into the review distribution."""

import importlib.metadata
import re
import shutil
import sys
from pathlib import Path

# Used only while building; their notices would suggest they ship when they do not.
BUILD_ONLY = {
    "pip",
    "setuptools",
    "wheel",
    "pillow",
    "altgraph",
    "pefile",
    "pywin32-ctypes",
    "packaging",
    "pyinstaller-hooks-contrib",
    "pytest",
    "pluggy",
    "iniconfig",
    "pygments",
}
# The PySide6/shiboken6 wheels carry only a commercial Qt license reference. Collector uses Qt
# under the LGPLv3 (see qt-licenses/README.md), so shipping that file would mislead.
MISLEADING = {"licenseref-qt-commercial.txt"}
ROOT_NOTICES = ("LICENSE", "NOTICE", "TRADEMARKS.md")


def collect(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for package in importlib.metadata.distributions():
        name = re.sub(r"[^A-Za-z0-9._-]", "_", package.metadata["Name"])
        if name.lower().replace("_", "-") in BUILD_ONLY:
            continue
        for item in package.files or []:
            if item.name.lower() in MISLEADING:
                continue
            if any(word in item.name.lower() for word in ("license", "notice", "copying")):
                source = Path(package.locate_file(item))
                if source.is_file():
                    relative = Path(str(item))
                    if relative.is_absolute() or ".." in relative.parts:
                        continue
                    target = destination / name / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    shutil.copytree(Path(__file__).parent / "qt-licenses", destination / "Qt", dirs_exist_ok=True)
    own = destination / "Tanren-Collector"
    own.mkdir(exist_ok=True)
    for notice in ROOT_NOTICES:
        source = Path(__file__).parents[1] / notice
        if not source.is_file():
            raise RuntimeError("Tanren Collector notice missing: " + notice)
        shutil.copy2(source, own / notice)
    base = Path(sys.base_prefix)
    python_license = base / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError("Python runtime license missing from build interpreter")
    shutil.copy2(python_license, destination / "Python-LICENSE.txt")
    licenses = list((base / "tcl").rglob("license.terms"))
    if len(licenses) < 2:
        raise RuntimeError("Review Tcl/Tk license locations before distributing")
    for index, item in enumerate(licenses):
        shutil.copy2(item, destination / f"TclTk-{index}-license.terms")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="dist/TanrenCollector/THIRD_PARTY_LICENSES")
    collect(parser.parse_args().output)
