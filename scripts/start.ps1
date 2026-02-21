# ============================================
# Anima Project Start Script (PowerShell)
# Enhanced with resource cleanup and graceful shutdown
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

# Store PIDs for tracking
$script:BackendPid = $null
$script:FrontendPid = $null
$script:BackendCmdPid = $null
$script:FrontendCmdPid = $null

# ============================================
# Resource Cleanup Functions
# ============================================

function Stop-ProcessOnPort {
    param(
        [int]$Port,
        [string]$ServiceName,
        [switch]$Graceful
    )

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
        Write-Warning "Found $($pids.Count) process(es) using port ${Port}: $($pids -join ', ')"

        foreach ($processId in $pids) {
            try {
                $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
                if ($process) {
                    if ($Graceful) {
                        Write-Info "Attempting graceful shutdown of process ${processId} ($($process.ProcessName))..."
                        # Send CTRL+C to Windows process
                        $process.CloseMainWindow() | Out-Null
                        Start-Sleep -Milliseconds 1500

                        # Check if still running
                        $stillRunning = Get-Process -Id $processId -ErrorAction SilentlyContinue
                        if ($stillRunning) {
                            Write-Warning "Process ${processId} did not close gracefully, forcing..."
                            Stop-Process -Id $processId -Force
                        } else {
                            Write-Success "Process ${processId} closed gracefully"
                        }
                    } else {
                        Write-Info "Force stopping process ${processId} ($($process.ProcessName))..."
                        Stop-Process -Id $processId -Force
                    }
                    Start-Sleep -Milliseconds 500
                }
            } catch {
                $errorMsg = $_.Exception.Message
                Write-Warning "Could not stop process ${processId}: $errorMsg"
            }
        }

        # Wait for ports to be released
        $maxWait = 5
        $waited = 0
        while ($waited -lt $maxWait) {
            $stillListening = netstat -ano | Select-String ":$Port\s" | Select-String "LISTENING"
            if (-not $stillListening) {
                break
            }
            Start-Sleep -Seconds 1
            $waited++
        }

        # Final verification
        $stillListening = netstat -ano | Select-String ":$Port\s" | Select-String "LISTENING"
        if ($stillListening) {
            Write-Error "Port $Port is still in use after cleanup. Please manually check processes."
            return $false
        } else {
            Write-Success "Port $Port released successfully"
        }
    } else {
        Write-Success "Port $Port is free"
    }

    return $true
}

function Stop-ProjectProcesses {
    Write-Info "Checking for existing Anima processes..."

    $stopped = $false

    # Stop Python processes (backend) - more specific matching
    $pythonProcesses = Get-WmiObject Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -eq "python.exe" -and
            ($_.CommandLine -like "*socketio_server*" -or $_.CommandLine -like "*anima*")
        }

    if ($pythonProcesses) {
        Write-Warning "Found $($pythonProcesses.Count) Anima Python process(es)"
        foreach ($proc in $pythonProcesses) {
            Write-Info "Stopping Python process $($proc.ProcessId)..."
            try {
                Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
                $stopped = $true
            } catch {
                Write-Warning "Could not stop process $($proc.ProcessId) - $($_.Exception.Message)"
            }
        }
    }

    # Stop Node.js processes (frontend) - more specific matching
    $nodeProcesses = Get-WmiObject Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -eq "node.exe" -and
            ($_.CommandLine -like "*next*" -or $_.CommandLine -like "*anima*" -or $_.CommandLine -like "*3000*")
        }

    if ($nodeProcesses) {
        Write-Warning "Found $($nodeProcesses.Count) Anima Node.js process(es)"
        foreach ($proc in $nodeProcesses) {
            Write-Info "Stopping Node.js process $($proc.ProcessId)..."
            try {
                Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
                $stopped = $true
            } catch {
                Write-Warning "Could not stop process $($proc.ProcessId) - $($_.Exception.Message)"
            }
        }
    }

    # Stop cmd windows with Anima titles
    $cmdProcesses = Get-Process cmd -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -like "*Anima*" }

    if ($cmdProcesses) {
        Write-Warning "Found $($cmdProcesses.Count) Anima terminal window(s)"
        foreach ($proc in $cmdProcesses) {
            Write-Info "Closing terminal window $($proc.Id)..."
            try {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                $stopped = $true
            } catch {
                Write-Warning "Could not close window $($proc.Id) - $($_.Exception.Message)"
            }
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

function Clear-TempFiles {
    Write-Info "Cleaning up temporary files..."

    $tempPaths = @(
        "$env:TEMP\anima_*",
        "$ProjectRoot\.next\cache",
        "$ProjectRoot\frontend\.next\cache",
        "$ProjectRoot\src\__pycache__",
        "$ProjectRoot\logs\*.log"
    )

    $cleaned = $false
    foreach ($pattern in $tempPaths) {
        $items = Get-Item -Path $pattern -ErrorAction SilentlyContinue
        if ($items) {
            foreach ($item in $items) {
                try {
                    Remove-Item -Path $item.FullName -Recurse -Force -ErrorAction SilentlyContinue
                    Write-Info "Removed: $($item.FullName)"
                    $cleaned = $true
                } catch {
                    Write-Warning "Could not remove $($item.FullName) - $($_.Exception.Message)"
                }
            }
        }
    }

    if (-not $cleaned) {
        Write-Success "No temporary files to clean"
    } else {
        Write-Success "Temporary files cleaned up"
    }
}

# ============================================
# Shutdown Handler
# ============================================

function Invoke-Cleanup {
    Write-Info "`nInitiating graceful shutdown..."

    # Stop frontend first (it depends on backend)
    if ($script:FrontendCmdPid) {
        Write-Info "Stopping frontend (PID: $($script:FrontendCmdPid))..."
        try {
            Stop-Process -Id $script:FrontendCmdPid -Force -ErrorAction SilentlyContinue
        } catch {
            Write-Warning "Could not stop frontend: $($_.Exception.Message)"
        }
    }

    # Stop backend
    if ($script:BackendCmdPid) {
        Write-Info "Stopping backend (PID: $($script:BackendCmdPid))..."
        try {
            Stop-Process -Id $script:BackendCmdPid -Force -ErrorAction SilentlyContinue
        } catch {
            Write-Warning "Could not stop backend: $($_.Exception.Message)"
        }
    }

    # Additional cleanup for child processes
    Stop-ProcessOnPort -Port 3000 -ServiceName "Frontend" -Graceful:$false
    Stop-ProcessOnPort -Port 12394 -ServiceName "Backend" -Graceful:$false

    Write-Success "All services stopped"
    exit 0
}

# Register shutdown handlers
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    Invoke-Cleanup
}
trap {
    Invoke-Cleanup
}

# ============================================
# Show Help
# ============================================

if ($Help) {
    Write-Host @"
Usage: ./scripts/start.ps1 [Options]

Options:
    -SkipBackend    Skip backend startup
    -SkipFrontend   Skip frontend startup
    -Install        Reinstall dependencies
    -Help           Show help message

Resource Management:
    - Automatically stops existing processes on startup
    - Cleans up temporary files and caches
    - Graceful shutdown on script exit
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

# ============================================
# Phase 1: Stop Existing Services
# ============================================

Write-Host "========================================" -ForegroundColor Yellow
Write-Host "  Phase 1: Stopping Existing Services" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Yellow
Write-Host ""

# Stop backend port
if (-not $SkipBackend) {
    if (-not (Stop-ProcessOnPort -Port 12394 -ServiceName "Backend" -Graceful:$true)) {
        Write-Error "Failed to stop existing backend services"
        exit 1
    }
}

# Stop frontend port
if (-not $SkipFrontend) {
    if (-not (Stop-ProcessOnPort -Port 3000 -ServiceName "Frontend" -Graceful:$true)) {
        Write-Error "Failed to stop existing frontend services"
        exit 1
    }
}

# Stop any remaining project processes
Stop-ProjectProcesses

Write-Host ""
Write-Success "All existing services stopped"
Write-Host ""

# ============================================
# Phase 2: Clean Temporary Files
# ============================================

Write-Host "========================================" -ForegroundColor Yellow
Write-Host "  Phase 2: Cleaning Resources" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Yellow
Write-Host ""

Clear-TempFiles

Write-Host ""

# ============================================
# Phase 3: Install Dependencies (Optional)
# ============================================

if ($Install) {
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host "  Phase 3: Installing Dependencies" -ForegroundColor Yellow
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

# ============================================
# Phase 4: Start Services
# ============================================

Write-Host "========================================" -ForegroundColor Green
Write-Host "  Phase 4: Starting Services" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# Start backend
if (-not $SkipBackend) {
    Write-Info "Starting backend server (port 12394)..."

    $backendProcess = Start-Process -FilePath "python" `
        -ArgumentList "-m", "anima.socketio_server" `
        -WorkingDirectory "$ProjectRoot\src" `
        -PassThru `
        -WindowStyle Normal

    $script:BackendPid = $backendProcess.Id

    Write-Success "Backend started: http://localhost:12394 (PID: $($backendProcess.Id))"

    Write-Info "Waiting for backend to start..."
    Start-Sleep -Seconds 3

    # Verify backend is running
    $backendRunning = Get-Process -Id $backendProcess.Id -ErrorAction SilentlyContinue
    if (-not $backendRunning) {
        Write-Error "Backend failed to start. Check logs for details."
        exit 1
    }
} else {
    Write-Warning "Skipping backend"
}

# Start frontend
if (-not $SkipFrontend) {
    Write-Info "Starting frontend dev server..."

    # Disable Turbopack benchmark to avoid warning
    $env:NEXT_PRIVATE_BENCHMARK_ENABLED = "false"
    $env:NODE_OPTIONS = "--no-warnings"

    $frontendCmd = "cd /d `"$ProjectRoot\frontend`" && $PkgManager dev"
    $frontendProcess = Start-Process -FilePath "cmd" `
        -ArgumentList "/c", $frontendCmd `
        -PassThru `
        -WindowStyle Normal

    $script:FrontendPid = $frontendProcess.Id

    Write-Success "Frontend started: http://localhost:3000 (PID: $($frontendProcess.Id))"
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
Write-Host "  Press Ctrl+C to stop all services" -ForegroundColor Yellow
Write-Host "  Or run: .\scripts\stop.ps1" -ForegroundColor Gray
Write-Host ""

# Keep script running to handle shutdown
try {
    while ($true) {
        Start-Sleep -Seconds 1

        # Check if processes are still running
        if ($script:BackendPid) {
            $backendRunning = Get-Process -Id $script:BackendPid -ErrorAction SilentlyContinue
            if (-not $backendRunning) {
                Write-Warning "Backend process has stopped unexpectedly"
                $script:BackendPid = $null
            }
        }

        if ($script:FrontendPid) {
            $frontendRunning = Get-Process -Id $script:FrontendPid -ErrorAction SilentlyContinue
            if (-not $frontendRunning) {
                Write-Warning "Frontend process has stopped unexpectedly"
                $script:FrontendPid = $null
            }
        }

        # Exit if both stopped
        if (-not $script:BackendPid -and -not $script:FrontendPid) {
            Write-Warning "All services have stopped"
            break
        }
    }
} finally {
    Invoke-Cleanup
}
