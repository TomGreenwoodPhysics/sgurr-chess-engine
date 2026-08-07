@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem ============================================================
rem Sgurr gen8 clean-data generation (king-bucket dataset)
rem Safe/resumable launcher for sgurr_cpp\datagen.exe
rem ============================================================

rem Repository root, resolved from this script's own location (tools\..) so
rem a clone anywhere works. pushd/popd normalises the "..", which a bare
rem %~dp0.. does not -- the unnormalised form breaks the tasklist and
rem PowerShell -LiteralPath checks below.
pushd "%~dp0.."
set "ROOT=%CD%"
popd
set "ENGINE=%ROOT%\sgurr_cpp\datagen.exe"
set "OUT=%ROOT%\data\gen8_raw"
set "BOOK=%ROOT%\testing\book.epd"
set "NET=%ROOT%\nets\gen7.nnue"
set "LOGDIR=%ROOT%\runs\gen8_datagen"

rem TARGET is a high cap, not a goal: gen8 feeds king buckets, which want volume.
rem At ~7M positions/day (12 SIMD workers) this will not be reached inside a
rem 6-day window, so datagen runs the whole time instead of stopping early.
set "TARGET=150000000"
set "LIMIT=nodes:150000"
rem 12 workers on a 16-thread 7800X3D: datagen is NODE-limited (nodes:150000),
rem so oversubscribing cores changes throughput but not the data. Leaves some
rem headroom so the machine stays usable. Was 6 for the old 6-core i5.
set "WORKERS=12"

if /I "%~1"=="worker" goto :worker

echo ============================================================
echo Sgurr gen8 clean-data generation (king-bucket dataset)
echo ============================================================
echo Target : %TARGET% positions
echo Workers: %WORKERS%
echo Limit  : %LIMIT%
echo Output : %OUT%
echo.
echo IMPORTANT: datagen.exe must be the build compiled with -DSGR_RFP=0.
echo.

if not exist "%ENGINE%" (
    echo ERROR: Missing generator:
    echo   %ENGINE%
    pause
    exit /b 1
)

if not exist "%BOOK%" (
    echo ERROR: Missing opening book:
    echo   %BOOK%
    pause
    exit /b 1
)

if not exist "%NET%" (
    echo ERROR: Missing NNUE:
    echo   %NET%
    pause
    exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

rem Refuse to launch a duplicate generator set. This intentionally blocks if
rem any datagen.exe is running, including a different generation.
tasklist /FI "IMAGENAME eq datagen.exe" 2>NUL | find /I "datagen.exe" >NUL
if not errorlevel 1 (
    echo ERROR: At least one datagen.exe process is already running.
    echo Stop or inspect it before launching another generator set.
    pause
    exit /b 1
)

rem A forced stop can interrupt only the final record of a shard.
rem Inspect generator shards ONLY: data_*.bin.
rem Before removing a sub-32-byte torn tail, preserve the original file as a
rem timestamped .torn-*.bak copy. Complete 32-byte records are never removed.
echo Checking generator shards for incomplete record tails...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$files = @(Get-ChildItem -LiteralPath '%OUT%' -Filter 'data_*.bin' -File -ErrorAction SilentlyContinue);" ^
  "foreach ($f in $files) {" ^
  "  $extra = $f.Length %% 32;" ^
  "  if ($extra -ne 0) {" ^
  "    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff';" ^
  "    $backup = $f.FullName + '.torn-' + $stamp + '.bak';" ^
  "    Copy-Item -LiteralPath $f.FullName -Destination $backup -ErrorAction Stop;" ^
  "    $newLength = $f.Length - $extra;" ^
  "    Write-Host ('Repairing {0}: preserving {1}, then trimming {2} invalid tail byte(s)' -f $f.Name, [IO.Path]::GetFileName($backup), $extra);" ^
  "    $stream = [System.IO.File]::Open($f.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read);" ^
  "    try { $stream.SetLength($newLength) } finally { $stream.Dispose() }" ^
  "  }" ^
  "}"

if errorlevel 1 (
    echo ERROR: Shard validation/repair failed. No workers were launched.
    pause
    exit /b 1
)

for /f %%N in ('powershell -NoProfile -Command "$sum = (Get-ChildItem -LiteralPath '%OUT%' -Filter 'data_*.bin' -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum; if ($null -eq $sum) { 0 } else { [long]($sum / 32) }"') do set "EXISTING=%%N"

echo Existing complete positions: !EXISTING!
if !EXISTING! GEQ %TARGET% (
    echo Target has already been reached. Nothing was started.
    pause
    exit /b 0
)

echo Launching %WORKERS% workers...
for /L %%I in (1,1,%WORKERS%) do (
    start "Sgurr gen8 worker %%I" /MIN "%ComSpec%" /D /C call "%~f0" worker %%I
)

echo.
echo Started. Logs:
echo   %LOGDIR%\worker_1.log
echo   ...
echo   %LOGDIR%\worker_%WORKERS%.log
echo.
echo Run pause_gen8_datagen.bat to stop the workers.
exit /b 0


:worker
set "WORKER_ID=%~2"
if not defined WORKER_ID set "WORKER_ID=unknown"

if not exist "%LOGDIR%" mkdir "%LOGDIR%"
cd /d "%ROOT%"

>>"%LOGDIR%\worker_%WORKER_ID%.log" echo.
>>"%LOGDIR%\worker_%WORKER_ID%.log" echo ============================================================
>>"%LOGDIR%\worker_%WORKER_ID%.log" echo [%DATE% %TIME%] Worker %WORKER_ID% starting
>>"%LOGDIR%\worker_%WORKER_ID%.log" echo Command: "%ENGINE%" "%OUT%" %TARGET% %LIMIT% "%BOOK%" "%NET%"
>>"%LOGDIR%\worker_%WORKER_ID%.log" echo ============================================================

"%ENGINE%" "%OUT%" %TARGET% %LIMIT% "%BOOK%" "%NET%" >>"%LOGDIR%\worker_%WORKER_ID%.log" 2>&1
set "RC=%ERRORLEVEL%"

>>"%LOGDIR%\worker_%WORKER_ID%.log" echo [%DATE% %TIME%] Worker %WORKER_ID% exited with code %RC%
exit /b %RC%
