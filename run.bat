@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  echo Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ and check Add python.exe to PATH.
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt -r backend\requirements-dev.txt
if errorlevel 1 exit /b 1
set SERVE_FRONTEND=1
set PORT=47321
set BIND_HOST=0.0.0.0
if not defined DATA_DIR set DATA_DIR=%~dp0data
echo AI Job Finder: http://127.0.0.1:47321
echo Leave this window open. Closing it stops the API.
".venv\Scripts\python.exe" backend\app.py
