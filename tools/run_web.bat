@echo off
REM Start the Sgurr frontend and engine backend in one process.
REM The release list and default engine are defined in web/backend/main.py.
REM
REM After "Application startup complete" appears, browse to
REM   http://127.0.0.1:8000/
REM Keep this window open while playing. Press Ctrl+C or close it to stop.

REM Run from the repository root so uvicorn can resolve web.backend.main.
cd /d "%~dp0.."

REM Access logging is disabled to avoid logging every health poll.
".venv\Scripts\python.exe" -m uvicorn web.backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
