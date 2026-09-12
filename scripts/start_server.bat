@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM NightOwls — plug-and-play tracker (server).
REM
REM Usage:
REM   server.bat
REM   scripts\start_server.bat --port 5000

cd /d "%~dp0\.."
set "ROOT=%CD%"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
set "PIP=%ROOT%\.venv\Scripts\pip.exe"

if not defined TRACKER_HOST set "TRACKER_HOST=0.0.0.0"
if not defined TRACKER_PORT set "TRACKER_PORT=5000"
if not defined TRACKER_DB set "TRACKER_DB=%ROOT%\data\tracker.db"

:parse
if "%~1"=="" goto after_parse
if /I "%~1"=="-h" goto show_help
if /I "%~1"=="--help" goto show_help
if /I "%~1"=="--host" (
  if "%~2"=="" ( echo error: --host needs a value & exit /b 1 )
  set "TRACKER_HOST=%~2"
  shift & shift & goto parse
)
if /I "%~1"=="--port" (
  if "%~2"=="" ( echo error: --port needs a value & exit /b 1 )
  set "TRACKER_PORT=%~2"
  shift & shift & goto parse
)
if /I "%~1"=="--db" (
  if "%~2"=="" ( echo error: --db needs a value & exit /b 1 )
  set "TRACKER_DB=%~2"
  shift & shift & goto parse
)
echo error: unknown option: %~1
goto show_help

:after_parse
if not exist "%PYTHON%" (
  echo [server] creating virtualenv at .venv ...
  python -m venv "%ROOT%\.venv"
  if errorlevel 1 (
    echo error: failed to create venv. Is Python on PATH?
    exit /b 1
  )
)

"%PYTHON%" -c "import flask" >nul 2>&1
if errorlevel 1 (
  echo [server] installing requirements ...
  "%PYTHON%" -m pip install -r "%ROOT%\requirements.txt"
  if errorlevel 1 exit /b 1
)

for %%I in ("%TRACKER_DB%") do if not exist "%%~dpI" mkdir "%%~dpI"

set "ADVERTISE_IP=127.0.0.1"
where tailscale >nul 2>&1
if not errorlevel 1 (
  for /f "usebackq delims=" %%I in (`tailscale ip -4 2^>nul`) do (
    if "!ADVERTISE_IP!"=="127.0.0.1" set "ADVERTISE_IP=%%I"
  )
)

echo.
echo ==============================================
echo  NightOwls tracker (server)
echo ----------------------------------------------
echo  Listening:  %TRACKER_HOST%:%TRACKER_PORT%
echo  Database:   %TRACKER_DB%
echo  Local:      http://127.0.0.1:%TRACKER_PORT%/files
echo  Share this: http://%ADVERTISE_IP%:%TRACKER_PORT%
echo ----------------------------------------------
echo  On other machines:
echo    client.bat http://%ADVERTISE_IP%:%TRACKER_PORT%
echo ----------------------------------------------
echo  Press Ctrl+C to stop.
echo ==============================================
echo.

set "TRACKER_DB=%TRACKER_DB%"
set "TRACKER_HOST=%TRACKER_HOST%"
set "TRACKER_PORT=%TRACKER_PORT%"

"%PYTHON%" -c "from tracker.app import create_app, app; create_app(); app.run(host='%TRACKER_HOST%', port=int('%TRACKER_PORT%'), debug=False, use_reloader=False)"
exit /b %ERRORLEVEL%

:show_help
echo NightOwls tracker (server)
echo.
echo Usage: %~nx0 [options]
echo.
echo Options:
echo   --host ADDR     Bind address (default: 0.0.0.0)
echo   --port N        Port (default: 5000)
echo   --db PATH       SQLite path (default: .\data\tracker.db)
echo   -h, --help      Show this help
exit /b 1
