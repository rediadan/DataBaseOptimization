param(
  [string]$OutputName = "iterative_balance_runs_strategy_matrix_v3_confirm_5000p",
  [string]$SeedBalance = "strategy_matrix_seed_patch_v3.json",
  [int]$Seed = 20260603,
  [double]$PatchStrength = 0.035,
  [double]$StrategyDiversityWeight = 0.30,
  [int]$Playouts = 5000,
  [int]$MaxIterations = 24,
  [int]$Matches = 80,
  [int]$ValidationSeeds = 2,
  [int]$ConfirmationSeeds = 2,
  [int]$CandidateMatches = 14,
  [int]$CandidateSeeds = 2,
  [int]$CandidateLimit = 10
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
$script = Join-Path $scriptDir "iterative_balance_train.py"
$out = Join-Path $scriptDir $OutputName
$log = Join-Path $out "run_console.log"
$seedArgs = @()

if ($SeedBalance) {
  $seedBalancePath = Join-Path $scriptDir $SeedBalance
  $seedArgs = @("--seed-balance", $seedBalancePath)
}

New-Item -ItemType Directory -Force -Path $out | Out-Null
Set-Location $root

Write-Host "Raspberry Blue strategy training started" -ForegroundColor Cyan
Write-Host "Seed balance: $SeedBalance"
Write-Host "Output:       $out"
Write-Host "Log:          $log"
Write-Host "Seed:         $Seed"
Write-Host ""

python -u $script `
  @seedArgs `
  --out $out `
  --playouts $Playouts `
  --max-iterations $MaxIterations `
  --matches $Matches `
  --validation-seeds $ValidationSeeds `
  --target-confirmations 1 `
  --confirmation-seeds $ConfirmationSeeds `
  --candidate-matches $CandidateMatches `
  --candidate-seeds $CandidateSeeds `
  --candidate-limit $CandidateLimit `
  --patch-strength $PatchStrength `
  --tolerance 0.06 `
  --target 0.50 `
  --seed $Seed `
  --control-weight 0.35 `
  --strategy-diversity-weight $StrategyDiversityWeight 2>&1 | Tee-Object -FilePath $log

Write-Host ""
Write-Host "Training command finished. Press Enter to close this window." -ForegroundColor Green
Read-Host
