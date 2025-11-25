from pathlib import Path
import os
import sys
from typing import List

from PySide6 import QtCore, QtGui, QtWidgets

from app.win_effects import enable_windows_blur
from app.ui.widgets.spinner import SpinnerOverlay


class PopupWindow(QtWidgets.QWidget):
    """프레임 없는, 둥근 모서리의 우하단 팝업."""

    request_index = QtCore.Signal()
    request_search = QtCore.Signal(str, int)
    request_open = QtCore.Signal(str)
    request_settings = QtCore.Signal()
    request_cancel = QtCore.Signal()

    def __init__(self):
        super().__init__(
            None, QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool
        )
        # 바깥 윈도우는 완전 투명
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")
        self.setWindowOpacity(1.0)
        self.setWindowTitle("CLIP 검색")

        # 카드 컨테이너
        self.card = QtWidgets.QFrame()
        self.card.setObjectName("card")
        self.card.setAttribute(QtCore.Qt.WA_NativeWindow, True)  # 카드에만 아크릴 적용
        self.card.setStyleSheet(
            """
            /* Apple-inspired light glass, cleaner controls */
            #card { background: rgba(250,250,253,180); border-radius: 16px; }
            QLineEdit {
                padding: 10px 14px; border: 1px solid rgba(0,0,0,28); border-radius: 14px;
                font-size: 14px; background: rgba(255,255,255,235); color: #0b0b0f;
                selection-background-color: #bcd9ff;
            }
            QLineEdit:focus { border: 1px solid #0a84ff; }
            QListWidget { background: rgba(246,248,251,210); border-radius: 10px; color: #0b0b0f; }
            QListWidget::item{ padding-top:4px; border-radius:8px; color: #0b0b0f; }
            QListWidget::item:hover{ background: rgba(10,132,255,0.08); color: #0b0b0f; }
            QListWidget::item:selected{ background: rgba(10,132,255,0.16); color: #0b0b0f; }
            QPushButton { border-radius: 14px; padding: 8px 14px; border: 1px solid rgba(0,0,0,22); background: rgba(255,255,255,235); color: #0b0b0f; }
            QPushButton:hover  { background: rgba(248,248,250,235); }
            QPushButton:pressed{ background: rgba(242,243,247,235); }
            QPushButton#primary { background: #0a84ff; color: white; border: 1px solid #0a84ff; }
            QPushButton#primary:hover { background: #3393ff; }
            QPushButton#primary:pressed { background: #0a74df; }
            QPushButton#iconButton { background: rgba(255,255,255,235); border: 1px solid rgba(0,0,0,18); }
            QPushButton#iconButton:hover { background: rgba(248,248,250,235); }
            QPushButton#iconButton:pressed { background: rgba(242,243,247,235); }

            /* Modern thin scrollbars */
            QScrollBar:vertical {
                background: transparent;
                width: 10px;
                margin: 6px 4px 6px 2px; /* top right bottom left */
                border: none;
            }
            QScrollBar::handle:vertical {
                background: rgba(0,0,0,70);
                border-radius: 5px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(0,0,0,110);
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical,
            QScrollBar::up-arrow:vertical,
            QScrollBar::down-arrow:vertical {
                height: 0; width: 0; border: none; background: transparent;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }

            QScrollBar:horizontal {
                background: transparent;
                height: 10px;
                margin: 4px 6px 2px 6px; /* top right bottom left */
                border: none;
            }
            QScrollBar::handle:horizontal {
                background: rgba(0,0,0,70);
                border-radius: 5px;
                min-width: 24px;
            }
            QScrollBar::handle:horizontal:hover {
                background: rgba(0,0,0,110);
            }
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal,
            QScrollBar::left-arrow:horizontal,
            QScrollBar::right-arrow:horizontal {
                height: 0; width: 0; border: none; background: transparent;
            }
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {
                background: transparent;
            }
            """
        )

        # 카드 그림자
        shadow = QtWidgets.QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 16)
        shadow.setColor(QtGui.QColor(0, 0, 0, 36))
        self.card.setGraphicsEffect(shadow)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.card)

        v = QtWidgets.QVBoxLayout(self.card)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)

        # 결과 그리드
        self.list = QtWidgets.QListWidget()
        self.list.setViewMode(QtWidgets.QListView.IconMode)
        self.list.setIconSize(QtCore.QSize(160, 160))  # 초기값, 이후 동적 조정
        self.list.setResizeMode(QtWidgets.QListView.Adjust)
        self.list.setUniformItemSizes(True)
        self.list.setWrapping(True)
        self.list.setSpacing(8)
        # Smooth pixel-based scrolling for modern feel
        self.list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.list.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.list.setMovement(QtWidgets.QListView.Static)
        self.list.setGridSize(QtCore.QSize(180, 200))  # 초기값, 이후 동적 조정
        self.list.itemDoubleClicked.connect(
            lambda it: self.request_open.emit(it.data(QtCore.Qt.UserRole))
        )
        v.addWidget(self.list, 1)

        # 검색 행
        bottom = QtWidgets.QHBoxLayout()
        self.edQuery = QtWidgets.QLineEdit()
        self.edQuery.setPlaceholderText(
            "한국어, 영어, 일본어, 중국어 등 50개 언어 지원"
        )
        self.edQuery.returnPressed.connect(self._emit_search)
        self.btnSearch = QtWidgets.QPushButton("검색")
        self.btnSearch.setObjectName("primary")
        self.btnSearch.setMinimumHeight(36)
        self.btnSearch.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.btnSettings = QtWidgets.QPushButton()
        self.btnSettings.setObjectName("iconButton")
        self.btnSettings.setFixedSize(36, 36)
        self.btnSettings.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        # 설정 아이콘: 왜곡 방지를 위해 정사각 아이콘 크기와 모드 설정
        settings_icon = QtGui.QIcon(
            str(Path(__file__).parent / "assets" / "settings.svg")
        )
        self.btnSettings.setIcon(settings_icon)
        self.btnSettings.setIconSize(QtCore.QSize(18, 18))
        self.btnSettings.setStyleSheet("QPushButton#iconButton { padding: 0; }")
        bottom.addWidget(self.edQuery, 1)
        bottom.addWidget(self.btnSearch)
        bottom.addWidget(self.btnSettings)
        v.addLayout(bottom)

        # 오버레이
        self.overlay = SpinnerOverlay(self.card)
        self.overlay.hide()
        self.overlay.cancel_clicked.connect(self.request_cancel.emit)

        # 연결
        self.btnSearch.clicked.connect(self._emit_search)
        self.btnSettings.clicked.connect(self.request_settings.emit)

        # 5열 고정
        self._columns = 5

        self.resize(900, 560)
        # 초기 레이아웃이 잡힌 뒤 한번 더 계산
        QtCore.QTimer.singleShot(0, self._recalc_grid)
        self._drag_pos = None

        # 시스템 폰트 적용(가변 폰트 우선)
        try:
            f = QtGui.QFont("Segoe UI Variable", 10)
            if not QtGui.QFontInfo(f).family():
                f = QtGui.QFont("Segoe UI", 10)
            self.setFont(f)
        except Exception:
            pass

    # 드래그 이동
    def mousePressEvent(self, e: QtGui.QMouseEvent):
        if e.button() == QtCore.Qt.LeftButton:
            self._drag_pos = (
                e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            e.accept()

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):
        if self._drag_pos and e.buttons() & QtCore.Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, _):
        self._drag_pos = None

    def show_at_bottom_right(self):
        screen = QtWidgets.QApplication.primaryScreen()
        ag = screen.availableGeometry()
        m = 20
        self.move(ag.right() - self.width() - m, ag.bottom() - self.height() - m)
        self.show()
        self.raise_()
        self.activateWindow()
        enable_windows_blur(self.card, acrylic=True, opacity=180, color=(255, 255, 255))
        self.overlay.setGeometry(self.card.rect())

    # set_progress 교체: 위젯 show/hide + 값 갱신
    def set_progress(self, percent, done: int, total: int):
        # 퍼센트는 float 그대로 전달(0.00% 포맷은 Overlay가 처리)
        self.overlay.set_progress(percent, done, total)

        # 완료 임계값 여유 (99.995 이상이면 100.00%로 표기되는 값)
        try:
            fv = float(percent)
        except Exception:
            fv = 0.0
        if fv >= 99.995:
            # ✅ 강제 hide (isVisible 검사 없이)
            if self.overlay.isVisible():
                self.overlay.hide()
            else:
                # 혹시 다음 이벤트 루프에서 다시 show되는 경쟁을 방지
                QtCore.QTimer.singleShot(0, self.overlay.hide)
        else:
            if not self.overlay.isVisible():
                self.overlay.show()

    def set_results(self, root: Path, results: List[str]):
        self.list.clear()
        for path in results:
            fp = root / path if not os.path.isabs(path) else Path(path)
            if not fp.exists():
                continue
            icon = QtGui.QIcon(str(fp))
            it = QtWidgets.QListWidgetItem(icon, fp.name)
            # 파일명 텍스트는 항상 어두운 색으로 고정(흰색 배경에서도 가독성 확보)
            it.setForeground(QtGui.QBrush(QtGui.QColor("#0b0b0f")))
            it.setToolTip(str(fp))
            it.setData(QtCore.Qt.UserRole, str(fp))
            self.list.addItem(it)
        # 결과 갱신 후에도 5열 유지
        self._recalc_grid()
        # 검색 완료 후 오버레이 닫기 (검색은 빠르게 끝나므로 결과 세팅 후 닫음)
        self.set_progress(100.0, len(results), len(results))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "overlay"):
            self.overlay.setGeometry(self.card.rect())
        # 창 크기 변경 시 5열 유지
        self._recalc_grid()

    @QtCore.Slot()
    def _emit_search(self):
        q = self.edQuery.text().strip()
        if q:
            # 검색 시작: Busy 오버레이 표시
            if not self.overlay.isVisible():
                self.overlay.set_busy("검색 중…")
                self.overlay.show()
            self.request_search.emit(q, 30)

    # (디밍 기능 제거)

    # 내부: 5열 그리드 계산
    def _recalc_grid(self):
        try:
            cols = max(1, int(getattr(self, "_columns", 5)))
            vp = self.list.viewport()
            avail = vp.width()
            if avail <= 0:
                return
            # 간격/패딩 계산
            spacing = self.list.spacing() if hasattr(self.list, "spacing") else 8
            total_spacing = spacing * (cols - 1)

            # 각 셀 폭 계산
            cell_w = max(80, (avail - total_spacing) // cols)

            # 아이콘 크기: 셀보다 약간 작게
            icon_w = max(64, cell_w - 20)
            icon_h = icon_w

            # 텍스트 공간: 폰트 높이 기준으로 대략 1~2줄 여유
            fm = self.list.fontMetrics()
            text_h = fm.height() * 2
            grid_h = icon_h + text_h + 8  # 약간의 여유 패딩

            self.list.setIconSize(QtCore.QSize(icon_w, icon_h))
            self.list.setGridSize(QtCore.QSize(cell_w, grid_h))
        except Exception:
            # 초기화 타이밍 등으로 인한 예외 무시
            pass
