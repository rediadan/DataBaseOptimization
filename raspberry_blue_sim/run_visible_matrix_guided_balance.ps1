param(
  [string]$OutputName = "live_training_current",
  [string]$MatrixRun = "live_matrix_current",
  [string]$BalanceRun = "iterative_balance_runs_strategy_mcts_upgrade_tuned_confirm_5000p",
  [string]$PolicyDir = "live_strategy_policy_current",
  [int]$ProblemLimit = 14,
  [int]$CandidateLimit = 8,
  [int]$CandidateMatches = 40,
  [int]$Seed = 20260613,
  [double]$PatchStrength = 0.055,
  [switch]$NoArchive
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
$script = Join-Path $scriptDir "matrix_guided_balance.py"

$matrixCsv = if ([System.IO.Path]::IsPathRooted($MatrixRun)) {
  Join-Path $MatrixRun "strategy_matrix.csv"
} else {
  Join-Path $scriptDir "$MatrixRun\strategy_matrix.csv"
}

$balance = if ([System.IO.Path]::IsPathRooted($BalanceRun)) {
  Join-Path $BalanceRun "final_result.json"
} else {
  Join-Path $scriptDir "$BalanceRun\final_result.json"
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
  -LiveName "live_training_current" `
  -ArchivePrefix "matrix_guided_balance" `
  -ArchiveLabel $MatrixRun `
  -NoArchive:$NoArchive
$log = Join-Path $out "run_console.log"

Set-Location $root

Write-Host "Raspberry Blue matrix-guided balance started" -ForegroundColor Cyan
Write-Host "Matrix CSV:        $matrixCsv"
Write-Host "Balance result:    $balance"
Write-Host "Policy dir:        $resolvedPolicyDir"
Write-Host "Output:            $out"
Write-Host "Problem limit:     $ProblemLimit"
Write-Host "Candidate limit:   $CandidateLimit"
Write-Host "Candidate matches: $CandidateMatches"
Write-Host "Seed:              $Seed"
Write-Host "Patch strength:    $PatchStrength"
Write-Host "Log:               $log"
Write-Host ""

python -u $script `
  --out $out `
  --matrix-csv $matrixCsv `
  --balance-result $balance `
  --policy-dir $resolvedPolicyDir `
  --problem-limit $ProblemLimit `
  --candidate-limit $CandidateLimit `
  --candidate-matches $CandidateMatches `
  --seed $Seed `
  --patch-strength $PatchStrength 2>&1 | Tee-Object -FilePath $log

Write-Host ""
Write-Host "Matrix-guided balance finished. Press Enter to close this window." -ForegroundColor Green
Read-Host
