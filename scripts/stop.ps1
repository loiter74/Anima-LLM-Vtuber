# ============================================
# Anima 项目停止脚本 (PowerShell)
# 一键关闭前后端服务
# ============================================

param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$Help
)

# 显示帮助
if ($Help) {
    Write-Host "用法: ./stop.ps1 [选项]"
    Write-Host ""
    Write-Host "选项:"
    Write-Host "  -SkipBackend     跳过后端停止"
    Write-Host "  -SkipFrontend    跳过前端停止"
    Write-Host "  -Help            显示帮助信息"
    exit 0
}

Write-Host ""
Write-Host "========================================"
Write-Host "  Anima 项目停止脚本"
Write-Host "========================================"
Write-Host ""

# 获取脚本所在目录
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

# 停止后端服务 (端口 12394)
if (-not $SkipBackend) {
    Write-Host "[信息] 停止后端服务 (端口 12394)..."
    
    # 方法1: 通过窗口标题关闭
    $backendWindows = Get-Process -Name "cmd" -ErrorAction SilentlyContinue | 
        Where-Object { $_.MainWindowTitle -like "Anima Backend*" }
    
    if ($backendWindows) {
        $backendWindows | Stop-Process -Force
        Write-Host "[成功] 已关闭后端服务窗口"
    }
    
    # 方法2: 通过端口号关闭进程
    $backendProcess = Get-NetTCPConnection -LocalPort 12394 -ErrorAction SilentlyContinue | 
        Select-Object -ExpandProperty OwningProcess -Unique
    
    if ($backendProcess) {
        foreach ($processId in $backendProcess) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            Write-Host "[成功] 已终止后端进程 (PID: $processId)"
        }
    }
    
    # 方法3: 通过 python 进程名关闭 (包含 socketio_server)
    $pythonProcesses = Get-WmiObject Win32_Process -ErrorAction SilentlyContinue | 
        Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -like "*socketio_server*" }
    
    if ($pythonProcesses) {
        foreach ($proc in $pythonProcesses) {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "[成功] 已终止后端 Python 进程 (PID: $($proc.ProcessId))"
        }
    }
} else {
    Write-Host "[跳过] 后端服务"
}

# 停止前端服务 (端口 3000)
if (-not $SkipFrontend) {
    Write-Host "[信息] 停止前端服务 (端口 3000)..."
    
    # 方法1: 通过窗口标题关闭
    $frontendWindows = Get-Process -Name "cmd" -ErrorAction SilentlyContinue | 
        Where-Object { $_.MainWindowTitle -like "Anima Frontend*" }
    
    if ($frontendWindows) {
        $frontendWindows | Stop-Process -Force
        Write-Host "[成功] 已关闭前端服务窗口"
    }
    
    # 方法2: 通过端口号关闭进程
    $frontendProcess = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue | 
        Select-Object -ExpandProperty OwningProcess -Unique
    
    if ($frontendProcess) {
        foreach ($processId in $frontendProcess) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            Write-Host "[成功] 已终止前端进程 (PID: $processId)"
        }
    }
    
    # 方法3: 通过 node 进程名关闭 (包含 next)
    $nodeProcesses = Get-WmiObject Win32_Process -ErrorAction SilentlyContinue | 
        Where-Object { $_.Name -eq "node.exe" -and $_.CommandLine -like "*next*" }
    
    if ($nodeProcesses) {
        foreach ($proc in $nodeProcesses) {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "[成功] 已终止前端 Node 进程 (PID: $($proc.ProcessId))"
        }
    }
} else {
    Write-Host "[跳过] 前端服务"
}

Write-Host ""
Write-Host "========================================"
Write-Host "  停止完成！"
Write-Host "========================================"
Write-Host ""

# 显示当前端口占用情况
Write-Host "[信息] 当前端口状态:"
Write-Host ""

$backendPort = Get-NetTCPConnection -LocalPort 12394 -ErrorAction SilentlyContinue
if ($backendPort) {
    Write-Host "  端口 12394 (后端): 仍在使用"
} else {
    Write-Host "  端口 12394 (后端): 未被占用"
}

$frontendPort = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue
if ($frontendPort) {
    Write-Host "  端口 3000 (前端): 仍在使用"
} else {
    Write-Host "  端口 3000 (前端): 未被占用"
}

Write-Host ""