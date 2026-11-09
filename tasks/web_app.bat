@echo off
rem Wrapper for the web app's keep-alive task (python data/autostart.py on web [--lan] [--home FOLDER]). The task runs
rem this every 5 minutes; launch.py exits at once while the app is up, and starts it when it is not. Extra arguments
rem (--lan for phones, --home) go to launch.py. No browser window is opened.
rem The output goes to %LOCALAPPDATA%\MitraHome\logs, NOT to the app folder: on a first start launch.py moves the
rem app folder's own logs into the household folder, and a file held open by this redirect made that fail (0.130.2).
cd /d "%~dp0.."
set "LOGDIR=%LOCALAPPDATA%\MitraHome\logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if exist "%LOCALAPPDATA%\FamilyAgent\venv\Scripts\python.exe" set "PY=%LOCALAPPDATA%\FamilyAgent\venv\Scripts\python.exe"
if exist "%LOCALAPPDATA%\MitraHome\venv\Scripts\python.exe" set "PY=%LOCALAPPDATA%\MitraHome\venv\Scripts\python.exe"
"%PY%" launch.py --keep-alive --no-browser %* >> "%LOGDIR%\web_autostart.out" 2>&1
exit /b %ERRORLEVEL%
