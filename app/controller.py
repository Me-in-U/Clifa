import logging
import os
import sys
from pathlib import Path

import torch
from PySide6 import QtCore, QtGui, QtWidgets

from app.search.visual_ai import VisualAISearchWithProgress
from app.search.worker import (
    AutoIndexWorker,
    CancelToken,
    InitIndexWorker,
    SearchWorker,
)
from app.ui.settings import SettingsDialog

LOCAL_BASE = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "Clifa"
)
LOG_DIR = LOCAL_BASE / "logs"
LOG_FILE = LOG_DIR / "controller.log"

logging.basicConfig(
    level=logging.DEBUG,  # DEBUG/INFO/WARNING/ERROR
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)


class AppController(QtCore.QObject):
    """비즈니스 로직: 인덱싱/검색/감시 + UI 연결"""

    def __init__(self, ui):
        super().__init__()
        self.ui = ui
        self.logger = logging.getLogger("clifa.controller")
        self.pool = QtCore.QThreadPool.globalInstance()
        self.searcher: VisualAISearchWithProgress | None = None
        self.cancel_token = None
        self._indexing_busy = False
        self._autoindex_blocked = False
        self._active_search_worker = None
        self._search_watchdog = None

        # === 공용 QSettings (스코프 고정) ===
        # SettingsDialog 등 다른 모듈과 반드시 동일 스코프를 사용해야 함
        self.settings = QtCore.QSettings("Clifa", "Clifa")

        # === 예외 안전 경로 검사 헬퍼 ===
        def _safe_dir(p: str | Path | None) -> Path | None:
            if not p:
                return None
            try:
                pp = Path(p)
                if pp.exists() and pp.is_dir():
                    return pp
                return None
            except OSError as e:
                # UNC/권한 문제 등으로 exists() 자체가 실패할 수 있음
                QtCore.qWarning(f"[RootCheck] inaccessible: {p} ({e})")
                return None

        # settings에서 루트 복원
        saved = self.settings.value("last_root_dir", "", type=str)

        # 기록이 없으면 Pictures 기본값
        default_dir = Path.home() / "Pictures"
        # 안전하게 후보 결정
        candidate = _safe_dir(saved) or _safe_dir(default_dir)
        # 최종 루트(없으면 default를 그냥 사용하되, 부팅 체크에서 다시 유도)
        self.root_path = candidate or default_dir

        self.logger.debug(f"[QSettings] saved={saved!r}, default={default_dir}")
        self.logger.debug(f"[Boot] candidate={candidate}, root={self.root_path}")

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
        # === exists()/rglob()도 예외 가능성이 있어 안전 래퍼 사용 ===
        def _exists_dir(path: Path) -> bool:
            try:
                return path.exists() and path.is_dir()
            except OSError:
                return False

        def _has_images(path: Path) -> bool:
            IMG_FORMATS = {
                "bmp",
                "dng",
                "jpeg",
                "jpg",
                "mpo",
                "png",
                "tif",
                "tiff",
                "webp",
                "pfm",
            }
            try:
                for f in path.rglob("*"):
                    if f.is_file() and f.suffix.lower().lstrip(".") in IMG_FORMATS:
                        return True
            except Exception:
                pass
            return False

        self.ui.set_progress(0.0, 0, 0)

        # 기본 디렉토리 검증(접근 불가/이미지 없음)
        if not _exists_dir(self.root_path) or not _has_images(self.root_path):
            # 저장값/최종값/사유를 구분해 안내
            saved = self.settings.value("last_root_dir", "", type=str)
            reasons: list[str] = []
            if not _exists_dir(Path(saved)):
                reasons.append(f"저장된 경로 사용 불가: {saved or '(비어있음)'}")
            elif not _has_images(Path(saved)):
                reasons.append(f"저장된 경로에 이미지가 없음: {saved}")
            if not _exists_dir(self.root_path):
                reasons.append(f"변경된 경로 접근 불가: {self.root_path}")
            elif not _has_images(self.root_path):
                reasons.append(f"변경된 경로에 이미지가 없음: {self.root_path}")

            reasons_text = "\n".join(reasons) if reasons else "확인 불가"
            msg = (
                "이미지 폴더 접근/내용 확인에 문제가 있습니다.\n\n"
                f"- 저장된 경로: {saved or '(없음)'}\n"
                f"- 최종 선택 경로: {self.root_path}\n\n"
                f"판단 사유\n {reasons_text}\n\n"
                "설정에서 이미지 폴더를 지정하세요."
            )
            self.logger.warning(msg.replace("\n", " "))

            QtWidgets.QMessageBox.information(self.ui, "디렉토리 문제 발생", msg)
            self.ui.set_progress(100.0, 0, 0)  # 스피너 멈춤
            self.open_settings()  # 바로 설정창 열기
            return  # 인덱싱 중단

        try:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.logger.info(f"[Device] Using {device}")

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
            self.logger.exception("인덱스 로드/생성 실패")
            QtWidgets.QMessageBox.critical(self.ui, "인덱스 로드/생성 실패", f"{e}\n\n")
            self.ui.set_progress(100.0, 0, 0)

    @QtCore.Slot(float, int, int)
    def _on_progress_token(self, pct: float, done: int, total: int):
        self.ui.set_progress(pct, done, total)

    @QtCore.Slot(int)
    def _on_done_token(self, added_or_total: int):
        self._indexing_busy = False
        if added_or_total > 0:
            QtWidgets.QToolTip.showText(
                QtGui.QCursor.pos(), f"신규 {added_or_total}개 반영"
            )
            self.ui.set_progress(100.0, added_or_total, added_or_total)

    @QtCore.Slot(str)
    def _on_error_token(self, msg: str):
        self._indexing_busy = False
        self.logger.error(f"[Index] 에러: {msg}")
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
        # rglob 도중 접근 예외 방어
        try:
            for p in root.rglob("*"):
                try:
                    if p.is_dir():
                        dirs.add(str(p))
                except Exception:
                    continue
        except Exception:
            pass
        if dirs:
            try:
                self.watcher.addPaths(list(dirs))
            except Exception:
                pass

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
            # 오버레이 안전 종료
            try:
                self.ui.set_progress(100.0, 0, 0)
            except Exception:
                pass
            return
        # 이전 검색이 진행 중이면 무시(원하면 취소 로직으로 확장 가능)
        if self._active_search_worker is not None:
            QtWidgets.QToolTip.showText(
                QtGui.QCursor.pos(), "이전 검색이 아직 진행 중입니다…"
            )
            return

        # UI는 busy 오버레이가 이미 표시됨. 워커에서 검색 수행
        worker = SearchWorker(self.searcher, query, k)

        def _on_results(results):
            try:
                self.ui.set_results(self.root_path, results)
            finally:
                self._clear_search_state()

        worker.signals.results.connect(_on_results)
        worker.signals.error.connect(self._on_search_error)

        # 상태 메시지 수신 → 오버레이 busy 텍스트 반영
        def _on_status(msg: str):
            try:
                if msg and msg.strip():
                    self.ui.overlay.set_busy(msg.strip())
                    if not self.ui.overlay.isVisible():
                        self.ui.overlay.show()
            except Exception:
                pass

        worker.signals.status.connect(_on_status)

        # 참조 유지(garbage collection 방지)
        self._active_search_worker = worker
        self.pool.start(worker)

        # 워치독: 60초 초과 시 오버레이 종료 + 안내
        self._search_watchdog = QtCore.QTimer(self)
        self._search_watchdog.setSingleShot(True)
        self._search_watchdog.setInterval(60000)
        self._search_watchdog.timeout.connect(self._on_search_timeout)
        self._search_watchdog.start()

    def _clear_search_state(self):
        # 워커 참조와 워치독 정리
        self._active_search_worker = None
        if self._search_watchdog:
            try:
                self._search_watchdog.stop()
            except Exception:
                pass
            self._search_watchdog = None

    @QtCore.Slot(str)
    def _on_search_error(self, msg: str):
        self.logger.error(f"[Search] 에러: {msg}")
        QtWidgets.QMessageBox.critical(self.ui, "검색 실패", msg)
        # 안전하게 오버레이 종료
        self.ui.set_progress(100.0, 0, 0)
        self._clear_search_state()

    @QtCore.Slot()
    def _on_search_timeout(self):
        # 과도한 지연(모델 다운로드/디바이스 초기화 등) 시 사용자 안내
        self.logger.warning("[Search] 워치독 타임아웃 - 오버레이 종료")
        try:
            self.ui.set_progress(100.0, 0, 0)
        except Exception:
            pass
        QtWidgets.QMessageBox.information(
            self.ui,
            "검색 지연",
            "검색이 예상보다 오래 걸립니다.\n처음 실행 시 모델 다운로드 또는 디바이스 초기화가 진행될 수 있습니다.",
        )
        self._clear_search_state()

    # 파일 열기
    @QtCore.Slot(str)
    def open_file(self, path: str):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}"')
        except Exception as e:
            self.logger.error(f"파일 열기 실패: {path} ({e})")

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

        # 설정값 즉시 저장 (스코프 고정)
        try:
            self.settings.setValue("last_root_dir", str(self.root_path))
        except Exception:
            pass

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
                device = "cuda" if torch.cuda.is_available() else "cpu"
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
                self.logger.exception("인덱스 재생성 실패")
                QtWidgets.QMessageBox.critical(self.ui, "인덱스 재생성 실패", str(e))
                self.ui.set_progress(100.0, 0, 0)

        QtCore.QTimer.singleShot(1000, _start)  # 1000ms 정도만 지연해도 충분

    @QtCore.Slot()
    def cancel_indexing(self):  # ✅ 취소 API
        if self.cancel_token:
            try:
                self.cancel_token.cancel()
            except Exception:
                pass

    @QtCore.Slot(int)
    def _on_autoindex_done(self, added: int):
        self._indexing_busy = False
        if added > 0:
            QtWidgets.QToolTip.showText(
                QtGui.QCursor.pos(), f"신규 {added}개 자동 반영 완료"
            )
        self.ui.set_progress(100, added, added)

    @QtCore.Slot(str)
    def _on_autoindex_error(self, msg: str):
        self._indexing_busy = False
        self.logger.error(f"[AutoIndex] 에러: {msg}")
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
