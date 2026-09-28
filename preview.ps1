<#
    preview.ps1 — сгенерировать статью локально, ничего не публикуя.

    Запуск из PowerShell:
        .\preview.ps1
        .\preview.ps1 -Topic "тема статьи"

    Результат: jobs\<дата>-<слаг>\preview.html — открывается в браузере
    со стилями сайта, чтобы оценить вёрстку до публикации.

    Никакого CMD: chcp не вызывается, кодировка ставится средствами .NET.
#>
param(
    [string]$Topic = ""
)

$ErrorActionPreference = "Continue"
. "$PSScriptRoot\ps-common.ps1"

$root = $ProjectRoot
Set-Location $root
Initialize-Console

$python = Get-PythonPath
if (-not $python) {
    Write-Host "ОШИБКА: не найден python.exe" -ForegroundColor Red
    exit 1
}

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$runArgs = @((Join-Path $root "src\run_one.py"), "--no-publish")
if ($Topic) { $runArgs += $Topic }

& $python @runArgs

$job = Get-ChildItem (Join-Path $root "jobs") -Directory -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($job) {
    $preview = Join-Path $job.FullName "preview.html"
    if (Test-Path $preview) {
        Write-Host ""
        Write-Host "Предпросмотр: $preview" -ForegroundColor Green
        Start-Process $preview
    }
}
