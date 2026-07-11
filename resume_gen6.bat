@echo off
REM Start / resume the gen6 pipeline DETACHED - it keeps running after this
REM window, the terminal, or VSCode is closed. Only a reboot / shutdown /
REM explicit stop ends it. It recounts positions already on disk and continues
REM to the 8M target, then runs the rest of the pipeline on its own.
REM
REM PREREQUISITE (once, before first launch): datagen.exe rebuilt from current
REM source so the labeller searches with the shipped v4.0 engine (plus any
REM search features that won the overnight prune pool):
REM   /c/msys64/clang64/bin/clang++ -std=c++20 -O3 -march=native -DNDEBUG -static ^
REM       datagen.cpp board.cpp evaluation.cpp search.cpp nnue.cpp -o datagen.exe
cd /d "%~dp0"

REM A hard stop / power-off leaves a stale lock behind; clear it so the
REM pipeline will start. (Only safe because the pipeline is NOT running now.)
if exist "runs\gen6\.lock" del "runs\gen6\.lock"
if not exist "runs\gen6" mkdir "runs\gen6"

powershell -NoProfile -Command "Start-Process 'E:\Anaconda\python.exe' -ArgumentList 'pipeline.py','pipeline_gen6.json' -WorkingDirectory '%~dp0.' -RedirectStandardOutput '%~dp0runs\gen6\pipeline.log' -RedirectStandardError '%~dp0runs\gen6\pipeline.err.log' -WindowStyle Hidden"

echo.
echo Resumed in the background (detached). Safe to close everything.
echo Check progress any time with:
echo    type "%~dp0runs\gen6\pipeline.log"
timeout /t 5 >nul
