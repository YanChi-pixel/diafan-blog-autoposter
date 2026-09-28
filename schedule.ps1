<#
    schedule.ps1 — регистрация задач в Планировщике Windows (НЕОБЯЗАТЕЛЬНО).

    По умолчанию автозапуск НЕ настроен: статьи публикуются вручную
    командой  .\publish.ps1 -Count 2  — как в остальных проектах.

    Этот скрипт нужен, только если когда-нибудь понадобится вернуть
    автоматическую публикацию по расписанию.

    Запуск (из PowerShell):
        .\schedule.ps1                       # 10:00 и 16:00
        .\schedule.ps1 -Times "09:30","14:30","19:30"
        .\schedule.ps1 -Remove               # удалить задачи
        .\schedule.ps1 -Show                 # показать состояние

    Задачи запускают PowerShell напрямую — CMD не участвует.
    Предпочитается PowerShell 7 (pwsh), при его отсутствии используется
    Windows PowerShell 5.1.

    Компьютер должен быть включён в момент запуска. Если он спит,
    задача выполнится при следующем пробуждении (StartWhenAvailable).
#>
param(
    [string[]]$Times = @("10:00", "16:00"),
    [switch]$Remove,
    [switch]$Show
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\ps-common.ps1"
Initialize-Console

$root = $ProjectRoot
$taskPrefix = "Diafan-Blog"

if ($Show) {
    Get-ScheduledTask -TaskName "$taskPrefix-*" -ErrorAction SilentlyContinue |
        ForEach-Object {
            $info = $_ | Get-ScheduledTaskInfo
            "{0}  {1}  след. запуск: {2}  последний результат: {3}" -f `
                $_.TaskName, $_.State, $info.NextRunTime, $info.LastTaskResult
        }
    return
}

if ($Remove) {
    Get-ScheduledTask -TaskName "$taskPrefix-*" -ErrorAction SilentlyContinue |
        ForEach-Object {
            Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false
            Write-Host "Удалена задача: $($_.TaskName)"
        }
    return
}

$script = Join-Path $root "publish.ps1"
if (-not (Test-Path $script)) { throw "Не найден $script" }

# Хост PowerShell: pwsh 7, иначе powershell.exe. Оба принимают
# -NoProfile -ExecutionPolicy Bypass -File.
$hostExe = Get-PowerShellHost
Write-Host "Хост PowerShell: $hostExe"

$i = 0
foreach ($t in $Times) {
    $i++
    $name = "$taskPrefix-$i"
    $action = New-ScheduledTaskAction -Execute $hostExe `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -Count 1" `
        -WorkingDirectory $root

    $trigger = New-ScheduledTaskTrigger -Daily -At $t

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
        -MultipleInstances IgnoreNew

    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
        -Settings $settings -Force `
        -Description "Автопостинг блога на Diafan.CMS: одна статья в $t" | Out-Null

    Write-Host "Зарегистрирована задача $name на $t"
}

Write-Host ""
Write-Host "Проверить:         .\schedule.ps1 -Show"
Write-Host "Запустить вручную: Start-ScheduledTask -TaskName '$taskPrefix-1'"
Write-Host "Логи:              $root\logs\"
