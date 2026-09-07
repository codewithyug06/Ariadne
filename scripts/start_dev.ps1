# Ariadne local development runner for Windows (PowerShell)
# Starts both the Ariadne backend proxy and the dashboard frontend.

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $PSScriptRoot

Set-Location $RootDir

# Ensure .env exists
if (-not (Test-Path "$RootDir\.env")) {
    Write-Host "No .env found; copying .env.example..." -ForegroundColor Yellow
    Copy-Item "$RootDir\.env.example" "$RootDir\.env"
}

# Ensure data directory exists
if (-not (Test-Path "$RootDir\data")) {
    New-Item -ItemType Directory -Path "$RootDir\data" | Out-Null
}

# Locate python
$PythonPath = "$RootDir\.venv\Scripts\python.exe"
if (-not (Test-Path $PythonPath)) {
    $PythonPath = "python"
}

Write-Host "Starting Ariadne proxy on port 8000..." -ForegroundColor Cyan
$backend = Start-Process -FilePath $PythonPath -ArgumentList "-m", "uvicorn", "ariadne.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload" -PassThru -NoNewWindow

$frontend = $null
if (Test-Path "$RootDir\dashboard\node_modules") {
    Write-Host "Starting Ariadne dashboard on port 5173..." -ForegroundColor Cyan
    $frontend = Start-Process -FilePath "npm" -ArgumentList "run", "dev", "--", "--host" -WorkingDirectory "$RootDir\dashboard" -PassThru -NoNewWindow
} else {
    Write-Warning "dashboard/node_modules missing - run 'cd dashboard; npm install' to enable the UI."
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Ariadne local host services running:   " -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Dashboard: http://localhost:5173" -ForegroundColor White
Write-Host "  Backend:   http://localhost:8000" -ForegroundColor White
Write-Host "  Health:    http://localhost:8000/health" -ForegroundColor White
Write-Host "  MCP Proxy: http://localhost:8000/mcp" -ForegroundColor White
Write-Host ""
Write-Host "  Admin Login:" -ForegroundColor Yellow
Write-Host "    Email:    admin@example.com" -ForegroundColor Gray
Write-Host "    Password: dev-admin-password" -ForegroundColor Gray
Write-Host ""
Write-Host "Press Ctrl+C to stop both processes." -ForegroundColor Gray

try {
    Wait-Process -Id $backend.Id
} finally {
    if ($backend -and -not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
    if ($frontend -and -not $frontend.HasExited) {
        Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue
    }
}
