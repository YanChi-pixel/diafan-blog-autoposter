"""FTP-клиент под капризный shared-хостинг.

Особенности сервера, выясненные экспериментально:
  * LIST не работает (data-соединение отваливается) — используем MLSD/NLST;
  * жёсткий лимит на частоту подключений (~1 в 30-60 с), иначе IP банится;
  * поэтому: одно долгоживущее соединение + ретраи с нарастающей паузой.

Все операции идемпотентны и безопасны для повторного вызова.
"""
from __future__ import annotations

import ftplib
import io
import time
from pathlib import Path

import settings

CONNECT_ATTEMPTS = 6
OP_ATTEMPTS = 4
BASE_PAUSE = 6.0


class FtpError(RuntimeError):
    pass


class Ftp:
    """Контекстный менеджер: with Ftp() as f: f.upload(...)"""

    def __init__(self) -> None:
        self.host = settings.env("FTP_HOST")
        self.port = int(settings.env("FTP_PORT", "21"))
        self.user = settings.env("FTP_USER")
        self.password = settings.env("FTP_PASSWORD")
        self.site_path = settings.env("FTP_SITE_PATH", "www").strip("/")
        self.conn: ftplib.FTP | None = None

    # ---------- соединение ----------

    def connect(self) -> "Ftp":
        last: Exception | None = None
        for attempt in range(CONNECT_ATTEMPTS):
            try:
                c = ftplib.FTP()
                c.connect(self.host, self.port, timeout=60)
                c.set_pasv(True)
                c.login(self.user, self.password)
                c.encoding = "utf-8"
                self.conn = c
                return self
            except Exception as e:  # noqa: BLE001
                last = e
                self._sleep(BASE_PAUSE * (attempt + 1))
        raise FtpError("не удалось подключиться к FTP: %s" % last)

    def __enter__(self) -> "Ftp":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.quit()
            except Exception:  # noqa: BLE001
                try:
                    self.conn.close()
                except Exception:  # noqa: BLE001
                    pass
            self.conn = None

    def reconnect(self) -> None:
        self.close()
        self._sleep(BASE_PAUSE)
        self.connect()

    @staticmethod
    def _sleep(seconds: float) -> None:
        time.sleep(seconds)

    def _op(self, fn, *args, **kwargs):
        """Выполнить операцию с ретраями и переподключением."""
        last: Exception | None = None
        for attempt in range(OP_ATTEMPTS):
            try:
                return fn(*args, **kwargs)
            except ftplib.error_perm:
                raise
            except Exception as e:  # noqa: BLE001
                last = e
                self._sleep(BASE_PAUSE)
                try:
                    self.reconnect()
                except Exception as e2:  # noqa: BLE001
                    last = e2
        raise FtpError("операция не удалась после %d попыток: %s" % (OP_ATTEMPTS, last))

    # ---------- пути ----------

    def remote(self, rel_path: str) -> str:
        """Путь относительно веб-корня сайта."""
        return "%s/%s" % (self.site_path, rel_path.lstrip("/"))

    # ---------- операции ----------

    def ls(self, rel_path: str = "") -> list[tuple[str, bool, int]]:
        """[(имя, это_каталог, размер)] для пути относительно веб-корня."""
        target = self.remote(rel_path) if rel_path else self.site_path
        out: list[tuple[str, bool, int]] = []

        def _do():
            out.clear()
            for name, facts in self.conn.mlsd(target):
                if name in (".", ".."):
                    continue
                out.append((name, facts.get("type") == "dir", int(facts.get("size") or 0)))

        self._op(_do)
        return sorted(out)

    def exists(self, rel_path: str) -> bool:
        """Проверка наличия файла через SIZE (каталоги вернут ошибку)."""
        try:
            self._op(lambda: self.conn.size(self.remote(rel_path)))
            return True
        except Exception:  # noqa: BLE001
            return False

    def read_bytes(self, rel_path: str) -> bytes:
        buf = io.BytesIO()
        self._op(lambda: self.conn.retrbinary("RETR " + self.remote(rel_path), buf.write))
        return buf.getvalue()

    def read_text(self, rel_path: str) -> str:
        raw = self.read_bytes(rel_path)
        for enc in ("utf-8", "cp1251"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", "replace")

    def upload_bytes(self, rel_path: str, data: bytes) -> None:
        self._op(lambda: self.conn.storbinary("STOR " + self.remote(rel_path), io.BytesIO(data)))

    def upload_text(self, rel_path: str, text: str) -> None:
        self.upload_bytes(rel_path, text.encode("utf-8"))

    def upload_file(self, local: Path, rel_path: str) -> None:
        data = Path(local).read_bytes()
        self.upload_bytes(rel_path, data)

    def delete(self, rel_path: str) -> None:
        self._op(lambda: self.conn.delete(self.remote(rel_path)))

    def mkdir(self, rel_path: str) -> None:
        try:
            self._op(lambda: self.conn.mkd(self.remote(rel_path)))
        except ftplib.error_perm:
            pass  # уже существует

    def ensure_dir(self, rel_path: str) -> None:
        """Создаёт каталог со всеми родителями (относительно веб-корня)."""
        parts = [p for p in rel_path.strip("/").split("/") if p]
        current = ""
        for part in parts:
            current = (current + "/" + part) if current else part
            self.mkdir(current)

    def upload_file_deep(self, local: Path, rel_path: str) -> None:
        """Загрузка файла с созданием недостающих каталогов."""
        from pathlib import PurePosixPath
        parent = str(PurePosixPath(rel_path).parent)
        if parent and parent != ".":
            self.ensure_dir(parent)
        self.upload_file(local, rel_path)


def _rel(absolute_inside_site: str) -> str:
    """'www/site.ru/modules' -> 'modules'."""
    parts = absolute_inside_site.split("/", 2)
    return parts[2] if len(parts) > 2 else ""
