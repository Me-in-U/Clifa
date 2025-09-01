import hashlib
import os
from pathlib import Path
from PIL import Image
from typing import List

import numpy as np
import torch
from PySide6 import QtCore
from ultralytics.nn.text_model import build_text_model
from ultralytics.utils.checks import check_requirements
from ultralytics.utils.torch_utils import select_device


import re
import unicodedata


def _slugify_path(p: Path) -> str:
    """
    루트 경로를 OS-안전 ASCII 슬러그 + 해시로 변환.
    - 경로 구분자/콜론은 '_'로 치환
    - 비-ASCII는 제거(NFKD 폴딩)
    - 영문/숫자/._-만 허용, 나머지는 '_' 치환
    - 본문 최대 40자
    """
    # UNC 공유에서도 resolve()가 느리거나 실패할 수 있어 absolute() 사용 권장
    norm = str(p.absolute())
    safe = norm.replace(":", "_").replace("\\", "_").replace("/", "_")
    ascii_fold = (
        unicodedata.normalize("NFKD", safe).encode("ascii", "ignore").decode("ascii")
    )
    ascii_fold = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_fold)
    ascii_fold = ascii_fold[:40].strip("_") or "root"
    h = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:8]
    return f"{ascii_fold}__{h}"


class IndexCancelled(Exception):
    pass


class VisualAISearchWithProgress(QtCore.QObject):
    """Ultralytics CLIP + FAISS 기반 시각 검색."""

    def __init__(
        self,
        data="images",
        device: str | None = None,
        progress_cb=None,
        defer_build: bool = False,
    ):
        super().__init__()
        self.progress_cb = progress_cb

        # === 디바이스 선택(자동) ===
        self.device = device or select_device(
            "0" if torch.cuda.is_available() else "cpu"
        )
        print(f"[VisualAI] using device: {self.device}")
        # ==========================

        # ---- (변경) 캐시/인덱스는 %LOCALAPPDATA%\ClipFAISS\indexes\<slug>\* 로 저장
        # 사용자 폴더 기준
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
        base_cache = local / "ClipFAISS" / "indexes"

        self.data_dir = Path(data).resolve()
        slug = _slugify_path(self.data_dir)  # 루트별 고유 디렉터리
        self.index_dir = base_cache / slug
        # 쓰기 가능 여부 사전 점검 (UNC/권한 문제 조기 감지)
        try:
            self.index_dir.mkdir(parents=True, exist_ok=True)
            testfile = self.index_dir / ".write_test"
            with open(testfile, "wb") as f:
                f.write(b"ok")
            testfile.unlink(missing_ok=True)
        except Exception as e:
            raise RuntimeError(
                f"인덱스 디렉터리에 쓸 수 없습니다: {self.index_dir}\n원인: {e!r}"
            )

        self.faiss_index = str(self.index_dir / "faiss.index")
        self.data_path_npy = str(self.index_dir / "paths.npy")

        # deps & model
        check_requirements("faiss-cpu")
        self.faiss = __import__("faiss")

        self.model = None

        self.index = None
        self.image_paths = []
        if not defer_build:
            self.build_full_index(
                progress_cb=self.progress_cb
            )  # 즉시 빌드(기본), 지연 모드면 건너뜀

    def _ensure_model(self):
        if self.model is None:
            self.model = build_text_model("clip:ViT-L/14", device=self.device)
            try:
                self.model.model.eval()  # 있으면 eval
            except Exception:
                pass

    def build_full_index(self, progress_cb=None, cancel_token=None) -> None:
        from ultralytics.data.utils import IMG_FORMATS

        # 파일 스캔 (하위폴더 포함 권장: rglob)
        files = [
            f
            for f in self.data_dir.rglob("*")
            if f.is_file() and f.suffix.lower().lstrip(".") in IMG_FORMATS
        ]

        # 캐시가 있으면 로드
        if Path(self.faiss_index).exists() and Path(self.data_path_npy).exists():
            self.index = self.faiss.read_index(self.faiss_index)
            self.image_paths = np.load(self.data_path_npy)
            # 진행 UI 동기화 (있다면)
            if progress_cb:
                total = len(self.image_paths)
                progress_cb(100, total, total)
            return

        total = len(files)
        vectors, paths = [], []

        for i, file in enumerate(files, 1):
            if cancel_token and cancel_token.is_cancelled():
                raise IndexCancelled()  # ✅ 중단
            try:
                # 상대경로 저장(동명이인 충돌 방지)
                self._ensure_model()
                vectors.append(self.extract_image_feature(file))
                paths.append(str(file.relative_to(self.data_dir)))
            except Exception:
                pass
            if self.progress_cb and total:
                pct = i * 100.0 / total
                self.progress_cb(pct, i, total)

        if cancel_token and cancel_token.is_cancelled():
            raise IndexCancelled()  # ✅ 마지막 체크

        if self.progress_cb:
            self.progress_cb(100.0, total, total)

        if not vectors:
            print("[VisualAI] No images found in", self.data_dir)
            self.index = None
            self.image_paths = np.array([])
            if self.progress_cb:
                self.progress_cb(100, 0, 0)
            return

        X = np.vstack(vectors).astype("float32")
        self.faiss.normalize_L2(X)

        self.index = self.faiss.IndexFlatIP(X.shape[1])
        self.index.add(X)
        self.image_paths = np.array(paths)

        try:
            self.faiss.write_index(self.index, self.faiss_index)
        except Exception as e:
            raise RuntimeError(
                f"FAISS 인덱스 저장 실패: '{self.faiss_index}'\n"
                f"루트: '{self.data_dir}'\n원인: {e!r}"
            )
        try:
            np.save(self.data_path_npy, self.image_paths)
        except Exception as e:
            raise RuntimeError(
                f"경로 목록 저장 실패: '{self.data_path_npy}'\n"
                f"루트: '{self.data_dir}'\n원인: {e!r}"
            )

        if progress_cb:
            progress_cb(100, total, total)

    def index_new_files(self, progress_cb=None, cancel_token=None):
        from ultralytics.data.utils import IMG_FORMATS

        progress = progress_cb or self.progress_cb
        known = (
            set(map(str, self.image_paths))
            if isinstance(self.image_paths, (list, np.ndarray))
            else set()
        )
        files = [
            f
            for f in self.data_dir.rglob("*")
            if f.is_file() and f.suffix.lower().lstrip(".") in IMG_FORMATS
        ]
        new_files = [f for f in files if str(f.relative_to(self.data_dir)) not in known]

        total = len(new_files)
        if total == 0:
            if progress:
                progress(100, 0, 0)
            return 0

        vectors, names = [], []
        for i, f in enumerate(new_files, 1):
            if cancel_token and cancel_token.is_cancelled():
                raise IndexCancelled()
            try:
                vectors.append(self.extract_image_feature(f))
                names.append(str(f.relative_to(self.data_dir)))  # ✅ 상대경로
            except Exception:
                pass
            if progress:
                pct = i * 100.0 / total
                progress(pct, i, total)

        if self.progress_cb:
            self.progress_cb(100.0, total, total)

        if not vectors:
            return 0

        X = np.vstack(vectors).astype("float32")
        self.faiss.normalize_L2(X)
        if self.index is None:
            self.index = self.faiss.IndexFlatIP(X.shape[1])
        self.index.add(X)

        updated = (
            list(map(str, self.image_paths))
            if isinstance(self.image_paths, (list, np.ndarray))
            else []
        )
        updated.extend(names)
        self.image_paths = np.array(updated)

        self.faiss.write_index(self.index, self.faiss_index)
        np.save(self.data_path_npy, self.image_paths)
        if progress:
            progress(100, total, total)
        return len(names)

    def extract_image_feature(self, path: Path) -> np.ndarray:
        self._ensure_model()
        with Image.open(path) as im:
            im = im.convert("RGB")
            with torch.inference_mode():
                return self.model.encode_image(im).cpu().numpy()

    def extract_text_feature(self, text: str) -> np.ndarray:
        self._ensure_model()
        return self.model.encode_text(self.model.tokenize([text])).cpu().numpy()

    # --- search ---
    def search(
        self, query: str, k: int = 30, similarity_thresh: float = 0.1
    ) -> List[str]:
        text_feat = self.extract_text_feature(query).astype("float32")
        self.faiss.normalize_L2(text_feat)
        D, I = self.index.search(text_feat, k)
        results = [
            (self.image_paths[i], float(D[0][j]))
            for j, i in enumerate(I[0])
            if i >= 0 and D[0][j] >= similarity_thresh
        ]
        results.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in results]
