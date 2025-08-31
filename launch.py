#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
import io
import datetime

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
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    / "ClipFAISS"
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
os.environ.setdefault("CLIPFAISS_HOME", str(LOCAL_BASE))
os.environ.setdefault("CLIPFAISS_CACHE", str(CACHE_DIR))
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
        from ctypes import windll
        import ctypes

        windll.user32.MessageBoxW(0, body, title, 0x10)
    except Exception:
        print(title, body)


def run(cmd, cwd=None, env=None, check=True, hide_window=False):
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


def create_venv():
    log(f"create_venv: target={VENV_DIR}")
    if VENV_DIR.exists():
        log("create_venv: already exists")
        return
    VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
    log(f"venv ready: {VENV_DIR}")

    # 사용자가 3.11이 없을 수 있으니 3.11 -> 3.10 순으로 시도, 둘 다 없으면 현재 파이썬
    def try_py(tag: str) -> bool:
        try:
            run(["py", f"-{tag}", "-m", "venv", str(VENV_DIR)])
            return True
        except Exception:
            return False

    ok = try_py("3.11")
    if not ok:
        ok = try_py("3.10")

    if not ok:
        # Windows py 런처가 없거나 지정 버전이 없을 때: 현재 파이썬으로 시도
        run([sys.executable, "-m", "venv", str(VENV_DIR)])

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
        ]
    )


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


def choose_torch_index_url():
    log("choosing torch index url …")
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
            print(f"Trying PyTorch with {tag} …")
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
                ]
            )
            return tag, url
        except subprocess.CalledProcessError:
            continue
    # 모두 실패 → CPU
    log("Falling back to CPU PyTorch …")
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
        ]
    )
    return "cpu", "https://download.pytorch.org/whl/cpu"


def pip_install_requirements(req_file: Path):
    log(f"pip install -r {req_file}")
    # 기본 requirements 설치
    run(venv_pip() + ["install", "-r", str(req_file)])
    # Ultralytics가 요구하는 clip가 빠진 경우 대비(사전 설치)
    try:
        run(venv_pip() + ["install", "git+https://github.com/ultralytics/CLIP.git"])
    except subprocess.CalledProcessError:
        # 네트워크/권한 이슈가 있을 수 있으니 치명적 실패로 보지 않고 경고만
        print(
            "WARNING: failed to preinstall ultralytics CLIP; ultralytics may try to auto-install at runtime."
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
    os.environ["CLIPFAISS_HOME"] = str(LOCAL_BASE)
    os.environ["CLIPFAISS_CACHE"] = str(CACHE_DIR)


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


def stage_sources():
    """번들된 main.py, requirements.txt, app/ 를 로컬로 복사/동기화."""
    log("staging bundled sources to LOCALAPPDATA …")
    APP_DIR.mkdir(parents=True, exist_ok=True)
    # app/ 동기화
    if not BUNDLED_APP.exists():
        raise SystemExit("Bundled 'app/' folder is missing in the exe.")
    copytree_update(BUNDLED_APP, APP_DIR)
    # main.py, requirements.txt 복사
    write_bundled_file(BUNDLED_MAIN, APP_DIR / "main.py")
    write_bundled_file(BUNDLED_REQS, LOCAL_BASE / "requirements.txt")
    (APP_DIR / "__init__.py").touch(exist_ok=True)


def start_app():
    export_runtime_env()
    entry = APP_DIR / "main.py"
    if not entry.exists():
        raise SystemExit("Bundled main.py not found inside the exe.")
    # GUI는 pythonw + 콘솔 숨김
    cmd = [venv_pythonw(), "-m", "app.main"]
    log(f"start_app (module): {' '.join(cmd)}  cwd={LOCAL_BASE}")
    run(cmd, cwd=str(LOCAL_BASE), hide_window=True)


def main():
    ensure_log()
    log("===== ClipFAISS Launcher start =====")
    dump_env()

    # 1) venv 준비
    create_venv()

    # 2) 번들된 requirements.txt를 사용자 로컬에 복사
    #    (pip가 파일 경로를 요구하므로 임시로 로컬 복사본을 만들어 사용)
    req_target = LOCAL_BASE / "requirements.txt"
    write_bundled_file(BUNDLED_REQS, req_target)

    stage_sources()

    # 3) PyTorch(CUDA/CPU) 선택 설치
    choose_torch_index_url()

    # 4) 그 외 requirements 설치 + ultralytics/CLIP 사전 설치
    pip_install_requirements(req_target)

    # 5) 앱 실행
    start_app()


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
            messagebox.showerror("ClipFAISS Launcher", msg)
        except Exception:
            pass
        print(msg, file=sys.stderr)
        sys.exit(e.returncode)
