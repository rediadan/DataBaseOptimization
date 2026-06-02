param(
  [string]$BalanceRun = "iterative_balance_runs_strategy_matrix_v3_confirm_5000p",
  [string]$OutputName = "strategy_matrix_v3_from_strategy_matrix_balance",
  [int]$Matches = 80,
  [int]$Seed = 20260603,
  [string]$AgentMode = "strategy_mcts",
  [int]$MctsIterations = 4
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
$script = Join-Path $scriptDir "run_strategy_matrix.py"
$balance = Join-Path $scriptDir "$BalanceRun\final_result.json"
$out = Join-Path $scriptDir $OutputName
$log = Join-Path $out "run_console.log"

New-Item -ItemType Directory -Force -Path $out | Out-Null
Set-Location $root

Write-Host "Raspberry Blue strategy matrix started" -ForegroundColor Cyan
Write-Host "Balance run: $BalanceRun"
Write-Host "Balance:     $balance"
Write-Host "Output:      $out"
Write-Host "Matches:     $Matches"
Write-Host "Seed:        $Seed"
Write-Host "Agent mode:  $AgentMode"
Write-Host "MCTS iter:   $MctsIterations"
Write-Host "Log:         $log"
Write-Host ""

python -u $script `
  --out $out `
  --balance-result $balance `
  --matches $Matches `
  --seed $Seed `
  --agent-mode $AgentMode `
  --mcts-iterations $MctsIterations 2>&1 | Tee-Object -FilePath $log

Write-Host ""
Write-Host "Strategy matrix finished. Press Enter to close this window." -ForegroundColor Green
Read-Host
