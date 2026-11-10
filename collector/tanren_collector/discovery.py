"""Bounded local Windows discovery: process image paths, uninstall registry and common roots.

No profile/password/terminal config scraping, no network shares, no automatic terminal attachment.
"""

import os
from pathlib import Path

from .build_profile import ENGINEERING, current


def candidates(running=(), installed=(), roots=()):
    found = {}
    for raw, source in [(p, "running") for p in running] + [(p, "installed") for p in installed]:
        path = Path(raw)
        if not path.is_absolute() or str(path).startswith("\\\\"):
            continue
        if path.is_dir():
            path = path / "terminal64.exe"
        if (
            path.is_absolute()
            and path.name.lower() == "terminal64.exe"
            and path.is_file()
            and not str(path).startswith("\\\\")
        ):
            key = os.path.normcase(str(path.resolve()))
            found.setdefault(key, {"path": str(path.resolve()), "running": False})["running"] |= (
                source == "running"
            )
    for root in roots:
        root = Path(root)
        if root.is_dir():
            # Two directory levels only; never recursively walk the disk or users' profiles.
            paths = [root / "terminal64.exe"]
            for child in list(root.iterdir())[:512]:
                if child.is_dir():
                    paths.append(child / "terminal64.exe")
                    try:
                        paths.extend(
                            p / "terminal64.exe" for p in list(child.iterdir())[:128] if p.is_dir()
                        )
                    except OSError:
                        continue
            for item in candidates(installed=paths):
                found.setdefault(os.path.normcase(item["path"]), item)
    return sorted(found.values(), key=lambda x: (not x["running"], x["path"].lower()))


def running_paths():
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("usage", wintypes.DWORD),
            ("pid", wintypes.DWORD),
            ("heap", ctypes.c_size_t),
            ("module", wintypes.DWORD),
            ("threads", wintypes.DWORD),
            ("parent", wintypes.DWORD),
            ("priority", wintypes.LONG),
            ("flags", wintypes.DWORD),
            ("exe", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return []
    result = []
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(Entry)
        available = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while available:
            if entry.exe.lower() == "terminal64.exe":
                handle = kernel.OpenProcess(0x1000, False, entry.pid)
                if handle:
                    try:
                        buffer = ctypes.create_unicode_buffer(32768)
                        size = wintypes.DWORD(len(buffer))
                        if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                            result.append(buffer.value)
                    finally:
                        kernel.CloseHandle(handle)
            available = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return result


def registry_paths():
    import winreg

    result = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(
                    hive,
                    r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
                    0,
                    winreg.KEY_READ | view,
                ) as root:
                    for index in range(min(winreg.QueryInfoKey(root)[0], 4096)):
                        try:
                            with winreg.OpenKey(root, winreg.EnumKey(root, index)) as key:
                                value = winreg.QueryValueEx(key, "InstallLocation")[0]
                                result.append(value)
                        except OSError:
                            continue
            except OSError:
                continue
    return result


def discover():
    if current() == ENGINEERING:
        return []
    if os.name != "nt":
        return []
    roots = [os.environ.get(name, "") for name in ("ProgramFiles", "ProgramFiles(x86)")]
    roots.append(str(Path(os.environ["LOCALAPPDATA"]) / "Programs"))
    return candidates(running_paths(), registry_paths(), [r for r in roots if r])
