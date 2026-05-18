@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo 未找到 python，请先安装 Python 3.10+，或把 python.exe 加入 PATH。
  pause
  exit /b 1
)

python run.py --host 127.0.0.1 --port 8010
pause
