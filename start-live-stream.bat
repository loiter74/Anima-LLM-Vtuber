@echo off
echo ========================================
echo  Animetta Live Stream Launcher
echo ========================================
echo.
echo  This will:
echo  1. Start Docker backend (if not running)
echo  2. Open Electron live stream window
echo.
echo  Press any key to start...
pause >nul

:: Start Docker backend
echo.
echo Starting Docker backend...
cd /d "%~dp0"
docker compose up -d --build

:: Wait for health
echo.
echo Waiting for backend to be ready...
:check_health
curl -s http://localhost/health >nul 2>&1
if errorlevel 1 (
    echo   Waiting...
    timeout /t 5 /nobreak >nul
    goto check_health
)
echo Backend is ready!

:: Start Electron
echo.
echo Starting Electron live stream window...
cd /d "%~dp0\frontend"

:: Install dependencies if needed
if not exist "node_modules" (
    echo Installing frontend dependencies...
    call npm install
)

:: Start Electron
call npm run dev:electron
