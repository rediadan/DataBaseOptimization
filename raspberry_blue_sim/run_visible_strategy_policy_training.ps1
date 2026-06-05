param(
  [string]$OutputName = "live_strategy_policy_current",
  [string]$BalanceRun = "iterative_balance_runs_strategy_mcts_upgrade_tuned_confirm_5000p",
  [int]$Playouts = 1500,
  [int]$Seed = 20260609,
  [switch]$NoArchive,
  [switch]$NoPause
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
$script = Join-Path $scriptDir "train_strategy_policies.py"
$balance = Join-Path $scriptDir "$BalanceRun\final_result.json"
. (Join-Path $scriptDir "live_run_utils.ps1")
$out = Initialize-LiveOutput `
  -ScriptDir $scriptDir `
  -OutputName $OutputName `
  -LiveName "live_strategy_policy_current" `
  -ArchivePrefix "strategy_policy" `
  -ArchiveLabel $BalanceRun `
  -NoArchive:$NoArchive
$log = Join-Path $out "run_console.log"

Set-Location $root

Write-Host "Raspberry Blue strategy policy training started" -ForegroundColor Cyan
Write-Host "Balance run: $BalanceRun"
Write-Host "Balance:     $balance"
Write-Host "Output:      $out"
Write-Host "Playouts:    $Playouts per strategy"
Write-Host "Seed:        $Seed"
Write-Host "Log:         $log"
Write-Host ""

python -u $script `
  --out $out `
  --balance-result $balance `
  --playouts $Playouts `
  --seed $Seed 2>&1 | Tee-Object -FilePath $log

Write-Host ""
if ($NoPause) {
  Write-Host "Strategy policy training finished." -ForegroundColor Green
} else {
  Write-Host "Strategy policy training finished. Press Enter to close this window." -ForegroundColor Green
  Read-Host
}
