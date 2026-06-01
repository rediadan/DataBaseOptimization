$ErrorActionPreference = "Stop"

$root = "C:\Users\User\Documents\AIAssistantLocal"
$script = Join-Path $root "raspberry_blue_sim\iterative_balance_train.py"
$out = Join-Path $root "raspberry_blue_sim\iterative_balance_runs_upgrade_v4_confirm_5000p_stable"
$log = Join-Path $out "run_console.log"

New-Item -ItemType Directory -Force -Path $out | Out-Null
Set-Location $root

Write-Host "Raspberry Blue training started" -ForegroundColor Cyan
Write-Host "Output: $out"
Write-Host "Log:    $log"
Write-Host ""

python -u $script `
  --out $out `
  --playouts 5000 `
  --max-iterations 24 `
  --matches 80 `
  --validation-seeds 2 `
  --target-confirmations 1 `
  --confirmation-seeds 2 `
  --candidate-matches 14 `
  --candidate-seeds 2 `
  --candidate-limit 8 `
  --patch-strength 0.045 `
  --tolerance 0.06 `
  --target 0.50 `
  --seed 20260604 `
  --control-weight 0.35 2>&1 | Tee-Object -FilePath $log

Write-Host ""
Write-Host "Training command finished. Press Enter to close this window." -ForegroundColor Green
Read-Host
