@echo off
echo ========================================
echo  Animetta Live Stream - One Click Start
echo ========================================
echo.

:: Check if Docker is running
echo [1/4] Checking Docker...
docker info >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker is not running!
    echo Please start Docker Desktop first.
    pause
    exit /b 1
)
echo      Docker is running.

:: Check if backend container is running
echo [2/4] Checking backend container...
docker ps --format "table {{.Names}}\t{{.Status}}" | findstr "anima-animetta-1" >nul 2>&1
if errorlevel 1 (
    echo      Backend not running, starting...
    cd /d "%~dp0\.."
    docker compose up -d --build
    echo      Waiting for health check...
    timeout /t 30 /nobreak >nul
) else (
    echo      Backend is running.
)

:: Check health
echo [3/4] Checking backend health...
curl -s http://localhost/health >nul 2>&1
if errorlevel 1 (
    echo      Waiting for backend...
    timeout /t 10 /nobreak >nul
)
echo      Backend is healthy.

:: Start Electron
echo [4/4] Starting Electron window...
echo.
cd /d "%~dp0"

:: Install dependencies if needed
if not exist "node_modules" (
    echo Installing dependencies...
    call npm install
)

:: Start Electron in dev mode
echo.
echo Starting Animetta Live Stream...
echo.
call npm run dev:electron
