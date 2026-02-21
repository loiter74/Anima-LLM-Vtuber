# ============================================
# Quick Start Script - 停止旧服务并启动新服务
# ============================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "  Anima Quick Start" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""

# Get project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

# Step 1: Stop all Python processes
Write-Host "[INFO] Stopping all Python processes..." -ForegroundColor Cyan
$pythonProcesses = Get-Process python -ErrorAction SilentlyContinue
if ($pythonProcesses) {
    foreach ($proc in $pythonProcesses) {
        Write-Host "  - Stopping Python process $($proc.Id)" -ForegroundColor Yellow
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "[SUCCESS] All Python processes stopped" -ForegroundColor Green
} else {
    Write-Host "[INFO] No Python processes found" -ForegroundColor Cyan
}

# Step 2: Stop all Node processes
Write-Host "[INFO] Stopping all Node processes..." -ForegroundColor Cyan
$nodeProcesses = Get-Process node -ErrorAction SilentlyContinue
if ($nodeProcesses) {
    foreach ($proc in $nodeProcesses) {
        Write-Host "  - Stopping Node process $($proc.Id)" -ForegroundColor Yellow
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "[SUCCESS] All Node processes stopped" -ForegroundColor Green
} else {
    Write-Host "[INFO] No Node processes found" -ForegroundColor Cyan
}

# Wait for ports to be released
Write-Host "[INFO] Waiting for ports to be released..." -ForegroundColor Cyan
Start-Sleep -Seconds 2

# Verify ports are free
$backendInUse = Get-NetTCPConnection -LocalPort 12394 -ErrorAction SilentlyContinue
$frontendInUse = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue

if ($backendInUse -or $frontendInUse) {
    Write-Host "[ERROR] Ports still in use!" -ForegroundColor Red
    Write-Host "  Port 12394: " -NoNewline
    if ($backendInUse) { Write-Host "IN USE" -ForegroundColor Red } else { Write-Host "FREE" -ForegroundColor Green }
    Write-Host "  Port 3000: " -NoNewline
    if ($frontendInUse) { Write-Host "IN USE" -ForegroundColor Red } else { Write-Host "FREE" -ForegroundColor Green }
    Write-Host ""
    Write-Host "[ERROR] Please close all terminal windows manually and try again" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[SUCCESS] All ports are free" -ForegroundColor Green
Write-Host ""

# Step 3: Start backend
Write-Host "[INFO] Starting backend server..." -ForegroundColor Cyan
$backendCmd = "cmd /k `"cd /d `"$ProjectRoot`" && python -m anima.socketio_server`""
$backendJob = Start-Process -FilePath "cmd" -ArgumentList "/k", "cd /d `"$ProjectRoot\src`" && python -m anima.socketio_server" -PassThru -WindowStyle Normal
Write-Host "[SUCCESS] Backend started (PID: $($backendJob.Id))" -ForegroundColor Green

Write-Host "[INFO] Waiting for backend to initialize..." -ForegroundColor Cyan
Start-Sleep -Seconds 3

# Step 4: Start frontend
Write-Host "[INFO] Starting frontend dev server..." -ForegroundColor Cyan
$env:NEXT_PRIVATE_BENCHMARK_ENABLED = "false"
$frontendJob = Start-Process -FilePath "cmd" -ArgumentList "/k", "cd /d `"$ProjectRoot\frontend`" && pnpm dev" -PassThru -WindowStyle Normal
Write-Host "[SUCCESS] Frontend started (PID: $($frontendJob.Id))" -ForegroundColor Green

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Startup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Backend:  " -NoNewline
Write-Host "http://localhost:12394" -ForegroundColor Cyan
Write-Host "  Frontend: " -NoNewline
Write-Host "http://localhost:3000" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Press Ctrl+C in the service windows to stop them" -ForegroundColor Gray
Write-Host ""
Write-Host "  Testing VAD:" -ForegroundColor Yellow
Write-Host "    1. Open http://localhost:3000" -ForegroundColor Gray
Write-Host "    2. Click the '🧪 测试音频' button" -ForegroundColor Gray
Write-Host "    3. Check backend terminal for VAD logs" -ForegroundColor Gray
Write-Host ""
