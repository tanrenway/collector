"""Portable integrity/promotion checks. Windows signature verification is performed separately.

JSON reports alone are NOT cryptographic evidence.
complete-release.ps1 re-verifies PE files using Windows trust APIs.
"""

import argparse
import hashlib
import json
import re
import struct
from datetime import datetime, timedelta
from pathlib import Path

GENERATED = {"RELEASE_MANIFEST.json", "SHA256SUMS.txt", "RELEASE_GATE.json"}
REQUIRED = {"TanrenCollectorSetup.exe", "TanrenCollector/TanrenCollector.exe"}
CHECKS = {
    "mt5_native_frozen_comparison",
    "mt5_terminal_initialize_reconnect",
    "mt5_real_e2e",
    "rc_04_upgrade",
    "rc_profile_retention",
    "rc_windows_lifecycle",
    "qt_windows10",
    "qt_windows11",
    "qt_qml_plugins",
    "qt_dpi_accessibility",
    "qt_license_review",
    "qt_minimum_os_review",
    "tk_fallback",
    "clean_install",
    "upgrade_03",
    "reinstall",
    "running_upgrade",
    "failed_upgrade_recovery",
    "main_exe",
    "child_processes",
    "native_modules",
    "autostart",
    "tray",
    "rebuilt_version",
}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def is_pe(path):
    with Path(path).open("rb") as stream:
        header = stream.read(64)
        if not header.startswith(b"MZ"):
            return False
        if len(header) < 64:
            raise ValueError("Malformed DOS header")
        offset = struct.unpack_from("<I", header, 60)[0]
        if offset > path.stat().st_size - 4:
            raise ValueError("Malformed PE offset")
        stream.seek(offset)
        if stream.read(4) != b"PE\0\0":
            raise ValueError("Malformed PE signature")
    return True


def inventory(root):
    root = Path(root).resolve()
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinks forbidden in release payload")
        if path.is_file():
            name = path.relative_to(root).as_posix()
            if name in GENERATED:
                continue
            pe = is_pe(path)
            if path.suffix.lower() in {".exe", ".dll", ".pyd"} and not pe:
                raise ValueError("Executable extension without a PE header")
            if pe:
                with path.open("rb") as stream:
                    stream.seek(60)
                    offset = struct.unpack("<I", stream.read(4))[0]
                    stream.seek(offset + 4)
                    machine = stream.read(2)
                # Inno's bootstrapper may be x86; the embedded application must be x64.
                allowed = (
                    {b"\x64\x86", b"\x4c\x01"}
                    if name == "TanrenCollectorSetup.exe"
                    else {b"\x64\x86"}
                )
                if machine not in allowed:
                    raise ValueError("Unsupported PE architecture: " + name)
            result[name] = {"sha256": sha(path), "bytes": path.stat().st_size, "pe": pe}
    if not REQUIRED.issubset(result):
        raise ValueError("Missing application/installer")
    return result


def checksum_text(root, manifest):
    sums = {
        **manifest["files"],
        "RELEASE_MANIFEST.json": {"sha256": sha(Path(root) / "RELEASE_MANIFEST.json")},
    }
    return "".join(f"{v['sha256']}  {k}\n" for k, v in sorted(sums.items()))


def validate(root, manifest, require_checksums=True):
    if manifest.get("schema") != 1 or manifest.get("status") != "signed-candidate":
        raise ValueError("Signed candidate manifest required")
    info = manifest["build"]
    if info.get("source_clean") is not True or not re.fullmatch(
        r"[0-9a-f]{40}", info.get("source_commit", "")
    ):
        raise ValueError("Clean immutable source required")
    if info.get("signed_uninstaller") is not True or info.get("provider") not in {
        "certificate-store",
        "azure-artifact",
    }:
        raise ValueError("Signed uninstaller/provider provenance required")
    if info != json.loads((Path(root) / "BUILD_INFO.json").read_text()):
        raise ValueError("Build provenance mismatch")
    actual = inventory(root)
    if actual != manifest["files"]:
        raise ValueError("Release payload changed or includes unrecorded files")
    report = json.loads((Path(root) / "SIGNATURE_REPORT.json").read_text())
    native = {name for name, item in actual.items() if item["pe"]}
    if set(report) != native:
        raise ValueError("Every PE, including DLL/PYD, needs native verification")
    for name, signature in report.items():
        if (
            signature.get("status") != "Valid"
            or signature.get("embedded") is not True
            or signature.get("rsa") is not True
            or signature.get("timestamp") is not True
            or not signature.get("thumbprint")
            or not signature.get("timestamp_thumbprint")
            or signature.get("sha256") != actual[name]["sha256"]
        ):
            raise ValueError("Invalid/missing signature, timestamp or digest")
        if name in REQUIRED and signature.get("subject") != info["publisher"]:
            raise ValueError("Publisher mismatch")
    if require_checksums and (Path(root) / "SHA256SUMS.txt").read_text() != checksum_text(
        root, manifest
    ):
        raise ValueError("Final SHA256 inventory mismatch")
    return True


def promotion(root, evidence):
    root = Path(root)
    manifest = json.loads((root / "RELEASE_MANIFEST.json").read_text())
    validate(root, manifest)
    if (
        evidence.get("schema") != 1
        or evidence.get("source_commit") != manifest["build"]["source_commit"]
        or evidence.get("manifest_sha256") != sha(root / "RELEASE_MANIFEST.json")
        or evidence.get("setup_sha256") != sha(root / "TanrenCollectorSetup.exe")
    ):
        raise ValueError("Evidence must identify these exact signed bytes/source")
    if (
        evidence.get("windows11") is not True
        or evidence.get("sac_enforced") is not True
        or evidence.get("policy") != "VerifiedAndReputableDesktop"
        or type(evidence.get("code_integrity_blocks")) is not int
        or evidence["code_integrity_blocks"] != 0
    ):
        raise ValueError("Successful enforced SAC evidence required")
    if set(evidence.get("checks", {})) != CHECKS or not all(
        evidence["checks"][k] is True for k in CHECKS
    ):
        raise ValueError("Incomplete native install/upgrade/recovery/rebuild evidence")
    if (
        evidence.get("owner_reviewed") is not True
        or evidence.get("runtime_security_reviewed") is not True
        or not evidence.get("report_reference")
        or not evidence.get("tested_at_utc")
    ):
        raise ValueError("Owner-reviewed native/runtime security report required")
    stamp = datetime.fromisoformat(evidence["tested_at_utc"])
    if (
        stamp.tzinfo is None
        or stamp.utcoffset() != timedelta(0)
        or "REPLACE" in evidence["report_reference"].upper()
    ):
        raise ValueError("Real UTC test report reference required")
    if manifest["build"]["api_origin"] != "https://tanrenway.com":
        raise ValueError("Isolated-target build is not a production release")
    return {
        "status": "production-eligible",
        "published": False,
        "manifest_sha256": sha(root / "RELEASE_MANIFEST.json"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if args.create:
        info = json.loads((args.root / "BUILD_INFO.json").read_text())
        manifest = {
            "schema": 1,
            "status": "signed-candidate",
            "build": info,
            "files": inventory(args.root),
        }
        validate(args.root, manifest, require_checksums=False)
        (args.root / "RELEASE_MANIFEST.json").write_text(json.dumps(manifest, indent=2))
        sums = {
            **manifest["files"],
            "RELEASE_MANIFEST.json": {"sha256": sha(args.root / "RELEASE_MANIFEST.json")},
        }
        (args.root / "SHA256SUMS.txt").write_text(
            "".join(f"{v['sha256']}  {k}\n" for k, v in sorted(sums.items()))
        )
    else:
        validate(args.root, json.loads((args.root / "RELEASE_MANIFEST.json").read_text()))
    gate = (
        promotion(args.root, json.loads(args.evidence.read_text()))
        if args.evidence
        else {
            "status": "BLOCKED",
            "published": False,
            "reason": "Native SAC/upgrade/runtime/owner evidence missing",
        }
    )
    (args.root / "RELEASE_GATE.json").write_text(json.dumps(gate, indent=2))
    print(json.dumps(gate))
