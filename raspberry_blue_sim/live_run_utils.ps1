function Initialize-LiveOutput {
  param(
    [Parameter(Mandatory = $true)][string]$ScriptDir,
    [Parameter(Mandatory = $true)][string]$OutputName,
    [Parameter(Mandatory = $true)][string]$LiveName,
    [Parameter(Mandatory = $true)][string]$ArchivePrefix,
    [string]$ArchiveLabel = "",
    [switch]$NoArchive
  )

  $out = Join-Path $ScriptDir $OutputName
  $isLiveOutput = $OutputName -eq $LiveName

  if ($isLiveOutput -and -not $NoArchive -and (Test-Path $out)) {
    $existing = Get-ChildItem -LiteralPath $out -Force -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($existing) {
      $archiveRoot = Join-Path $ScriptDir "archives"
      New-Item -ItemType Directory -Force -Path $archiveRoot | Out-Null

      $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
      $safeLabel = if ($ArchiveLabel) {
        $ArchiveLabel -replace '[\\/:*?"<>| ]+', '_'
      } else {
        "run"
      }
      $archiveName = "${ArchivePrefix}_${stamp}_${safeLabel}"
      $archivePath = Join-Path $archiveRoot $archiveName
      $suffix = 1
      while (Test-Path $archivePath) {
        $archivePath = Join-Path $archiveRoot "${archiveName}_$suffix"
        $suffix += 1
      }

      Move-Item -LiteralPath $out -Destination $archivePath
      Write-Host "Archived previous live output: $archivePath" -ForegroundColor Yellow
    }
  }

  New-Item -ItemType Directory -Force -Path $out | Out-Null
  return $out
}
