<#
    test_schedule.ps1 — проверка, что задача Планировщика реально отрабатывает.

    Создаёт ВРЕМЕННУЮ задачу, запускает publish.ps1 в выбранном режиме,
    ждёт завершения, показывает новые строки лога и удаляет задачу.

    Проверяет боевой путь: Task Scheduler -> PowerShell -> publish.ps1
    -> python -> run_one.py, включая рабочую папку, PATH и кодировку.

    Режимы (-Mode):
        Preview  — генерация без публикации (по умолчанию)
        DryRun   — полный путь, включая HTTPS-запрос к публикатору,
                   но БЕЗ создания записи на сайте
        Publish  — настоящая публикация статьи

    Использование:
        .\test_schedule.ps1                # Preview
        .\test_schedule.ps1 -Mode DryRun   # проверить и сетевой вызов
#>
param(
    [ValidateSet("Preview", "DryRun", "Publish")]
    [string]$Mode = "Preview"
)

$ErrorActionPreference = "Continue"
. "$PSScriptRoot\ps-common.ps1"
Initialize-Console

$root = $ProjectRoot
$taskName = "Diafan-Blog-SelfTest"

$switch = switch ($Mode) {
    "Preview" { "-Preview" }
    "DryRun"  { "-DryRun" }
    "Publish" { "" }
}

$script = Join-Path $root "publish.ps1"
if (-not (Test-Path $script)) { throw "Не найден $script" }

$hostExe = Get-PowerShellHost
Write-Host "Каталог проекта: $root"
Write-Host "Хост PowerShell: $hostExe"
Write-Host "Режим: $Mode ($switch)"

# подчистить прошлый прогон
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$stamp = Get-Date -Format "yyyy-MM-dd"
$log = Join-Path $root "logs\publish-$stamp.log"
$before = if (Test-Path $log) { (Get-Content $log).Count } else { 0 }

$action = New-ScheduledTaskAction -Execute $hostExe `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -Count 1 $switch" `
    -WorkingDirectory $root

# запуск «как можно скорее»: триггер на прошедшее время активируется сразу
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(-1)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew

Write-Host "Регистрирую временную задачу $taskName ..."
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null

Write-Host "Запускаю ..."
Start-ScheduledTask -TaskName $taskName

# ждём завершения (максимум 20 минут)
$deadline = (Get-Date).AddMinutes(20)
$state = "Unknown"
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 10
    $state = (Get-ScheduledTask -TaskName $taskName).State
    if ($state -ne "Running") { break }
}

$info = Get-ScheduledTask -TaskName $taskName | Get-ScheduledTaskInfo
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Временная задача удалена."

Write-Host "`n=== Новые строки лога ==="
if (Test-Path $log) {
    $lines = Get-Content $log
    $new = $lines | Select-Object -Skip $before
    if ($new) { $new | ForEach-Object { Write-Host $_ } } else { Write-Host "(лог не пополнился!)" }
} else {
    Write-Host "ЛОГ НЕ СОЗДАН — задача не отработала!"
}

Write-Host ("`nИтог: состояние={0}, код возврата={1}" -f $state, $info.LastTaskResult)
