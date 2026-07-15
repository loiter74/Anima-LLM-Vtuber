$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

& $python -m pytest tests/config/test_runtime_manifest.py `
    -q `
    -n 0 `
    --cov=animetta.config.manifest `
    --cov-branch `
    --cov-report=term-missing `
    --cov-fail-under=100

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
