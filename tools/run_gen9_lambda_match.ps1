[CmdletBinding()]
param(
    [ValidateSet('0.7', '0.8', '1.0')] [string]$Lambda = '1.0',
    [ValidateRange(1, 1000000)] [int]$Rounds = 500,
    [ValidateRange(1, 64)] [int]$Concurrency = 7
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$lambdaConfig = if ($Lambda -eq '0.7') {
    @{ Directory = 'lambda_07_vs_09'; Engine = 'sgr_gen9_l07_s0.exe'; Seed = 20260922 }
} elseif ($Lambda -eq '0.8') {
    @{ Directory = 'lambda_08_vs_09'; Engine = 'sgr_gen9_l08_s0.exe'; Seed = 20260921 }
} else {
    @{ Directory = 'lambda_1_vs_09'; Engine = 'sgr_gen9_l1_s0.exe'; Seed = 20260920 }
}
$experiment = Join-Path $root "runs\gen9_102m\$($lambdaConfig.Directory)"
$run = Join-Path $experiment 'match'
$candidate = Join-Path $experiment "engines\$($lambdaConfig.Engine)"
$reference = Join-Path $experiment 'engines\sgr_gen9_l09_s0.exe'
$fastchess = Join-Path $root 'benchmarks\tools\fastchess.exe'
$book = Join-Path $root 'testing\UHO_4060_v4.epd'
$buildManifest = Join-Path $experiment 'build.json'
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
    opening_seed = $lambdaConfig.Seed
    book = $book
    book_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $book).Hash.ToLowerInvariant()
    candidate = [ordered]@{ path = $candidate; sha256 = $candidateHash }
    reference = [ordered]@{ path = $reference; sha256 = $referenceHash }
    pgn = $pgn
}
$status | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statusPath -Encoding utf8

$fastchessArgs = @(
    '-engine', "cmd=$candidate", "name=Sgurr-gen9-102M-lambda$Lambda-s0",
    '-engine', "cmd=$reference", 'name=Sgurr-gen9-102M-lambda0.9-s0',
    '-each', 'tc=8+0.08', 'restart=on', 'option.Hash=256',
    '-rounds', "$Rounds", '-repeat', '-concurrency', "$Concurrency",
    '-openings', "file=$book", 'format=epd', 'order=random',
    '-srand', "$($lambdaConfig.Seed)", '-ratinginterval', '50',
    '-pgnout', "file=$pgn", 'notation=san', 'append=false',
    '-event', "Gen9 102M lambda $Lambda vs 0.9", '-site', 'local'
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
