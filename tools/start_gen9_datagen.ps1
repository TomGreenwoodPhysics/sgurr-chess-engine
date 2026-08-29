# Start 12 hidden gen9 workers writing to data\gen9_raw.
# Use the v8.0 net as the labeller and the verified -DSGR_RFP=0 datagen build.
# RFP-enabled builds can record raw scores and must not label this data.
#
# The target is a high cap because the data study still found gains at 56M.
# At roughly 7.9M positions per day, collect as long as the schedule allows.
#
# The run is resumable after stopping workers or shutting down the PC.
# Resolve the repository root from this script so clones work anywhere.
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
