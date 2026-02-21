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

# Stop existing services
function Stop-ExistingServices {
    param([string]$Port, [string]$ServiceName)

    Write-Info "Checking for existing $ServiceName processes on port $Port..."

    # Find processes using the port
    $netstat = netstat -ano | Select-String ":$Port\s" | Select-String "LISTENING"
    $pids = @()

    foreach ($line in $netstat) {
        if ($line -match '\s+(\d+)\s*$') {
            $pids += [int]$matches[1]
        }
    }

    if ($pids.Count -gt 0) {
        Write-Warning "Found $($pids.Count) process(es) using port $Port: $($pids -join ', ')"

        foreach ($pid in $pids) {
            try {
                $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
                if ($process) {
                    Write-Info "Stopping process $pid ($($process.ProcessName))..."
                    Stop-Process -Id $pid -Force
                    Start-Sleep -Milliseconds 500
                } else {
                    Write-Warning "Process $pid not found, skipping..."
                }
            } catch {
                Write-Warning "Could not stop process $pid: $_"
            }
        }

        # Wait for ports to be released
        Start-Sleep -Seconds 1

        # Verify port is free
        $stillListening = netstat -ano | Select-String ":$Port\s" | Select-String "LISTENING"
        if ($stillListening) {
            Write-Error "Port $Port is still in use. Please close all terminal windows and try again."
            return $false
        } else {
            Write-Success "Port $Port released successfully"
        }
    } else {
        Write-Success "Port $Port is free"
    }

    return $true
}

# Stop all Python and Node.js processes for this project
function Stop-ProjectProcesses {
    Write-Info "Checking for existing Anima processes..."

    $stopped = $false

    # Stop Python processes (backend)
    $pythonProcesses = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
        $_.MainWindowTitle -like "*anima*" -or $_.Path -like "*anima*"
    }

    if ($pythonProcesses) {
        Write-Warning "Found $($pythonProcesses.Count) Anima Python process(es)"
        foreach ($proc in $pythonProcesses) {
            Write-Info "Stopping Python process $($proc.Id)..."
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            $stopped = $true
        }
    }

    # Stop Node.js processes (frontend)
    $nodeProcesses = Get-Process node -ErrorAction SilentlyContinue | Where-Object {
        $_.MainWindowTitle -like "*next*" -or $_.MainWindowTitle -like "*anima*"
    }

    if ($nodeProcesses) {
        Write-Warning "Found $($nodeProcesses.Count) Anima Node.js process(es)"
        foreach ($proc in $nodeProcesses) {
            Write-Info "Stopping Node.js process $($proc.Id)..."
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            $stopped = $true
        }
    }

    if ($stopped) {
        Start-Sleep -Seconds 1
        Write-Success "All existing Anima processes stopped"
    } else {
        Write-Success "No existing Anima processes found"
    }

    return $true
}

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

# Stop existing services
Write-Host "========================================" -ForegroundColor Yellow
Write-Host "  Stopping Existing Services" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Yellow
Write-Host ""

# Stop backend port
if (-not $SkipBackend) {
    if (-not (Stop-ExistingServices -Port 12394 -ServiceName "Backend")) {
        Write-Error "Failed to stop existing backend services"
        exit 1
    }
}

# Stop frontend port
if (-not $SkipFrontend) {
    if (-not (Stop-ExistingServices -Port 3000 -ServiceName "Frontend")) {
        Write-Error "Failed to stop existing frontend services"
        exit 1
    }
}

# Stop any remaining project processes
Stop-ProjectProcesses

Write-Host ""
Write-Success "All existing services stopped"
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