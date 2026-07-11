@echo off
REM Cleanly pause the gen6 pipeline + datagen (e.g. before a reboot/shutdown).
REM Data is append-only, so this can never corrupt anything; at worst one
REM in-flight game per worker is dropped (a torn sub-record tail the freeze
REM stage trims automatically). Double-click resume_gen6.bat to carry on from
REM exactly where it left off.

echo Stopping gen6 datagen workers...
taskkill /IM datagen.exe /F >nul 2>&1

echo Stopping the pipeline driver...
REM Kill only the python running pipeline.py (leaves any other python alone).
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*pipeline.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo.
echo Done - gen6 is paused. Safe to shut the PC down.
echo Double-click resume_gen6.bat to carry on.
timeout /t 5 >nul
