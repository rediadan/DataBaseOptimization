param(
  [string]$BalanceRun = "iterative_balance_runs_strategy_matrix_v3_confirm_5000p",
  [string]$OutputName = "live_matrix_current",
  [int]$Matches = 80,
  [int]$Seed = 20260603,
  [string]$AgentMode = "strategy_mcts",
  [int]$MctsIterations = 4,
  [string]$PolicyDir = "",
  [switch]$NoArchive
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
$script = Join-Path $scriptDir "run_strategy_matrix.py"
$balance = Join-Path $scriptDir "$BalanceRun\final_result.json"
. (Join-Path $scriptDir "live_run_utils.ps1")
$archiveLabel = if ($AgentMode -eq "strategy_policy" -and $PolicyDir) {
  "strategy_policy_" + (Split-Path -Leaf $PolicyDir)
} else {
  "${AgentMode}_$BalanceRun"
}
$out = Initialize-LiveOutput `
  -ScriptDir $scriptDir `
  -OutputName $OutputName `
  -LiveName "live_matrix_current" `
  -ArchivePrefix "matrix" `
  -ArchiveLabel $archiveLabel `
  -NoArchive:$NoArchive
$log = Join-Path $out "run_console.log"

Set-Location $root

Write-Host "Raspberry Blue strategy matrix started" -ForegroundColor Cyan
Write-Host "Balance run: $BalanceRun"
Write-Host "Balance:     $balance"
Write-Host "Output:      $out"
Write-Host "Matches:     $Matches"
Write-Host "Seed:        $Seed"
Write-Host "Agent mode:  $AgentMode"
Write-Host "MCTS iter:   $MctsIterations"
Write-Host "Policy dir:  $PolicyDir"
Write-Host "Log:         $log"
Write-Host ""

python -u $script `
  --out $out `
  --balance-result $balance `
  --matches $Matches `
  --seed $Seed `
  --agent-mode $AgentMode `
  --mcts-iterations $MctsIterations `
  --policy-dir $PolicyDir 2>&1 | Tee-Object -FilePath $log

Write-Host ""
Write-Host "Strategy matrix finished. Press Enter to close this window." -ForegroundColor Green
Read-Host
