import hashlib
import os
from pathlib import Path
from typing import List

import numpy as np
import torch
from PySide6 import QtCore
from ultralytics.nn.text_model import build_text_model
from ultralytics.utils.checks import check_requirements
from ultralytics.utils.torch_utils import select_device


def _slugify_path(p: Path) -> str:
    """
    루트 경로를 사람이 알아볼 수 있게 prefix + 해시로 변환.
    예: 'D:\\Photos' -> 'D__Photos__a1b2c3d4'
    """
    norm = str(p.resolve())
    safe = norm.replace(":", "_").replace("\\", "_").replace("/", "_")
    h = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:8]
    return f"{safe}__{h}"


class VisualAISearchWithProgress(QtCore.QObject):
    """Ultralytics CLIP + FAISS 기반 시각 검색."""

    def __init__(self, data="images", device: str | None = None, progress_cb=None):
        super().__init__()
        self.progress_cb = progress_cb

        # === 디바이스 선택(자동) ===
        self.device = select_device("0" if torch.cuda.is_available() else "cpu")
        print(f"[VisualAI] using device: {self.device}")
        # ==========================

        # ---- (변경) 캐시/인덱스는 %LOCALAPPDATA%\ClipFAISS\indexes\<slug>\* 로 저장
        # 사용자 폴더 기준
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
        base_cache = local / "ClipFAISS" / "indexes"

        self.data_dir = Path(data).resolve()
        slug = _slugify_path(self.data_dir)  # 루트별 고유 디렉터리
        self.index_dir = base_cache / slug
        self.index_dir.mkdir(parents=True, exist_ok=True)

        self.faiss_index = str(self.index_dir / "faiss.index")
        self.data_path_npy = str(self.index_dir / "paths.npy")

        # deps & model
        check_requirements("faiss-cpu")
        self.faiss = __import__("faiss")

        self.model = build_text_model("clip:ViT-B/32", device=self.device)

        self.index = None
        self.image_paths = []
        self.load_or_build_index()

    def load_or_build_index(self) -> None:
        from ultralytics.data.utils import IMG_FORMATS

        if Path(self.faiss_index).exists() and Path(self.data_path_npy).exists():
            self.index = self.faiss.read_index(self.faiss_index)
            self.image_paths = np.load(self.data_path_npy)
            return

        files = [
            f
            for f in self.data_dir.iterdir()
            if f.suffix.lower().lstrip(".") in IMG_FORMATS
        ]
        total = len(files)
        vectors, paths = [], []

        for i, file in enumerate(files, 1):
            try:
                vectors.append(self.extract_image_feature(file))
                paths.append(file.name)
            except Exception:
                pass
            if self.progress_cb and total:
                self.progress_cb(int(i * 100 / total))

        if not vectors:
            print("[VisualAI] No images found in", self.data_dir)
            self.index = None
            self.image_paths = np.array([])
            if self.progress_cb:
                self.progress_cb(100)
            return

        X = np.vstack(vectors).astype("float32")
        self.faiss.normalize_L2(X)

        self.index = self.faiss.IndexFlatIP(X.shape[1])
        self.index.add(X)
        self.image_paths = np.array(paths)

        self.faiss.write_index(self.index, self.faiss_index)
        np.save(self.data_path_npy, self.image_paths)

    def index_new_files(self, progress_cb=None):
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
        new_files = [f for f in files if f.name not in known]

        total = len(new_files)
        if total == 0:
            if progress:
                progress(100)
            return 0

        vecs, names = [], []
        for i, f in enumerate(new_files, 1):
            try:
                vecs.append(self.extract_image_feature(f))
                names.append(f.name)
            except Exception:
                pass
            if progress:
                progress(int(i * 100 / total))

        if not vecs:
            return 0

        X = np.vstack(vecs).astype("float32")
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
            progress(100)
        return len(names)

    # --- feature utils ---
    def extract_image_feature(self, path: Path) -> np.ndarray:
        from PIL import Image

        return self.model.encode_image(Image.open(path)).cpu().numpy()

    def extract_text_feature(self, text: str) -> np.ndarray:
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
