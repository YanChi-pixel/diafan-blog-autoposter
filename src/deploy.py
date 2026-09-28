"""Деплой на хостинг по FTP: список, бэкап, удаление, загрузка.

Из-за рейт-лимитов хостинга всё делается ОДНИМ соединением за запуск.
Перед удалением файл всегда сохраняется в data/backups/ — удаление без
бэкапа невозможно.

Примеры:
    python src/deploy.py ls
    python src/deploy.py ls modules/news
    python src/deploy.py backup import.php upd.php
    python src/deploy.py rm import.php upd.php
    python src/deploy.py put server/publisher.php pub-5582c1dc0a.php
"""
from __future__ import annotations

import sys
from datetime import datetime

import settings
from ftp_client import Ftp, FtpError

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def backup_dir():
    d = settings.ROOT / settings.load_config()["paths"]["backup_dir"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_ls(f: Ftp, args: list[str]) -> None:
    rel = args[0] if args else ""
    print("=== %s ===" % (f.remote(rel) if rel else f.site_path))
    for name, is_dir, size in f.ls(rel):
        print("  %-48s %-5s %10s" % (name, "dir" if is_dir else "file", size))


def cmd_backup(f: Ftp, args: list[str]) -> list[str]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    saved = []
    for rel in args:
        try:
            data = f.read_bytes(rel)
        except FtpError as e:
            print("  ПРОПУСК %-30s (%s)" % (rel, str(e)[:60]))
            continue
        dest = backup_dir() / stamp / rel.replace("/", "__")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        saved.append(rel)
        print("  БЭКАП  %-30s -> %s (%d байт)" % (rel, dest.name, len(data)))
    return saved


def cmd_rm(f: Ftp, args: list[str]) -> None:
    """Сначала бэкап, потом удаление. Без успешного бэкапа не удаляем."""
    print("Бэкап перед удалением:")
    saved = set(cmd_backup(f, args))
    print("Удаление:")
    for rel in args:
        if rel not in saved:
            print("  ОТКАЗ  %-30s — нет бэкапа, файл не тронут" % rel)
            continue
        try:
            f.delete(rel)
            print("  УДАЛЁН %-30s" % rel)
        except FtpError as e:
            print("  ОШИБКА %-30s %s" % (rel, str(e)[:80]))


def cmd_put(f: Ftp, args: list[str]) -> None:
    if len(args) != 2:
        print("использование: put <локальный> <путь_на_сайте>")
        return
    local, remote = args
    f.upload_file_deep(settings.ROOT / local, remote)
    size = (settings.ROOT / local).stat().st_size
    print("  ЗАГРУЖЕН %s -> %s (%d байт)" % (local, remote, size))


def cmd_get(f: Ftp, args: list[str]) -> None:
    if len(args) != 2:
        print("использование: get <путь_на_сайте> <локальный>")
        return
    remote, local = args
    data = f.read_bytes(remote)
    dest = settings.ROOT / local
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print("  СКАЧАН %s -> %s (%d байт)" % (remote, local, len(data)))


def publisher_remote() -> str:
    return settings.env("PUBLISHER_PATH").lstrip("/")


def cmd_publisher(f: Ftp, args: list[str]) -> None:
    """Задеплоить publisher.php с подставленным секретом."""
    src = settings.ROOT / "server" / "publisher.php"
    token = settings.env("PUBLISHER_TOKEN")
    if not token or token == "REPLACE_ME":
        print("  ОШИБКА: PUBLISHER_TOKEN не задан в .env")
        return
    code = src.read_text(encoding="utf-8")
    if "__PUBLISHER_TOKEN__" not in code:
        print("  ОШИБКА: в publisher.php нет плейсхолдера __PUBLISHER_TOKEN__")
        return
    code = code.replace("__PUBLISHER_TOKEN__", token)
    remote = publisher_remote()
    f.upload_text(remote, code)
    print("  ЗАДЕПЛОЕН %s (%d байт)" % (remote, len(code.encode("utf-8"))))
    print("  URL: %s/%s" % (settings.env("SITE_URL").rstrip("/"), remote))


def cmd_unpublish(f: Ftp, args: list[str]) -> None:
    """Снять publisher.php с сайта (с бэкапом)."""
    cmd_rm(f, [publisher_remote()])


COMMANDS = {
    "ls": cmd_ls,
    "backup": cmd_backup,
    "rm": cmd_rm,
    "put": cmd_put,
    "get": cmd_get,
    "publisher": cmd_publisher,
    "unpublish": cmd_unpublish,
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("команды: %s" % ", ".join(COMMANDS))
        return 2
    cmd, args = sys.argv[1], sys.argv[2:]
    print("Подключение к %s ..." % settings.env("FTP_HOST"))
    with Ftp() as f:
        print("OK, корень сайта: %s\n" % f.site_path)
        COMMANDS[cmd](f, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
