[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$activePath = Join-Path $root 'runs\gen9_datagen\active.json'
if (-not (Test-Path -LiteralPath $activePath)) {
    Write-Host 'No Gen9 active-session record exists.'
    exit 0
}

$active = Get-Content -Raw -LiteralPath $activePath | ConvertFrom-Json
$expectedExe = [System.IO.Path]::GetFullPath([string]$active.binary)

function Get-SafeProcessPath($Process) {
    try { $raw = $Process.Path } catch { return $null }
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    try { return [System.IO.Path]::GetFullPath($raw) } catch { return $null }
}

$stopped = 0
foreach ($worker in @($active.workers)) {
    $process = Get-Process -Id ([int]$worker.pid) -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    if ($process.ProcessName -ne 'datagen') {
        Write-Warning "PID $($worker.pid) is now $($process.ProcessName), not datagen; leaving it alone"
        continue
    }
    $procPath = Get-SafeProcessPath $process
    if ($procPath -and $procPath -ne $expectedExe) {
        Write-Warning "PID $($worker.pid) is a different executable; leaving it alone"
        continue
    }
    try { Stop-Process -Id $process.Id -Force -ErrorAction Stop; $stopped++ } catch { }
}

# The launcher spawns workers before it writes active.json, so a pause during
# that window would leave unrecorded workers running and still report success.
# Sweep for any datagen still alive from the expected binary and stop those too.
$orphans = 0
foreach ($process in @(Get-Process datagen -ErrorAction SilentlyContinue)) {
    $procPath = Get-SafeProcessPath $process
    if ($procPath -and $procPath -ne $expectedExe) {
        Write-Warning "PID $($process.Id) is a different datagen build; leaving it alone"
        continue
    }
    try { Stop-Process -Id $process.Id -Force -ErrorAction Stop; $orphans++ } catch { }
}

Start-Sleep -Seconds 2
$remaining = @(Get-Process datagen -ErrorAction SilentlyContinue).Count
$positions = 0L
foreach ($file in @(Get-ChildItem -LiteralPath $active.output -Filter 'data_*.bin' -File -ErrorAction SilentlyContinue)) {
    $positions += [long][math]::Floor($file.Length / 32)
}

Write-Host "Stopped $stopped recorded Gen9 worker(s)."
if ($orphans) { Write-Host "Also stopped $orphans unrecorded worker(s) from the same binary." }
Write-Host "Remaining datagen processes: $remaining"
Write-Host "Complete positions on disk: $positions"
Write-Host 'Any incomplete final record will be preserved and repaired by the next launch preflight.'
