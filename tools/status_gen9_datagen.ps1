[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$activePath = Join-Path $root 'runs\gen9_datagen\active.json'

$live = @(Get-Process datagen -ErrorAction SilentlyContinue)

if (-not (Test-Path -LiteralPath $activePath)) {
    Write-Host 'No Gen9 session record exists.'
    Write-Host ("Live datagen processes: {0}" -f $live.Count)
    exit 0
}

$active = Get-Content -Raw -LiteralPath $activePath | ConvertFrom-Json
$out = [string]$active.output

$positions = 0L
foreach ($f in @(Get-ChildItem -LiteralPath $out -Filter 'data_*.bin' -File -ErrorAction SilentlyContinue)) {
    $positions += [long][math]::Floor($f.Length / 32)
}

$target  = [long]$active.target_positions
$startPos = [long]$active.existing_positions
$started = [datetime]$active.started_at
$elapsed = ((Get-Date) - $started).TotalSeconds
$made    = $positions - $startPos
$rate    = if ($elapsed -gt 0) { $made / $elapsed } else { 0 }

# Recorded workers that are still alive and still the expected binary.
$expected = [System.IO.Path]::GetFullPath([string]$active.binary)
$alive = 0
foreach ($w in @($active.workers)) {
    $p = Get-Process -Id ([int]$w.pid) -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -eq 'datagen' -and
        [System.IO.Path]::GetFullPath($p.Path) -eq $expected) { $alive++ }
}

$state = if ($alive -gt 0) { "RUNNING ($alive workers)" }
         elseif ($live.Count -gt 0) { "UNRECORDED datagen running ($($live.Count)) - not this session" }
         else { 'STOPPED' }

Write-Host '=============================================='
Write-Host " Gen9 datagen : $state"
Write-Host '=============================================='
Write-Host ("  session     : {0}  (started {1:yyyy-MM-dd HH:mm})" -f $active.session, $started)
Write-Host ("  positions   : {0:N0} / {1:N0}   ({2:N1}%)" -f $positions, $target, (100 * $positions / $target))
if ($elapsed -gt 60) {
    Write-Host ("  this session: +{0:N0} in {1:N0}h {2:N0}m  =  {3:N2}M/day" -f `
        $made, [math]::Floor($elapsed/3600), (($elapsed % 3600)/60), ($rate * 86400 / 1e6))
}
if ($rate -gt 0 -and $positions -lt $target) {
    $left = ($target - $positions) / $rate
    Write-Host ("  remaining   : {0:N0}  ->  ETA {1:yyyy-MM-dd HH:mm}  (in {2:N0}d {3:N0}h)" -f `
        ($target - $positions), (Get-Date).AddSeconds($left), [math]::Floor($left/86400), (($left % 86400)/3600))
} elseif ($positions -ge $target) {
    Write-Host '  TARGET REACHED - workers exit after their current game.'
}
Write-Host ("  recipe      : {0}  nodes:{1}  book {2}" -f `
    (Split-Path -Leaf $active.labeller), $active.nodes_per_move, (Split-Path -Leaf $active.book))
Write-Host ("  output      : {0}" -f $out)
