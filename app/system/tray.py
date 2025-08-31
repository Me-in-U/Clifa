from PySide6 import QtCore, QtWidgets, QtGui


class TrayManager(QtCore.QObject):
    """시스템 트레이 아이콘 + 메뉴 + 윈도우 표시/숨김 제어"""

    def __init__(
        self,
        app: QtWidgets.QApplication,
        window: QtWidgets.QMainWindow,
        controller=None,
    ):
        super().__init__()
        self.app = app
        self.window = window
        self.controller = controller

        icon = QtGui.QIcon.fromTheme("system-search")
        if icon.isNull():
            icon = self.app.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)

        self.tray = QtWidgets.QSystemTrayIcon(icon, self)
        self.tray.setToolTip("CLIP 이미지 검색")

        menu = QtWidgets.QMenu()
        act_show = menu.addAction("열기 / 복원")
        act_hide = menu.addAction("숨기기")
        menu.addSeparator()
        act_index = menu.addAction("지금 인덱싱")
        menu.addSeparator()
        act_quit = menu.addAction("종료")

        act_show.triggered.connect(self.show_window)
        act_hide.triggered.connect(self.hide_window)
        act_index.triggered.connect(self.controller.manual_index)
        act_quit.triggered.connect(self.quit_app)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

        self.window.hide()
        self.tray.showMessage(
            "CLIP 이미지 검색",
            "트레이에 있습니다. 아이콘을 더블클릭하면 열립니다.",
            QtWidgets.QSystemTrayIcon.Information,
            3000,
        )
        self._install_close_to_tray()

    @QtCore.Slot()
    def show_window(self):
        if hasattr(self.window, "show_at_bottom_right"):
            self.window.show_at_bottom_right()
        else:
            self.window.show()

    @QtCore.Slot()
    def hide_window(self):
        self.window.hide()

    @QtCore.Slot(QtWidgets.QSystemTrayIcon.ActivationReason)
    def on_tray_activated(self, reason):
        if reason in (
            QtWidgets.QSystemTrayIcon.DoubleClick,
            QtWidgets.QSystemTrayIcon.Trigger,
        ):
            if self.window.isVisible():
                self.hide_window()
            else:
                self.show_window()

    @QtCore.Slot()
    def quit_app(self):
        self.tray.hide()
        self.app.quit()

    def _install_close_to_tray(self):
        def _close_event(ev: QtGui.QCloseEvent):
            ev.ignore()
            self.hide_window()
            self.tray.showMessage(
                "CLIP 이미지 검색",
                "앱이 트레이로 최소화되었습니다.",
                QtWidgets.QSystemTrayIcon.Information,
                2000,
            )

        self.window.closeEvent = _close_event  # type: ignore
