[CmdletBinding()]
param(
    [ValidateRange(1, 64)] [int]$Workers = 12,
    [ValidateRange(1, 1000000)] [int]$Nodes = 150000,
    [ValidateRange(1, 1000000000)] [long]$Target = 200000000,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$eng  = Join-Path $root 'sgurr_cpp\datagen.exe'
$out  = Join-Path $root 'data\gen9_raw_generic'
$legacyOut = Join-Path $root 'data\gen9_raw'
$book = Join-Path $root 'testing\datagen_gen9.epd'
$bookManifest = Join-Path $root 'testing\datagen_gen9_book.json'
$net  = Join-Path $root 'nets\gen8.nnue'
$logd = Join-Path $root 'runs\gen9_datagen'
$expectedNetHash = '896EB832D74776A42375E7FA152B4E032FFF1CF85BA2E529B420FE2D1B4B74BF'
$expectedBookHash = 'DC7C21BDA62D7BA413AFE1D3BB316B30E966AACD33D0634F0FB7BA3008A3473E'
$expectedBookSourceHash = '5835239F88CC2C7511B177C32392A69F3EDE21819CF0616F80A7F907CD21D17E'
$expectedBookPositions = 15000

function Get-CompletePositions([string]$Directory) {
    $sum = 0L
    foreach ($file in @(Get-ChildItem -LiteralPath $Directory -Filter 'data_*.bin' -File -ErrorAction SilentlyContinue)) {
        $sum += [long][math]::Floor($file.Length / 32)
    }
    return $sum
}

function Stop-StartedWorkers($Processes) {
    foreach ($process in @($Processes)) {
        Get-Process -Id $process.Id -ErrorAction SilentlyContinue | Stop-Process -Force
    }
}

Write-Host '============================================================'
Write-Host 'Sgurr Gen9 data generation preflight'
Write-Host '============================================================'

foreach ($path in @($eng, $book, $bookManifest, $net)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required input is missing: $path"
    }
}
New-Item -ItemType Directory -Force -Path $out, $logd | Out-Null

$busy = @(Get-Process datagen, fastchess -ErrorAction SilentlyContinue)
if ($busy.Count) {
    throw "Refusing to start while datagen/fastchess is active: $($busy.ProcessName -join ', ')"
}

$buildInfo = (& $eng --build-info 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $buildInfo -notmatch '(^| )rfp=0( |$)') {
    throw "Generator does not prove that RFP is disabled: '$buildInfo'"
}
if ($buildInfo -match ' (iir|nmpscale|razor|futility|seeprune|histprune|caphist|rootpvs|evalscale)=1( |$)') {
    throw "Generator has an unaccepted v9 search experiment enabled: '$buildInfo'"
}

$netHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $net).Hash
if ($netHash -ne $expectedNetHash) {
    throw "Gen8 labeller hash mismatch: $netHash"
}
$bookLines = @(Get-Content -LiteralPath $book | Where-Object { $_ -and -not $_.StartsWith('#') }).Count
if ($bookLines -ne $expectedBookPositions) {
    throw "Expected the $expectedBookPositions-position Gen9 datagen book, found $bookLines positions"
}
$bookHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $book).Hash
if ($bookHash -ne $expectedBookHash) {
    throw "Gen9 datagen book hash mismatch: $bookHash"
}
$bookMetadata = Get-Content -Raw -LiteralPath $bookManifest | ConvertFrom-Json
if ($bookMetadata.output_sha256.ToUpperInvariant() -ne $expectedBookHash `
        -or $bookMetadata.source_sha256.ToUpperInvariant() -ne $expectedBookSourceHash `
        -or [long]$bookMetadata.output_stats.positions -ne $expectedBookPositions) {
    throw 'Gen9 datagen book manifest does not match the approved source/output recipe'
}

# Preserve and remove only incomplete record tails left by a forced stop.
foreach ($file in @(Get-ChildItem -LiteralPath $out -Filter 'data_*.bin' -File -ErrorAction SilentlyContinue)) {
    $extra = $file.Length % 32
    if ($extra) {
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
        $backup = "$($file.FullName).torn-$stamp.bak"
        Copy-Item -LiteralPath $file.FullName -Destination $backup
        $stream = [System.IO.File]::Open(
            $file.FullName, [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
        try { $stream.SetLength($file.Length - $extra) } finally { $stream.Dispose() }
        Write-Host "Repaired $($file.Name): preserved $backup and trimmed $extra byte(s)"
    }
}

$existing = Get-CompletePositions $out
if ($existing -ge $Target) {
    Write-Host "Target already reached: $existing / $Target positions"
    exit 0
}

$drive = [System.IO.DriveInfo]::new(([System.IO.Path]::GetPathRoot($out)))
$rawBytesNeeded = [long](($Target - $existing) * 32)
$reserve = 5GB
if ($drive.AvailableFreeSpace -lt ($rawBytesNeeded + $reserve)) {
    throw 'Insufficient disk space: need raw data plus a 5 GiB reserve'
}

$binaryHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $eng).Hash
$commit = (& git -C $root rev-parse HEAD).Trim()
$dirty = [bool]((& git -C $root status --porcelain | Out-String).Trim())
$legacyPositions = if (Test-Path -LiteralPath $legacyOut -PathType Container) {
    Get-CompletePositions $legacyOut
} else { 0L }

Write-Host "Build     : $buildInfo"
Write-Host "Binary    : $binaryHash"
Write-Host "Labeller  : gen8.nnue $netHash"
Write-Host "Book      : $bookLines positions $bookHash"
Write-Host "Existing  : $existing / $Target positions"
if ($legacyPositions) {
    Write-Host "Excluded  : $legacyPositions pilot positions made with testing/book.epd"
}
Write-Host "Workers   : $Workers at nodes:$Nodes"
Write-Host "Disk free : $([math]::Round($drive.AvailableFreeSpace / 1GB, 1)) GiB"

if ($PreflightOnly) {
    Write-Host 'PREFLIGHT PASSED -- no workers started'
    exit 0
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$session = Join-Path $logd $stamp
New-Item -ItemType Directory -Force -Path $session | Out-Null
$processes = @()
try {
    for ($i = 1; $i -le $Workers; $i++) {
        $stdout = Join-Path $session "worker_$i.out.log"
        $stderr = Join-Path $session "worker_$i.err.log"
        $processes += Start-Process -FilePath $eng `
            -ArgumentList @("`"$out`"", "$Target", "nodes:$Nodes", "`"$book`"", "`"$net`"") `
            -WorkingDirectory $root -WindowStyle Hidden `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
        Start-Sleep -Milliseconds 150
    }

    Start-Sleep -Seconds 6
    $alive = @($processes | Where-Object { Get-Process -Id $_.Id -ErrorAction SilentlyContinue })
    if ($alive.Count -ne $Workers) {
        throw "Only $($alive.Count) of $Workers workers survived startup"
    }
    foreach ($i in 1..$Workers) {
        $stderr = Join-Path $session "worker_$i.err.log"
        $text = Get-Content -Raw -LiteralPath $stderr -ErrorAction SilentlyContinue
        if ($text -notmatch 'labelling with NNUE:' -or $text -notmatch "labelling by nodes=$Nodes") {
            throw "Worker $i did not confirm the NNUE and node budget; inspect $stderr"
        }
    }

    $workerRecords = @($processes | ForEach-Object {
        $live = Get-Process -Id $_.Id -ErrorAction Stop
        [ordered]@{ pid = $_.Id; started_at = $live.StartTime.ToString('o') }
    })
    $manifest = [ordered]@{
        schema_version = 1
        session = $stamp
        started_at = (Get-Date).ToString('o')
        source_commit = $commit
        source_dirty = $dirty
        binary = $eng
        binary_sha256 = $binaryHash
        build_info = $buildInfo
        output = $out
        existing_positions = $existing
        target_positions = $Target
        nodes_per_move = $Nodes
        workers = $workerRecords
        book = $book
        book_positions = $bookLines
        book_sha256 = $bookHash
        book_manifest = $bookManifest
        book_source_sha256 = $expectedBookSourceHash
        labeller = $net
        labeller_sha256 = $netHash
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $session 'manifest.json') -Encoding utf8
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $logd 'active.json') -Encoding utf8
}
catch {
    Stop-StartedWorkers $processes
    throw
}

Write-Host "STARTED $Workers verified Gen9 workers"
Write-Host "Session logs: $session"
Write-Host 'Pause with:  powershell -File tools\pause_gen9_datagen.ps1'
