[CmdletBinding()]
param(
    [ValidateSet('preflight','status','download','tool-setup','convert','train','build','verify','verify-fixture','match','match-status','test')]
    [string]$Stage = 'status',
    [string]$Config = 'nnue/stockfish_teacher/pilot.json'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw "Python environment missing: $python" }
if (-not [System.IO.Path]::IsPathRooted($Config)) { $Config = Join-Path $root $Config }
$Config = [System.IO.Path]::GetFullPath($Config)
$cfg = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
if ([string]$cfg.run -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid run ID' }
$logs = Join-Path $root "runs/stockfish_teacher/$($cfg.run)/logs"
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$log = Join-Path $logs ("{0}-{1}.log" -f $Stage, (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
Write-Host "Python: $python"
Write-Host "Root: $root"
Write-Host "Config: $Config"
Write-Host "Log: $log"
Push-Location -LiteralPath $root
try {
    if ($Stage -eq 'test') {
        $runner = "import runpy,sys; sys.stderr=sys.stdout; runpy.run_module('unittest',run_name='__main__')"
        & $python -u -c $runner discover -s nnue/stockfish_teacher/tests -v | Tee-Object -FilePath $log
    } else {
        $runner = "import runpy,sys; sys.stderr=sys.stdout; script=sys.argv.pop(1); sys.path.insert(0,'nnue/stockfish_teacher'); runpy.run_path(script,run_name='__main__')"
        & $python -u -c $runner nnue/stockfish_teacher/workflow.py $Stage --config $Config | Tee-Object -FilePath $log
    }
    $code = $LASTEXITCODE
} finally { Pop-Location }
if ($code -ne 0) { throw "External-data stage failed ($code); see $log" }
