@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM NightOwls — Windows demo host (tracker + seeder peer).
REM Then expose the tracker with ngrok in another terminal.
REM
REM Usage:
REM   demo.bat
REM   demo.bat --no-seed

cd /d "%~dp0\.."
set "ROOT=%CD%"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"

if not defined TRACKER_HOST set "TRACKER_HOST=0.0.0.0"
if not defined TRACKER_PORT set "TRACKER_PORT=5000"
if not defined TRACKER_DB set "TRACKER_DB=%ROOT%\data\demo_tracker.db"
if not defined PEER_PORT set "PEER_PORT=6001"
if not defined PEER_IP set "PEER_IP=demo-host"
if not defined PEER_HOST set "PEER_HOST=0.0.0.0"
if not defined RUN_DIR set "RUN_DIR=%TEMP%\nightowls_demo_host"
set "DO_SEED=1"

:parse
if "%~1"=="" goto after_parse
if /I "%~1"=="-h" goto show_help
if /I "%~1"=="--help" goto show_help
if /I "%~1"=="--no-seed" (
  set "DO_SEED=0"
  shift
  goto parse
)
if /I "%~1"=="--port" (
  if "%~2"=="" ( echo error: --port needs a value & exit /b 1 )
  set "TRACKER_PORT=%~2"
  shift & shift & goto parse
)
if /I "%~1"=="--peer-port" (
  if "%~2"=="" ( echo error: --peer-port needs a value & exit /b 1 )
  set "PEER_PORT=%~2"
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
set "LOCAL_TRACKER_URL=http://127.0.0.1:%TRACKER_PORT%"
set "PEER_DATA_DIR=%RUN_DIR%\seeder"

if not exist "%PYTHON%" (
  echo [demo] .venv missing — running setup.bat ...
  call "%ROOT%\scripts\setup.bat"
  if errorlevel 1 exit /b 1
)

"%PYTHON%" -c "import flask, wormhole, crochet" >nul 2>&1
if errorlevel 1 (
  echo [demo] installing requirements ...
  "%PYTHON%" -m pip install -r "%ROOT%\requirements.txt"
  if errorlevel 1 exit /b 1
)

if not exist "%RUN_DIR%" mkdir "%RUN_DIR%"
if not exist "%PEER_DATA_DIR%" mkdir "%PEER_DATA_DIR%"
for %%I in ("%TRACKER_DB%") do if not exist "%%~dpI" mkdir "%%~dpI"
if exist "%TRACKER_DB%" del /f /q "%TRACKER_DB%" >nul 2>&1

taskkill /FI "WINDOWTITLE eq NightOwls-tracker*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq NightOwls-seeder*" /T /F >nul 2>&1
timeout /t 1 /nobreak >nul

REM Write tiny launcher scripts (avoids nested-quote hell in start).
(
  echo @echo off
  echo cd /d "%ROOT%"
  echo set TRACKER_DB=%TRACKER_DB%
  echo set TRACKER_HOST=%TRACKER_HOST%
  echo set TRACKER_PORT=%TRACKER_PORT%
  echo "%PYTHON%" -c "from tracker.app import create_app, app; create_app(); app.run(host='%TRACKER_HOST%', port=int('%TRACKER_PORT%'), debug=False, use_reloader=False)"
) > "%RUN_DIR%\run_tracker.bat"

(
  echo @echo off
  echo cd /d "%ROOT%"
  echo set PEER_DATA_DIR=%PEER_DATA_DIR%
  echo set PEER_PORT=%PEER_PORT%
  echo set PEER_IP=%PEER_IP%
  echo set PEER_HOST=%PEER_HOST%
  echo set TRACKER_URL=%LOCAL_TRACKER_URL%
  echo "%PYTHON%" -m peer.app
) > "%RUN_DIR%\run_seeder.bat"

echo [demo] starting tracker on %TRACKER_HOST%:%TRACKER_PORT% ...
start "NightOwls-tracker" /MIN "%RUN_DIR%\run_tracker.bat"

call :wait_http "%LOCAL_TRACKER_URL%/files" "tracker"
if errorlevel 1 goto fail

echo [demo] starting seeder peer on :%PEER_PORT% ...
start "NightOwls-seeder" /MIN "%RUN_DIR%\run_seeder.bat"

call :wait_http "http://127.0.0.1:%PEER_PORT%/health" "seeder peer"
if errorlevel 1 goto fail

if "%DO_SEED%"=="1" (
  echo [demo] seeding demo files ...
  set "SEED_DIR=%RUN_DIR%\seed_sources"
  if not exist "%SEED_DIR%" mkdir "%SEED_DIR%"
  "%PYTHON%" -c "from pathlib import Path; b=Path(r'%SEED_DIR%'); (b/'notes.txt').write_text('NightOwls demo notes\n'*8000, encoding='utf-8'); (b/'sample.bin').write_bytes((b'NightOwls-demo-chunk-'*20000)[:400000]); print('wrote seed files')"
  if errorlevel 1 goto fail
  "%PYTHON%" -m peer.swarm upload --path "%SEED_DIR%\notes.txt" --tracker "%LOCAL_TRACKER_URL%" --data-dir "%PEER_DATA_DIR%" --peer-ip "%PEER_IP%" --peer-port %PEER_PORT% --filename notes.txt
  if errorlevel 1 goto fail
  "%PYTHON%" -m peer.swarm upload --path "%SEED_DIR%\sample.bin" --tracker "%LOCAL_TRACKER_URL%" --data-dir "%PEER_DATA_DIR%" --peer-ip "%PEER_IP%" --peer-port %PEER_PORT% --filename sample.bin
  if errorlevel 1 goto fail
  echo [demo] seeded notes.txt + sample.bin
)

echo.
echo ==============================================
echo  NightOwls demo host is running
echo ----------------------------------------------
echo  Tracker (local):  %LOCAL_TRACKER_URL%/portal
echo  Seeder UI:        http://127.0.0.1:%PEER_PORT%/
echo  Logs / helpers:   %RUN_DIR%\
echo ----------------------------------------------
echo  NEXT — expose the tracker with ngrok:
echo.
echo    ngrok http %TRACKER_PORT%
echo.
echo  Then set tracker_url in config\nightowls.json to the
echo  https://….ngrok-free.app URL ngrok prints.
echo.
echo  On ANY machine with that config:
echo    client.bat          (Windows)
echo    ./client            (Linux/macOS)
echo ----------------------------------------------
echo  First-time Windows install:  setup.bat
echo ----------------------------------------------
echo  Press any key to STOP tracker + seeder.
echo ==============================================
echo.
pause >nul

echo [demo] shutting down...
taskkill /FI "WINDOWTITLE eq NightOwls-tracker*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq NightOwls-seeder*" /T /F >nul 2>&1
echo [demo] stopped.
exit /b 0

:fail
echo [demo] ERROR — see console windows or %RUN_DIR%
taskkill /FI "WINDOWTITLE eq NightOwls-tracker*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq NightOwls-seeder*" /T /F >nul 2>&1
exit /b 1

:wait_http
set "URL=%~1"
set "LABEL=%~2"
set /a "_i=0"
:wait_loop
set /a "_i+=1"
if !_i! GTR 60 (
  echo [demo] ERROR: !LABEL! did not become ready ^(!URL!^)
  exit /b 1
)
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri '%URL%').StatusCode | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
  echo [demo] !LABEL! is up
  exit /b 0
)
timeout /t 1 /nobreak >nul
goto wait_loop

:show_help
echo NightOwls demo host — tracker + seeder peer (for ngrok demos)
echo.
echo Usage: %~nx0 [options]
echo.
echo Options:
echo   --no-seed         Do not pre-seed demo files
echo   --port N          Tracker port
echo   --peer-port N     Seeder peer port
echo   --db PATH         Tracker SQLite path
echo   -h, --help        Show this help
exit /b 0
