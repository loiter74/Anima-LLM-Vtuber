# Anima Project Start Script
param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$Install,
    [switch]$Help
)

function Write-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "[SUCCESS] $msg" -ForegroundColor Green }
function Write-Warning { param($msg) Write-Host "[WARNING] $msg" -ForegroundColor Yellow }
function Write-Error { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }

$script:BackendPid = $null
$script:FrontendPid = $null

function Stop-ProcessOnPort {
    param([int]$Port, [string]$ServiceName)
    Write-Info "Checking for existing $ServiceName on port ${Port}..."
    $netstat = netstat -ano | Select-String ":${Port}\s" | Select-String "LISTENING"
    $processIds = @()
    foreach ($line in $netstat) {
        if ($line -match '\s+(\d+)\s*$') {
            $processIds += [int]$matches[1]
        }
    }
    if ($processIds.Count -gt 0) {
        $pidList = $processIds -join ', '
        Write-Warning "Found process on port ${Port}: PID ${pidList}"
        foreach ($processId in $processIds) {
            try {
                Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
                Start-Sleep -Milliseconds 500
                Write-Success "Process ${processId} stopped"
            } catch {
                Write-Warning "Could not stop process ${processId}"
            }
        }
        Start-Sleep -Seconds 1
        $stillListening = netstat -ano | Select-String ":${Port}\s" | Select-String "LISTENING"
        if ($stillListening) {
            Write-Error "Port ${Port} is still in use"
            return $false
        } else {
            Write-Success "Port ${Port} released"
        }
    } else {
        Write-Success "Port ${Port} is free"
    }
    return $true
}

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

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python not found"
    exit 1
}

if (Get-Command pnpm -ErrorAction SilentlyContinue) {
    $PkgManager = "pnpm"
} elseif (Get-Command npm -ErrorAction SilentlyContinue) {
    $PkgManager = "npm"
    Write-Warning "pnpm not found, using npm"
} else {
    Write-Error "Node.js not found"
    exit 1
}

Write-Info "Package manager: $PkgManager"
Write-Host ""

Write-Host "========================================" -ForegroundColor Yellow
Write-Host "  Phase 1: Stopping Existing Services" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Yellow
Write-Host ""

if (-not $SkipBackend) {
    Stop-ProcessOnPort -Port 12394 -ServiceName "Backend"
}
if (-not $SkipFrontend) {
    Stop-ProcessOnPort -Port 3000 -ServiceName "Frontend"
}

Write-Success "All existing services stopped"
Write-Host ""

if ($Install) {
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host "  Phase 2: Installing Dependencies" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host ""
    Write-Info "Installing backend dependencies..."
    pip install -r requirements.txt
    Write-Info "Installing frontend dependencies..."
    Set-Location frontend
    & $PkgManager install
    Set-Location ..
    Write-Host ""
}

Write-Host "========================================" -ForegroundColor Green
Write-Host "  Phase 3: Starting Services" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

$env:PYTHONPATH = "$ProjectRoot\src"

if (-not $SkipBackend) {
    Write-Info "Starting backend server (port 12394)..."

    # Set PYTHONPATH environment variable
    $originalPath = $env:PYTHONPATH
    $env:PYTHONPATH = "$ProjectRoot\src"

    $backendProcess = Start-Process -FilePath "python" `
        -ArgumentList "-m", "anima.socketio_server" `
        -WorkingDirectory "$ProjectRoot" `
        -WindowStyle Normal `
        -PassThru

    # Restore original PYTHONPATH
    $env:PYTHONPATH = $originalPath

    $script:BackendPid = $backendProcess.Id
    Write-Success "Backend started (PID: $($backendProcess.Id))"

    Write-Info "Waiting for backend to start..."
    $maxWait = 15
    $waited = 0
    $backendStarted = $false

    while ($waited -lt $maxWait -and -not $backendStarted) {
        Start-Sleep -Seconds 2
        $waited += 2
        Write-Host "." -NoNewline

        $backendListening = netstat -ano | Select-String ":12394.*LISTENING"
        if ($backendListening) {
            $backendStarted = $true
            if ($backendListening -match '\s+(\d+)\s*$') {
                $actualPid = [int]$matches[1]
                $script:BackendPid = $actualPid
            }
        }
    }
    Write-Host ""

    if ($backendStarted) {
        Write-Success "Backend is listening on port 12394"
    } else {
        Write-Error "Backend failed to start"
        exit 1
    }
}

if (-not $SkipFrontend) {
    Write-Info "Starting frontend dev server..."
    $env:NEXT_PRIVATE_BENCHMARK_ENABLED = "false"
    $env:NODE_OPTIONS = "--no-warnings"

    # 使用 start 命令创建独立窗口，窗口不会自动关闭
    $frontendProcess = Start-Process -FilePath "cmd" `
        -ArgumentList "/c", "start `"Frontend Dev Server`" cmd /k `"cd /d `"$ProjectRoot\frontend`" && $PkgManager dev`"" `
        -WindowStyle Hidden `
        -PassThru

    $script:FrontendPid = $frontendProcess.Id
    Write-Success "Frontend started (PID: $($frontendProcess.Id))"

    Write-Info "Waiting for frontend to start..."
    $maxWait = 25
    $waited = 0
    $frontendStarted = $false

    while ($waited -lt $maxWait -and -not $frontendStarted) {
        Start-Sleep -Seconds 2
        $waited += 2
        Write-Host "." -NoNewline

        $frontendListening = netstat -ano | Select-String ":3000.*LISTENING"
        if ($frontendListening) {
            $frontendStarted = $true
            if ($frontendListening -match '\s+(\d+)\s*$') {
                $actualPid = [int]$matches[1]
                $script:FrontendPid = $actualPid
            }
        }
    }
    Write-Host ""

    if ($frontendStarted) {
        Write-Success "Frontend is listening on port 3000"
    } else {
        Write-Warning "Frontend not yet listening on port 3000"
        Write-Info "Frontend may still be compiling..."
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Startup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

if (-not $SkipBackend) {
    Write-Host "  Backend:  " -NoNewline
    Write-Host "http://localhost:12394" -ForegroundColor Cyan
}
if (-not $SkipFrontend) {
    Write-Host "  Frontend: " -NoNewline
    Write-Host "http://localhost:3000" -ForegroundColor Cyan
}
Write-Host ""
Write-Host "  Services are running in separate windows." -ForegroundColor Cyan
Write-Host ""
Write-Host "  To stop services:" -ForegroundColor Yellow
Write-Host "    1. Press Ctrl+C in each window, OR" -ForegroundColor Gray
Write-Host "    2. Run: .\scripts\stop.ps1" -ForegroundColor Gray
Write-Host ""
