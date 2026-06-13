# Animetta Live Stream - Electron Development
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Animetta Live Stream - Electron Dev" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Installing dependencies..." -ForegroundColor Yellow
Set-Location $PSScriptRoot
npm install

Write-Host ""
Write-Host "Starting development environment..." -ForegroundColor Green
Write-Host "- Vite dev server: http://localhost:3000" -ForegroundColor Gray
Write-Host "- Electron window will open automatically" -ForegroundColor Gray
Write-Host ""
Write-Host "Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host ""

npm run dev:electron
