#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import traceback
from pathlib import Path

from PySide6 import QtCore, QtWidgets

# --- 로그/경로 설정 ---
LOCAL_BASE = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "Clifa"
)
LOG_DIR = LOCAL_BASE / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "controller.log"


def _log_write(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8", newline="") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _excepthook(etype, value, tb):
    txt = "\n".join(
        [
            "[FATAL] Unhandled exception in main.py",
            "".join(traceback.format_exception(etype, value, tb)),
        ]
    )
    _log_write(txt)
    try:
        QtWidgets.QMessageBox.critical(
            None, "Clifa", "앱 시작 중 오류가 발생했습니다.\n\n" + str(value)
        )
    except Exception:
        pass


sys.excepthook = _excepthook

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")  # GPU 강제 비활성
from app.controller import AppController
from app.system.tray import TrayManager
from app.ui.popup import PopupWindow


def main():
    try:
        app = QtWidgets.QApplication(sys.argv)

        # QSettings 식별자
        QtCore.QCoreApplication.setOrganizationName("MeinU")
        QtCore.QCoreApplication.setOrganizationDomain("ios.kr")
        QtCore.QCoreApplication.setApplicationName("SearchYourImages")

        app.setQuitOnLastWindowClosed(False)

        popup = PopupWindow()
        controller = AppController(popup)
        tray = TrayManager(app, popup, controller)

        # 첫 실행(설정된 루트 없음) 시 바로 창을 보여 사용자가 종료된 것으로 오해하지 않도록 함
        try:
            s = QtCore.QSettings("Clifa", "Clifa")
            last_root = s.value("last_root_dir", "", type=str)
            if not last_root:
                tray.show_window()
        except Exception:
            # 설정 조회 실패 시에도 창을 표시
            tray.show_window()

        rc = app.exec()
        sys.exit(rc)
    except Exception as e:
        _log_write("[FATAL] main() failed: " + repr(e))
        try:
            QtWidgets.QMessageBox.critical(None, "Clifa", f"앱 시작 실패: {e}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
