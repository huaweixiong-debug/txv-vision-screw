@echo off
setlocal
cd /d "%~dp0"
title Expansion Valve HMI Launcher

set "PORT=8010"
set "HOST=0.0.0.0"
set "URL=http://192.168.0.99:8010/"
set "PYTHON_EXE=C:\Python314\python.exe"

if not exist "%PYTHON_EXE%" (
  for /f "delims=" %%i in ('where python 2^>nul') do (
    set "PYTHON_EXE=%%i"
    goto :python_found
  )
  echo [ERROR] Python not found. Please install Python or verify C:\Python314\python.exe exists.
  pause
  exit /b 1
)

:python_found
echo [1/4] Stopping old HMI process...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$procs = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*run.py*--port %PORT%*' }; foreach($p in $procs){ try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {} }" >nul 2>nul

echo [2/4] Starting HMI service...
start "ExpansionValveHMI" /min "%PYTHON_EXE%" run.py --host %HOST% --port %PORT% >> "runtime\hmi_stdout.log" 2>> "runtime\hmi_stderr.log"

echo [3/4] Waiting for service...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ok = $false; for($i = 0; $i -lt 30; $i++){ try { $r = Invoke-WebRequest -UseBasicParsing '%URL%api/health' -TimeoutSec 2; if($r.StatusCode -eq 200){ $ok = $true; break } } catch {}; Start-Sleep -Milliseconds 500 }; if(-not $ok){ exit 1 }"
if errorlevel 1 (
  echo [ERROR] Service failed to start. Check Python, camera, or port usage.
  pause
  exit /b 1
)

echo [4/4] Opening browser...
start "" "%URL%"
echo HMI started: %URL%
exit /b 0
