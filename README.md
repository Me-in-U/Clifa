# 📸 Clifa

> **CLIP + FAISS 기반 로컬 이미지 검색기**  
> 원하는 문장을 입력하면, 이미지 폴더를 인덱싱해 가장 유사한 이미지를 빠르게 찾아줍니다.

<img width="400" alt="image" src="https://github.com/user-attachments/assets/b2d0a228-1d07-4d96-b50d-7d22588faa92" />

<img width="500" alt="image" src="https://github.com/user-attachments/assets/ff459700-ab2e-42e1-a3a2-6b6c4186d00f" />

## ✨ 주요 기능

- 📂 **이미지 폴더 인덱싱**

  - CLIP 임베딩 + FAISS 인덱스를 활용한 고속 검색
  - 최초 전체 인덱싱 및 변경 감지 기반 자동 인덱싱 지원
  - 진행 상황 표시 (퍼센트 %, 현재/전체 개수)
  - 인덱싱 작업 중 취소 가능

- 🔍 **텍스트 기반 이미지 검색**

  - 자연어 쿼리로 이미지 찾기 (예: `"벤치에 앉아있는 강아지"`, `"a dog sitting on a bench"`)
  - **50개 이상 언어 지원**: 한국어, 영어, 일본어, 중국어 등 다국어 검색 가능
  - Sentence-Transformers Multilingual CLIP 모델 사용
  - 검색 결과 썸네일 + 파일명 그리드 표시
  - 더블클릭 시 원본 이미지 열기

- 🎨 **UI/UX**

  - PySide6 기반 프레임리스 GUI
  - Windows 10+ Acrylic Blur 효과 지원
  - 우하단 팝업 창 + 드래그 이동 가능
  - 시스템 트레이 아이콘 (열기/숨기기, 즉시 인덱싱, 종료)

- ⚙️ **설정 & 안정성**
  - 이미지 루트 디렉토리 지정 (QSettings 저장)
  - 잘못된 경로나 이미지 없음 감지 시 안내
  - 로깅 지원 (`LOCALAPPDATA\Clifa\logs`)

---

## 🚀 빌드 및 실행

### .exe 빌드(파이썬 설치된 환경)

- `C:\Users\[User]\AppData\Local\Clifa` 경로에 파이썬 가상환경 및 의존 패키지 자동 설치된 후 자동 실행

### 처음 실행 시 안내

- 설치/초기화 동안 콘솔 창 대신 작은 설치 창(스플래시)이 표시됩니다.
- 단계: 1) 가상환경 생성 → 2) 앱 파일 준비 → 3) PyTorch 설치(CUDA/CPU) → 4) 기타 패키지 → 5) CLIP 모델 다운로드 → 6) 앱 시작
- **CLIP 모델 다운로드**: 설치 단계에서 이미지 인코더(clip-ViT-B-32)와 다국어 텍스트 인코더(clip-ViT-B-32-multilingual-v1)를 자동으로 다운로드합니다. 네트워크 속도에 따라 수 분 소요될 수 있습니다.
- 설치 진행 상황은 체크리스트(⏳ → 🔄 → ✅)로 실시간 표시되며, 로그는 파일로도 저장됩니다.
- 설치가 끝나면 앱이 트레이로 최소화될 수 있습니다. 트레이 아이콘을 더블클릭하면 창이 열립니다.

### 다국어 검색 지원

- **Multilingual CLIP 모델 사용**: Sentence-Transformers의 `clip-ViT-B-32-multilingual-v1` 모델을 통해 50개 이상 언어를 네이티브 지원합니다.
- **지원 언어**: 한국어(ko), 일본어(ja), 중국어(zh-cn, zh-tw), 영어(en), 독일어(de), 프랑스어(fr), 스페인어(es) 등
- **번역 불필요**: 별도 번역 API 없이 한국어, 일본어 등으로 바로 검색 가능합니다.
- **동작 방식**:
  - 텍스트 쿼리를 다국어 CLIP 인코더로 임베딩 변환
  - 이미지 임베딩과의 유사도를 FAISS로 고속 검색
  - 별도 번역 과정 없이 입력한 언어 그대로 검색

### 로그 위치

- 런처 설치 로그: `%LOCALAPPDATA%\Clifa\logs\launcher.log`
- 앱 실행 로그: `%LOCALAPPDATA%\Clifa\logs\controller.log`

### 문제 해결(Troubleshooting)

- 설치 후 바로 꺼지는 것처럼 보일 때:
  - 실제로는 트레이로 최소화되었을 수 있습니다. 트레이 아이콘을 더블클릭해 열어보세요.
  - 위 로그 파일(특히 `controller.log`)에서 오류 메시지를 확인하세요.
  - 네트워크 환경(프록시/방화벽) 요

---

## 🤝 기여

- 버그 제보, 기능 제안은 [Issues](https://github.com/Me-in-U/Clifa/issues)에서 해주세요.
- PR 환영합니다! 🙌
