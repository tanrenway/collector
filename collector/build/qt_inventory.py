"""Fail-closed Qt inventory for source-equivalent/review bundles, never trust/sign evidence."""

import argparse
import hashlib
import json
from pathlib import Path

# Qt modules offered only under GPL (doc.qt.io/qt-6/licensing.html "GPL-only modules"). The
# installer ships Qt under LGPLv3, so none of these may be bundled; the build fails instead.
GPL_ONLY = (
    "qt6charts",
    "qt6datavisualization",
    "qt6graphs",
    "qt6lottie",
    "qt6networkauth",
    "qt6qmlcompiler",
    "qt6quick3dphysics",
    "qt6quicktimeline",
    "qt6shadertools",
    "qt6virtualkeyboard",
    "qt6waylandcompositor",
    "qt6httpserver",
    "qt6protobuf",
    "qt6grpc",
    "qt6coap",
    "qt6mqtt",
    "qt6opcua",
)
GPL_ONLY_QML = (
    "qml/qtcharts",
    "qml/qtdatavisualization",
    "qml/qtgraphs",
    "qml/qt/labs/lottieqt",
    "qml/qtquick/timeline",
    "qml/qtquick/virtualkeyboard",
)


def gpl_only(relative):
    name = relative.lower()
    stem = name.rsplit("/", 1)[-1]
    return stem.startswith(GPL_ONLY) or any(f"/{part}/" in f"/{name}" for part in GPL_ONLY_QML)


def inventory(root, windows=False):
    root = Path(root)
    rows = {}
    for file in sorted(root.rglob("*")):
        if file.is_file() and ("PySide6" in file.parts or "shiboken6" in file.parts):
            relative = file.relative_to(root).as_posix()
            if "webengine" in relative.lower():
                raise ValueError("Unreviewed QtWebEngine dependency")
            if gpl_only(relative):
                raise ValueError("GPL-only Qt module must not ship: " + relative)
            rows[relative] = {
                "bytes": file.stat().st_size,
                "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            }
    for required in [
        "qml/QtQml/",
        "qml/QtQuick/Controls/Basic/",
        "qml/QtQuick/Layouts/",
        "qml/QtQuick/Shapes/",
    ]:
        if not any(required in name for name in rows):
            raise ValueError("Missing required Qt module: " + required)
    if windows and not any(name.endswith("/qwindows.dll") for name in rows):
        raise ValueError("Missing Windows platform plugin")
    return {
        "kind": "review-inventory-not-release-evidence",
        "files": rows,
        "windows_inventory": windows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--windows", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(inventory(args.root, args.windows), indent=2) + "\n")
