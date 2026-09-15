@echo off
REM Plug-and-play peer client. Reads tracker_url from config\nightowls.json by default.
REM From the project root: client.bat
call "%~dp0scripts\start_client.bat" %*
