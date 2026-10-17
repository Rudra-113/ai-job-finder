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
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 exit /b 1
echo Job Agent: http://127.0.0.1:47321
echo Leave this window open. Closing it stops the agent.
".venv\Scripts\python.exe" app.py
