#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
from PySide6 import QtCore, QtWidgets

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")  # GPU 강제 비활성
from app.ui.popup import PopupWindow
from app.controller import AppController
from app.system.tray import TrayManager


def main():
    app = QtWidgets.QApplication(sys.argv)

    # QSettings 식별자
    QtCore.QCoreApplication.setOrganizationName("MeinU")
    QtCore.QCoreApplication.setOrganizationDomain("ios.kr")
    QtCore.QCoreApplication.setApplicationName("SearchYourImages")

    app.setQuitOnLastWindowClosed(False)

    popup = PopupWindow()
    controller = AppController(popup)
    tray = TrayManager(app, popup, controller)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
