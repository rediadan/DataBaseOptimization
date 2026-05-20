if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env 파일을 생성했습니다. 설정을 확인한 뒤 다시 실행해도 됩니다."
}

python ".\app.py"
