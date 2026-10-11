param([string]$Python = "python", [string]$Output = ("runs/reproduce-" + (Get-Date -Format "yyyyMMdd-HHmmss")))
$ErrorActionPreference = "Stop"
Push-Location (Join-Path $PSScriptRoot "..")
try {
    & $Python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 2)"
    if ($LASTEXITCODE) { throw "Python 3.9+ required. Pass -Python with the full path to a supported interpreter." }
    & $Python -m kylin_memory_bench doctor
    if ($LASTEXITCODE) { throw "doctor failed" }
    & $Python -m unittest discover -s tests -v
    if ($LASTEXITCODE) { throw "tests failed" }
    & $Python -m kylin_memory_bench demo --output $Output --repeats 3
    if ($LASTEXITCODE) { throw "benchmark failed" }
    & $Python -m kylin_memory_bench verify $Output
    if ($LASTEXITCODE) { throw "verification failed" }
} finally { Pop-Location }
