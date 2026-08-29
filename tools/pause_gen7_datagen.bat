@echo off
setlocal EnableExtensions

rem Resolve and normalise the repository root so clones work anywhere.
pushd "%~dp0.."
set "ROOT=%CD%"
popd
set "OUT=%ROOT%\data\gen7_raw"

echo ============================================================
echo Pausing Sgurr gen7 clean-data generation
echo ============================================================

rem Stop only datagen.exe processes writing to gen7_raw.
rem A hard kill preserves complete records and repairs any partial tail next run.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$procs = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'datagen.exe' -and $_.CommandLine -like '*gen7_raw*' });" ^
  "if ($procs.Count -eq 0) { Write-Host 'No gen7 datagen workers are running.'; exit 0 };" ^
  "foreach ($p in $procs) {" ^
  "  try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Write-Host ('Stopped PID {0}' -f $p.ProcessId) }" ^
  "  catch { Write-Warning ('Could not stop PID {0}: {1}' -f $p.ProcessId, $_.Exception.Message) }" ^
  "};" ^
  "Write-Host ('Requested stop for {0} gen7 worker(s).' -f $procs.Count)"

set "RC=%ERRORLEVEL%"
echo.

for /f %%N in ('powershell -NoProfile -Command "$sum = (Get-ChildItem -LiteralPath '%OUT%' -Filter 'data_*.bin' -File -ErrorAction SilentlyContinue | ForEach-Object { [long]([math]::Floor($_.Length / 32)) } | Measure-Object -Sum).Sum; if ($null -eq $sum) { 0 } else { [long]$sum }"') do set "POSITIONS=%%N"

echo Complete positions currently on disk: %POSITIONS%
echo Any possible torn final record will be backed up and repaired on restart.
echo.

if not "%RC%"=="0" (
    echo WARNING: PowerShell returned exit code %RC%.
    pause
    exit /b %RC%
)

echo Gen7 generation is paused.
pause
exit /b 0
