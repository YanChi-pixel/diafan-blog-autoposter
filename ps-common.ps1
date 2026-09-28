<#
    ps-common.ps1 — общие функции для скриптов проекта.

    Подключается так:
        . "$PSScriptRoot\ps-common.ps1"

    Здесь собрано всё, что раньше тянуло за собой CMD или ломалось
    в Планировщике задач.
#>

$script:ProjectRoot = $PSScriptRoot

<#
    Настройка кодировки консоли БЕЗ вызова chcp.

    chcp — это внешняя утилита chcp.com, то есть лишний процесс CMD.
    Устанавливаем кодировку средствами .NET. В неинтерактивной сессии
    Планировщика консоли может не быть — поэтому в try/catch.
#>
function Initialize-Console {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    try { [Console]::OutputEncoding = $utf8 } catch { }
    try { $global:OutputEncoding = $utf8 } catch { }
    try { [Console]::InputEncoding = $utf8 } catch { }
}

<#
    Предпочитаемый хост PowerShell.

    Сначала PowerShell 7 (pwsh) — у него UTF-8 по умолчанию и предсказуемая
    работа с дочерними процессами. Если его нет, берём Windows PowerShell 5.1,
    который есть на любой Windows.

    Возвращает полный путь к исполняемому файлу.
#>
function Get-PowerShellHost {
    $pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($pwsh -and (Test-Path $pwsh.Source)) { return $pwsh.Source }
    $win = Get-Command powershell -ErrorAction SilentlyContinue
    if ($win -and (Test-Path $win.Source)) { return $win.Source }
    return "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
}

<#
    Записывает строку и в консоль, и в UTF-8-файл лога.

    Пишем через .NET, а не Add-Content -Encoding UTF8: в Windows PowerShell 5.1
    этот параметр добавляет BOM при создании файла и не добавляет при
    дозаписи, из-за чего лог получается смешанным.
#>
function Write-Log {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [string]$Path
    )
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Text
    try { Write-Host $line } catch { }
    if ($Path) {
        try {
            $utf8 = New-Object System.Text.UTF8Encoding($false)
            [System.IO.File]::AppendAllText($Path, $line + "`r`n", $utf8)
        } catch { }
    }
}

<#
    Разрешает путь к python.exe.

    Планировщик запускает задачу без пользовательского PATH, поэтому
    Get-Command может ничего не найти.
#>
function Get-PythonPath {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Path $cmd.Source)) { return $cmd.Source }

    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "C:\Python313\python.exe",
        "C:\Python312\python.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    return $null
}
