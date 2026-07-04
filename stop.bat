@echo off
setlocal
cd /d "%~dp0"

echo [news-picker] stopping...

REM backend (whatever listens on :8100)
powershell -NoLogo -Command "$c = Get-NetTCPConnection -LocalPort 8100 -State Listen -ErrorAction SilentlyContinue; if ($c) { Stop-Process -Id $c[0].OwningProcess -Force }"

REM llama-server (9B/35B both)
taskkill /IM llama-server.exe /F >nul 2>&1

REM app (NOTE: kills every electron.exe on this machine)
taskkill /IM electron.exe /F >nul 2>&1

echo [news-picker] stopped.
endlocal
