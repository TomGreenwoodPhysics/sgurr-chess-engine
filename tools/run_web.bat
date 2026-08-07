@echo off
REM Start the Sgurr web backend. One process serves the frontend and the
REM engine; the release list it offers is defined in web/backend/main.py
REM (v8.2 is the default) and is chosen in the UI from the menu.
REM
REM Once this window shows "Application startup complete", browse to
REM   http://127.0.0.1:8000/
REM Keep this window open while you play; press Ctrl+C (or close it) to stop.

REM Run from the repository root (this script lives in tools\), because
REM uvicorn resolves web.backend.main as a package from the working dir.
cd /d "%~dp0.."

REM --no-access-log: don't log every /health poll (avoids churning a file
REM that Live Server might watch and reload on). Logs go to this console.
".venv\Scripts\python.exe" -m uvicorn web.backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
