"""Cooperative shutdown: bounded acknowledgement, never force-kill a writing service."""

from PySide6.QtCore import QObject, Qt, QTimer, Signal


class ShutdownGuard(QObject):
    stop = Signal()
    failed = Signal()

    def __init__(self, service, thread, timeout_ms=10000):
        super().__init__()
        self.pending = False
        self.thread = thread
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(timeout_ms)
        self.timer.timeout.connect(self.failed)
        self.stop.connect(service.stop, Qt.ConnectionType.QueuedConnection)
        # quit() is thread-safe. Do not require the GUI event loop to deliver this acknowledgement.
        service.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(self.timer.stop)

    def request(self):
        if self.pending or not self.thread.isRunning():
            return
        self.pending = True
        self.timer.start()
        self.stop.emit()
