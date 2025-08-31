@echo off
setlocal

set VENV=.venv
if not exist "%VENV%" (
  echo [*] Creating venv...
  rem Prefer Python Launcher with 3.11 -> 3.10
  where py >nul 2>nul && (
    py -3.11 -m venv "%VENV%" || py -3.10 -m venv "%VENV%"
  ) || (
    rem Fallbacks
    python3.11 -m venv "%VENV%" || python3.10 -m venv "%VENV%" || python -m venv "%VENV%"
  )
)

call "%VENV%\Scripts\activate"
python -m pip install --upgrade pip setuptools wheel
if exist requirements.txt (
  python -m pip install -r requirements.txt
)
python main.py %*

endlocal
