param(
  [string]$OutputName = "live_training_current",
  [string]$SeedBalance = "",
  [int]$Seed = 20260604,
  [double]$PatchStrength = 0.045,
  [double]$StrategyDiversityWeight = 0.20,
  [int]$Playouts = 5000,
  [int]$MaxIterations = 24,
  [int]$Matches = 80,
  [int]$ValidationSeeds = 2,
  [int]$ConfirmationSeeds = 2,
  [int]$CandidateMatches = 14,
  [int]$CandidateSeeds = 2,
  [int]$CandidateLimit = 8,
  [switch]$NoArchive
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
$script = Join-Path $scriptDir "iterative_balance_train.py"
. (Join-Path $scriptDir "live_run_utils.ps1")
$archiveLabel = if ($SeedBalance) { [IO.Path]::GetFileNameWithoutExtension($SeedBalance) } else { "base_balance" }
$out = Initialize-LiveOutput `
  -ScriptDir $scriptDir `
  -OutputName $OutputName `
  -LiveName "live_training_current" `
  -ArchivePrefix "training" `
  -ArchiveLabel $archiveLabel `
  -NoArchive:$NoArchive
$log = Join-Path $out "run_console.log"
$seedArgs = @()

if ($SeedBalance) {
  $seedBalancePath = Join-Path $scriptDir $SeedBalance
  $seedArgs = @("--seed-balance", $seedBalancePath)
}

Set-Location $root

Write-Host "Raspberry Blue training started" -ForegroundColor Cyan
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
