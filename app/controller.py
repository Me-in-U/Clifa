import os
import sys
from pathlib import Path

import torch
from PySide6 import QtCore, QtGui, QtWidgets
from ultralytics.utils.torch_utils import select_device

from app.search.visual_ai import VisualAISearchWithProgress
from app.search.worker import AutoIndexWorker
from app.ui.settings import SettingsDialog


class AppController(QtCore.QObject):
    """비즈니스 로직: 인덱싱/검색/감시 + UI 연결"""

    def __init__(self, ui):
        super().__init__()
        self.ui = ui
        self.pool = QtCore.QThreadPool.globalInstance()
        self.searcher: VisualAISearchWithProgress | None = None

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

        # 시작 시 인덱스 확인/로드
        QtCore.QTimer.singleShot(0, self._boot_index_check)

    # 진행률
    @QtCore.Slot(int)
    def _on_progress(self, v: int):
        self.ui.set_progress(v)

    def _boot_index_check(self):
        self.ui.set_progress(0)
        # 기본 디렉토리 검증
        if (
            not self.root_path.exists()
            or not any(self.root_path.glob("*.jpg"))
            and not any(self.root_path.glob("*.png"))
        ):
            QtWidgets.QMessageBox.information(
                self.ui,
                "알림",
                f"기본 이미지 폴더({self.root_path})가 비어있거나 존재하지 않습니다.\n설정에서 이미지 폴더를 지정하세요.",
            )
            self.ui.set_progress(100)  # 스피너 멈춤
            self.open_settings()  # 바로 설정창 열기
            return  # 인덱싱 중단

        try:
            device = select_device("0" if torch.cuda.is_available() else "cpu")

            self.searcher = VisualAISearchWithProgress(
                data=str(self.root_path), device=device, progress_cb=self._on_progress
            )

            self._setup_watcher(self.root_path)

            worker = AutoIndexWorker(self.searcher)
            worker.signals.progress.connect(self._on_progress)
            worker.signals.done.connect(self._on_autoindex_done)
            worker.signals.error.connect(self._on_autoindex_error)
            self.pool.start(worker)
        except Exception as e:
            # 이미지 없음/읽기 실패 같은 경우를 안내
            QtWidgets.QMessageBox.critical(self.ui, "인덱스 로드/생성 실패", f"{e}\n\n")

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
        if not self.searcher:
            return
        self._setup_watcher(self.root_path)
        worker = AutoIndexWorker(self.searcher)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.done.connect(self._on_autoindex_done)
        worker.signals.error.connect(self._on_autoindex_error)
        self.pool.start(worker)

    @QtCore.Slot(int)
    def _on_autoindex_done(self, added: int):
        if added > 0:
            QtWidgets.QToolTip.showText(
                QtGui.QCursor.pos(), f"신규 {added}개 자동 반영 완료"
            )
        self.ui.set_progress(100)

    @QtCore.Slot(str)
    def _on_autoindex_error(self, msg: str):
        QtWidgets.QMessageBox.critical(self.ui, "자동 인덱싱 실패", msg)
        self.ui.set_progress(100)

    # 트레이 메뉴용 수동 인덱싱
    @QtCore.Slot()
    def manual_index(self):
        if not self.searcher:
            return
        worker = AutoIndexWorker(self.searcher)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.done.connect(self._on_autoindex_done)
        worker.signals.error.connect(self._on_autoindex_error)
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
        dlg = SettingsDialog(self.ui)
        dlg.root_changed.connect(self._on_root_changed)
        dlg.exec()

    @QtCore.Slot(str)
    def _on_root_changed(self, new_root: str):
        self.root_path = Path(new_root)

        # 1) 스피너 보이기
        self.ui.set_progress(0)

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
                # ⚠️ 생성자에서 인덱스 빌드가 수행되는 구조이므로 지연 호출
                self.searcher = VisualAISearchWithProgress(
                    data=str(self.root_path),
                    device=device,
                    progress_cb=self._on_progress,
                )
                self._setup_watcher(self.root_path)

                # 백그라운드 자동 인덱싱
                worker = AutoIndexWorker(self.searcher)
                worker.signals.progress.connect(self._on_progress)
                worker.signals.done.connect(self._on_autoindex_done)
                worker.signals.error.connect(self._on_autoindex_error)
                self.pool.start(worker)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self.ui, "인덱스 재생성 실패", str(e))
                self.ui.set_progress(100)

        QtCore.QTimer.singleShot(50, _start)  # 50ms 정도만 지연해도 충분
