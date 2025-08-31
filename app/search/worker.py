from PySide6 import QtCore


class WorkerSignals(QtCore.QObject):
    progress = QtCore.Signal(int)
    done = QtCore.Signal(int)
    error = QtCore.Signal(str)


class AutoIndexWorker(QtCore.QRunnable):
    def __init__(self, searcher):
        super().__init__()
        self.searcher = searcher
        self.signals = WorkerSignals()

    @QtCore.Slot()
    def run(self):
        try:
            added = self.searcher.index_new_files(
                progress_cb=self.signals.progress.emit
            )
            self.signals.done.emit(added)
        except Exception as e:
            self.signals.error.emit(str(e))
