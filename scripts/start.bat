@echo off
REM ============================================
REM Anima Project Start Script (Windows)
REM Enhanced with resource cleanup
REM ============================================

setlocal EnableDelayedExpansion

echo.
echo ========================================
echo   Anima Project Startup Script
echo ========================================
echo.

REM Get script and project directories
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
cd /d "%PROJECT_ROOT%"

REM ============================================
REM Check Prerequisites
REM ============================================

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found, please install Python first
    pause
    exit /b 1
)

REM Check Node.js/pnpm
pnpm --version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] pnpm not found, trying npm...
    npm --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Node.js not found, please install Node.js first
        pause
        exit /b 1
    )
    set "PKG_MANAGER=npm"
) else (
    set "PKG_MANAGER=pnpm"
)

echo [INFO] Package manager: !PKG_MANAGER!
echo.

REM ============================================
REM Parse Arguments
REM ============================================

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
echo Usage: start.bat [Options]
echo.
echo Options:
echo   --skip-backend    Skip backend startup
echo   --skip-frontend   Skip frontend startup
echo   --install         Reinstall dependencies
echo   -h, --help        Show help message
echo.
echo Resource Management:
echo   - Automatically stops existing processes on startup
echo   - Cleans up temporary files and caches
echo.
pause
exit /b 0

:end_parse

REM ============================================
REM Phase 1: Stop Existing Services
REM ============================================

echo ========================================
echo   Phase 1: Stopping Existing Services
echo ========================================
echo.

REM Stop backend processes
if "%SKIP_BACKEND%"=="0" (
    echo [INFO] Stopping backend services on port 12394...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":12394.*LISTENING"') do (
        echo [INFO] Stopping process %%a...
        taskkill /F /PID %%a >nul 2>&1
    )
    timeout /t 1 /nobreak >nul

    REM Also stop Python processes with anima/socketio_server
    for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq python.exe" ^| findstr "python.exe"') do (
        wmic process where "ProcessId=%%a and CommandLine like '%%socketio_server%%'" call terminate >nul 2>&1
    )
)

REM Stop frontend processes
if "%SKIP_FRONTEND%"=="0" (
    echo [INFO] Stopping frontend services on port 3000...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000.*LISTENING"') do (
        echo [INFO] Stopping process %%a...
        taskkill /F /PID %%a >nul 2>&1
    )
    timeout /t 1 /nobreak >nul

    REM Also stop Node processes with next
    for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq node.exe" ^| findstr "node.exe"') do (
        wmic process where "ProcessId=%%a and CommandLine like '%%next%%'" call terminate >nul 2>&1
    )
)

echo [SUCCESS] All existing services stopped
echo.

REM ============================================
REM Phase 2: Clean Temporary Files
REM ============================================

echo ========================================
echo   Phase 2: Cleaning Resources
echo ========================================
echo.

if exist "%PROJECT_ROOT%\src\__pycache__" (
    rmdir /s /q "%PROJECT_ROOT%\src\__pycache__" 2>nul
    echo [INFO] Removed Python cache
)

if exist "%PROJECT_ROOT%\frontend\.next\cache" (
    rmdir /s /q "%PROJECT_ROOT%\frontend\.next\cache" 2>nul
    echo [INFO] Removed Next.js cache
)

echo [SUCCESS] Temporary files cleaned
echo.

REM ============================================
REM Phase 3: Install Dependencies (Optional)
REM ============================================

if "%INSTALL_DEPS%"=="1" (
    echo ========================================
    echo   Phase 3: Installing Dependencies
    echo ========================================
    echo.

    echo [INFO] Installing backend dependencies...
    pip install -r requirements.txt

    echo [INFO] Installing frontend dependencies...
    cd frontend
    if "!PKG_MANAGER!"=="pnpm" (
        pnpm install
    ) else (
        npm install
    )
    cd ..
    echo.
)

REM ============================================
REM Phase 4: Start Services
REM ============================================

echo ========================================
echo   Phase 4: Starting Services
echo ========================================
echo.

REM Start backend
if "%SKIP_BACKEND%"=="0" (
    echo [INFO] Starting backend server (port 12394)...
    start "Anima Backend" cmd /k "cd /d "%PROJECT_ROOT%\src" && python -m anima.socketio_server"
    echo [SUCCESS] Backend started: http://localhost:12394

    echo [INFO] Waiting for backend to start...
    timeout /t 3 /nobreak >nul
) else (
    echo [WARNING] Skipping backend
)

REM Start frontend
if "%SKIP_FRONTEND%"=="0" (
    echo [INFO] Starting frontend dev server...
    cd frontend
    if "!PKG_MANAGER!"=="pnpm" (
        start "Anima Frontend" cmd /k "set NEXT_PRIVATE_BENCHMARK_ENABLED=false&& pnpm dev"
    ) else (
        start "Anima Frontend" cmd /k "set NEXT_PRIVATE_BENCHMARK_ENABLED=false&& npm run dev"
    )
    cd ..
    echo [SUCCESS] Frontend started: http://localhost:3000
) else (
    echo [WARNING] Skipping frontend
)

echo.
echo ========================================
echo   Startup Complete!
echo ========================================
echo.

if "%SKIP_BACKEND%"=="0" echo   Backend: http://localhost:12394
if "%SKIP_FRONTEND%"=="0" echo   Frontend: http://localhost:3000

echo.
echo   Press Ctrl+C in service windows to stop
echo   Or run: scripts\stop.bat
echo.

pause
exit /b 0
