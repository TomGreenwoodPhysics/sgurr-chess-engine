[CmdletBinding()]
param(
    [ValidateRange(1, 1000000)] [int]$Rounds = 500,
    [ValidateRange(1, 64)] [int]$Concurrency = 7
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$run = Join-Path $root 'runs\gen9_102m\match_seed0'
$candidate = Join-Path $root 'runs\gen9_102m\engines\sgr_gen9_102m_s0.exe'
$reference = Join-Path $root 'runs\gen9_102m\engines\sgr_gen8_ref.exe'
$fastchess = Join-Path $root 'benchmarks\tools\fastchess.exe'
$book = Join-Path $root 'testing\UHO_4060_v4.epd'
$buildManifest = Join-Path $root 'runs\gen9_102m\build.json'
$pgn = Join-Path $run 'games.pgn'
$statusPath = Join-Path $run 'status.json'

foreach ($path in @($candidate, $reference, $fastchess, $book, $buildManifest)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing match input: $path"
    }
}

$blocked = @(Get-Process datagen, fastchess, Trackmania -ErrorAction SilentlyContinue)
if ($blocked.Count) {
    throw "Timed match requires an idle PC; active: $($blocked.ProcessName -join ', ')"
}

New-Item -ItemType Directory -Force -Path $run | Out-Null
if (Test-Path -LiteralPath $pgn) {
    throw "Refusing to overwrite an existing match: $pgn"
}

$build = Get-Content -Raw -LiteralPath $buildManifest | ConvertFrom-Json
$candidateHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $candidate).Hash.ToLowerInvariant()
$referenceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $reference).Hash.ToLowerInvariant()
if ($candidateHash -ne [string]$build.candidate.engine_sha256 `
        -or $referenceHash -ne [string]$build.reference.engine_sha256) {
    throw 'A match engine changed after its admission gates passed'
}

$status = [ordered]@{
    schema_version = 1
    state = 'running'
    started_at = (Get-Date).ToString('o')
    runner_pid = $PID
    rounds = $Rounds
    games = 2 * $Rounds
    concurrency = $Concurrency
    time_control = '8+0.08'
    hash_mb = 256
    opening_pairing = 'colour-reversed pairs'
    opening_seed = 20260919
    book = $book
    book_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $book).Hash.ToLowerInvariant()
    candidate = [ordered]@{ path = $candidate; sha256 = $candidateHash }
    reference = [ordered]@{ path = $reference; sha256 = $referenceHash }
    pgn = $pgn
}
$status | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statusPath -Encoding utf8

$fastchessArgs = @(
    '-engine', "cmd=$candidate", 'name=Sgurr-gen9-102M-s0',
    '-engine', "cmd=$reference", 'name=Sgurr-gen8',
    '-each', 'tc=8+0.08', 'restart=on', 'option.Hash=256',
    '-rounds', "$Rounds", '-repeat', '-concurrency', "$Concurrency",
    '-openings', "file=$book", 'format=epd', 'order=random',
    '-srand', '20260919', '-ratinginterval', '50',
    '-pgnout', "file=$pgn", 'notation=san', 'append=false',
    '-event', 'Sgurr Gen9 102M seed0 vs Gen8', '-site', 'local'
)

# Keep the computer awake while allowing the display to switch off.
$signature = @'
[DllImport("kernel32.dll", SetLastError = true)]
public static extern uint SetThreadExecutionState(uint esFlags);
'@
$power = Add-Type -MemberDefinition $signature -Name PowerState -Namespace Sgurr -PassThru
[void]$power::SetThreadExecutionState([uint32]2147483649)
try {
    & $fastchess @fastchessArgs
    $matchExitCode = $LASTEXITCODE
} finally {
    [void]$power::SetThreadExecutionState([uint32]2147483648)
}

$status.state = if ($matchExitCode -eq 0) { 'complete' } else { 'failed' }
$status.completed_at = (Get-Date).ToString('o')
$status.exit_code = $matchExitCode
$status | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statusPath -Encoding utf8
exit $matchExitCode
