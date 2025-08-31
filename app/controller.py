import os
import sys
from pathlib import Path

import torch
from PySide6 import QtCore, QtGui, QtWidgets
from ultralytics.utils.torch_utils import select_device

from app.search.visual_ai import VisualAISearchWithProgress
from app.search.worker import AutoIndexWorker, CancelToken, InitIndexWorker
from app.ui.settings import SettingsDialog
from ultralytics.data.utils import IMG_FORMATS


class AppController(QtCore.QObject):
    """비즈니스 로직: 인덱싱/검색/감시 + UI 연결"""

    def __init__(self, ui):
        super().__init__()
        self.ui = ui
        self.pool = QtCore.QThreadPool.globalInstance()
        self.searcher: VisualAISearchWithProgress | None = None
        self.cancel_token = None
        self._indexing_busy = False
        self._autoindex_blocked = False
        # settings에서 루트 복원
        st = QtCore.QSettings()
        root = st.value("last_root_dir", "", type=str)

        # 기록이 없으면 Pictures 기본값
        default_dir = Path.home() / "Pictures"
        self.root_path = Path(root) if root and Path(root).exists() else default_dir

        # 파일 변경 감시 & 디바운스
        self.watcher = QtCore.QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self._on_dir_changed)
        self.debounce = QtCore.QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(1200)
        self.debounce.timeout.connect(self._on_fs_debounced)

        # UI 신호 연결
        self.ui.request_search.connect(self.on_search)
        self.ui.request_open.connect(self.open_file)
        self.ui.request_settings.connect(self.open_settings)
        self.ui.request_cancel.connect(self.cancel_indexing)

        # 시작 시 인덱스 확인/로드
        QtCore.QTimer.singleShot(0, self._boot_index_check)

    # 진행률
    @QtCore.Slot(float, int, int)
    def _on_progress(self, percent: float, done: int, total: int):
        self.ui.set_progress(percent, done, total)

    def _boot_index_check(self):
        def _has_images(path: Path) -> bool:
            try:
                for f in path.rglob("*"):
                    if f.is_file() and f.suffix.lower().lstrip(".") in IMG_FORMATS:
                        return True
            except Exception:
                pass
            return False

        self.ui.set_progress(0.0, 0, 0)
        # 기본 디렉토리 검증
        if not self.root_path.exists() or not _has_images(self.root_path):
            QtWidgets.QMessageBox.information(
                self.ui,
                "알림",
                f"기본 이미지 폴더({self.root_path})가 비어있거나 존재하지 않습니다.\n설정에서 이미지 폴더를 지정하세요.",
            )
            self.ui.set_progress(100.0, 0, 0)  # 스피너 멈춤
            self.open_settings()  # 바로 설정창 열기
            return  # 인덱싱 중단

        try:
            device = select_device("0" if torch.cuda.is_available() else "cpu")

            self.searcher = VisualAISearchWithProgress(
                data=str(self.root_path),
                device=device,
                progress_cb=self._on_progress,
                defer_build=True,  # ✅ 생성 가볍게
            )

            self._setup_watcher(self.root_path)

            # ✅ 초기 전체 빌드는 전용 워커로
            self.cancel_token = CancelToken()
            self._indexing_busy = True
            init = InitIndexWorker(self.searcher, self.cancel_token)
            init.signals.progress.connect(self._on_progress_token)
            init.signals.done.connect(self._on_done_token)
            init.signals.error.connect(self._on_error_token)
            init.signals.cancelled.connect(self._on_autoindex_cancelled)
            self.pool.start(init)
        except Exception as e:
            # 이미지 없음/읽기 실패 같은 경우를 안내
            QtWidgets.QMessageBox.critical(self.ui, "인덱스 로드/생성 실패", f"{e}\n\n")

    @QtCore.Slot(float, int, int)
    def _on_progress_token(self, pct: float, done: int, total: int):
        self.ui.set_progress(pct, done, total)

    @QtCore.Slot(int)
    def _on_done_token(self, added_or_total: int):
        if added_or_total > 0:
            QtWidgets.QToolTip.showText(
                QtGui.QCursor.pos(), f"신규 {added_or_total}개 반영"
            )
            self.ui.set_progress(100.0, 0, 0)

    @QtCore.Slot(str)
    def _on_error_token(self, msg: str):
        QtWidgets.QMessageBox.critical(self.ui, "인덱싱 실패", msg)
        self.ui.set_progress(100.0, 0, 0)

    # 감시 경로 구성
    def _setup_watcher(self, root: Path):
        try:
            if self.watcher.directories():
                self.watcher.removePaths(self.watcher.directories())
        except Exception:
            pass
        dirs = {str(root)}
        for p in root.rglob("*"):
            if p.is_dir():
                dirs.add(str(p))
        if dirs:
            self.watcher.addPaths(list(dirs))

    # 변경 이벤트 → 디바운스
    @QtCore.Slot(str)
    def _on_dir_changed(self, _path: str):
        self.debounce.start()

    # 디바운스 만료 → 자동 인덱싱
    def _on_fs_debounced(self):
        if not self.searcher or self._autoindex_blocked or self._indexing_busy:
            return
        self.cancel_token = CancelToken()
        self._indexing_busy = True
        worker = AutoIndexWorker(self.searcher, self.cancel_token)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.done.connect(self._on_autoindex_done)
        worker.signals.error.connect(self._on_autoindex_error)
        worker.signals.cancelled.connect(self._on_autoindex_cancelled)  # ✅
        self.pool.start(worker)

    # 트레이 메뉴용 수동 인덱싱
    @QtCore.Slot()
    def manual_index(self):
        if not self.searcher:
            return
        self.cancel_indexing()
        self.cancel_token = CancelToken()  # ✅
        self._indexing_busy = True
        worker = AutoIndexWorker(self.searcher, self.cancel_token)  # ✅ 토큰 전달
        worker.signals.progress.connect(self._on_progress)
        worker.signals.done.connect(self._on_autoindex_done)
        worker.signals.error.connect(self._on_autoindex_error)
        worker.signals.cancelled.connect(self._on_autoindex_cancelled)
        self.pool.start(worker)

    # 검색
    @QtCore.Slot(str, int)
    def on_search(self, query: str, k: int):
        if not self.searcher:
            QtWidgets.QMessageBox.warning(
                self.ui, "경고", "인덱싱이 완료되지 않았습니다."
            )
            return
        try:
            results = self.searcher.search(query, k=k)
            self.ui.set_results(self.root_path, results)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self.ui, "검색 실패", str(e))

    # 파일 열기
    @QtCore.Slot(str)
    def open_file(self, path: str):
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')

    # 설정
    @QtCore.Slot()
    def open_settings(self):
        # 인덱싱 중이면 취소
        self.cancel_indexing()  # ✅
        self._autoindex_blocked = True  # ✅ 자동 인덱싱 잠금
        try:
            dlg = SettingsDialog(self.ui)
            dlg.root_changed.connect(self._on_root_changed)
            dlg.exec()
        finally:
            self._autoindex_blocked = False  # ✅ 해제

    @QtCore.Slot(str)
    def _on_root_changed(self, new_root: str):
        self.root_path = Path(new_root)

        # 1) 스피너 보이기
        self.ui.set_progress(0.0, 0, 0)

        # 2) 비모달 정보 팝업 (스피너/메인 UI 동작 방해 X)
        m = QtWidgets.QMessageBox(self.ui)
        m.setIcon(QtWidgets.QMessageBox.Information)
        m.setWindowTitle("인덱싱 시작")
        m.setText(
            f"이미지 폴더를 '{self.root_path}'로 설정했습니다.\n인덱싱을 시작합니다…"
        )
        m.setStandardButtons(QtWidgets.QMessageBox.Ok)
        m.setModal(False)
        m.show()

        # 3) 다음 이벤트 루프에서 무거운 초기화 시작 (UI 그려질 시간 확보)
        def _start():
            try:
                device = select_device("0" if torch.cuda.is_available() else "cpu")
                self.searcher = VisualAISearchWithProgress(
                    data=str(self.root_path),
                    device=device,
                    progress_cb=self._on_progress,
                    defer_build=True,  # ✅ 생성 가볍게
                )
                self._setup_watcher(self.root_path)

                # 진행 중 작업 취소 + 새 토큰으로 교체
                self.cancel_indexing()  # 이전 작업 중단 요청
                self.cancel_token = CancelToken()  # ✅ 반드시 새 토큰 생성
                self._indexing_busy = True

                # ✅ 초기 전체 빌드는 전용 워커로 (UI 비블로킹)
                init = InitIndexWorker(self.searcher, self.cancel_token)
                init.signals.progress.connect(self._on_progress)
                init.signals.done.connect(self._on_autoindex_done)
                init.signals.error.connect(self._on_autoindex_error)
                init.signals.cancelled.connect(self._on_autoindex_cancelled)
                self.pool.start(init)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self.ui, "인덱스 재생성 실패", str(e))
                self.ui.set_progress(100.0, 0, 0)

        QtCore.QTimer.singleShot(150, _start)  # 150ms 정도만 지연해도 충분

    @QtCore.Slot()
    def cancel_indexing(self):  # ✅ 취소 API
        if self.cancel_token:
            self.cancel_token.cancel()

    @QtCore.Slot(int)
    def _on_autoindex_done(self, added: int):
        self._indexing_busy = False
        if added > 0:
            QtWidgets.QToolTip.showText(
                QtGui.QCursor.pos(), f"신규 {added}개 자동 반영 완료"
            )
        self.ui.set_progress(100.0, 0, 0)

    @QtCore.Slot(str)
    def _on_autoindex_error(self, msg: str):
        box = QtWidgets.QMessageBox(self.ui)
        box.setIcon(QtWidgets.QMessageBox.Critical)
        box.setWindowTitle("자동 인덱싱 실패")
        # 첫 줄은 본문, 전체는 Details 로
        first = (msg or "").strip().splitlines()
        box.setText(first[0] if first else "예외가 발생했지만 메시지가 없습니다.")
        box.setDetailedText(msg or "")
        # 텍스트 복사/선택 가능
        box.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard
        )
        box.exec()
        self.ui.set_progress(100.0, 0, 0)

    @QtCore.Slot()
    def _on_autoindex_cancelled(self):
        self._indexing_busy = False
        self.ui.set_progress(100.0, 0, 0)
