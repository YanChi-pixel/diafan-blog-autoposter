"""Дублирование вывода в UTF-8-файл.

Зачем это отдельным модулем: Планировщик Windows запускает Windows
PowerShell 5.1, который декодирует вывод дочернего процесса через кодовую
страницу консоли — русский текст в логе превращается в мусор. Вдобавок
захват двух потоков дочернего процесса через ReadToEnd() приводит к
взаимной блокировке, если один из буферов переполнится.

Поэтому лог пишет сам Python, а PowerShell только запускает процесс и
читает код возврата.
"""
from __future__ import annotations

import sys
from pathlib import Path


class Tee:
    """Пишет и в исходный поток, и в файл (UTF-8, без BOM)."""

    def __init__(self, stream, path):
        self.stream = stream
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(self.path, "a", encoding="utf-8", newline="\n")

    def write(self, data):
        if not isinstance(data, str):
            data = str(data)
        try:
            self.stream.write(data)
        except Exception:  # noqa: BLE001
            pass
        stripped = data.rstrip("\n")
        if stripped:
            self.file.write(stripped + "\n")
            self.file.flush()

    def flush(self):
        try:
            self.stream.flush()
        except Exception:  # noqa: BLE001
            pass
        self.file.flush()

    def isatty(self):
        return False


def install(path: str | None):
    """Включает дублирование вывода в файл. Возвращает исходный stdout."""
    original = sys.stdout
    if path:
        tee = Tee(original, path)
        sys.stdout = tee
        sys.stderr = tee
    return original


def restore(original):
    try:
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass
    sys.stdout = original
    sys.stderr = sys.__stderr__
