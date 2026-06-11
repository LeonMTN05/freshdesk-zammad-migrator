"""Qt-Worker-Threads, damit die GUI während API-Aufrufen bedienbar bleibt."""
from PySide6.QtCore import QThread, Signal


class FunctionWorker(QThread):
    """Führt eine beliebige Funktion im Hintergrund aus."""
    result = Signal(object)
    error = Signal(str)

    def __init__(self, fn, *args, parent=None, **kwargs):
        super().__init__(parent)
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            self.result.emit(self._fn(*self._args, **self._kwargs))
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class MigrationWorker(QThread):
    """Führt die MigrationEngine aus und reicht Fortschritt/Log als Signale weiter."""
    progress = Signal(int, int, str)
    log_line = Signal(str)
    finished_ok = Signal(dict)
    error = Signal(str)

    def __init__(self, engine, data, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._data = data
        engine.progress_cb = self._emit_progress
        engine.log_cb = self.log_line.emit

    def _emit_progress(self, done, total, msg):
        self.progress.emit(done, total, msg)

    def cancel(self):
        self.engine.cancel()

    def run(self):
        try:
            self.finished_ok.emit(self.engine.run(self._data))
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))
