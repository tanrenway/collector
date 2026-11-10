"""Current-user Windows lifecycle primitives. No privileged service or captured passwords."""

import ctypes
import hashlib
import os
import sys
from pathlib import Path

from .build_profile import check_storage_path, current, profile_root


class FileLock:
    def __init__(self, path):
        check_storage_path(path)
        self.file = open(path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                self.file.seek(0)
                if not self.file.read(1):
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            self.file.close()
            raise

    def close(self):
        self.file.close()


def terminal_lock(directory, path):
    name = hashlib.sha256(os.path.normcase(str(Path(path).resolve())).encode()).hexdigest()
    root = Path(directory) / "locks"
    check_storage_path(root)
    root.mkdir(exist_ok=True)
    return FileLock(root / (name + ".lock"))


def data_directory():
    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        raise RuntimeError("WINDOWS_USER_PROFILE_REQUIRED")
    root = profile_root() / "v2"
    check_storage_path(root)
    root.mkdir(parents=True, exist_ok=True)
    # Inherit the private Windows profile ACL, not a shared/custom/network data directory.
    if str(root).startswith("\\\\"):
        raise RuntimeError("LOCAL_PROFILE_REQUIRED")
    return root


def autostart(enabled):
    import winreg

    if not getattr(sys, "frozen", False):
        raise RuntimeError("AUTOSTART_REQUIRES_INSTALLED_BUILD")
    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as registry:
        if enabled:
            winreg.SetValueEx(
                registry,
                current().autostart_value,
                0,
                winreg.REG_SZ,
                f'"{sys.executable}" --background',
            )
        else:
            try:
                winreg.DeleteValue(registry, current().autostart_value)
            except FileNotFoundError:
                pass


class AppMutex:
    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        self.kernel.CreateMutexW.restype = ctypes.c_void_p
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.handle = self.kernel.CreateMutexW(None, False, current().mutex)
        if not self.handle or ctypes.get_last_error() == 183:
            if self.handle:
                self.kernel.CloseHandle(self.handle)
            raise RuntimeError("COLLECTOR_ALREADY_RUNNING")

    def close(self):
        self.kernel.CloseHandle(self.handle)


def autostart_enabled():
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
        ) as registry:
            value = winreg.QueryValueEx(registry, current().autostart_value)[0]
            return value == f'"{sys.executable}" --background'
    except OSError:
        return False


def icon_path():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1] / "build"))
    path = base / "collector.ico"
    return path if path.is_file() else None


def show_existing():
    user = ctypes.WinDLL("user32", use_last_error=True)
    from ctypes import wintypes

    user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user.FindWindowW.restype = wintypes.HWND
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    handle = user.FindWindowW(None, current().display_name)
    if handle:
        user.ShowWindow(handle, 9)
        user.SetForegroundWindow(handle)
        return True
    return False
