@echo off
REM ============================================
REM Anima 项目停止脚本 (Windows)
REM 一键关闭前后端服务
REM ============================================

setlocal EnableDelayedExpansion

echo.
echo ========================================
echo   Anima 项目停止脚本
echo ========================================
echo.

REM 获取脚本所在目录的父目录（项目根目录）
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
cd /d "%PROJECT_ROOT%"

REM 解析参数
set "SKIP_BACKEND=0"
set "SKIP_FRONTEND=0"

:parse_args
if "%~1"=="" goto :end_parse
if /i "%~1"=="--skip-backend" set "SKIP_BACKEND=1"
if /i "%~1"=="--skip-frontend" set "SKIP_FRONTEND=1"
if /i "%~1"=="-h" goto :show_help
if /i "%~1"=="--help" goto :show_help
shift
goto :parse_args

:show_help
echo 用法: stop.bat [选项]
echo.
echo 选项:
echo   --skip-backend    跳过后端停止
echo   --skip-frontend   跳过前端停止
echo   -h, --help        显示帮助信息
echo.
exit /b 0

:end_parse

REM 停止后端服务 (端口 12394)
if "%SKIP_BACKEND%"=="0" (
    echo [信息] 停止后端服务 (端口 12394)...
    
    REM 方法1: 通过窗口标题关闭
    tasklist /fi "windowtitle eq Anima Backend*" 2>nul | find "cmd.exe" >nul
    if not errorlevel 1 (
        taskkill /fi "windowtitle eq Anima Backend*" /f >nul 2>&1
        echo [成功] 已关闭后端服务窗口
    )
    
    REM 方法2: 通过端口号关闭进程
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":12394 " ^| findstr "LISTENING"') do (
        taskkill /pid %%a /f >nul 2>&1
        echo [成功] 已终止后端进程 (PID: %%a)
    )
) else (
    echo [跳过] 后端服务
)

REM 停止前端服务 (端口 3000)
if "%SKIP_FRONTEND%"=="0" (
    echo [信息] 停止前端服务 (端口 3000)...
    
    REM 方法1: 通过窗口标题关闭
    tasklist /fi "windowtitle eq Anima Frontend*" 2>nul | find "cmd.exe" >nul
    if not errorlevel 1 (
        taskkill /fi "windowtitle eq Anima Frontend*" /f >nul 2>&1
        echo [成功] 已关闭前端服务窗口
    )
    
    REM 方法2: 通过端口号关闭进程
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000 " ^| findstr "LISTENING"') do (
        taskkill /pid %%a /f >nul 2>&1
        echo [成功] 已终止前端进程 (PID: %%a)
    )
    
    REM 方法3: 关闭 node 进程 (如果有多个可能需要更谨慎)
    REM 不建议直接杀所有 node 进程，因为可能影响其他项目
) else (
    echo [跳过] 前端服务
)

echo.
echo ========================================
echo   停止完成！
echo ========================================
echo.

REM 显示当前端口占用情况
echo [信息] 当前端口状态:
echo.
echo   端口 12394 (后端):
netstat -ano | findstr ":12394 " | findstr "LISTENING" >nul
if errorlevel 1 (
    echo     未被占用
) else (
    echo     仍在使用
)

echo   端口 3000 (前端):
netstat -ano | findstr ":3000 " | findstr "LISTENING" >nul
if errorlevel 1 (
    echo     未被占用
) else (
    echo     仍在使用
)

echo.

exit /b 0