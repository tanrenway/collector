"""Portable trust gate tests with fake PE/signature records, NOT native Authenticode proof."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "release_manifest", Path(__file__).parents[1] / "build/release_manifest.py"
)
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


@pytest.fixture
def candidate(tmp_path):
    for name in policy.REQUIRED | {"TanrenCollector/_internal/native.pyd"}:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = bytearray(128)
        data[:2] = b"MZ"
        data[60] = 64
        data[64:68] = b"PE\0\0"
        data[68:70] = b"\x64\x86"
        path.write_bytes(data)
    info = {
        "source_commit": "a" * 40,
        "source_clean": True,
        "signed_uninstaller": True,
        "provider": "certificate-store",
        "publisher": "CN=Fixture",
        "api_origin": "https://tanrenway.com",
    }
    (tmp_path / "BUILD_INFO.json").write_text(json.dumps(info))
    report = {
        name: {
            "status": "Valid",
            "embedded": True,
            "rsa": True,
            "timestamp": True,
            "subject": "CN=Fixture",
            "thumbprint": "A" * 40,
            "timestamp_thumbprint": "B" * 40,
            "sha256": policy.sha(tmp_path / name),
        }
        for name in policy.inventory(tmp_path)
        if policy.is_pe(tmp_path / name)
    }
    (tmp_path / "SIGNATURE_REPORT.json").write_text(json.dumps(report))
    manifest = {
        "schema": 1,
        "status": "signed-candidate",
        "build": info,
        "files": policy.inventory(tmp_path),
    }
    (tmp_path / "RELEASE_MANIFEST.json").write_text(json.dumps(manifest))
    (tmp_path / "SHA256SUMS.txt").write_text(policy.checksum_text(tmp_path, manifest))
    return tmp_path, manifest


def evidence(root):
    return {
        "schema": 1,
        "source_commit": "a" * 40,
        "manifest_sha256": policy.sha(root / "RELEASE_MANIFEST.json"),
        "setup_sha256": policy.sha(root / "TanrenCollectorSetup.exe"),
        "windows11": True,
        "sac_enforced": True,
        "policy": "VerifiedAndReputableDesktop",
        "code_integrity_blocks": 0,
        "checks": dict.fromkeys(policy.CHECKS, True),
        "owner_reviewed": True,
        "runtime_security_reviewed": True,
        "report_reference": "fixture-not-real-evidence",
        "tested_at_utc": "2026-10-25T12:00:00Z",
    }


def test_intact_candidate_and_exact_evidence_format(candidate):
    root, manifest = candidate
    assert policy.validate(root, manifest)
    assert policy.promotion(root, evidence(root))["published"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "NotSigned"),
        ("status", "HashMismatch"),
        ("embedded", False),
        ("timestamp", False),
        ("timestamp", "true"),
        ("rsa", False),
        ("timestamp_thumbprint", ""),
        ("sha256", "0" * 64),
    ],
)
def test_unsigned_tampered_ecc_or_missing_timestamp_never_pass(candidate, field, value):
    root, manifest = candidate
    report = json.loads((root / "SIGNATURE_REPORT.json").read_text())
    report["TanrenCollectorSetup.exe"][field] = value
    (root / "SIGNATURE_REPORT.json").write_text(json.dumps(report))
    manifest["files"] = policy.inventory(
        root
    )  # Even recomputing metadata cannot hide bad predicate.
    with pytest.raises(ValueError):
        policy.validate(root, manifest)


def test_payload_or_inventory_change_rejected(candidate):
    root, manifest = candidate
    (root / "TanrenCollector/_internal/native.pyd").write_bytes(b"MZtampered")
    with pytest.raises(ValueError):
        policy.validate(root, manifest)


def test_unreported_native_dependency_rejected(candidate):
    root, manifest = candidate
    path = root / "TanrenCollector/extra.bin"
    path.write_bytes((root / "TanrenCollectorSetup.exe").read_bytes())
    manifest["files"] = policy.inventory(root)
    with pytest.raises(ValueError, match="Every PE"):
        policy.validate(root, manifest)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_clean", False),
        ("source_commit", "main"),
        ("signed_uninstaller", False),
        ("provider", "unsigned-review"),
    ],
)
def test_bad_source_or_unsigned_build_metadata_rejected(candidate, field, value):
    root, manifest = candidate
    manifest["build"][field] = value
    with pytest.raises(ValueError):
        policy.validate(root, manifest)


@pytest.mark.parametrize(
    "field,value",
    [
        ("sac_enforced", False),
        ("sac_enforced", 1),
        ("windows11", False),
        ("setup_sha256", "0" * 64),
        ("manifest_sha256", "0" * 64),
        ("source_commit", "b" * 40),
        ("code_integrity_blocks", 1),
        ("code_integrity_blocks", False),
        ("owner_reviewed", False),
        ("runtime_security_reviewed", False),
        ("report_reference", ""),
        ("report_reference", "REPLACE_REPORT"),
        ("tested_at_utc", "2026-10-25T12:00:00"),
        ("tested_at_utc", "invalid-date"),
    ],
)
def test_incomplete_wrong_artifact_or_failed_sac_evidence_blocks(candidate, field, value):
    root, _ = candidate
    report = evidence(root)
    report[field] = value
    with pytest.raises(ValueError):
        policy.promotion(root, report)


def test_each_native_acceptance_case_mandatory(candidate):
    root, _ = candidate
    for check in policy.CHECKS:
        report = evidence(root)
        del report["checks"][check]
        with pytest.raises(ValueError):
            policy.promotion(root, report)


def test_checksum_document_must_match_verified_payload(candidate):
    root, manifest = candidate
    (root / "SHA256SUMS.txt").write_text("wrong")
    with pytest.raises(ValueError, match="SHA256"):
        policy.validate(root, manifest)


def test_vendor_fetch_hash_and_traversal_guards(tmp_path, monkeypatch):
    import hashlib
    import io
    import zipfile

    spec = importlib.util.spec_from_file_location(
        "fetch_trust_tools", Path(__file__).parents[1] / "build/fetch_trust_tools.py"
    )
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)

    def archive(name):
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w") as output:
            output.writestr(name, b"fixture-vendor-tool")
        return result.getvalue()

    blob = archive("bin/tool.exe")
    lock = {
        name: {
            "url": "https://api.nuget.org/v3-flatcontainer/fixture.zip",
            "sha256": hashlib.sha256(blob).hexdigest(),
            "file": "bin/tool.exe",
            "file_sha256": hashlib.sha256(b"fixture-vendor-tool").hexdigest(),
        }
        for name in ("sdk", "artifact_client")
    }

    class Opener:
        def open(self, *args, **kwargs):
            return io.BytesIO(blob)

    monkeypatch.setattr(fetch.urllib.request, "build_opener", lambda *args: Opener())
    result = fetch.fetch(lock, tmp_path / "valid")
    assert Path(result["sdk"]).read_bytes() == b"fixture-vendor-tool"
    lock["sdk"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        fetch.fetch(lock, tmp_path / "bad-hash")
    blob = archive("../../escape.exe")
    lock["sdk"]["sha256"] = hashlib.sha256(blob).hexdigest()
    with pytest.raises(ValueError, match="path"):
        fetch.fetch(lock, tmp_path / "bad-path")
    assert not (tmp_path / "escape.exe").exists()


@pytest.mark.parametrize(
    "name", ["TanrenCollector/TanrenCollector.exe", "TanrenCollector/_internal/native.pyd"]
)
def test_wrong_architecture_rejected_before_signature_metadata(candidate, name):
    root, _ = candidate
    path = root / name
    data = bytearray(path.read_bytes())
    data[68:70] = b"\x4c\x01"
    path.write_bytes(data)
    with pytest.raises(ValueError, match="architecture"):
        policy.inventory(root)


@pytest.mark.parametrize("gate", sorted(policy.CHECKS))
def test_each_native_gate_individually_fails_closed(candidate, gate):
    root, _ = candidate
    proof = evidence(root)
    proof["checks"][gate] = False
    with pytest.raises(ValueError):
        policy.promotion(root, proof)


@pytest.mark.parametrize("name", sorted(policy.REQUIRED))
def test_missing_windows_binary_cannot_form_inventory(candidate, name):
    root, _ = candidate
    (root / name).unlink()
    with pytest.raises(ValueError, match="Missing application/installer"):
        policy.inventory(root)


def test_missing_native_signing_report_cannot_validate(candidate):
    root, manifest = candidate
    (root / "SIGNATURE_REPORT.json").unlink()
    manifest["files"] = policy.inventory(root)
    with pytest.raises(FileNotFoundError):
        policy.validate(root, manifest)
