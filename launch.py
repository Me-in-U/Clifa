#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
import io
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path

# 설치 진행 표시용(초기 venv/pip 단계에서 PySide가 없을 수 있으므로 Tk 사용)
try:
    import tkinter as _tk
    from tkinter import scrolledtext as _scrolled
    from tkinter import ttk as _ttk
except Exception:  # 런타임에 사용 불가 시, 콘솔/로그만 사용
    _tk = None
    _ttk = None
    _scrolled = None

# -----------------------------
# PyInstaller / 일반 실행 구분
# -----------------------------
FROZEN = getattr(sys, "frozen", False)
HERE = Path(sys._MEIPASS) if FROZEN else Path(__file__).parent.resolve()

# 번들 안에 함께 포장할 파일들
BUNDLED_MAIN = HERE / "main.py"  # --add-data 로 포함
BUNDLED_REQS = HERE / "requirements.txt"  # --add-data 로 포함
BUNDLED_APP = HERE / "app"

# 사용자 LocalAppData 쪽으로 모든 상태를 몰아넣음
LOCAL_BASE = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "Clifa"
)
APP_DIR = LOCAL_BASE / "app"
VENV_DIR = LOCAL_BASE / ".venv"
CACHE_DIR = LOCAL_BASE / "cache"
LOG_DIR = LOCAL_BASE / "logs"
LOG_FILE = LOG_DIR / "launcher.log"
LOCAL_BASE.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 환경변수: 캐시/인덱스 경로 강제(앱/ultralytics가 참조)
os.environ.setdefault("CLIFA_HOME", str(LOCAL_BASE))
os.environ.setdefault("CLIFA_CACHE", str(CACHE_DIR))
# Torch/Ultralytics가 임시 다운로드 하는 경로도 사용자 영역으로
os.environ.setdefault("TORCH_HOME", str(CACHE_DIR / "torch"))
os.environ.setdefault("HF_HOME", str(CACHE_DIR / "hf"))
os.environ.setdefault(
    "UV_CACHE_DIR", str(CACHE_DIR / "pip")
)  # 일부 환경에서 pip 캐시로 활용됨

# Ultralytics가 내부적으로 CLIP를 자동 설치하려고 할 때, venv 안에서만 하도록 보호
os.environ.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")


def ensure_log():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # 간단 회전(최근 3개 보관)
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > 5_000_000:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        LOG_FILE.rename(LOG_DIR / f"launcher_{ts}.log")
        # 오래된 로그 3개 초과시 삭제
        olds = sorted(
            LOG_DIR.glob("launcher_*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for p in olds[3:]:
            p.unlink(missing_ok=True)


def log(msg: str):
    ensure_log()
    with open(LOG_FILE, "a", encoding="utf-8", newline="") as f:
        f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


# -----------------------------
# 간단 설치 스플래시(UI)
# -----------------------------
class _InstallerUI:
    """Tk 기반의 아주 단순한 설치 진행 창.

    - 단계 텍스트와 로그를 표시
    - 콘솔 창 없이도 사용자에게 진행 상황을 알려줌
    """

    def __init__(self, total_steps: int = 6):
        self.total_steps = total_steps
        self._step = 0
        self._q: "queue.Queue[tuple[str,str]]" = queue.Queue()
        self._root = None
        self._phase_label = None
        self._progress = None
        self._log = None
        self._closed = threading.Event()

        if _tk is None:
            return  # UI 불가 환경

        self._root = _tk.Tk()
        self._root.title("Clifa 설치 준비 중…")
        self._root.geometry("640x500")
        self._root.attributes("-topmost", True)
        try:
            self._root.iconify()
            self._root.deiconify()
        except Exception:
            pass

        frm = _tk.Frame(self._root)
        frm.pack(fill=_tk.BOTH, expand=True, padx=12, pady=12)

        title = _tk.Label(frm, text="실행 준비 중", font=("Segoe UI", 12, "bold"))
        title.pack(anchor="w")

        self._phase_label = _tk.Label(
            frm,
            text="단계 준비…",
            font=("Segoe UI", 10),
            justify=_tk.LEFT,
            wraplength=480,
        )
        self._phase_label.pack(anchor="w", pady=(6, 8))

        self._progress = _ttk.Progressbar(
            frm, mode="determinate", maximum=self.total_steps
        )
        self._progress.pack(fill=_tk.X)

        hint = _tk.Label(
            frm,
            text=(
                "프로그램 실행시 가상환경/패키지 설치로 수 분 소요될 수 있어요.\n"
                f"로그 파일: {LOG_FILE}"
            ),
            font=("Segoe UI", 9),
            justify=_tk.LEFT,
        )
        hint.pack(anchor="w", pady=(6, 4))

        # 체크리스트 프레임
        checklist_frame = _tk.LabelFrame(
            frm, text="설치 항목", font=("Segoe UI", 9, "bold")
        )
        checklist_frame.pack(fill=_tk.X, pady=(0, 8))

        # 체크리스트 항목들
        self._checklist_items = {}
        items = [
            ("venv", "가상환경 설정"),
            ("files", "앱 파일 준비"),
            ("pytorch", "PyTorch 설치"),
            ("packages", "필수 패키지 설치"),
            ("models", "CLIP 모델 다운로드"),
            ("app", "앱 실행"),
        ]

        for key, label in items:
            item_frame = _tk.Frame(checklist_frame)
            item_frame.pack(fill=_tk.X, padx=8, pady=2)

            status_label = _tk.Label(
                item_frame, text="⏳", font=("Segoe UI", 10), width=2
            )
            status_label.pack(side=_tk.LEFT)

            text_label = _tk.Label(
                item_frame, text=label, font=("Segoe UI", 9), anchor="w"
            )
            text_label.pack(side=_tk.LEFT, fill=_tk.X, expand=True)

            self._checklist_items[key] = {
                "status": status_label,
                "text": text_label,
                "state": "pending",  # pending, running, done
            }

        self._log = _scrolled.ScrolledText(frm, height=12, font=("Consolas", 9))
        self._log.pack(fill=_tk.BOTH, expand=True)
        self._log.insert("end", "설치 로그가 여기에 표시됩니다…\n")
        self._log.configure(state="disabled")

        # 주기적으로 큐 폴링
        self._root.after(80, self._drain)

        # 닫기 요청은 무시(강제 종료 방지)
        def _on_close():
            pass

        self._root.protocol("WM_DELETE_WINDOW", _on_close)

    def start_loop(self):
        if self._root is not None:
            try:
                self._root.mainloop()
            finally:
                self._closed.set()

    def close(self):
        if self._root is not None:
            try:
                self._root.destroy()
            except Exception:
                pass
        self._closed.set()

    # --- 스레드-안전 API (내부적으로 큐에 적재) ---
    def set_phase(self, text: str, step: int | None = None):
        if step is not None:
            self._step = max(self._step, step)
        self._q.put(("phase", text))

    def update_checklist(self, key: str, state: str):
        """체크리스트 항목 상태 업데이트
        state: 'pending' (⏳), 'running' (🔄), 'done' (✅)
        """
        self._q.put(("checklist", (key, state)))

    def append_log(self, text: str):
        # 지나치게 긴 줄은 줄이기
        if len(text) > 4000:
            text = text[:4000] + "…\n"
        self._q.put(("log", text))

    def _drain(self):
        # UI 스레드에서 큐 비우기
        # UI가 파괴되었는지 확인
        if self._root is None:
            return

        try:
            # 루트 윈도우가 아직 살아있는지 확인
            self._root.winfo_exists()
        except _tk.TclError:
            return

        try:
            while True:
                typ, payload = self._q.get_nowait()
                if typ == "phase" and self._phase_label is not None:
                    try:
                        self._phase_label.config(
                            text=f"[{self._step}/{self.total_steps}] {payload}"
                        )
                        if self._progress is not None:
                            self._progress["value"] = min(self.total_steps, self._step)
                    except _tk.TclError:
                        return
                elif typ == "checklist":
                    key, state = payload
                    if key in self._checklist_items:
                        item = self._checklist_items[key]
                        item["state"] = state
                        try:
                            if state == "pending":
                                item["status"].config(text="⏳", fg="gray")
                            elif state == "running":
                                item["status"].config(text="🔄", fg="blue")
                            elif state == "done":
                                item["status"].config(text="✅", fg="green")
                        except _tk.TclError:
                            return
                elif typ == "log" and self._log is not None:
                    try:
                        self._log.configure(state="normal")
                        self._log.insert("end", payload)
                        self._log.see("end")
                        self._log.configure(state="disabled")
                    except _tk.TclError:
                        return
        except queue.Empty:
            pass

        try:
            self._root.after(120, self._drain)
        except _tk.TclError:
            pass


def dump_env():
    log(f"FROZEN={FROZEN}, HERE={HERE}")
    log(f"PYTHON={venv_python() if VENV_DIR.exists() else sys.executable}")
    log(f"LOCAL_BASE={LOCAL_BASE}")
    log(f"APP_DIR={APP_DIR}, VENV_DIR={VENV_DIR}")
    log(f"PATH[0:2]={os.environ.get('PATH','').split(os.pathsep)[:2]}")
    log(f"HTTPS_PROXY={os.environ.get('HTTPS_PROXY')}")
    log(f"HTTP_PROXY={os.environ.get('HTTP_PROXY')}")


def show_error_box(title, body):
    body = str(body) + f"\n\nLog: {LOG_FILE}"
    try:
        import ctypes
        from ctypes import windll

        windll.user32.MessageBoxW(0, body, title, 0x10)
    except Exception:
        print(title, body)


def run(cmd, cwd=None, env=None, check=True, hide_window=False, stream=None):
    ensure_log()
    log(f"RUN: {cmd} (cwd={cwd}, hide_window={hide_window})")
    try:
        creationflags = 0
        startupinfo = None
        if hide_window and os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        with open(LOG_FILE, "a", encoding="utf-8", newline="") as f:
            for line in proc.stdout:
                f.write(line)
                if stream:
                    try:
                        stream(line)
                    except Exception:
                        pass
        rc = proc.wait()
        log(f"EXIT CODE: {rc}")
        if check and rc != 0:
            raise subprocess.CalledProcessError(rc, cmd)
        return rc
    except Exception as e:
        log(f"RUN ERROR: {e!r}")
        if check:
            raise
        return 1


def venv_python() -> str:
    if os.name == "nt":
        return str(VENV_DIR / "Scripts" / "python.exe")
    return str(VENV_DIR / "bin" / "python")


def venv_pythonw() -> str:
    # GUI 실행용(콘솔 없음)
    if os.name == "nt":
        return str(VENV_DIR / "Scripts" / "pythonw.exe")
    return venv_python()


def venv_pip() -> list[str]:
    return [venv_python(), "-m", "pip"]


def create_venv(ui: _InstallerUI | None = None):
    log(f"create_venv: target={VENV_DIR}")
    if ui:
        ui.update_checklist("venv", "running")
    if VENV_DIR.exists():
        log("create_venv: already exists")
        if ui:
            ui.update_checklist("venv", "done")
        return
    VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
    log(f"venv ready: {VENV_DIR}")

    # 사용자가 3.11이 없을 수 있으니 3.11 -> 3.10 순으로 시도, 둘 다 없으면 현재 파이썬
    def try_py(tag: str) -> bool:
        try:
            run(["py", f"-{tag}", "-m", "venv", str(VENV_DIR)], hide_window=True)
            return True
        except Exception:
            return False

    ok = try_py("3.11")
    if not ok:
        ok = try_py("3.10")

    if not ok:
        # Windows py 런처가 없거나 지정 버전이 없을 때: 현재 파이썬으로 시도
        run([sys.executable, "-m", "venv", str(VENV_DIR)], hide_window=True)

    # venv pip 최신화
    run(
        [
            venv_python(),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ],
        hide_window=True,
    )
    if ui:
        ui.update_checklist("venv", "done")


def write_bundled_file(src: Path, dst: Path):
    """번들 내부 파일을 대상 경로로 복사(갱신)."""
    if not src.exists():
        raise SystemExit(f"Bundled file missing: {src}")
    if not dst.exists() or src.read_bytes() != dst.read_bytes():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def detect_nvidia():
    """nvidia-smi로 드라이버/쿠다 대략 감지(없으면 None)."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
        )
        driver = out.strip().splitlines()[0].strip()
        return {"driver": driver}
    except Exception:
        return None


def choose_torch_index_url(ui: _InstallerUI | None = None):
    log("choosing torch index url …")
    if ui:
        ui.update_checklist("pytorch", "running")
    """
    가능한 CUDA 버전을 높은 순서로 시도.
    성공적으로 인스톨되면 그걸로 유지, 모두 실패하면 CPU로.
    """
    # 우선 실제로 CUDA가 보이는지 아주 대략 판단
    nv = detect_nvidia()
    candidates = [
        ("cu128", "https://download.pytorch.org/whl/cu128"),
        ("cu126", "https://download.pytorch.org/whl/cu126"),
        ("cu124", "https://download.pytorch.org/whl/cu124"),
        ("cu121", "https://download.pytorch.org/whl/cu121"),
        ("cu118", "https://download.pytorch.org/whl/cu118"),
    ]
    # GPU가 전혀 감지되지 않으면 바로 CPU로
    if not nv:
        return "cpu", "https://download.pytorch.org/whl/cpu"
    # GPU가 보여도 특정 버전이 안 맞을 수 있어 위에서부터 순차 시도
    for tag, url in candidates:
        try:
            msg = f"PyTorch {tag} 시도 중…"
            print(msg)
            if ui:
                ui.set_phase(msg, step=3)
            run(
                venv_pip()
                + [
                    "install",
                    "--upgrade",
                    "torch",
                    "torchvision",
                    "torchaudio",
                    "--index-url",
                    url,
                ],
                hide_window=True,
                stream=(ui.append_log if ui else None),
            )
            if ui:
                ui.update_checklist("pytorch", "done")
            return tag, url
        except subprocess.CalledProcessError:
            continue
    # 모두 실패 → CPU
    log("Falling back to CPU PyTorch …")
    if ui:
        ui.set_phase("PyTorch CPU 설치로 대체", step=3)
    run(
        venv_pip()
        + [
            "install",
            "--upgrade",
            "torch",
            "torchvision",
            "torchaudio",
            "--index-url",
            "https://download.pytorch.org/whl/cpu",
        ],
        hide_window=True,
        stream=(ui.append_log if ui else None),
    )
    if ui:
        ui.update_checklist("pytorch", "done")
    return "cpu", "https://download.pytorch.org/whl/cpu"


def pip_install_requirements(req_file: Path, ui: _InstallerUI | None = None):
    log(f"pip install -r {req_file}")
    if ui:
        ui.update_checklist("packages", "running")
    # 기본 requirements 설치
    if ui:
        ui.set_phase("기타 패키지 설치", step=4)
    run(
        venv_pip() + ["install", "-r", str(req_file)],
        hide_window=True,
        stream=(ui.append_log if ui else None),
    )
    if ui:
        ui.update_checklist("packages", "done")


def preload_clip_models(ui: _InstallerUI | None = None):
    """sentence-transformers CLIP 모델 사전 다운로드"""
    log("Preloading CLIP models...")
    if ui:
        ui.update_checklist("models", "running")
        ui.set_phase("CLIP 모델 다운로드 (이미지 인코더)", step=5)

    # 임시 스크립트로 모델 다운로드
    script = textwrap.dedent(
        """
        import os
        os.environ['HF_HOME'] = r'{}'
        from sentence_transformers import SentenceTransformer
        print('[1/2] 이미지 인코더 다운로드 중...')
        img_model = SentenceTransformer('clip-ViT-B-32')
        print('[2/2] 텍스트 인코더 다운로드 중...')
        text_model = SentenceTransformer('sentence-transformers/clip-ViT-B-32-multilingual-v1')
        print('모델 다운로드 완료!')
    """
    ).format(CACHE_DIR / "hf")

    try:
        run(
            [venv_python(), "-c", script],
            hide_window=True,
            stream=(ui.append_log if ui else None),
        )
        if ui:
            ui.update_checklist("models", "done")
            ui.set_phase("CLIP 모델 다운로드 완료", step=5)
    except subprocess.CalledProcessError as e:
        log(f"WARNING: 모델 사전 다운로드 실패: {e}")
        if ui:
            ui.append_log(
                f"\n경고: 모델 사전 다운로드 실패. 첫 실행 시 자동 다운로드됩니다.\n"
            )


def export_runtime_env():
    """
    앱이 CUDA 미탐지로 죽지 않게, 기본 장치를 'auto'로 두고
    CUDA가 없으면 자동으로 CPU로 가도록 힌트를 줌.
    또한 인덱스/캐시 경로를 환경변수로 전달.
    """
    os.environ.setdefault("ULTRALYTICS_CACHE_DIR", str(CACHE_DIR / "ultralytics"))
    os.environ.setdefault("UV_CACHE_DIR", str(CACHE_DIR / "pip"))
    # 장치 힌트: 사용자가 main에서 select_device("cuda") 하더라도,
    # CUDA 미탐지면 torch 쪽에서 CPU로 떨어지도록 안내 메시지 최소화
    os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    # 앱에서 읽어 쓸 수 있게
    os.environ["CLIFA_HOME"] = str(LOCAL_BASE)
    os.environ["CLIFA_CACHE"] = str(CACHE_DIR)


def copytree_update(src: Path, dst: Path):
    """src 전체를 dst에 동기화(없으면 복사, 있으면 변경분만 대체)."""
    for root, dirs, files in os.walk(src):
        r = Path(root)
        rel = r.relative_to(src)
        out_dir = dst / rel
        out_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            s = r / f
            d = out_dir / f
            if (
                not d.exists()
                or s.stat().st_mtime_ns != d.stat().st_mtime_ns
                or s.stat().st_size != d.stat().st_size
            ):
                shutil.copy2(s, d)


def stage_sources(ui: _InstallerUI | None = None):
    """번들된 main.py, requirements.txt, app/ 를 로컬로 복사/동기화."""
    log("staging bundled sources to LOCALAPPDATA …")
    if ui:
        ui.update_checklist("files", "running")
    APP_DIR.mkdir(parents=True, exist_ok=True)
    # app/ 동기화
    if not BUNDLED_APP.exists():
        raise SystemExit("Bundled 'app/' folder is missing in the exe.")
    copytree_update(BUNDLED_APP, APP_DIR)
    # main.py, requirements.txt 복사
    write_bundled_file(BUNDLED_MAIN, APP_DIR / "main.py")
    write_bundled_file(BUNDLED_REQS, LOCAL_BASE / "requirements.txt")
    (APP_DIR / "__init__.py").touch(exist_ok=True)
    if ui:
        ui.update_checklist("files", "done")


def start_app(detach: bool = True):
    export_runtime_env()
    # app 패키지로 모듈 실행해야 내부 import(app.*)가 올바르게 동작
    cmd = [venv_pythonw(), "-m", "app.main"]
    log(f"start_app (module): {' '.join(cmd)}  cwd={LOCAL_BASE}")
    if detach:
        # 백그라운드로 앱 시작 후 즉시 리턴
        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW | getattr(
                subprocess, "DETACHED_PROCESS", 0
            )
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        proc = subprocess.Popen(
            cmd,
            cwd=str(LOCAL_BASE),
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        return proc
    else:
        return run(cmd, cwd=str(LOCAL_BASE), hide_window=True)


def main():
    ensure_log()
    log("===== Clifa Launcher start =====")
    dump_env()

    # 스플래시 준비(UI 비사용 모드면 None)
    use_ui = os.environ.get("CLIFA_NO_SPLASH", "0") != "1"
    ui = _InstallerUI(total_steps=6) if use_ui else None

    def _work():
        try:
            # 1) venv 준비
            if ui:
                ui.set_phase("가상환경(.venv) 생성/준비", step=1)
            create_venv(ui)

            # 2) 번들된 파일 스테이징
            if ui:
                ui.set_phase("앱 파일 준비", step=2)
            req_target = LOCAL_BASE / "requirements.txt"
            write_bundled_file(BUNDLED_REQS, req_target)
            stage_sources(ui)

            # 3) PyTorch 설치(환경 자동 선택)
            choose_torch_index_url(ui)

            # 4) 기타 requirements 설치
            pip_install_requirements(req_target, ui)

            # 5) CLIP 모델 사전 다운로드
            preload_clip_models(ui)

            # 6) 앱 실행(백그라운드)
            if ui:
                ui.update_checklist("app", "running")
                ui.set_phase("앱 시작", step=6)
            proc = start_app(detach=True)

            # 헬스체크: 1) 로그 파일이 생기면 즉시 성공
            #          2) 그렇지 않더라도 프로세스가 일정 시간 생존하면 성공으로 간주
            ctrl_log = LOG_DIR / "controller.log"
            alive_deadline = time.time() + 12.0  # 최대 12초 관찰
            ok = False
            while time.time() < alive_deadline:
                # 로그가 생겼으면 성공
                try:
                    if ctrl_log.exists() and ctrl_log.stat().st_size > 0:
                        ok = True
                        if ui:
                            ui.update_checklist("app", "done")
                        break
                except Exception:
                    pass
                # 프로세스가 이미 종료되었으면 실패 가능성 높음 → 즉시 탈출
                try:
                    if proc and proc.poll() is not None:
                        ok = False
                        break
                except Exception:
                    # 핸들 확인 실패 시, 다음 루프로
                    pass
                if ui:
                    ui.append_log(".")
                time.sleep(0.5)

            # 루프 종료 후에도 프로세스가 계속 살아있으면 성공 처리
            if not ok:
                try:
                    if proc and proc.poll() is None:
                        ok = True
                except Exception:
                    pass

            if not ok:
                msg = (
                    "앱이 시작되지 않았습니다. 설치는 완료되었지만 실행 중 오류가 발생했을 수 있습니다.\n\n"
                    f"로그를 확인해 주세요:\n- 런처: {LOG_FILE}\n- 앱: {ctrl_log}"
                )
                show_error_box("Clifa 실행 확인", msg)
        except subprocess.CalledProcessError as e:
            msg = textwrap.dedent(
                f"""
                설치/실행 중 오류가 발생했습니다. (exit {e.returncode})

                CMD: {' '.join(map(str, e.cmd))}

                네트워크 또는 프록시 환경을 확인한 뒤 다시 시도해주세요.
                자세한 내용은 로그를 확인하세요.\n{LOG_FILE}
                """
            ).strip()
            show_error_box("Clifa Launcher", msg)
            if ui:
                ui.append_log("\n" + msg + "\n")
            raise
        finally:
            # UI 닫기
            if ui:
                ui.close()

    if ui:
        t = threading.Thread(target=_work, daemon=True)
        t.start()
        ui.start_loop()
    else:
        _work()


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        # PyInstaller onefile 환경에서 에러 메시지가 묻히는 걸 방지
        msg = textwrap.dedent(
            f"""
        Launch failed with exit code {e.returncode}

        CMD: {' '.join(map(str, e.cmd))}

        If this happened during 'pip install', please check your network / proxy,
        and re-run the launcher.
        """
        ).strip()
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Clifa Launcher", msg)
        except Exception:
            pass
        print(msg, file=sys.stderr)
        sys.exit(e.returncode)
