# Resumes gen8 datagen: 12 hidden workers appending into data\gen8_raw.
# Called by the "START Sgurr" desktop button. Safe to run after any shutdown --
# datagen counts what's already on disk and continues; the training freeze
# stage trims any partial record left by an abrupt stop, so nothing is lost.
$root = 'C:\Coding\Sgurr'
$eng  = "$root\sgurr_cpp\datagen.exe"
$out  = "$root\data\gen8_raw"
$book = "$root\testing\book.epd"
$net  = "$root\nets\gen7.nnue"
$logd = "$root\runs\gen8_datagen"

New-Item -ItemType Directory -Force -Path $out, $logd | Out-Null

for ($i = 1; $i -le 12; $i++) {
    Start-Process -FilePath $eng `
        -ArgumentList "`"$out`"", "150000000", "nodes:150000", "`"$book`"", "`"$net`"" `
        -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput "$logd\worker_$i.log" `
        -RedirectStandardError  "$logd\worker_$i.err.log"
    Start-Sleep -Milliseconds 150
}
Start-Sleep 3
"Started " + (Get-Process datagen -ErrorAction SilentlyContinue).Count + " workers."
