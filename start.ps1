param (
    [string]$ApiKey = $env:ARIADNE_API_KEY,
    [string]$ProxyUrl = $env:MCP_PROXY_URL
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$ScriptDir\demo\start.ps1" -ApiKey $ApiKey -ProxyUrl $ProxyUrl
