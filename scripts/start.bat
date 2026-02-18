@echo off
REM ============================================
REM Anima 项目启动脚本 (Windows)
REM 同时启动后端和前端服务
REM ============================================

setlocal EnableDelayedExpansion

echo.
echo ========================================
echo   Anima 项目启动脚本
echo ========================================
echo.

REM 获取脚本所在目录的父目录（项目根目录）
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
cd /d "%PROJECT_ROOT%"

REM 检查 Python 是否可用
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python
    pause
    exit /b 1
)

REM 检查 Node.js/pnpm 是否可用
pnpm --version >nul 2>&1
if errorlevel 1 (
    echo [警告] 未找到 pnpm，尝试使用 npm...
    npm --version >nul 2>&1
    if errorlevel 1 (
        echo [错误] 未找到 Node.js，请先安装 Node.js
        pause
        exit /b 1
    )
    set "PKG_MANAGER=npm"
) else (
    set "PKG_MANAGER=pnpm"
)

echo [信息] 使用包管理器: !PKG_MANAGER!
echo.

REM 解析参数
set "SKIP_BACKEND=0"
set "SKIP_FRONTEND=0"
set "INSTALL_DEPS=0"

:parse_args
if "%~1"=="" goto :end_parse
if /i "%~1"=="--skip-backend" set "SKIP_BACKEND=1"
if /i "%~1"=="--skip-frontend" set "SKIP_FRONTEND=1"
if /i "%~1"=="--install" set "INSTALL_DEPS=1"
if /i "%~1"=="-h" goto :show_help
if /i "%~1"=="--help" goto :show_help
shift
goto :parse_args

:show_help
echo 用法: start.bat [选项]
echo.
echo 选项:
echo   --skip-backend    跳过后端启动
echo   --skip-frontend   跳过前端启动
echo   --install         重新安装依赖
echo   -h, --help        显示帮助信息
echo.
pause
exit /b 0

:end_parse

REM 安装依赖
if "%INSTALL_DEPS%"=="1" (
    echo [信息] 安装后端依赖...
    pip install -r requirements.txt
    
    echo [信息] 安装前端依赖...
    cd frontend
    if "!PKG_MANAGER!"=="pnpm" (
        pnpm install
    ) else (
        npm install
    )
    cd ..
    echo.
)

REM 启动后端
if "%SKIP_BACKEND%"=="0" (
    echo [信息] 启动后端服务器 (端口 12394)...
    start "Anima Backend" cmd /k "cd /d "%PROJECT_ROOT%\src" && python -m anima.socketio_server"
    echo [成功] 后端服务已在新窗口启动: http://localhost:12394
) else (
    echo [跳过] 后端服务
)

REM 等待后端启动
if "%SKIP_BACKEND%"=="0" (
    echo [信息] 等待后端启动...
    timeout /t 3 /nobreak >nul
)

REM 启动前端
if "%SKIP_FRONTEND%"=="0" (
    echo [信息] 启动前端开发服务器...
    cd frontend
    if "!PKG_MANAGER!"=="pnpm" (
        start "Anima Frontend" cmd /k "set NEXT_PRIVATE_BENCHMARK_ENABLED=false&& pnpm dev"
    ) else (
        start "Anima Frontend" cmd /k "set NEXT_PRIVATE_BENCHMARK_ENABLED=false&& npm run dev"
    )
    cd ..
    echo [成功] 前端服务已在新窗口启动: http://localhost:3000
) else (
    echo [跳过] 前端服务
)

echo.
echo ========================================
echo   启动完成！
echo ========================================
echo.
if "%SKIP_BACKEND%"=="0" echo   后端: http://localhost:12394
if "%SKIP_FRONTEND%"=="0" echo   前端: http://localhost:3000
echo.
echo   按任意键退出此窗口...
echo   (服务将在独立的命令行窗口中运行)
echo ========================================
echo.

pause >nul
exit /b 0