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
            #card { background: rgba(255,255,255,180); border-radius: 14px; }
            QLineEdit {
                padding: 10px 12px; border: 1px solid #d0d0d0; border-radius: 10px;
                font-size: 14px; background: rgba(20,20,20,210); color: #e9eef3;
            }
            QListWidget { background: rgba(30,30,30,180); border-radius: 8px; }
            QPushButton {
                border-radius: 10px; padding: 8px 12px; background: rgba(240,241,245,210);
                border: 1px solid #d0d0d0;
            }
            QPushButton:hover  { background: rgba(230,232,237,210); }
            QPushButton:pressed{ background: rgba(220,223,230,210); }
        """
        )

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.card)

        v = QtWidgets.QVBoxLayout(self.card)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)

        # 결과 그리드
        self.list = QtWidgets.QListWidget()
        self.list.setViewMode(QtWidgets.QListView.IconMode)
        self.list.setIconSize(QtCore.QSize(160, 160))
        self.list.setResizeMode(QtWidgets.QListView.Adjust)
        self.list.setUniformItemSizes(True)
        self.list.setWrapping(True)
        self.list.setGridSize(QtCore.QSize(180, 200))
        self.list.itemDoubleClicked.connect(
            lambda it: self.request_open.emit(it.data(QtCore.Qt.UserRole))
        )
        v.addWidget(self.list, 1)

        # 검색 행
        bottom = QtWidgets.QHBoxLayout()
        self.edQuery = QtWidgets.QLineEdit()
        self.edQuery.setPlaceholderText('예) "a dog sitting on a bench"')
        self.edQuery.returnPressed.connect(self._emit_search)
        self.btnSearch = QtWidgets.QPushButton("검색")
        self.btnSettings = QtWidgets.QPushButton("⚙")
        self.btnSettings.setFixedWidth(42)
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

        self.resize(900, 560)
        self._drag_pos = None

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

        # show/hide만 제어(카운트/퍼센트는 항상 업데이트)
        try:
            fv = float(percent)
        except Exception:
            fv = 0.0
        if fv >= 100.0:
            if self.overlay.isVisible():
                self.overlay.hide()
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
            it.setToolTip(str(fp))
            it.setData(QtCore.Qt.UserRole, str(fp))
            self.list.addItem(it)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "overlay"):
            self.overlay.setGeometry(self.card.rect())

    @QtCore.Slot()
    def _emit_search(self):
        q = self.edQuery.text().strip()
        if q:
            self.request_search.emit(q, 30)
