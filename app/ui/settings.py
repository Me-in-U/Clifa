from pathlib import Path
from PySide6 import QtCore, QtWidgets


class SettingsDialog(QtWidgets.QDialog):
    root_changed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setModal(True)
        self.setFixedSize(420, 160)

        lay = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.edRoot = QtWidgets.QLineEdit()
        self.btnBrowse = QtWidgets.QPushButton("변경…")
        row.addWidget(QtWidgets.QLabel("이미지 디렉토리"))
        row.addStretch(1)
        lay.addLayout(row)

        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(self.edRoot, 1)
        row2.addWidget(self.btnBrowse)
        lay.addLayout(row2)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        lay.addStretch(1)
        lay.addWidget(btns)

        self.btnBrowse.clicked.connect(self.choose_dir)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        st = QtCore.QSettings()
        self.edRoot.setText(st.value("last_root_dir", "", type=str))

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
        QtCore.QSettings().setValue("last_root_dir", p)

        # ✅ 다이얼로그를 먼저 닫고, 다음 이벤트 루프로 넘겨 emit
        super().accept()
        QtCore.QTimer.singleShot(0, lambda: self.root_changed.emit(p))
