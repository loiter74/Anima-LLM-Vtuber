# ============================================
# Anima Project Start Script (PowerShell)
# Start both backend and frontend services
# ============================================

param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$Install,
    [switch]$Help
)

# Color output functions
function Write-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "[SUCCESS] $msg" -ForegroundColor Green }
function Write-Warning { param($msg) Write-Host "[WARNING] $msg" -ForegroundColor Yellow }
function Write-Error { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }

# Show help
if ($Help) {
    Write-Host @"
Usage: ./scripts/start.ps1 [Options]

Options:
    -SkipBackend    Skip backend startup
    -SkipFrontend   Skip frontend startup
    -Install        Reinstall dependencies
    -Help           Show help message
"@
    exit 0
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "  Anima Project Startup Script" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""

# Get project root directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

# Check Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python not found, please install Python first"
    exit 1
}

# Check package manager
if (Get-Command pnpm -ErrorAction SilentlyContinue) {
    $PkgManager = "pnpm"
} elseif (Get-Command npm -ErrorAction SilentlyContinue) {
    $PkgManager = "npm"
    Write-Warning "pnpm not found, using npm"
} else {
    Write-Error "Node.js not found, please install Node.js first"
    exit 1
}

Write-Info "Package manager: $PkgManager"
Write-Host ""

# Install dependencies
if ($Install) {
    Write-Info "Installing backend dependencies..."
    pip install -r requirements.txt
    
    Write-Info "Installing frontend dependencies..."
    Set-Location frontend
    & $PkgManager install
    Set-Location ..
    Write-Host ""
}

# Start backend
if (-not $SkipBackend) {
    Write-Info "Starting backend server (port 12394)..."
    
    $backendJob = Start-Process -FilePath "cmd" -ArgumentList "/k", "cd /d `"$ProjectRoot\src`" && python -m anima.socketio_server" -PassThru -WindowStyle Normal
    
    Write-Success "Backend started: http://localhost:12394 (PID: $($backendJob.Id))"
    
    Write-Info "Waiting for backend to start..."
    Start-Sleep -Seconds 3
} else {
    Write-Warning "Skipping backend"
}

# Start frontend
if (-not $SkipFrontend) {
    Write-Info "Starting frontend dev server..."
    
    # Disable Turbopack benchmark to avoid warning
    $env:NODE_OPTIONS = "--no-warnings"
    
    $frontendJob = Start-Process -FilePath "cmd" -ArgumentList "/k", "cd /d `"$ProjectRoot\frontend`" && set NEXT_PRIVATE_BENCHMARK_ENABLED=false&& $PkgManager dev" -PassThru -WindowStyle Normal
    
    Write-Success "Frontend started: http://localhost:3000 (PID: $($frontendJob.Id))"
} else {
    Write-Warning "Skipping frontend"
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Startup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

if (-not $SkipBackend) { Write-Host "  Backend: " -NoNewline; Write-Host "http://localhost:12394" -ForegroundColor Cyan }
if (-not $SkipFrontend) { Write-Host "  Frontend: " -NoNewline; Write-Host "http://localhost:3000" -ForegroundColor Cyan }

Write-Host ""
Write-Host "  Services run in separate terminal windows" -ForegroundColor Gray
Write-Host "  Close the windows to stop the services" -ForegroundColor Gray
Write-Host ""