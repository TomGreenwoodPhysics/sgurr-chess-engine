# Sgurr overnight driver.
#   Phase 1: run the gen7 pipeline (freeze -> ... -> calibrate, ledger).
#   Phase 2: ONLY if the pipeline finished cleanly and sgr_gen7.exe exists,
#            play extended calibration until you stop it (Ctrl+C) in the morning.
#
# Launch from a standalone PowerShell window (not the VS Code terminal) so
# closing the editor cannot kill it:
#   cd C:\Coding\Sgurr ; .\run_overnight.ps1
#
# The pipeline checkpoints every stage to runs\gen7\, so a phase-1 failure is
# resumable with:  .\.venv\Scripts\python.exe pipeline.py pipeline_gen7.json
$ErrorActionPreference = 'Continue'
$root = 'C:\Coding\Sgurr'
$py   = Join-Path $root '.venv\Scripts\python.exe'

Write-Host "=== PHASE 1: gen7 pipeline  ($(Get-Date -Format 'ddd HH:mm')) ===" -ForegroundColor Cyan
& $py (Join-Path $root 'pipeline.py') (Join-Path $root 'pipeline_gen7.json')
$rc = $LASTEXITCODE
Write-Host "pipeline exit code: $rc"

if ($rc -ne 0) {
    Write-Host "Pipeline did not finish cleanly -- NOT starting calibration." -ForegroundColor Yellow
    Write-Host "Resume with: .\.venv\Scripts\python.exe pipeline.py pipeline_gen7.json"
    exit $rc
}

$gen7 = Join-Path $root 'sgurr_cpp\sgr_gen7.exe'
if (-not (Test-Path $gen7)) {
    Write-Host "Pipeline exited 0 but $gen7 is missing -- NOT starting calibration." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "=== PHASE 2: extended calibration  ($(Get-Date -Format 'ddd HH:mm')) ===" -ForegroundColor Cyan
Write-Host "Runs until you press Ctrl+C. Every finished game is saved to PGN." -ForegroundColor Green
& $py (Join-Path $root 'extend_calibration.py') --rounds 100000
