from PySide6 import QtCore
from time import monotonic


class WorkerSignals(QtCore.QObject):
    progress = QtCore.Signal(float, int, int)  # (pct, done, total)
    done = QtCore.Signal(int)  # (added_or_total)
    error = QtCore.Signal(str)  # (msg)
    cancelled = QtCore.Signal()


class CancelToken(QtCore.QObject):  # ✅ 추가
    def __init__(self):
        super().__init__()
        self._cancel = False

    @QtCore.Slot()
    def cancel(self):
        self._cancel = True

    def is_cancelled(self) -> bool:
        return self._cancel


# 쓰로틀 콜백
def _throttled_emit(emit):
    from time import monotonic

    last = 0.0

    def inner(pct, done, total):
        nonlocal last
        now = monotonic()
        if pct >= 100 or now - last >= 0.05 or done == total:
            emit(pct, done, total)
            last = now

    return inner


class AutoIndexWorker(QtCore.QRunnable):
    def __init__(self, searcher, cancel_token: CancelToken | None = None):
        super().__init__()
        self.searcher = searcher
        self.cancel_token = cancel_token
        self.signals = WorkerSignals()

    @QtCore.Slot()
    def run(self):
        try:
            added = self.searcher.index_new_files(
                progress_cb=lambda pct, done, total: self.signals.progress.emit(
                    float(pct), int(done), int(total)
                ),
                cancel_token=self.cancel_token,  # ✅ 전달
            )
            if self.cancel_token and self.cancel_token.is_cancelled():
                self.signals.cancelled.emit()  # ✅ 중간 취소
                return
            self.signals.done.emit(added)
        except Exception as e:
            self.signals.error.emit(str(e))


class InitIndexWorker(QtCore.QRunnable):
    def __init__(self, searcher, cancel_token: CancelToken | None = None):
        super().__init__()
        self.searcher = searcher
        self.cancel_token = cancel_token
        self.signals = WorkerSignals()

    @QtCore.Slot()
    def run(self):
        try:
            self.searcher.build_full_index(
                progress_cb=lambda pct, done, total: self.signals.progress.emit(
                    float(pct), int(done), int(total)
                ),
                cancel_token=self.cancel_token,  # ✅ 전달
            )
            if self.cancel_token and self.cancel_token.is_cancelled():
                self.signals.cancelled.emit()  # ✅
                return
            total = len(getattr(self.searcher, "image_paths", []))
            self.signals.done.emit(total)
        except Exception:
            import traceback

            self.signals.error.emit(traceback.format_exc())
