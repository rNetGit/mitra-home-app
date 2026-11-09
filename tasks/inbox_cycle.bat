@echo off
rem Scheduled task wrapper. All logic lives in run_task.py (reads config/family.json at run time).
cd /d "%~dp0.."
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if exist "%LOCALAPPDATA%\FamilyAgent\venv\Scripts\python.exe" set "PY=%LOCALAPPDATA%\FamilyAgent\venv\Scripts\python.exe"
if exist "%LOCALAPPDATA%\MitraHome\venv\Scripts\python.exe" set "PY=%LOCALAPPDATA%\MitraHome\venv\Scripts\python.exe"
"%PY%" tasks\run_task.py inbox_cycle
