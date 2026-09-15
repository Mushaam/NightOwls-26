@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM NightOwls — plug-and-play peer client (Windows).
REM Reads tracker_url from config\nightowls.json by default.
REM
REM Usage:
REM   client.bat
REM   client.bat https://….ngrok-free.app
REM   client.bat 192.168.1.10 --port 6001

cd /d "%~dp0\.."
set "ROOT=%CD%"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"

set "TRACKER_FROM_CLI=0"
set "TRACKER_FROM_ENV=0"
set "PEER_PORT_SET=0"
set "PEER_IP_SET=0"
set "PEER_HOST_SET=0"
set "TRACKER_ARG="
set "CONFIG_PATH="
set "TRACKER_SOURCE=config"
set "DEFAULT_TRACKER_PORT=5000"

if defined TRACKER_URL set "TRACKER_FROM_ENV=1"
if defined PEER_PORT set "PEER_PORT_SET=1"
if defined PEER_IP set "PEER_IP_SET=1"
if defined PEER_HOST set "PEER_HOST_SET=1"

if not defined PEER_DATA_DIR set "PEER_DATA_DIR=%USERPROFILE%\NightOwls-data"

:parse
if "%~1"=="" goto after_parse

if /I "%~1"=="-h" goto show_help
if /I "%~1"=="--help" goto show_help

if /I "%~1"=="--port" (
  if "%~2"=="" ( echo error: --port needs a value & exit /b 1 )
  set "PEER_PORT=%~2"
  set "PEER_PORT_SET=1"
  shift & shift & goto parse
)
if /I "%~1"=="--ip" (
  if "%~2"=="" ( echo error: --ip needs a value & exit /b 1 )
  set "PEER_IP=%~2"
  set "PEER_IP_SET=1"
  shift & shift & goto parse
)
if /I "%~1"=="--data-dir" (
  if "%~2"=="" ( echo error: --data-dir needs a value & exit /b 1 )
  set "PEER_DATA_DIR=%~2"
  shift & shift & goto parse
)

echo %~1 | findstr /B /C:"-" >nul
if not errorlevel 1 (
  echo error: unknown option: %~1
  goto show_help
)

if "%TRACKER_FROM_CLI%"=="1" (
  echo error: unexpected extra argument: %~1
  exit /b 1
)
set "TRACKER_ARG=%~1"
set "TRACKER_FROM_CLI=1"
shift
goto parse

:after_parse

if not exist "%PYTHON%" (
  echo [client] .venv missing — running setup.bat ...
  call "%ROOT%\scripts\setup.bat"
  if errorlevel 1 exit /b 1
)

REM Load config defaults via Python (same as Linux client).
set "CFG_FILE=%TEMP%\nightowls_client_cfg.txt"
"%PYTHON%" -c "from shared.config import load_config, config_path; c=load_config(); p=c.get('peer') or {}; path=config_path(); print(c.get('tracker_url') or ''); print(p.get('port') or ''); print(p.get('advertise_host') or ''); print(p.get('advertise_port') or ''); print(p.get('host') or ''); print(str(path) if path else '')" > "%CFG_FILE%"
if errorlevel 1 (
  echo error: could not read config
  exit /b 1
)

set "CFG_TRACKER="
set "CFG_PEER_PORT="
set "CFG_ADVERTISE_HOST="
set "CFG_ADVERTISE_PORT="
set "CFG_PEER_HOST="
set /a "_line=0"
for /f "usebackq delims=" %%L in ("%CFG_FILE%") do (
  set /a "_line+=1"
  if !_line!==1 set "CFG_TRACKER=%%L"
  if !_line!==2 set "CFG_PEER_PORT=%%L"
  if !_line!==3 set "CFG_ADVERTISE_HOST=%%L"
  if !_line!==4 set "CFG_ADVERTISE_PORT=%%L"
  if !_line!==5 set "CFG_PEER_HOST=%%L"
  if !_line!==6 set "CONFIG_PATH=%%L"
)
del /f /q "%CFG_FILE%" >nul 2>&1

if "%TRACKER_FROM_CLI%"=="1" (
  call :normalize_tracker "%TRACKER_ARG%"
  if errorlevel 1 exit /b 1
  set "TRACKER_SOURCE=CLI"
) else if "%TRACKER_FROM_ENV%"=="1" (
  set "TRACKER_SOURCE=env TRACKER_URL"
) else (
  if defined CFG_TRACKER (
    set "TRACKER_URL=%CFG_TRACKER%"
    set "TRACKER_SOURCE=config"
  )
)

if not defined TRACKER_URL (
  echo error: no tracker URL — set config\nightowls.json tracker_url
  echo   or pass: client.bat https://YOUR-NGROK.ngrok-free.app
  exit /b 1
)

if "%TRACKER_URL:~-1%"=="/" set "TRACKER_URL=%TRACKER_URL:~0,-1%"

if "%PEER_PORT_SET%"=="0" (
  if defined CFG_ADVERTISE_PORT (
    set "PEER_PORT=%CFG_ADVERTISE_PORT%"
  ) else if defined CFG_PEER_PORT (
    set "PEER_PORT=%CFG_PEER_PORT%"
  ) else (
    set "PEER_PORT=6001"
  )
)

if "%PEER_HOST_SET%"=="0" (
  if defined CFG_PEER_HOST (
    set "PEER_HOST=%CFG_PEER_HOST%"
  ) else (
    set "PEER_HOST=0.0.0.0"
  )
)

if "%PEER_IP_SET%"=="0" (
  if defined CFG_ADVERTISE_HOST if not "!CFG_ADVERTISE_HOST!"=="127.0.0.1" (
    set "PEER_IP=!CFG_ADVERTISE_HOST!"
    echo [client] advertising IP from config: !PEER_IP!
    goto peer_ip_done
  )
  set "PEER_IP="
  where tailscale >nul 2>&1
  if not errorlevel 1 (
    for /f "usebackq delims=" %%I in (`tailscale ip -4 2^>nul`) do (
      if not defined PEER_IP set "PEER_IP=%%I"
    )
  )
  if not defined PEER_IP set "PEER_IP=127.0.0.1"
  echo [client] advertising IP: !PEER_IP!
)
:peer_ip_done

"%PYTHON%" -c "import flask" >nul 2>&1
if errorlevel 1 (
  echo [client] installing requirements ...
  "%PYTHON%" -m pip install -r "%ROOT%\requirements.txt"
  if errorlevel 1 exit /b 1
)
"%PYTHON%" -c "import wormhole, crochet" >nul 2>&1
if errorlevel 1 (
  echo [client] installing magic-wormhole stack ...
  "%PYTHON%" -m pip install -r "%ROOT%\requirements.txt"
  if errorlevel 1 exit /b 1
)

if not exist "%PEER_DATA_DIR%" mkdir "%PEER_DATA_DIR%"
set "COMPLETE_DIR=%PEER_DATA_DIR%\complete"

echo.
echo ==============================================
echo  NightOwls peer client
echo ----------------------------------------------
echo  Tracker:     %TRACKER_URL%
echo  Source:      %TRACKER_SOURCE%
if defined CONFIG_PATH echo  Config:      %CONFIG_PATH%
echo  Peer IP:     %PEER_IP%  (advertised to tracker)
echo  Listen:      %PEER_HOST%:%PEER_PORT%
echo  Data dir:    %PEER_DATA_DIR%
echo  Downloads:   %COMPLETE_DIR%\file_id\filename
echo  UI:          http://127.0.0.1:%PEER_PORT%/  (local)
echo ----------------------------------------------
echo  Press Ctrl+C to stop.
echo ==============================================
echo.

"%PYTHON%" -m peer.app
exit /b %ERRORLEVEL%

:normalize_tracker
set "RAW=%~1"
echo %RAW% | findstr /B /I "http:// https://" >nul
if not errorlevel 1 (
  set "TRACKER_URL=%RAW%"
  exit /b 0
)
echo %RAW% | findstr /R "^[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*$" >nul
if not errorlevel 1 (
  set "TRACKER_URL=http://%RAW%:%DEFAULT_TRACKER_PORT%"
  exit /b 0
)
echo %RAW% | findstr /R "^[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*:[0-9][0-9]*$" >nul
if not errorlevel 1 (
  set "TRACKER_URL=http://%RAW%"
  exit /b 0
)
echo %RAW% | findstr /C:":" >nul
if not errorlevel 1 (
  set "TRACKER_URL=http://%RAW%"
) else (
  set "TRACKER_URL=http://%RAW%:%DEFAULT_TRACKER_PORT%"
)
exit /b 0

:show_help
echo NightOwls peer client (Windows)
echo.
echo Usage: %~nx0 [TRACKER_IP_OR_URL] [options]
echo.
echo Tracker address (first match wins):
echo   1. CLI argument
echo   2. TRACKER_URL env
echo   3. config\nightowls.json → tracker_url   (default)
echo.
echo Options:
echo   --port N              Peer listen port
echo   --ip IP               Advertise this IP to the tracker
echo   --data-dir DIR        Local storage (default: %%USERPROFILE%%\NightOwls-data)
echo   -h, --help            Show this help
echo.
echo Examples:
echo   %~nx0
echo   %~nx0 https://abc123.ngrok-free.app
echo   %~nx0 192.168.1.10 --port 6002
exit /b 1
