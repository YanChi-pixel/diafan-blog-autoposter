<#
    publish.ps1 — публикация N статей подряд.

    Использование (из PowerShell):
        .\publish.ps1                 # 1 статья (тема — первая из очереди)
        .\publish.ps1 -Count 2        # 2 статьи
        .\publish.ps1 -Topic "текст"  # конкретная тема
        .\publish.ps1 -DryRun         # проверить публикатор без записи
        .\publish.ps1 -Preview        # сгенерировать без публикации

    Тема уходит из очереди только после успешной публикации, поэтому
    повторный запуск после сбоя ничего не теряет.

    Никакого CMD: кодировка ставится средствами .NET, chcp не вызывается,
    вывод python не захватывается, лог пишет сам python через --log.

    ВАЖНО: файл сохранён в UTF-8 с BOM. Без BOM Windows PowerShell 5.1
    читает его как ANSI, русские строки ломают парсинг и задача падает
    с кодом 1, не создав даже лог.
#>
param(
    [int]$Count = 1,
    [string]$Topic = "",
    [switch]$DryRun,
    [switch]$Preview,
    [switch]$NoCheck
)

$ErrorActionPreference = "Continue"
. "$PSScriptRoot\ps-common.ps1"

$root = $ProjectRoot
Set-Location $root
Initialize-Console

$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$stamp = Get-Date -Format "yyyy-MM-dd"
$log = Join-Path $logDir "publish-$stamp.log"

$python = Get-PythonPath
if (-not $python) {
    Write-Log -Text "ОШИБКА: не найден python.exe" -Path $log
    exit 1
}

# python пишет лог сам (--log), поэтому вывод дочернего процесса
# НЕ захватывается: захват двух потоков через ReadToEnd() даёт дедлок
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$hostExe = Get-PowerShellHost
Write-Log -Text ("хост PowerShell: {0}" -f $hostExe) -Path $log
Write-Log -Text ("python: {0}" -f $python) -Path $log
Write-Log -Text ("=== Запуск: {0} статей ===" -f $Count) -Path $log

$ok = 0
$fail = 0
for ($i = 1; $i -le $Count; $i++) {
    Write-Log -Text ("--- статья {0} из {1} ---" -f $i, $Count) -Path $log

    # $args — автоматическая переменная PowerShell, используем своё имя
    $runArgs = @((Join-Path $root "src\run_one.py"), "--log", $log)
    if ($Topic -and $i -eq 1) { $runArgs += $Topic }
    if ($Preview) { $runArgs += "--no-publish" }
    elseif ($DryRun) { $runArgs += "--dry-run" }

    & $python @runArgs
    $code = $LASTEXITCODE

    if ($code -eq 0) {
        $ok++
        Write-Log -Text ("статья {0} — успех" -f $i) -Path $log
        # пауза между статьями: хостинг не любит частые запросы
        if ($i -lt $Count) {
            Write-Log -Text "пауза 90 с перед следующей статьёй" -Path $log
            Start-Sleep -Seconds 90
        }
    }
    else {
        $fail++
        Write-Log -Text ("статья {0} — ОШИБКА (код {1}), см. jobs\ и output\" -f $i, $code) -Path $log
    }
}

Write-Log -Text ("=== Итог: успешно {0}, ошибок {1} ===" -f $ok, $fail) -Path $log

if (-not $NoCheck -and -not $Preview) {
    Write-Log -Text "--- проверка опубликованных статей ---" -Path $log
    & $python (Join-Path $root "src\check.py") --log $log
}

exit $fail
