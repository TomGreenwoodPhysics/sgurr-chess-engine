[CmdletBinding()]
param(
    [ValidateRange(1, 1000000)] [int]$Rounds = 500,
    [ValidateRange(1, 64)] [int]$Concurrency = 7
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$run = Join-Path $root 'runs\gen9_102m\lambda_07_vs_08\match'
$candidateRoot = Join-Path $root 'runs\gen9_102m\lambda_07_vs_09'
$referenceRoot = Join-Path $root 'runs\gen9_102m\lambda_08_vs_09'
$candidate = Join-Path $candidateRoot 'engines\sgr_gen9_l07_s0.exe'
$reference = Join-Path $referenceRoot 'engines\sgr_gen9_l08_s0.exe'
$candidateManifest = Join-Path $candidateRoot 'build.json'
$referenceManifest = Join-Path $referenceRoot 'build.json'
$fastchess = Join-Path $root 'benchmarks\tools\fastchess.exe'
$book = Join-Path $root 'testing\UHO_4060_v4.epd'
$pgn = Join-Path $run 'games.pgn'
$statusPath = Join-Path $run 'status.json'

foreach ($path in @($candidate, $reference, $candidateManifest, $referenceManifest,
        $fastchess, $book)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing match input: $path"
    }
}

$blocked = @(Get-Process datagen, fastchess, Trackmania -ErrorAction SilentlyContinue)
if ($blocked.Count) {
    throw "Timed match requires an idle PC; active: $($blocked.ProcessName -join ', ')"
}

$candidateBuild = Get-Content -Raw -LiteralPath $candidateManifest | ConvertFrom-Json
$referenceBuild = Get-Content -Raw -LiteralPath $referenceManifest | ConvertFrom-Json
$candidateHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $candidate).Hash.ToLowerInvariant()
$referenceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $reference).Hash.ToLowerInvariant()
if ($candidateHash -ne [string]$candidateBuild.candidate.engine_sha256 `
        -or $referenceHash -ne [string]$referenceBuild.candidate.engine_sha256) {
    throw 'A match engine changed after its admission gates passed'
}
if (($candidateBuild.sources | ConvertTo-Json -Compress) -ne `
        ($referenceBuild.sources | ConvertTo-Json -Compress)) {
    throw 'The two engines were not built from identical search source'
}

New-Item -ItemType Directory -Force -Path $run | Out-Null
if (Test-Path -LiteralPath $pgn) {
    throw "Refusing to overwrite an existing match: $pgn"
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
    opening_seed = 20260923
    book = $book
    book_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $book).Hash.ToLowerInvariant()
    candidate = [ordered]@{ path = $candidate; sha256 = $candidateHash }
    reference = [ordered]@{ path = $reference; sha256 = $referenceHash }
    pgn = $pgn
}
$status | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statusPath -Encoding utf8

$fastchessArgs = @(
    '-engine', "cmd=$candidate", 'name=Sgurr-gen9-102M-lambda0.7-s0',
    '-engine', "cmd=$reference", 'name=Sgurr-gen9-102M-lambda0.8-s0',
    '-each', 'tc=8+0.08', 'restart=on', 'option.Hash=256',
    '-rounds', "$Rounds", '-repeat', '-concurrency', "$Concurrency",
    '-openings', "file=$book", 'format=epd', 'order=random',
    '-srand', '20260923', '-ratinginterval', '50',
    '-pgnout', "file=$pgn", 'notation=san', 'append=false',
    '-event', 'Gen9 102M lambda 0.7 vs 0.8', '-site', 'local'
)

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
