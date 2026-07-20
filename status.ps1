# Sgurr — one-glance status for remote (phone) check-ins.
# Usage from an SSH session:  cd to the repo, then:  .\status.ps1
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Line($n) { Write-Host ("-" * $n) }

Write-Host ""
Write-Host "  SGURR STATUS  $(Get-Date -Format 'ddd dd MMM  HH:mm')" -ForegroundColor Cyan
Line 46

# --- datagen workers ---
$dg = Get-Process datagen -ErrorAction SilentlyContinue
Write-Host ("  datagen workers : {0}" -f $(if ($dg) { "$($dg.Count) running" } else { "none running" }))

# --- position count vs target ---
$raw = Join-Path $root 'data\gen7_raw'
if (Test-Path $raw) {
    $bytes = (Get-ChildItem "$raw\data_*.bin" | Measure-Object Length -Sum).Sum
    $pos = [long]($bytes / 32)
    $target = 12000000
    $pct = [math]::Round(100.0 * $pos / $target, 1)
    Write-Host ("  gen7 positions  : {0:N0} / {1:N0}  ({2}%)" -f $pos, $target, $pct)
}

# --- pipeline driver (only if a pipeline run is active) ---
$pipe = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*pipeline.py*' }
if ($pipe) {
    Write-Host ("  pipeline driver : running (PID {0})" -f $pipe.ProcessId) -ForegroundColor Green
    $state = Join-Path $root 'runs\gen7\state.json'
    if (Test-Path $state) {
        $done = (Get-Content $state -Raw | ConvertFrom-Json).PSObject.Properties.Name -join ', '
        Write-Host ("  stages complete : {0}" -f $done)
    }
} else {
    Write-Host "  pipeline driver : not running"
}

# --- fastchess (games in progress) ---
$fc = Get-Process fastchess -ErrorAction SilentlyContinue
if ($fc) { Write-Host ("  fastchess       : {0} running (a match is underway)" -f $fc.Count) }

# --- machine health ---
$cpu = (Get-CimInstance Win32_Processor).LoadPercentage
$os = Get-CimInstance Win32_OperatingSystem
$freeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
$disk = Get-PSDrive C
$diskFreeGB = [math]::Round($disk.Free / 1GB, 1)
Line 46
Write-Host ("  cpu load        : {0}%" -f $cpu)
Write-Host ("  disk free (C:)  : {0} GB" -f $diskFreeGB)
Write-Host ("  ram free        : {0} GB" -f $freeGB)

# --- newest worker log line ---
$wlog = Join-Path $root 'runs\gen7_datagen\worker_1.log'
if (Test-Path $wlog) {
    $last = (Get-Content $wlog -Tail 1)
    Write-Host ""
    Write-Host "  latest datagen line:"
    Write-Host ("    {0}" -f $last) -ForegroundColor DarkGray
}
Write-Host ""
