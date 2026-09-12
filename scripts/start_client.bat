@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM NightOwls — start one peer client on a Tailscale / LAN network.
REM
REM Usage:
REM   scripts\start_client.bat http://100.x.y.z:5000
REM   scripts\start_client.bat http://100.x.y.z:5000 --port 6001
REM   set TRACKER_URL=http://100.x.y.z:5000 && scripts\start_client.bat
REM
REM Prerequisites:
REM   - Tailscale connected (or set PEER_IP / pass --ip)
REM   - Tracker already running and reachable at TRACKER_URL

cd /d "%~dp0\.."
set "ROOT=%CD%"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
set "PIP=%ROOT%\.venv\Scripts\pip.exe"

if not defined PEER_PORT set "PEER_PORT=6001"
if not defined PEER_HOST set "PEER_HOST=0.0.0.0"
if not defined PEER_DATA_DIR set "PEER_DATA_DIR=%USERPROFILE%\NightOwls-data"

:parse
if "%~1"=="" goto after_parse
if /I "%~1"=="-h" goto show_help
if /I "%~1"=="--help" goto show_help
if /I "%~1"=="--port" (
  if "%~2"=="" (
    echo error: --port needs a value
    exit /b 1
  )
  set "PEER_PORT=%~2"
  shift
  shift
  goto parse
)
if /I "%~1"=="--ip" (
  if "%~2"=="" (
    echo error: --ip needs a value
    exit /b 1
  )
  set "PEER_IP=%~2"
  shift
  shift
  goto parse
)
if /I "%~1"=="--data-dir" (
  if "%~2"=="" (
    echo error: --data-dir needs a value
    exit /b 1
  )
  set "PEER_DATA_DIR=%~2"
  shift
  shift
  goto parse
)
echo %~1| findstr /B /I "http:// https://" >nul
if not errorlevel 1 (
  set "TRACKER_URL=%~1"
  shift
  goto parse
)
echo error: unknown argument: %~1
goto show_help

:after_parse
if not defined TRACKER_URL (
  echo error: TRACKER_URL is required (pass it as the first argument).
  echo.
  goto show_help
)

REM strip trailing slash
if "!TRACKER_URL:~-1!"=="/" set "TRACKER_URL=!TRACKER_URL:~0,-1!"

if not defined PEER_IP (
  where tailscale >nul 2>&1
  if errorlevel 1 (
    echo error: Tailscale CLI not found and PEER_IP not set.
    echo   Install Tailscale, or pass --ip ^<your-tailscale-ip^>
    exit /b 1
  )
  for /f "usebackq delims=" %%I in (`tailscale ip -4 2^>nul`) do (
    if not defined PEER_IP set "PEER_IP=%%I"
  )
  if not defined PEER_IP (
    echo error: could not detect Tailscale IP.
    echo   Connect Tailscale, or pass --ip ^<your-tailscale-ip^>
    exit /b 1
  )
  echo [client] using Tailscale IP: !PEER_IP!
)

if not exist "%PYTHON%" (
  echo [client] creating virtualenv at .venv ...
  python -m venv "%ROOT%\.venv"
  if errorlevel 1 (
    echo error: failed to create venv. Is Python on PATH?
    exit /b 1
  )
)

"%PYTHON%" -c "import flask" >nul 2>&1
if errorlevel 1 (
  echo [client] installing requirements ...
  "%PIP%" install -r "%ROOT%\requirements.txt"
  if errorlevel 1 exit /b 1
)

if not exist "%PEER_DATA_DIR%" mkdir "%PEER_DATA_DIR%"
set "COMPLETE_DIR=%PEER_DATA_DIR%\complete"

echo.
echo ==============================================
echo  NightOwls peer client
echo ----------------------------------------------
echo  Tracker:     %TRACKER_URL%
echo  Peer IP:     %PEER_IP%  (advertised to tracker)
echo  Listen:      %PEER_HOST%:%PEER_PORT%
echo  Data dir:    %PEER_DATA_DIR%
echo  Downloads:   %COMPLETE_DIR%\<file_id>\<filename>
echo  UI:          http://%PEER_IP%:%PEER_PORT%/
echo               http://127.0.0.1:%PEER_PORT%/  (local)
echo ----------------------------------------------
echo  Press Ctrl+C to stop.
echo ==============================================
echo.

set "TRACKER_URL=%TRACKER_URL%"
set "PEER_IP=%PEER_IP%"
set "PEER_PORT=%PEER_PORT%"
set "PEER_HOST=%PEER_HOST%"
set "PEER_DATA_DIR=%PEER_DATA_DIR%"

"%PYTHON%" -m peer.app
exit /b %ERRORLEVEL%

:show_help
echo NightOwls Tailscale / LAN peer client
echo.
echo Usage: %~nx0 [TRACKER_URL] [options]
echo.
echo Arguments:
echo   TRACKER_URL           Tracker base URL, e.g. http://100.64.1.2:5000
echo                         (or set env TRACKER_URL)
echo.
echo Options:
echo   --port N              Peer listen port (default: 6001)
echo   --ip IP               Advertise this IP to the tracker (default: Tailscale IPv4)
echo   --data-dir DIR        Local storage for chunks + completed files
echo                         (default: %%USERPROFILE%%\NightOwls-data)
echo   -h, --help            Show this help
echo.
echo Examples:
echo   %~nx0 http://100.64.1.2:5000
echo   %~nx0 http://100.64.1.2:5000 --port 6002
echo.
echo Completed downloads appear under:
echo   ^<data-dir^>\complete\^<file_id^>\^<filename^>
exit /b 1
