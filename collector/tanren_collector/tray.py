"""Native Windows notification icon; only UI/lifecycle messages, no privileged service."""

import ctypes
from ctypes import wintypes

from .build_profile import current
from .windows import icon_path

MESSAGE = 0x8000 + 57


class Tray:
    def __init__(self, root, show, sync, quit_app, resume, pause=None):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.shell = ctypes.WinDLL("shell32", use_last_error=True)
        self.user.GetParent.argtypes = [wintypes.HWND]
        self.user.GetParent.restype = wintypes.HWND
        self.user.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
        self.user.LoadIconW.restype = wintypes.HICON
        root.update_idletasks()
        self.hwnd = self.user.GetParent(root.winfo_id()) or root.winfo_id()
        self.callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )
        self.user.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        self.user.SetWindowLongPtrW.restype = ctypes.c_void_p
        self.user.CallWindowProcW.argtypes = [
            ctypes.c_void_p,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user.CallWindowProcW.restype = ctypes.c_ssize_t
        self.user.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
        self.restart = self.user.RegisterWindowMessageW("TaskbarCreated")
        self.show, self.sync, self.quit_app, self.resume = show, sync, quit_app, resume
        self.can_sync = lambda: True
        self.can_pause = lambda: pause is not None
        self.pause = pause
        self.labels = ("Open " + current().display_name, "Sync now", "Quit")
        self.procedure = self.callback_type(self.dispatch)
        self.previous = self.user.SetWindowLongPtrW(
            self.hwnd, -4, ctypes.cast(self.procedure, ctypes.c_void_p)
        )
        if not self.previous:
            raise RuntimeError("TRAY_UNAVAILABLE")

        class Icon(ctypes.Structure):
            _fields_ = [
                ("size", wintypes.DWORD),
                ("window", wintypes.HWND),
                ("id", wintypes.UINT),
                ("flags", wintypes.UINT),
                ("message", wintypes.UINT),
                ("icon", wintypes.HICON),
                ("tip", wintypes.WCHAR * 128),
                ("state", wintypes.DWORD),
                ("mask", wintypes.DWORD),
                ("info", wintypes.WCHAR * 256),
                ("version", wintypes.UINT),
                ("title", wintypes.WCHAR * 64),
                ("info_flags", wintypes.DWORD),
                ("guid", ctypes.c_byte * 16),
                ("balloon_icon", wintypes.HICON),
            ]

        self.icon = Icon()
        self.icon.size = ctypes.sizeof(Icon)
        self.icon.window = self.hwnd
        self.icon.id = 1
        self.icon.flags = 7
        self.icon.message = MESSAGE
        self.own_icon = None
        if icon_path():
            self.user.LoadImageW.argtypes = [
                wintypes.HINSTANCE,
                wintypes.LPCWSTR,
                wintypes.UINT,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            self.user.LoadImageW.restype = wintypes.HANDLE
            self.own_icon = self.user.LoadImageW(None, str(icon_path()), 1, 0, 0, 0x10 | 0x40)
        self.icon.icon = self.own_icon or self.user.LoadIconW(None, ctypes.c_void_p(32512))
        self.icon.tip = current().display_name
        self.shell.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(Icon)]
        if not self.shell.Shell_NotifyIconW(0, ctypes.byref(self.icon)):
            self.close()
            raise RuntimeError("TRAY_UNAVAILABLE")

    def set_status(self, text):
        self.icon.tip = (current().display_name + " · " + text)[:127]
        self.shell.Shell_NotifyIconW(1, ctypes.byref(self.icon))

    def notify(self, title, text):
        self.icon.title = title[:63]
        self.icon.info = text[:255]
        self.icon.flags = 0x10
        try:
            self.shell.Shell_NotifyIconW(1, ctypes.byref(self.icon))
        finally:
            self.icon.flags = 1 | 2 | 4

    def menu(self):
        self.user.CreatePopupMenu.restype = wintypes.HMENU
        self.user.AppendMenuW.argtypes = [
            wintypes.HMENU,
            wintypes.UINT,
            ctypes.c_size_t,
            wintypes.LPCWSTR,
        ]
        self.user.TrackPopupMenu.argtypes = [
            wintypes.HMENU,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            ctypes.c_void_p,
        ]
        self.user.DestroyMenu.argtypes = [wintypes.HMENU]
        self.user.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        menu = self.user.CreatePopupMenu()
        try:
            for key, label in enumerate(self.labels, 1):
                disabled = (key == 2 and not self.can_sync()) or (key == 4 and not self.can_pause())
                self.user.AppendMenuW(menu, 1 if disabled else 0, key, label)
            point = wintypes.POINT()
            self.user.GetCursorPos(ctypes.byref(point))
            self.user.SetForegroundWindow(self.hwnd)
            choice = self.user.TrackPopupMenu(menu, 0x100 | 2, point.x, point.y, 0, self.hwnd, None)
            action = {1: self.show, 2: self.sync, 3: self.quit_app, 4: self.pause}.get(choice)
            if action:
                action()
        finally:
            self.user.DestroyMenu(menu)

    def dispatch(self, hwnd, message, wparam, lparam):
        try:
            if message == 0x11:
                return 1
            if message == 0x16 and wparam:
                self.quit_app()
                return 0
            if message == MESSAGE:
                if lparam in (0x202, 0x203):
                    self.show()
                elif lparam == 0x205:
                    self.menu()
                return 0
            if message == self.restart and hasattr(self, "icon"):
                self.shell.Shell_NotifyIconW(0, ctypes.byref(self.icon))
            if message == 0x218 and wparam in (7, 18):
                self.resume()
        except Exception:
            # Native callbacks cannot propagate/log arbitrary exception contents.
            self.callback_failed = True
        return self.user.CallWindowProcW(self.previous, hwnd, message, wparam, lparam)

    def close(self):
        if hasattr(self, "icon"):
            self.shell.Shell_NotifyIconW(2, ctypes.byref(self.icon))
        if getattr(self, "previous", None):
            self.user.SetWindowLongPtrW(self.hwnd, -4, self.previous)
            self.previous = None
        if getattr(self, "own_icon", None):
            self.user.DestroyIcon.argtypes = [wintypes.HICON]
            self.user.DestroyIcon(self.own_icon)
            self.own_icon = None
