@echo off
setlocal
cd /d "%~dp0"

echo [news-picker] starting...

REM ---- prerequisites -------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv not found.
  echo   py -3.13 -m venv .venv
  echo   .venv\Scripts\python -m pip install -r server\requirements.txt
  pause
  exit /b 1
)
if not exist "runtime\llama.cpp\llama-server.exe" (
  echo ERROR: llama-server not installed.
  echo   powershell -ExecutionPolicy Bypass -File scripts\install-llama-server.ps1
  pause
  exit /b 1
)
if not exist "dist\index.html" (
  echo [news-picker] dist not found, building UI...
  call npm run build
  if errorlevel 1 (
    pause
    exit /b 1
  )
)

REM ---- 1. llama-server 9B (skips if already running) -----------------------
powershell -NoLogo -ExecutionPolicy Bypass -File scripts\start-llama-server.ps1 -Model 9b

REM ---- 2. backend on :8100 (skip if already listening) ---------------------
powershell -NoLogo -Command "if (Get-NetTCPConnection -LocalPort 8100 -State Listen -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if %errorlevel%==0 (
  echo [news-picker] starting backend on :8100 ...
  start "news-picker backend" /min cmd /c ".venv\Scripts\python -m uvicorn server.api:app --port 8100"
) else (
  echo [news-picker] backend already running.
)

REM ---- 3. wait for backend health ------------------------------------------
powershell -NoLogo -Command "$ok=$false; foreach($i in 1..60){ try { Invoke-RestMethod http://127.0.0.1:8100/categories -TimeoutSec 2 | Out-Null; $ok=$true; break } catch { Start-Sleep -Milliseconds 500 } }; if($ok){ exit 0 } else { exit 1 }"
if not %errorlevel%==0 (
  echo ERROR: backend did not become healthy. Check the backend window.
  pause
  exit /b 1
)

REM ---- 4. app (ELECTRON_RUN_AS_NODE must be cleared; see CLAUDE.md) --------
set ELECTRON_RUN_AS_NODE=
start "news-picker" node_modules\electron\dist\electron.exe .

echo [news-picker] started. Close this window freely.
endlocal
