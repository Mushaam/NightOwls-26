@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM NightOwls — plug-and-play peer client.
REM
REM Usage:
REM   client.bat 192.168.1.10
REM   client.bat 192.168.1.10:5000
REM   client.bat http://192.168.1.10:5000 --port 6001

cd /d "%~dp0\.."
set "ROOT=%CD%"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
set "PIP=%ROOT%\.venv\Scripts\pip.exe"

if not defined PEER_PORT set "PEER_PORT=6001"
if not defined PEER_HOST set "PEER_HOST=0.0.0.0"
if not defined PEER_DATA_DIR set "PEER_DATA_DIR=%USERPROFILE%\NightOwls-data"
set "DEFAULT_TRACKER_PORT=5000"
set "TRACKER_ARG="

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
echo %~1| findstr /B /C:"-" >nul
if not errorlevel 1 (
  echo error: unknown option: %~1
  goto show_help
)
if defined TRACKER_ARG (
  echo error: tracker already set; unexpected argument: %~1
  exit /b 1
)
set "TRACKER_ARG=%~1"
shift
goto parse

:after_parse
if not defined TRACKER_ARG (
  if defined TRACKER_URL goto normalize_done
  echo error: tracker IP/URL is required.
  echo.
  echo Usage: %~nx0 ^<TRACKER_IP^>
  echo   e.g. %~nx0 192.168.1.10
  echo        %~nx0 192.168.1.10:5000
  echo.
  goto show_help
)

REM Normalize TRACKER_ARG → TRACKER_URL
echo %TRACKER_ARG%| findstr /B /I "http:// https://" >nul
if not errorlevel 1 (
  set "TRACKER_URL=%TRACKER_ARG%"
  goto normalize_done
)

REM Count dots + optional :port — treat as IPv4 if it looks like a.b.c.d[:port]
echo %TRACKER_ARG%| findstr /R "^[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*$" >nul
if not errorlevel 1 (
  set "TRACKER_URL=http://%TRACKER_ARG%:%DEFAULT_TRACKER_PORT%"
  goto normalize_done
)
echo %TRACKER_ARG%| findstr /R "^[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*:[0-9][0-9]*$" >nul
if not errorlevel 1 (
  set "TRACKER_URL=http://%TRACKER_ARG%"
  goto normalize_done
)

REM hostname or hostname:port
echo %TRACKER_ARG%| findstr /C:":" >nul
if not errorlevel 1 (
  set "TRACKER_URL=http://%TRACKER_ARG%"
) else (
  set "TRACKER_URL=http://%TRACKER_ARG%:%DEFAULT_TRACKER_PORT%"
)

:normalize_done
REM strip trailing slash
if "!TRACKER_URL:~-1!"=="/" set "TRACKER_URL=!TRACKER_URL:~0,-1!"

if not defined PEER_IP (
  where tailscale >nul 2>&1
  if not errorlevel 1 (
    for /f "usebackq delims=" %%I in (`tailscale ip -4 2^>nul`) do (
      if not defined PEER_IP set "PEER_IP=%%I"
    )
  )
  if not defined PEER_IP set "PEER_IP=127.0.0.1"
  echo [client] advertising IP: !PEER_IP!
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
echo NightOwls peer client
echo.
echo Usage: %~nx0 ^<TRACKER_IP_OR_URL^> [options]
echo.
echo Arguments:
echo   TRACKER_IP_OR_URL     Pass the tracker address every time:
echo                           192.168.1.10
echo                           192.168.1.10:5000
echo                           http://192.168.1.10:5000
echo.
echo Options:
echo   --port N              Peer listen port (default: 6001)
echo   --ip IP               Advertise this IP to the tracker
echo   --data-dir DIR        Local storage (default: %%USERPROFILE%%\NightOwls-data)
echo   -h, --help            Show this help
echo.
echo Examples:
echo   %~nx0 192.168.1.10
echo   %~nx0 100.64.1.2:5000
echo   %~nx0 http://192.168.1.10:5000 --port 6002
exit /b 1
