@echo off
REM Start the Sgurr web demo backend. It serves BOTH engines in one process:
REM   - Sgurr v4.0 "MacKenzie"   (released, gen5 net)
REM   - Sgurr v4.1_exp           (gen5 net + experimental RFP search)
REM Pick your opponent in the UI by clicking the engine button on the menu.
REM
REM Once this window shows "Application startup complete", open
REM   web\frontend\index.html  with Live Server (http://127.0.0.1:5500/...),
REM or just browse  http://127.0.0.1:8000/  directly.
REM Keep this window open while you play; press Ctrl+C (or close it) to stop.

cd /d "%~dp0"
REM --no-access-log: don't log every /health poll (avoids churning a file that
REM Live Server might watch and reload on). Logs go to this console only.
".venv\Scripts\python.exe" -m uvicorn web.backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
