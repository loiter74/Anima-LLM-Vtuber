# 环境配置切换脚本 (PowerShell)
# Usage: .\scripts\switch_env.ps1 [windows|wsl|linux]

param(
    [Parameter(Position=0)]
    [ValidateSet("windows", "wsl", "linux")]
    [string]$EnvName = "wsl"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$EnvFile = Join-Path $ProjectRoot ".env"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Anima 环境配置切换工具" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "项目根目录: $ProjectRoot"
Write-Host ""

# 备份现有 .env 文件
if (Test-Path $EnvFile) {
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $BackupFile = Join-Path $ProjectRoot ".env.backup.$Timestamp"
    Write-Host "📦 备份当前 .env 到: $BackupFile" -ForegroundColor Yellow
    Copy-Item $EnvFile $BackupFile
}

# 根据环境选择配置源
switch ($EnvName) {
    "windows" {
        $SourceFile = Join-Path $ProjectRoot ".env.windows.example"
        Write-Host "🪟 切换到 Windows 环境" -ForegroundColor Green
    }
    "wsl" {
        $SourceFile = Join-Path $ProjectRoot ".env.wsl.example"
        Write-Host "🐧 切换到 WSL 环境" -ForegroundColor Green
    }
    "linux" {
        $SourceFile = Join-Path $ProjectRoot ".env.linux.example"
        Write-Host "🐧 切换到 Linux 环境" -ForegroundColor Green
    }
}

# 检查源文件是否存在
if (-not (Test-Path $SourceFile)) {
    Write-Host "❌ 错误: 配置文件不存在: $SourceFile" -ForegroundColor Red
    Write-Host ""
    Write-Host "请先创建环境配置文件："
    Write-Host "  - .env.windows.example (Windows)"
    Write-Host "  - .env.wsl.example (WSL)"
    Write-Host "  - .env.linux.example (Linux)"
    exit 1
}

# 复制配置
Copy-Item $SourceFile $EnvFile
Write-Host "✅ 已复制配置: $SourceFile -> $EnvFile" -ForegroundColor Green
Write-Host ""

# 显示当前配置
Write-Host "⚠️  请检查并修改 .env 文件中的路径配置：" -ForegroundColor Yellow
Write-Host ""
Get-Content $EnvFile | Where-Object { $_ -match "^ANIMA_" } | ForEach-Object {
    Write-Host "  $_" -ForegroundColor Gray
}
Write-Host ""

Write-Host "✅ 环境切换完成！" -ForegroundColor Green
Write-Host ""
Write-Host "下一步:"
Write-Host "  1. 编辑 .env 文件，确认路径正确"
Write-Host "  2. 启动服务: python -m anima.socketio_server"
