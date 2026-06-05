$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
$port = 8765
$url = "http://127.0.0.1:$port/raspberry_blue_sim/live_strategy_dashboard/index.html"
$matrixLoopUrl = "http://127.0.0.1:$port/raspberry_blue_sim/live_strategy_dashboard/matrix_balance_loop.html"

Set-Location $root

Write-Host "Strategy matrix live dashboard" -ForegroundColor Cyan
Write-Host "URL: $url"
Write-Host "Matrix balance loop URL: $matrixLoopUrl"
Write-Host "Root: $root"
Write-Host ""

python -m http.server $port --bind 127.0.0.1
