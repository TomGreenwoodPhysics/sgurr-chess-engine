param([string]$A, [string]$B, [int]$N = 16, [int]$Depth = 13, [int]$Hash = 256)
# Compare the speed of two engine builds in sgurr_cpp, for example
#   powershell -File tools\npscmp.ps1 -A sgr_old.exe -B sgr_new.exe
# Runs interleaved benches, each pinned to one core at High priority, and
# reports B's paired speed change against A with a 95% interval. Hash 256 is
# the game setting; the default 48 MB fits the X3D's L3.
# METHODOLOGY section 11 describes how it is used.
$dir = Join-Path $PSScriptRoot '..\sgurr_cpp'
$ra = @(); $rb = @()
function Run($exe) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo (Join-Path $dir $exe)
    $psi.WorkingDirectory = $dir
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $p = [System.Diagnostics.Process]::Start($psi)
    try { $p.ProcessorAffinity = [IntPtr]4; $p.PriorityClass = 'High' } catch {}
    # The engine prints nps on stderr, so read both streams.
    $errTask = $p.StandardError.ReadToEndAsync()
    $outTask = $p.StandardOutput.ReadToEndAsync()
    $p.StandardInput.WriteLine("setoption name Hash value $Hash")
    $p.StandardInput.WriteLine("bench $Depth")
    $p.StandardInput.WriteLine("quit")
    $p.WaitForExit()
    $text = $errTask.Result + $outTask.Result
    return [double]([regex]::Match($text, 'nps (\d+)').Groups[1].Value)
}
for ($i = 0; $i -lt $N; $i++) { $ra += Run $A; $rb += Run $B }
$ratios = for ($i = 0; $i -lt $N; $i++) { $rb[$i] / $ra[$i] }
$m = ($ratios | Measure-Object -Average).Average
$sd = [math]::Sqrt((($ratios | ForEach-Object { ($_ - $m) * ($_ - $m) }) | Measure-Object -Sum).Sum / ($N - 1))
$sa = $ra | Sort-Object; $sb = $rb | Sort-Object
$h = [int]($N / 2)
"Hash {6}: {0} median {1:N3}M | {2} median {3:N3}M | change {4:+0.0%;-0.0%} +/- {5:P1}" -f $A, (($sa[$h-1]+$sa[$h])/2e6), $B, (($sb[$h-1]+$sb[$h])/2e6), ($m - 1), (1.96 * $sd / [math]::Sqrt($N)), $Hash
