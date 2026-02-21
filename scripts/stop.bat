@echo off
REM ============================================
REM Anima Project Stop Script (Windows)
REM Enhanced with graceful shutdown and resource verification
REM ============================================

setlocal EnableDelayedExpansion

echo.
echo ========================================
echo   Anima Project Stop Script
echo ========================================
echo.

REM Get script and project directories
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
cd /d "%PROJECT_ROOT%"

REM ============================================
REM Parse Arguments
REM ============================================

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
echo Usage: stop.bat [Options]
echo.
echo Options:
echo   --skip-backend     Skip backend stop
echo   --skip-frontend    Skip frontend stop
echo   -h, --help         Show help message
echo.
echo Features:
echo   - Graceful shutdown with SIGTERM first
echo   - Falls back to SIGKILL if needed
echo   - Verifies port release
echo   - Cleans up temporary files
echo.
pause
exit /b 0

:end_parse

set "BACKEND_STOPPED=0"
set "FRONTEND_STOPPED=0"

REM ============================================
REM Phase 1: Stop Services
REM ============================================

echo ========================================
echo   Phase 1: Stopping Services
echo ========================================
echo.

REM Stop frontend first (it depends on backend)
if "%SKIP_FRONTEND%"=="0" (
    echo [INFO] Stopping frontend (port 3000)...

    REM Find and stop processes on port 3000
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000.*LISTENING"') do (
        echo [INFO] Found process on port 3000: %%a
        taskkill /PID %%a /F >nul 2>&1
        if not errorlevel 1 (
            set "FRONTEND_STOPPED=1"
        )
    )

    timeout /t 2 /nobreak >nul

    if "!FRONTEND_STOPPED!"=="1" (
        echo [SUCCESS] Frontend service stopped
    ) else (
        echo [WARNING] No frontend service found on port 3000
    )
) else (
    echo [WARNING] Skipping frontend
)

echo.

REM Stop backend
if "%SKIP_BACKEND%"=="0" (
    echo [INFO] Stopping backend (port 12394)...

    REM Find and stop processes on port 12394
    set "BACKEND_PIDS="
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":12394.*LISTENING"') do (
        echo [INFO] Found process on port 12394: %%a
        set "BACKEND_PIDS=!BACKEND_PIDS! %%a"
    )

    REM First try graceful shutdown (without /F)
    if not "!BACKEND_PIDS!"=="" (
        echo [INFO] Attempting graceful shutdown...
        for %%p in (!BACKEND_PIDS!) do (
            taskkill /PID %%p >nul 2>&1
        )
        
        REM Wait for graceful shutdown
        timeout /t 3 /nobreak >nul
        
        REM Check if processes still exist
        for %%p in (!BACKEND_PIDS!) do (
            tasklist /FI "PID eq %%p" 2>nul | findstr "%%p" >nul
            if not errorlevel 1 (
                echo [WARNING] Process %%p did not close gracefully, forcing...
                taskkill /PID %%p /F >nul 2>&1
            )
        )
        
        set "BACKEND_STOPPED=1"
    )

    timeout /t 1 /nobreak >nul

    if "!BACKEND_STOPPED!"=="1" (
        echo [SUCCESS] Backend service stopped
    ) else (
        echo [WARNING] No backend service found on port 12394
    )
) else (
    echo [WARNING] Skipping backend
)

echo.

REM Also stop by process name for completeness
if "%SKIP_FRONTEND%"=="0" (
    for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq node.exe" ^| findstr "node.exe"') do (
        wmic process where "ProcessId=%%a and (CommandLine like '%%next%%' or CommandLine like '%%anima%%' or CommandLine like '%%3000%%')" call terminate >nul 2>&1
    )
)

if "%SKIP_BACKEND%"=="0" (
    for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq python.exe" ^| findstr "python.exe"') do (
        wmic process where "ProcessId=%%a and (CommandLine like '%%socketio_server%%' or CommandLine like '%%anima%%')" call terminate >nul 2>&1
    )
)

echo.

REM ============================================
REM Phase 2: Verify Ports Released
REM ============================================

echo ========================================
echo   Phase 2: Verifying Port Release
echo ========================================
echo.

set "BACKEND_PORT_IN_USE=0"
set "FRONTEND_PORT_IN_USE=0"

if "%SKIP_BACKEND%"=="0" (
    netstat -ano | findstr ":12394.*LISTENING" >nul 2>&1
    if not errorlevel 1 (
        echo [ERROR] Port 12394 (backend) is still in use
        set "BACKEND_PORT_IN_USE=1"

        REM Show which process is holding the port
        for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":12394.*LISTENING"') do (
            echo   Held by PID: %%a
            for /f "tokens=1,2" %%b in ('tasklist /FI "PID eq %%a" /FO CSV /NH') do (
                echo   Process: %%~b
            )
        )
    ) else (
        echo [SUCCESS] Port 12394 (backend): Released
    )
)

if "%SKIP_FRONTEND%"=="0" (
    netstat -ano | findstr ":3000.*LISTENING" >nul 2>&1
    if not errorlevel 1 (
        echo [ERROR] Port 3000 (frontend) is still in use
        set "FRONTEND_PORT_IN_USE=1"

        REM Show which process is holding the port
        for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000.*LISTENING"') do (
            echo   Held by PID: %%a
            for /f "tokens=1,2" %%b in ('tasklist /FI "PID eq %%a" /FO CSV /NH') do (
                echo   Process: %%~b
            )
        )
    ) else (
        echo [SUCCESS] Port 3000 (frontend): Released
    )
)

echo.

REM ============================================
REM Phase 3: Clean Temporary Files
REM ============================================

echo ========================================
echo   Phase 3: Cleaning Resources
echo ========================================
echo.

if exist "%PROJECT_ROOT%\src\__pycache__" (
    rmdir /s /q "%PROJECT_ROOT%\src\__pycache__" 2>nul
)

if exist "%PROJECT_ROOT%\frontend\.next\cache" (
    rmdir /s /q "%PROJECT_ROOT%\frontend\.next\cache" 2>nul
)

echo [SUCCESS] Temporary files cleaned
echo.

REM ============================================
REM Summary
REM ============================================

echo ========================================
echo   Stop Summary
echo ========================================
echo.

if "%BACKEND_STOPPED%"=="1" (
    echo [SUCCESS] Backend stopped
)

if "%FRONTEND_STOPPED%"=="1" (
    echo [SUCCESS] Frontend stopped
)

if "%BACKEND_STOPPED%"=="0" if "%FRONTEND_STOPPED%"=="0" (
    echo [WARNING] No services were stopped
)

echo.

if "%BACKEND_PORT_IN_USE%"=="1" goto :ports_in_use
if "%FRONTEND_PORT_IN_USE%"=="1" goto :ports_in_use

echo [SUCCESS] All resources released successfully
goto :stop_summary_end

:ports_in_use
echo [ERROR] Some ports are still in use - you may need to:
echo   1. Check for other instances holding the ports
echo   2. Restart your computer to clear all system resources
echo   3. Manually kill the processes shown above
echo.
pause
exit /b 1

:stop_summary_end

echo.
pause
exit /b 0
