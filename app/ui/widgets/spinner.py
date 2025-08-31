from PySide6 import QtCore, QtGui, QtWidgets


class Spinner(QtWidgets.QWidget):
    """회전하는 원형 스피너(도넛 아크)"""

    def __init__(self, size=64, parent=None):
        super().__init__(parent)
        self._angle = 0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(16)  # ~60fps
        self.setFixedSize(size, size)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)

    def _on_tick(self):
        self._angle = (self._angle + 6) % 360
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        rect = self.rect().adjusted(4, 4, -4, -4)

        # 배경 링
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 70), 6))
        p.drawEllipse(rect)

        # 회전 아크
        pen_fg = QtGui.QPen(QtGui.QColor(180, 190, 230, 220), 6)
        pen_fg.setCapStyle(QtCore.Qt.RoundCap)
        p.setPen(pen_fg)
        start = int((90 - self._angle) * 16)
        span = int(-270 * 16)
        p.drawArc(rect, start, span)


class SpinnerOverlay(QtWidgets.QWidget):
    """카드 위를 덮는 반투명 오버레이 + 중앙 스피너 + %"""

    cancel_clicked = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(
            QtCore.Qt.WA_TransparentForMouseEvents, False
        )  # 인덱싱 중 클릭 막기
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.hide()

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(QtCore.Qt.AlignCenter)

        inner = QtWidgets.QWidget(self)
        inner.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        v = QtWidgets.QVBoxLayout(inner)
        v.setAlignment(QtCore.Qt.AlignCenter)
        v.setSpacing(10)

        # 스피너
        self.spinner = Spinner(56, inner)

        # % 라벨
        self.lab = QtWidgets.QLabel("0 %", inner)
        self.lab.setStyleSheet(
            "color: rgba(255,255,255,230); font-size: 18px; font-weight: 600;"
        )

        # 현재/전체 라벨
        self.labCount = QtWidgets.QLabel("0/0", inner)
        self.labCount.setStyleSheet(
            "color: rgba(255,255,255,220); font-size: 13px; font-weight: 500;"
        )
        # 취소 버튼
        self.btnCancel = QtWidgets.QPushButton("취소", inner)
        self.btnCancel.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.btnCancel.setFixedWidth(96)
        self.btnCancel.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,230); border:1px solid #bbb; "
            "border-radius:8px; padding:6px 10px;}"
            "QPushButton:hover{background:rgba(245,245,245,230);}"
        )

        # 레이아웃 배치
        v.addWidget(self.spinner, 0, QtCore.Qt.AlignHCenter)
        v.addWidget(self.lab, 0, QtCore.Qt.AlignHCenter)
        v.addWidget(self.labCount, 0, QtCore.Qt.AlignHCenter)
        v.addWidget(self.btnCancel, 0, QtCore.Qt.AlignHCenter)
        lay.addWidget(inner)

        # 시그널 연결
        self.btnCancel.clicked.connect(self.cancel_clicked.emit)

    def set_percent(self, v):
        # float 허용 + 0.00% 포맷
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        fv = max(0.0, min(100.0, fv))
        self.lab.setText(f"{fv:.2f} %")

    # 추가: 현재/전체 세터
    def set_counts(self, done: int, total: int):
        self.labCount.setText(f"{done}/{total}")

    # 한 번에 업데이트
    def set_progress(self, v, done: int, total: int):
        # 퍼센트/카운트 항상 동시에 업데이트
        self.set_percent(v)
        self.set_counts(int(done), int(total))

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QtGui.QColor(30, 30, 40, 120))
