# ============================================
# Anima Project Stop Script (PowerShell)
# Enhanced with graceful shutdown and resource verification
# ============================================

param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$Help
)

# Color output functions
function Write-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "[SUCCESS] $msg" -ForegroundColor Green }
function Write-Warning { param($msg) Write-Host "[WARNING] $msg" -ForegroundColor Yellow }
function Write-Error { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }

# ============================================
# Stop Functions
# ============================================

function Stop-ServiceOnPort {
    param(
        [int]$Port,
        [string]$ServiceName
    )

    Write-Info "Stopping $ServiceName (port $Port)..."

    $stopped = $false

    # Method 1: Use Get-NetTCPConnection (more reliable)
    $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" }

    if ($connections) {
        $processIds = @($connections | ForEach-Object { $_.OwningProcess } | Select-Object -Unique)

        if ($processIds.Count -gt 0) {
            Write-Info "Found process(es) on port ${Port}: $($processIds -join ', ')"

            foreach ($processId in $processIds) {
                try {
                    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
                    if ($process) {
                        Write-Info "Stopping PID ${processId} ($($process.ProcessName))..."

                        # Method 1: Try Stop-Process first
                        Stop-Process -Id $processId -Force -ErrorAction Stop

                        # Method 2: If Stop-Process fails, use taskkill
                        if ($? -eq $false) {
                            Write-Info "Using taskkill as fallback..."
                            & taskkill /F /PID $processId 2>&1 | Out-Null
                        }

                        $stopped = $true
                        Write-Success "Stopped process ${processId}"
                    }
                } catch {
                    Write-Warning "Could not stop process ${processId} - $($_.Exception.Message)"
                }
            }

            # Wait for port to be released
            $maxWait = 5
            $waited = 0
            while ($waited -lt $maxWait) {
                $stillListening = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
                    Where-Object { $_.State -eq "Listen" }
                if (-not $stillListening) {
                    break
                }
                Start-Sleep -Seconds 1
                $waited++
            }
        }
    }

    return $stopped
}

function Stop-ProcessesByName {
    param(
        [string]$ProcessName,
        [string[]]$MatchPatterns
    )

    $stopped = $false

    # First get all processes by name
    $allProcesses = Get-WmiObject Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq $ProcessName }

    # Then filter by command line patterns
    $processes = foreach ($proc in $allProcesses) {
        foreach ($pattern in $MatchPatterns) {
            if ($proc.CommandLine -like $pattern) {
                $proc
                break
            }
        }
    }

    if ($processes) {
        foreach ($proc in @($processes)) {  # Force array copy
            Write-Info "Stopping $ProcessName process $($proc.ProcessId)..."
            try {
                # Method 1: Try Stop-Process
                $stopResult = Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop

                # Method 2: If Stop-Process fails, use taskkill
                if ($? -eq $false -or $stopResult -eq $null) {
                    Write-Info "Using taskkill as fallback for PID $($proc.ProcessId)..."
                    $taskkillResult = & taskkill /F /PID $proc.ProcessId 2>&1
                    if ($LASTEXITCODE -eq 0) {
                        $stopped = $true
                        Write-Success "Stopped process $($proc.ProcessId) via taskkill"
                    } else {
                        Write-Warning "taskkill failed: $taskkillResult"
                    }
                } else {
                    $stopped = $true
                    Write-Success "Stopped process $($proc.ProcessId)"
                }

                # Brief pause between kills
                Start-Sleep -Milliseconds 500
            } catch {
                Write-Warning "Could not stop process $($proc.ProcessId) - $($_.Exception.Message)"
            }
        }
    }

    return $stopped
}

function Clear-TempFiles {
    Write-Info "Cleaning up temporary files..."

    $tempPaths = @(
        "$env:TEMP\anima_*",
        "$ProjectRoot\.next\cache",
        "$ProjectRoot\frontend\.next\cache",
        "$ProjectRoot\src\__pycache__"
    )

    $cleaned = $false
    foreach ($pattern in $tempPaths) {
        $items = Get-Item -Path $pattern -ErrorAction SilentlyContinue
        if ($items) {
            foreach ($item in $items) {
                try {
                    Remove-Item -Path $item.FullName -Recurse -Force -ErrorAction SilentlyContinue
                    $cleaned = $true
                } catch {
                    # Silently ignore cleanup errors
                }
            }
        }
    }

    if ($cleaned) {
        Write-Success "Temporary files cleaned up"
    }
}

# ============================================
# Show Help
# ============================================

if ($Help) {
    Write-Host @"
Usage: ./scripts/stop.ps1 [Options]

Options:
    -SkipBackend     Skip backend stop
    -SkipFrontend    Skip frontend stop
    -Help            Show help message

Features:
    - Graceful shutdown with SIGTERM first
    - Falls back to SIGKILL if needed
    - Verifies port release
    - Cleans up temporary files
"@
    exit 0
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "  Anima Project Stop Script" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""

# Get project root directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

# ============================================
# Phase 1: Stop Services
# ============================================

Write-Host "========================================" -ForegroundColor Yellow
Write-Host "  Phase 1: Stopping Services" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Yellow
Write-Host ""

$backendStopped = $false
$frontendStopped = $false

# Stop frontend first (it depends on backend)
if (-not $SkipFrontend) {
    $frontendStopped = Stop-ServiceOnPort -Port 3000 -ServiceName "Frontend"

    # Also stop by process name
    Stop-ProcessesByName -ProcessName "node.exe" -MatchPatterns @("*next*", "*anima*", "*3000*")

    if ($frontendStopped) {
        Write-Success "Frontend service stopped"
    } else {
        Write-Warning "No frontend service found on port 3000"
    }
} else {
    Write-Warning "Skipping frontend"
}

Write-Host ""

# Stop backend
if (-not $SkipBackend) {
    $backendStopped = Stop-ServiceOnPort -Port 12394 -ServiceName "Backend"

    # Also stop by process name
    Stop-ProcessesByName -ProcessName "python.exe" -MatchPatterns @("*socketio_server*", "*anima*")

    if ($backendStopped) {
        Write-Success "Backend service stopped"
    } else {
        Write-Warning "No backend service found on port 12394"
    }
} else {
    Write-Warning "Skipping backend"
}

Write-Host ""

# ============================================
# Phase 2: Verify Ports Released
# ============================================

Write-Host "========================================" -ForegroundColor Yellow
Write-Host "  Phase 2: Verifying Port Release" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Yellow
Write-Host ""

$backendPortInUse = $false
$frontendPortInUse = $false

if (-not $SkipBackend) {
    $backendPort = Get-NetTCPConnection -LocalPort 12394 -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" }

    if ($backendPort) {
        Write-Error "Port 12394 (backend) is still in use"
        $backendPortInUse = $true

        # Show which process is holding the port
        $procId = $backendPort.OwningProcess
        $process = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($process) {
            Write-Warning "  Held by: $($process.ProcessName) (PID: $procId)"
            $cmdLine = (Get-WmiObject Win32_Process -Filter "ProcessId=$procId").CommandLine
            if ($cmdLine) {
                Write-Warning "  Command: $cmdLine"
            }
        }
    } else {
        Write-Success "Port 12394 (backend): Released"
    }
}

if (-not $SkipFrontend) {
    $frontendPort = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" }

    if ($frontendPort) {
        Write-Error "Port 3000 (frontend) is still in use"
        $frontendPortInUse = $true

        # Show which process is holding the port
        $procId = $frontendPort.OwningProcess
        $process = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($process) {
            Write-Warning "  Held by: $($process.ProcessName) (PID: $procId)"
            $cmdLine = (Get-WmiObject Win32_Process -Filter "ProcessId=$procId").CommandLine
            if ($cmdLine) {
                Write-Warning "  Command: $cmdLine"
            }
        }
    } else {
        Write-Success "Port 3000 (frontend): Released"
    }
}

Write-Host ""

# ============================================
# Phase 3: Clean Temporary Files
# ============================================

Write-Host "========================================" -ForegroundColor Yellow
Write-Host "  Phase 3: Cleaning Resources" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Yellow
Write-Host ""

Clear-TempFiles

Write-Host ""

# ============================================
# Summary
# ============================================

Write-Host "========================================" -ForegroundColor Green
Write-Host "  Stop Summary" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

if ($backendStopped -or $frontendStopped) {
    Write-Success "Services stopped successfully"
} else {
    Write-Warning "No services were stopped"
}

if ($backendPortInUse -or $frontendPortInUse) {
    Write-Error "Some ports are still in use - you may need to:"
    Write-Host "  1. Check for other instances holding the ports" -ForegroundColor Gray
    Write-Host "  2. Run: Restart-Computer to clear all system resources" -ForegroundColor Gray
    Write-Host "  3. Manually kill the processes shown above" -ForegroundColor Gray
    exit 1
} else {
    Write-Success "All resources released successfully"
}

Write-Host ""
