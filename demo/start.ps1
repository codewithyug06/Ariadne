param (
    [string]$ApiKey = $env:ARIADNE_API_KEY,
    [string]$ProxyUrl = $env:MCP_PROXY_URL
)

$ErrorActionPreference = "Stop"

if (-not $ProxyUrl) {
    $ProxyUrl = "http://localhost:8000/mcp"
}
$env:MCP_PROXY_URL = $ProxyUrl

if (-not $ApiKey) {
    Write-Host "[ERROR] ARIADNE_API_KEY is not set." -ForegroundColor Red
    Write-Host "        Pass -ApiKey 'ariadne_...' or set `$env:ARIADNE_API_KEY." -ForegroundColor Yellow
    exit 1
}
$env:ARIADNE_API_KEY = $ApiKey

$AriadneBaseUrl = $ProxyUrl.Replace("/mcp", "")
$ToolServerUrl = if ($env:DEMO_TOOL_SERVER_URL) { $env:DEMO_TOOL_SERVER_URL } else { "http://127.0.0.1:9000" }
$ToolServerPort = 9000
if ($ToolServerUrl -match ":(\d+)") {
    $ToolServerPort = $matches[1]
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path "$ScriptDir\..").Path

Write-Host ""
Write-Host "  Ariadne Agent Monitor" -ForegroundColor Cyan
Write-Host "  Proxy  : $ProxyUrl"
Write-Host "  Key    : $($ApiKey.Substring(0, [Math]::Min(18, $ApiKey.Length)))..."
Write-Host ""

# Check Ariadne reachable
try {
    $response = Invoke-RestMethod -Uri "$AriadneBaseUrl/health" -Headers @{ "X-Api-Key" = $ApiKey } -TimeoutSec 3 -ErrorAction Stop
    Write-Host "[OK] Ariadne reachable." -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Cannot reach Ariadne at $AriadneBaseUrl" -ForegroundColor Red
    Write-Host "        Start it first (from repo root):" -ForegroundColor Yellow
    Write-Host "          uvicorn ariadne.main:app --port 8000" -ForegroundColor Yellow
    exit 1
}

# Auto-start demo tool server on :9000 if not running
$toolServerRunning = $false
try {
    $tsResp = Invoke-RestMethod -Uri "$ToolServerUrl/health" -TimeoutSec 2 -ErrorAction Stop
    $toolServerRunning = $true
} catch {
    $toolServerRunning = $false
}

if (-not $toolServerRunning) {
    Write-Host "[INFO] Demo tool server not running - starting it on :$ToolServerPort..." -ForegroundColor Yellow
    Start-Process -FilePath "uvicorn" -ArgumentList "demo.tool_server.server:app --port $ToolServerPort --log-level warning" -WorkingDirectory $RepoRoot -WindowStyle Hidden
    Start-Sleep -Seconds 2
    Write-Host "[OK] Tool server started on :$ToolServerPort." -ForegroundColor Green
} else {
    Write-Host "[OK] Tool server already running on :$ToolServerPort." -ForegroundColor Green
}

Write-Host ""
Write-Host "[START] Running agent monitoring demo..." -ForegroundColor Cyan
Write-Host ""

# Locate Python
$PythonBin = "python"
if (Test-Path "$RepoRoot\.venv\Scripts\python.exe") {
    $PythonBin = "$RepoRoot\.venv\Scripts\python.exe"
}

Push-Location $RepoRoot
try {
    & $PythonBin demo/scripts/run_demo.py --direct
    Write-Host ""
    Write-Host "[OK] Run complete. Verifying assertions..." -ForegroundColor Green
    Write-Host ""
    & $PythonBin demo/scripts/verify_demo.py
    Write-Host ""
    Write-Host "Dashboard: http://localhost:5173" -ForegroundColor Cyan
    Write-Host ""
} finally {
    Pop-Location
}
