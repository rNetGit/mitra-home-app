@echo off
rem Logon task wrapper for the Discord bot (python onboard.py add discord). Runs until sign-out; restarts at next sign-in.
cd /d "%~dp0.."
if not exist logs mkdir logs
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if exist "%LOCALAPPDATA%\FamilyAgent\venv\Scripts\python.exe" set "PY=%LOCALAPPDATA%\FamilyAgent\venv\Scripts\python.exe"
if exist "%LOCALAPPDATA%\MitraHome\venv\Scripts\python.exe" set "PY=%LOCALAPPDATA%\MitraHome\venv\Scripts\python.exe"
"%PY%" data\chat_discord.py run >> logs\chat_discord.out 2>&1
