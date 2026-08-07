# gen9 datagen -- 12 hidden workers appending into data\gen9_raw.
#
# Labeller is the v8.0 net (nets/gen8.nnue), the strongest verified net: the
# flywheel's only proven lever (+126 Elo last turn). datagen.exe MUST be the
# -DSGR_RFP=0 build -- RFP returns raw rather than searched scores and poisoned
# gen6 entirely; the binary was rebuilt and byte-verified against an RFP=1 twin
# before this run.
#
# Target is a high CAP, not a goal: the 2026-08-01 data study found returns
# still ACCELERATING at 56M (14M->28M +17 Elo, 28M->56M +48), so more positions
# were still paying when measurement stopped. Collect as long as the calendar
# allows; ~7.9M/day means ~110M in two weeks.
#
# Safe to stop any time (Ctrl+C the workers, or Stop-Process datagen) and safe
# to shut the PC down: datagen counts what is already on disk and continues,
# and the pipeline's freeze stage trims any partial trailing record.
# Repository root, resolved from this script's own location (tools/..) so a
# clone anywhere works.
$root = Split-Path -Parent $PSScriptRoot
$eng  = "$root\sgurr_cpp\datagen.exe"
$out  = "$root\data\gen9_raw"
$book = "$root\testing\book.epd"
$net  = "$root\nets\gen8.nnue"
$logd = "$root\runs\gen9_datagen"

New-Item -ItemType Directory -Force -Path $out, $logd | Out-Null

if (Get-Process datagen -ErrorAction SilentlyContinue) {
    "datagen already running -- not starting a second set."
    exit 0
}

for ($i = 1; $i -le 12; $i++) {
    Start-Process -FilePath $eng `
        -ArgumentList "`"$out`"", "200000000", "nodes:150000", "`"$book`"", "`"$net`"" `
        -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput "$logd\worker_$i.log" `
        -RedirectStandardError  "$logd\worker_$i.err.log"
    Start-Sleep -Milliseconds 150
}
Start-Sleep 4
"Started " + (Get-Process datagen -ErrorAction SilentlyContinue).Count + " gen9 workers (labeller: gen8.nnue = v8.0)."
