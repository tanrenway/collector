"""Synthetic profile isolation; no real profile, native MT5, DPAPI or network access."""

import ctypes
import hashlib
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tanren_collector import __version__, build_target
from tanren_collector import build_profile as profile
from tanren_collector.client import Api
from tanren_collector.device_pairing import DeviceStore
from tanren_collector.runtime_store import DeviceReader, account_path
from tanren_collector.storage import DPAPI, ENGINEERING_SEAL, Queue, load_config, save_config
from tanren_collector.windows import FileLock, terminal_lock

REPO = Path(__file__).resolve().parents[2]
BASELINE_SHA256 = "f2b93525d62561727d46c5fda7a6a1a72add4fbd87a9bd55d96c211230aca864"


def installer(engineering, source=None):
    """Evaluate only the conditional/macro subset used by installer.iss, not native Inno."""
    defines = {"MinimumWindowsVersion": "10.0.22621", "DistributionRoot": "TEST-DISTRIBUTION"}
    if engineering:
        defines["EngineeringBuild"] = "1"
    active, stack, lines = True, [], []
    if source is None:
        source = (REPO / "collector/build/installer.iss").read_text(encoding="utf-8")
    for line in source.splitlines():
        if line.startswith(("#ifdef ", "#ifndef ")):
            directive, name = line.split()
            condition = name in defines
            if directive == "#ifndef":
                condition = not condition
            stack.append((active, condition))
            active = active and condition
        elif line == "#else":
            parent, condition = stack[-1]
            active = parent and not condition
        elif line == "#endif":
            active = stack.pop()[0]
        elif active and line.startswith("#define "):
            _, name, value = line.split(maxsplit=2)
            defines[name] = value.strip('"')
        elif active:
            lines.append(re.sub(r"\{#(\w+)\}", lambda match: defines[match[1]], line))
    if stack:
        raise AssertionError("Unbalanced Inno conditionals")
    return "\n".join(lines)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tanren-profile-test-")
        self.addCleanup(self.temporary.cleanup)
        self.local = Path(self.temporary.name)
        self.enterContext(patch.dict(os.environ, {"LOCALAPPDATA": str(self.local)}))
        self.enterContext(patch.object(build_target, "BUILD_PROFILE", "engineering", create=True))
        self.enterContext(patch.object(build_target, "ORIGIN", profile.OFFLINE_ORIGIN))
        self.root = profile.profile_root()
        self.root.mkdir()

    def test_production_defaults_unchanged(self):
        with patch.object(build_target, "BUILD_PROFILE", "production"):
            self.assertEqual(profile.current(), profile.PRODUCTION)
            self.assertEqual(profile.profile_root(), self.local / "TanrenCollector")
            profile.check_storage_path(self.local / "arbitrary-production-compatible-path")
            profile.require_native_mt5()
            profile.require_network()
        self.assertEqual(profile.PRODUCTION.mutex, r"Local\TanrenCollector.Desktop")
        self.assertEqual(profile.PRODUCTION.autostart_value, "TanrenCollector")
        self.assertEqual(profile.PRODUCTION.app_id, "A40F8247-D97C-4BB5-A778-452509E35053")

    def test_identities_differ(self):
        for field in profile.Identity.__dataclass_fields__:
            self.assertNotEqual(
                getattr(profile.PRODUCTION, field), getattr(profile.ENGINEERING, field)
            )

    def test_no_runtime_environment_opt_in(self):
        with (
            patch.object(build_target, "BUILD_PROFILE", "production"),
            patch.dict(
                os.environ, {"BUILD_PROFILE": "engineering", "COLLECTOR_PROFILE": "engineering"}
            ),
        ):
            self.assertEqual(profile.current(), profile.PRODUCTION)

    def test_invalid_profile_fails_closed(self):
        with patch.object(build_target, "BUILD_PROFILE", "unknown"):
            with self.assertRaisesRegex(RuntimeError, "INVALID_BUILD_PROFILE"):
                profile.current()

    def test_production_origin_rejected(self):
        with patch.object(build_target, "ORIGIN", "https://tanrenway.com"):
            with self.assertRaisesRegex(RuntimeError, "INVALID_BUILD_PROFILE"):
                profile.current()

    def test_profile_paths_and_sidecars_are_separate(self):
        for suffix in (".dpapi", ".sqlite", ".sqlite-wal", ".sqlite-shm", ".lock", ".log"):
            profile.check_storage_path(self.root / ("synthetic" + suffix))
            with self.assertRaisesRegex(RuntimeError, "ENGINEERING_PROFILE_PATH_REQUIRED"):
                profile.check_storage_path(self.local / "TanrenCollector" / ("synthetic" + suffix))

    def test_actual_data_directory_uses_engineering_root(self):
        from tanren_collector import windows

        # Model the OS boundary locally; never change global os.name/Path semantics.
        with patch.object(windows, "os", SimpleNamespace(name="nt", environ=os.environ)):
            self.assertEqual(windows.data_directory(), self.root / "v2")
        self.assertFalse((self.local / "TanrenCollector").exists())

    def test_traversal_rejected(self):
        with self.assertRaises(RuntimeError):
            profile.check_storage_path(self.root / ".." / "TanrenCollector" / "config.dpapi")

    def test_symlink_escape_rejected(self):
        target = self.local / "synthetic-other-profile"
        target.mkdir()
        link = self.root / "linked"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks requires Windows permission; no rights changed")
        with self.assertRaises(RuntimeError):
            profile.check_storage_path(link / "queue.sqlite")

    def test_storage_rejects_cross_profile_before_io(self):
        path = self.local / "TanrenCollector" / "synthetic"
        protector = Mock()
        with (
            patch("builtins.open", side_effect=AssertionError("Unexpected file access")),
            patch("sqlite3.connect", side_effect=AssertionError("Unexpected database access")),
        ):
            for operation in (
                lambda: load_config(path, protector),
                lambda: save_config(path, {}, protector),
                lambda: Queue(path, protector),
                lambda: FileLock(path),
                lambda: DeviceStore(path, protector),
                lambda: DeviceReader(path / "v2", protector),
                lambda: account_path(path, "00000000-0000-0000-0000-000000000001"),
                lambda: terminal_lock(path, "synthetic-terminal"),
            ):
                with self.subTest(operation=operation), self.assertRaises(RuntimeError):
                    operation()
        self.assertFalse(path.parent.exists())
        protector.open.assert_not_called()

    def test_dpapi_namespace_rejects_production_before_decryption(self):
        protector = object.__new__(DPAPI)
        protector.transform = Mock(side_effect=AssertionError("Unexpected DPAPI call"))
        with self.assertRaisesRegex(RuntimeError, "ENGINEERING_CREDENTIAL_NAMESPACE_REQUIRED"):
            protector.open(b"synthetic-production-ciphertext")
        protector.transform.assert_not_called()

    def test_dpapi_namespace_roundtrip_with_fake_transform(self):
        protector = object.__new__(DPAPI)
        protector.transform = lambda value, encrypt: value  # Test-only reversible protector.
        sealed = protector.seal(b"synthetic")
        self.assertTrue(sealed.startswith(ENGINEERING_SEAL))
        self.assertEqual(protector.open(sealed), b"synthetic")
        with patch.object(build_target, "BUILD_PROFILE", "production"):
            self.assertEqual(protector.seal(b"synthetic"), b"synthetic")
            self.assertEqual(protector.open(b"synthetic"), b"synthetic")

    def test_dpapi_rejects_false_inner_namespace(self):
        protector = object.__new__(DPAPI)
        protector.transform = Mock(return_value=b"synthetic-other-namespace")
        with self.assertRaisesRegex(RuntimeError, "ENGINEERING_CREDENTIAL_NAMESPACE_REQUIRED"):
            protector.open(ENGINEERING_SEAL + b"synthetic-ciphertext")

    def test_configuration_roundtrip_in_own_profile(self):
        protector = SimpleNamespace(seal=lambda value: value, open=lambda value: value)
        path = self.root / "settings.dpapi"
        save_config(path, {"synthetic": True}, protector)
        self.assertEqual(load_config(path, protector), {"synthetic": True})

    def test_synthetic_sqlite_uses_only_engineering_root(self):
        protector = SimpleNamespace(seal=lambda value: value, open=lambda value: value)
        path = self.root / "synthetic.sqlite"
        queue = Queue(path, protector)
        try:
            self.assertIsNone(queue.pending())
            self.assertEqual(Path(queue.db_path), path)
        finally:
            queue.close()
        self.assertFalse((self.local / "TanrenCollector").exists())

    def test_sqlite_sidecar_reparse_escape_fails_before_io(self):
        path = self.root / "synthetic.sqlite"
        resolve = Path.resolve

        def resolved(candidate):
            if candidate.name.endswith("-wal"):
                return self.local / "synthetic-other-profile/wal"
            return resolve(candidate)

        with (
            patch.object(Path, "resolve", autospec=True, side_effect=resolved),
            patch("builtins.open", side_effect=AssertionError("Unexpected file access")),
            self.assertRaisesRegex(RuntimeError, "ENGINEERING_PROFILE_PATH_REQUIRED"),
        ):
            Queue(path, Mock())

    def test_device_identity_does_not_read_other_profile(self):
        protector = Mock()
        with DeviceStoreForTest(self.root / "device-v3", protector) as store:
            self.assertEqual(store.get(), {})
            protector.open.assert_not_called()
        reader = DeviceReader(self.root / "v2", protector)
        self.assertEqual(reader.path, self.root / "device-v3/device.dpapi")
        self.assertEqual(reader.get(), {})

    def test_pairing_creates_fresh_synthetic_identity(self):
        from tanren_collector.device_pairing import PairingSession

        protector = SimpleNamespace(seal=lambda value: value, open=lambda value: value)
        with DeviceStoreForTest(self.root / "device-v3", protector) as store:
            PairingSession(store).begin("synthetic-code", "Engineering test")
            first = store.get()
        with DeviceStoreForTest(self.root / "other-synthetic-device", protector) as store:
            PairingSession(store).begin("synthetic-code", "Engineering test")
            second = store.get()
        for key in ("claim", "token", "request_id"):
            self.assertNotEqual(first[key], second[key])
        self.assertFalse((self.local / "TanrenCollector").exists())

    def test_runtime_rejects_cross_profile_before_workers(self):
        from tanren_collector.account_registration import RegistrationState
        from tanren_collector.application_runtime import ApplicationRuntime

        path = self.local / "TanrenCollector/v2"
        with patch("tanren_collector.runtime.SpawnPool", side_effect=AssertionError):
            with self.assertRaisesRegex(RuntimeError, "ENGINEERING_PROFILE_PATH_REQUIRED"):
                ApplicationRuntime(path)
        with self.assertRaisesRegex(RuntimeError, "ENGINEERING_PROFILE_PATH_REQUIRED"):
            RegistrationState(path, Mock())
        self.assertFalse(path.parent.exists())

    def test_no_network_even_for_offline_origin(self):
        api = Api(profile.OFFLINE_ORIGIN, "synthetic-token")
        api.opener = Mock()
        with self.assertRaisesRegex(RuntimeError, "ENGINEERING_OFFLINE"):
            api.call("/api/v1/mt5/collector/control")
        api.opener.open.assert_not_called()
        with self.assertRaisesRegex(ValueError, "ENGINEERING_OFFLINE_ORIGIN_REQUIRED"):
            Api("https://tanrenway.com", "synthetic-token")

    def test_no_mt5_initialization_or_import(self):
        from tanren_collector.terminal import Terminal, initialize_readonly

        native = Mock()
        with self.assertRaisesRegex(RuntimeError, "ENGINEERING_MT5_DISABLED"):
            initialize_readonly(native, "synthetic-terminal")
        native.initialize.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "ENGINEERING_MT5_DISABLED"):
            Terminal("synthetic-terminal", {})

    def test_discovery_does_not_inspect_real_terminals(self):
        from tanren_collector import discovery

        with (
            patch.object(discovery, "running_paths", side_effect=AssertionError),
            patch.object(discovery, "registry_paths", side_effect=AssertionError),
        ):
            self.assertEqual(discovery.discover(), [])

    def test_legacy_inventory_and_cli_refuse_engineering(self):
        from tanren_collector.__main__ import main
        from tanren_collector.legacy_transition import inventory

        with self.assertRaisesRegex(RuntimeError, "ENGINEERING_OFFLINE"):
            inventory(self.local / "TanrenCollector/v2", None, None, Mock())
        with self.assertRaisesRegex(RuntimeError, "ENGINEERING_DESKTOP_ONLY"):
            main()

    def test_engineering_log_is_identifiable_and_separate(self):
        import logging

        profile.configure_engineering_log()
        logger = logging.getLogger("tanren_collector.engineering")
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
        text = (self.root / "engineering.log").read_text()
        self.assertIn("ENGINEERING", text)
        self.assertFalse((self.local / "TanrenCollector").exists())

    def test_autostart_uses_engineering_key(self):
        from tanren_collector import windows

        fake = Mock()
        fake.CreateKey.return_value.__enter__ = Mock(return_value="synthetic-key")
        fake.CreateKey.return_value.__exit__ = Mock(return_value=False)
        fake.OpenKey.return_value.__enter__ = Mock(return_value="synthetic-key")
        fake.OpenKey.return_value.__exit__ = Mock(return_value=False)
        fake.QueryValueEx.return_value = (f'"{sys.executable}" --background', 1)
        with (
            patch.dict(sys.modules, {"winreg": fake}),
            patch.object(sys, "frozen", True, create=True),
        ):
            windows.autostart(True)
            self.assertEqual(fake.SetValueEx.call_args.args[1], profile.ENGINEERING.autostart_value)
            windows.autostart(False)
            self.assertEqual(
                fake.DeleteValue.call_args.args[1], profile.ENGINEERING.autostart_value
            )
            self.assertTrue(windows.autostart_enabled())
            self.assertEqual(
                fake.QueryValueEx.call_args.args[1], profile.ENGINEERING.autostart_value
            )

    def test_mutex_and_window_ipc_use_engineering_identity(self):
        from tanren_collector import windows

        kernel, user = Mock(), Mock()
        kernel.CreateMutexW.return_value = 42
        user.FindWindowW.return_value = 0

        def library(name, **_):
            return kernel if name == "kernel32" else user

        with (
            patch.object(
                windows,
                "ctypes",
                SimpleNamespace(
                    WinDLL=library,
                    get_last_error=lambda: 0,
                    c_void_p=ctypes.c_void_p,
                    c_int=ctypes.c_int,
                    c_wchar_p=ctypes.c_wchar_p,
                ),
            ),
        ):
            mutex = windows.AppMutex()
            mutex.close()
            windows.show_existing()
        self.assertEqual(kernel.CreateMutexW.call_args.args[2], profile.ENGINEERING.mutex)
        self.assertEqual(user.FindWindowW.call_args.args[1], profile.ENGINEERING.display_name)

    def test_installer_identities_and_uninstall_scope(self):
        prod, eng = installer(False), installer(True)
        for identity, text in ((profile.PRODUCTION, prod), (profile.ENGINEERING, eng)):
            self.assertIn("AppId={{" + identity.app_id + "}", text)
            self.assertIn("DefaultDirName={localappdata}\\Programs\\" + identity.display_name, text)
            self.assertIn("AppMutex=" + identity.mutex, text)
            self.assertIn('ValueName: "' + identity.autostart_value + '"', text)
            self.assertIn('Name: "{autoprograms}\\' + identity.display_name + '"', text)
        self.assertIn('Name: startup; Description: "{cm:Startup}"; Flags: unchecked', eng)
        self.assertIn('Name: startup; Description: "{cm:Startup}"; Flags: checkedonce', prod)
        self.assertIn("CloseApplications=no", eng)
        self.assertIn("CloseApplications=yes", prod)
        self.assertNotIn("[Run]", eng)
        self.assertIn("[Run]", prod)
        self.assertNotIn("[UninstallDelete]", eng.split("; Deliberately")[0])
        self.assertIn("PrepareToInstall", eng)
        self.assertIn("EngineeringFileAttributes", eng)
        self.assertNotIn("[Code]", prod)
        self.assertNotIn('ValueName: "TanrenCollector"', eng)

    def test_build_profile_is_explicit_and_provenanced(self):
        text = (REPO / "collector/build/build.ps1").read_text()
        self.assertIn("[string]$BuildProfile = 'production'", text)
        self.assertIn("$ApiOrigin -cne 'https://collector-offline.invalid'", text)
        self.assertIn("$Info.build_profile = 'engineering'", text)
        self.assertIn("Clean exact reviewed source SHA required", text)
        self.assertIn("TanrenCollectorEngineeringSetup.exe", text)

    def test_production_installer_configuration_matches_baseline(self):
        # Immutable baseline from 4667d84; works with GitHub's shallow checkout.
        raw = (REPO / "collector/tests/fixtures/installer-baseline-4667d84.iss").read_bytes()
        raw = raw.replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(raw).hexdigest(), BASELINE_SHA256)
        # The baseline guards the installer's configuration; the release number is meant to change.
        # The fixture is the 4667d84 configuration with only the product name renamed to Tanren.
        baseline = raw.decode("utf-8").replace("0.6.0", __version__)

        def normalize(text):
            return [line for line in text.splitlines() if line.strip() and not line.startswith(";")]

        self.assertEqual(normalize(installer(False)), normalize(installer(False, baseline)))


class DeviceStoreForTest(DeviceStore):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


if __name__ == "__main__":
    unittest.main()
