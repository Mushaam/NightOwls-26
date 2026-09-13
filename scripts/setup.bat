@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM NightOwls — one-time Windows setup (venv + dependencies).
REM
REM Usage:
REM   setup.bat
REM   scripts\setup.bat

cd /d "%~dp0\.."
set "ROOT=%CD%"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"

echo.
echo ==============================================
echo  NightOwls Windows setup
echo ----------------------------------------------
echo  Project: %ROOT%
echo ==============================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo error: Python not found on PATH.
  echo Install Python 3.11+ from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH".
  exit /b 1
)

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
  echo error: Python 3.10+ required.
  python --version
  exit /b 1
)

if not exist "%PYTHON%" (
  echo [setup] creating virtualenv at .venv ...
  python -m venv "%ROOT%\.venv"
  if errorlevel 1 (
    echo error: failed to create .venv
    exit /b 1
  )
)

echo [setup] installing requirements ...
"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
"%PYTHON%" -m pip install -r "%ROOT%\requirements.txt"
if errorlevel 1 exit /b 1

"%PYTHON%" -c "import flask, wormhole, crochet; print('[setup] flask + magic-wormhole OK')"
if errorlevel 1 (
  echo error: imports failed after install
  exit /b 1
)

if not exist "%ROOT%\config\nightowls.json" (
  echo [setup] WARNING: missing config\nightowls.json
) else (
  echo [setup] config: %ROOT%\config\nightowls.json
)

echo.
echo ==============================================
echo  Setup complete
echo ----------------------------------------------
echo  Host demo (then ngrok):   demo.bat
echo  Peer client:              client.bat
echo  Tracker only:             server.bat
echo ----------------------------------------------
echo  Edit config\nightowls.json → tracker_url
echo  after you start ngrok (https://….ngrok… ).
echo ==============================================
echo.
exit /b 0
