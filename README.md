# 📸 ClipFAISS

> **CLIP + FAISS 기반 로컬 이미지 검색기**  
> 원하는 문장을 입력하면, 이미지 폴더를 인덱싱해 가장 유사한 이미지를 빠르게 찾아줍니다.


<img width="400" alt="image" src="https://github.com/user-attachments/assets/8c14ee31-ed8a-4c20-9f3a-787e664272d4" />


<img width="500" alt="image" src="https://github.com/user-attachments/assets/ff459700-ab2e-42e1-a3a2-6b6c4186d00f" />



## ✨ 주요 기능

- 📂 **이미지 폴더 인덱싱**

  - CLIP 임베딩 + FAISS 인덱스를 활용한 고속 검색
  - 최초 전체 인덱싱 및 변경 감지 기반 자동 인덱싱 지원
  - 진행 상황 표시 (퍼센트 %, 현재/전체 개수)
  - 인덱싱 작업 중 취소 가능

- 🔍 **텍스트 기반 이미지 검색**

  - 자연어 쿼리로 이미지 찾기 (예: `"a dog sitting on a bench"`)
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
  - 로깅 지원 (`LOCALAPPDATA\ClipFAISS\logs`)

---

## 🚀 빌드 및 실행

### .exe 빌드(파이썬 설치된 환경)

```python
py -3.10 -m PyInstaller --noconsole --onefile ^
  --name ClipFAISSLauncher ^
  --add-data "requirements.txt;." ^
  --add-data "main.py;." ^
  --add-data "app;app" ^
  launch.py
```

### 빌드 된 exe실행

- `C:\Users\[User]\AppData\Local\ClipFAISS` 경로에 파이썬 가상환경 및 의존 패키지 자동 설치된 후 자동 실행

### 처음 실행 시 안내

- 설치/초기화 동안 콘솔 창 대신 작은 설치 창(스플래시)이 표시됩니다.
- 단계: 1) 가상환경 생성 → 2) 앱 파일 준비 → 3) PyTorch 설치(CUDA/CPU) → 4) 기타 패키지 → 5) 앱 시작
- 설치 로그는 실시간으로 스플래시에 표시되며, 파일로도 저장됩니다.
- 설치가 끝나면 앱이 트레이로 최소화될 수 있습니다. 트레이 아이콘을 더블클릭하면 창이 열립니다.

### 로그 위치

- 런처 설치 로그: `%LOCALAPPDATA%\ClipFAISS\logs\launcher.log`
- 앱 실행 로그: `%LOCALAPPDATA%\ClipFAISS\logs\controller.log`

### 문제 해결(Troubleshooting)

- 설치 후 바로 꺼지는 것처럼 보일 때:
  - 실제로는 트레이로 최소화되었을 수 있습니다. 트레이 아이콘을 더블클릭해 열어보세요.
  - 위 로그 파일(특히 `controller.log`)에서 오류 메시지를 확인하세요.
  - 네트워크 환경(프록시/방화벽) 이슈로 PyTorch 등 대용량 패키지 설치가 지연/실패할 수 있습니다. `launcher.log`의 마지막 부분을 확인하세요.
- 설치 스플래시를 끄고 싶다면 환경 변수 `CLIPFAISS_NO_SPLASH=1`을 설정 후 실행하세요.

---

## 🖼️ 사용 예시

1. 앱 실행 후 이미지 루트 폴더를 지정합니다.
2. 인덱싱이 완료되면, 검색창에 문장을 입력합니다.
3. 검색 결과에서 원하는 이미지를 더블클릭하면 열립니다.

---

## 🤝 기여

- 버그 제보, 기능 제안은 [Issues](https://github.com/Me-in-U/Clifa/issues)에서 해주세요.
- PR 환영합니다! 🙌
