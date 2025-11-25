from pathlib import Path
from PySide6 import QtCore, QtWidgets, QtGui
from app.win_effects import enable_windows_blur


class SettingsDialog(QtWidgets.QDialog):
    root_changed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setModal(True)
        self.setFixedSize(520, 280)
        # 프레임리스 + 아크릴 배경
        self.setWindowFlags(
            QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # 카드
        self.card = QtWidgets.QFrame()
        self.card.setObjectName("card")
        self.card.setAttribute(QtCore.Qt.WA_NativeWindow, True)
        self.card.setStyleSheet(
            """
            #card { background: rgba(20,20,25,200); border-radius: 14px; }
            QLineEdit {
                padding: 8px 12px; border: 1px solid rgba(255,255,255,40); border-radius: 12px;
                font-size: 13px; background: rgba(35,35,42,230); color: rgba(255,255,255,230);
                selection-background-color: #3a78ff; selection-color: white;
            }
            QPushButton { border-radius: 12px; padding: 6px 12px; border: 1px solid rgba(255,255,255,40); background: rgba(35,35,42,230); color: rgba(255,255,255,230); }
            QPushButton:hover  { background: rgba(45,45,54,230); }
            QPushButton:pressed{ background: rgba(38,38,46,230); }
            QLabel { color: rgba(255,255,255,235); }
            """
        )
        outer.addWidget(self.card)

        shadow = QtWidgets.QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 12)
        shadow.setColor(QtGui.QColor(0, 0, 0, 32))
        self.card.setGraphicsEffect(shadow)

        v = QtWidgets.QVBoxLayout(self.card)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)

        # 헤더(드래그 핸들)
        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("설정")
        title.setStyleSheet("font-weight: 600; color: rgba(255,255,255,235);")
        btn_close = QtWidgets.QPushButton("✕")
        btn_close.setFixedSize(28, 28)
        btn_close.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        btn_close.setStyleSheet("QPushButton{color: rgba(255,255,255,220);} ")
        btn_close.clicked.connect(self.reject)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(btn_close)
        v.addLayout(header)

        form1 = QtWidgets.QHBoxLayout()
        self.edRoot = QtWidgets.QLineEdit()
        self.btnBrowse = QtWidgets.QPushButton("변경…")
        form1.addWidget(QtWidgets.QLabel("이미지 디렉토리"))
        form1.addStretch(1)
        v.addLayout(form1)

        form2 = QtWidgets.QHBoxLayout()
        form2.addWidget(self.edRoot, 1)
        form2.addWidget(self.btnBrowse)
        v.addLayout(form2)

        v.addStretch(1)
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        v.addWidget(btns)

        self.btnBrowse.clicked.connect(self.choose_dir)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        st = QtCore.QSettings("Clifa", "Clifa")
        self.edRoot.setText(st.value("last_root_dir", "", type=str))

        # 블러 적용 및 위치 조정
        QtCore.QTimer.singleShot(0, self._after_show)

    def _after_show(self):
        # 다크 아크릴
        enable_windows_blur(self.card, acrylic=True, opacity=180, color=(20, 20, 25))
        self.card.setGeometry(self.rect())

    # 드래그 이동 지원(프레임리스)
    def mousePressEvent(self, e: QtGui.QMouseEvent):
        if e.button() == QtCore.Qt.LeftButton:
            self._drag_pos = (
                e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            e.accept()

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):
        if getattr(self, "_drag_pos", None) and e.buttons() & QtCore.Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, _):
        self._drag_pos = None

    def choose_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "이미지 폴더 선택", self.edRoot.text() or str(Path.cwd())
        )
        if d:
            self.edRoot.setText(d)

    def accept(self):
        p = self.edRoot.text().strip()
        if not p or not Path(p).exists():
            QtWidgets.QMessageBox.warning(self, "경고", "유효한 폴더를 선택하세요.")
            return
        st = QtCore.QSettings("Clifa", "Clifa")
        st.setValue("last_root_dir", p)

        # ✅ 다이얼로그를 먼저 닫고, 다음 이벤트 루프로 넘겨 emit
        super().accept()
        QtCore.QTimer.singleShot(0, lambda: self.root_changed.emit(p))
