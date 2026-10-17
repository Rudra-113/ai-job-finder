@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run run.bat once so Python and the app are installed.
  exit /b 1
)
".venv\Scripts\python.exe" start_tunnel.py
