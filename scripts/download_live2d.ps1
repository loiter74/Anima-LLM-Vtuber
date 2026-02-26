# Live2D Haru Model Download Script
# PowerShell script to download Live2D model files

$baseUrl = "https://raw.githubusercontent.com/guansss/pixi-live2d-display/master/demo/assets/haru/"
$targetDir = "C:\Users\30262\Project\Anima\frontend\public\live2d\haru"

# Create directory if not exists
if (-not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force
    Write-Host "Created directory: $targetDir" -ForegroundColor Green
}

# Files to download
$files = @(
    "haru_greeter_t03.model3.json",
    "haru_greeter_t03.moc3",
    "haru_greeter_t03_2048.png",
    "haru_greeter_t03_2048.texture.json",
    "haru_greeter_t03.physics3.json"
)

Write-Host "`n====================================" -ForegroundColor Cyan
Write-Host "Live2D Model Downloader" -ForegroundColor Cyan
Write-Host "====================================`n" -ForegroundColor Cyan

$successCount = 0
$failedFiles = @()

foreach ($file in $files) {
    $url = $baseUrl + $file
    $destPath = Join-Path $targetDir $file

    Write-Host "Downloading: $file" -ForegroundColor Yellow

    if (Test-Path $destPath) {
        Write-Host "  [SKIP] File already exists`n" -ForegroundColor Gray
        $successCount++
        continue
    }

    try {
        # Use Invoke-WebRequest with progress
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $url -OutFile $destPath -UseBasicParsing

        if (Test-Path $destPath) {
            $fileSize = (Get-Item $destPath).Length
            Write-Host "  [OK] Downloaded ($fileSize bytes)`n" -ForegroundColor Green
            $successCount++
        } else {
            Write-Host "  [ERROR] Download failed - file not created`n" -ForegroundColor Red
            $failedFiles += $file
        }
    }
    catch {
        Write-Host "  [ERROR] $($_.Exception.Message)`n" -ForegroundColor Red
        $failedFiles += $file
    }
}

Write-Host "`n====================================" -ForegroundColor Cyan
Write-Host "Download Summary" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host "Success: $successCount / $($files.Count) files" -ForegroundColor Green

if ($failedFiles.Count -gt 0) {
    Write-Host "`nFailed files:" -ForegroundColor Red
    foreach ($file in $failedFiles) {
        Write-Host "  - $file" -ForegroundColor Red
    }
    Write-Host "`nPlease download these files manually from:"
    Write-Host "https://github.com/guansss/pixi-live2d-display/tree/master/demo/assets/haru"
} else {
    Write-Host "`nAll files downloaded successfully!" -ForegroundColor Green
    Write-Host "`nNext steps:"
    Write-Host "1. Start backend: python -m anima.socketio_server"
    Write-Host "2. Start frontend: cd frontend && pnpm dev"
    Write-Host "3. Open: http://localhost:3000"
}
