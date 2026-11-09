@echo off
cd /d "%~dp0"
title Mitra Home
set "PYTHON="
rem the Windows installer's own Python comes first
if exist "%LOCALAPPDATA%\MitraHome\runtime\python.exe" set "PYTHON="%LOCALAPPDATA%\MitraHome\runtime\python.exe""
for %%C in ("py -3" "python" "python3") do (
  if not defined PYTHON (
    %%~C -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON=%%~C"
  )
)
if not defined PYTHON goto nopython
%PYTHON% launch.py %*
if errorlevel 1 pause
exit /b
:nopython
echo.
echo   Mitra Home needs Python 3.12 or newer, and this PC does not have it yet.
echo   A download page opens now. Install Python (tick "Add python.exe to PATH"),
echo   then double-click this file again.
echo.
start "" https://www.python.org/downloads/
pause
