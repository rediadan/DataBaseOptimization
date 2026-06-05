param(
  [string]$OutputName = "live_matrix_balance_loop_current",
  [string]$BaseBalanceRun = "iterative_balance_runs_strategy_mcts_upgrade_tuned_confirm_5000p",
  [string]$PolicyDir = "strategy_policy_runs_v2_stronger_prior_1500p",
  [int]$Iterations = 3,
  [int]$Matches = 40,
  [int]$Seed = 20260620,
  [double]$PatchStrength = 0.055,
  [double]$MinStrategyGap = 0.08,
  [int]$WeakCount = 2,
  [int]$TargetConfirmations = 2,
  [string]$AgentMode = "strategy_policy",
  [int]$MctsIterations = 4,
  [switch]$NoArchive,
  [switch]$NoPause
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
$script = Join-Path $scriptDir "matrix_balance_loop.py"

$baseBalance = if ([System.IO.Path]::IsPathRooted($BaseBalanceRun)) {
  Join-Path $BaseBalanceRun "final_result.json"
} else {
  Join-Path $scriptDir "$BaseBalanceRun\final_result.json"
}

$resolvedPolicyDir = if ([System.IO.Path]::IsPathRooted($PolicyDir)) {
  $PolicyDir
} else {
  Join-Path $scriptDir $PolicyDir
}

. (Join-Path $scriptDir "live_run_utils.ps1")
$out = Initialize-LiveOutput `
  -ScriptDir $scriptDir `
  -OutputName $OutputName `
  -LiveName "live_matrix_balance_loop_current" `
  -ArchivePrefix "matrix_balance_loop" `
  -ArchiveLabel $AgentMode `
  -NoArchive:$NoArchive
$log = Join-Path $out "run_console.log"

Set-Location $root

Write-Host "Raspberry Blue matrix balance loop started" -ForegroundColor Cyan
Write-Host "Base balance:      $baseBalance"
Write-Host "Policy dir:        $resolvedPolicyDir"
Write-Host "Output:            $out"
Write-Host "Iterations:        $Iterations"
Write-Host "Matches:           $Matches"
Write-Host "Seed:              $Seed"
Write-Host "Patch strength:    $PatchStrength"
Write-Host "Min strategy gap:  $MinStrategyGap"
Write-Host "Weak targets:      $WeakCount"
Write-Host "Confirm targets:   $TargetConfirmations"
Write-Host "Agent mode:        $AgentMode"
Write-Host "MCTS iterations:   $MctsIterations"
Write-Host "Dashboard:         http://127.0.0.1:8765/raspberry_blue_sim/live_strategy_dashboard/matrix_balance_loop.html"
Write-Host "Log:               $log"
Write-Host ""

python -u $script `
  --out $out `
  --base-balance-result $baseBalance `
  --policy-dir $resolvedPolicyDir `
  --iterations $Iterations `
  --matches $Matches `
  --seed $Seed `
  --patch-strength $PatchStrength `
  --min-strategy-gap $MinStrategyGap `
  --weak-count $WeakCount `
  --target-confirmations $TargetConfirmations `
  --agent-mode $AgentMode `
  --mcts-iterations $MctsIterations 2>&1 | Tee-Object -FilePath $log

Write-Host ""
if ($NoPause) {
  Write-Host "Matrix balance loop finished." -ForegroundColor Green
} else {
  Write-Host "Matrix balance loop finished. Press Enter to close this window." -ForegroundColor Green
  Read-Host
}
