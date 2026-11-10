"""Native event adapter. Unit dispatch is portable; real Windows lifecycle remains a gate."""

import os

from PySide6.QtCore import QAbstractNativeEventFilter


class NativeEvents(QAbstractNativeEventFilter):
    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge

    def dispatch(self, message, wparam):
        if message == 0x218 and wparam in {4, 7, 18}:
            self.bridge.suspensionRequested.emit(wparam == 4)

    def nativeEventFilter(self, event_type, message):
        if os.name == "nt":
            from ctypes.wintypes import MSG

            value = MSG.from_address(int(message))
            self.dispatch(value.message, value.wParam)
        return False, 0


def reduced_motion():
    if os.name != "nt":
        return False
    import ctypes
    from ctypes.wintypes import BOOL

    enabled = BOOL(True)
    if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
        return not bool(enabled.value)
    return False
