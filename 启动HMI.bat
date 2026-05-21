@echo off
title HMI Launcher

cd /d D:\expansion_valve_hmi
if not exist "run.py" (
  echo ERROR: D:\expansion_valve_hmi\run.py not found
  pause
  exit /b 1
)

set PYTHON=C:\Python314\python.exe
if not exist "%PYTHON%" set PYTHON=python

echo Stopping old HMI...
taskkill /F /IM python.exe 1>nul 2>nul
ping -n 3 127.0.0.1 1>nul

echo Starting HMI...
start "HMI" /min "%PYTHON%" run.py --host 0.0.0.0 --port 8010

echo Waiting...
ping -n 5 127.0.0.1 1>nul

echo.
echo HMI started: http://192.168.0.99:8010
echo Log: D:\expansion_valve_hmi\runtime\hmi_stdout.log
start "" http://192.168.0.99:8010
pause
