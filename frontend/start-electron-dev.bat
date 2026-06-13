@echo off
echo ========================================
echo  Animetta Live Stream - Electron Dev
echo ========================================
echo.

echo Installing dependencies...
cd /d "%~dp0"
call npm install

echo.
echo Starting development environment...
echo - Vite dev server: http://localhost:3000
echo - Electron window will open automatically
echo.
echo Press Ctrl+C to stop
echo.

call npm run dev:electron
