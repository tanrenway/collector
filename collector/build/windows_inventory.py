"""Static Windows x64 package integrity; does not prove imports, signatures or native E2E."""

import argparse
import hashlib
import json
import struct
from pathlib import Path


def pe_machine(file):
    with file.open("rb") as stream:
        head = stream.read(64)
        if len(head) < 64 or head[:2] != b"MZ":
            raise ValueError("Expected Windows PE, never Linux ELF")
        offset = struct.unpack_from("<I", head, 60)[0]
        if offset > file.stat().st_size - 6:
            raise ValueError("Invalid PE offset")
        stream.seek(offset)
        signature, machine = struct.unpack("<4sH", stream.read(6))
        if signature != b"PE\0\0" or machine != 0x8664:
            raise ValueError("AMD64 PE required")
    return machine


def inventory(root):
    root = Path(root).resolve()
    files = {}
    for file in sorted(root.rglob("*")):
        if file.is_symlink() or not file.resolve().is_relative_to(root):
            raise ValueError("Linked or external package files are forbidden")
        if not file.is_file():
            continue
        name = file.relative_to(root).as_posix()
        pe = file.suffix.lower() in {".exe", ".dll", ".pyd"}
        if pe:
            pe_machine(file)
        if "webengine" in name.lower():
            raise ValueError("Unreviewed QtWebEngine")
        files[name] = {
            "bytes": file.stat().st_size,
            "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            "amd64_pe": pe,
        }
    requirements = {
        "collector": lambda n: n == "TanrenCollector.exe",
        "python": lambda n: n.lower().endswith("/python312.dll"),
        "mt5_native": lambda n: "MetaTrader5/" in n and n.endswith(".pyd"),
        "numpy_native": lambda n: "/numpy/" in n and n.endswith(".pyd"),
        "tk_fallback": lambda n: n.lower().endswith("/_tkinter.pyd"),
        "qt_platform": lambda n: n.lower().endswith("/qwindows.dll"),
        "qml_controls": lambda n: "/qml/QtQuick/Controls/Basic/" in n,
    }
    for label, match in requirements.items():
        if not any(match(name) for name in files):
            raise ValueError("Required package component missing: " + label)
    return {"schema": 1, "kind": "static-windows-inventory-not-native-validation", "files": files}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--verify", type=Path)
    args = parser.parse_args()
    value = inventory(args.root)
    if args.verify:
        if value != json.loads(args.verify.read_text()):
            raise ValueError("Windows package integrity mismatch")
    else:
        args.output.write_text(json.dumps(value, indent=2) + "\n")
