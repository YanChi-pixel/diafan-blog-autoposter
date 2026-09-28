"""Загрузка настроек: .env (секреты) + config.json (параметры).

Секреты никогда не хранятся в config.json и не пишутся в логи.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _parse_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


_ENV = _parse_env(ROOT / ".env")
_CONFIG = None


def env(key: str, default: str = "") -> str:
    """Значение из .env, с приоритетом переменных окружения процесса."""
    return os.environ.get(key) or _ENV.get(key) or default


def site_url() -> str:
    """Базовый URL сайта из .env (SITE_URL) без замыкающего слэша."""
    return env("SITE_URL", "https://your-site.example.com").rstrip("/")


def site_host() -> str:
    """Хост сайта без схемы — по нему отличаем внутреннюю ссылку от внешней."""
    from urllib.parse import urlparse

    return urlparse(site_url()).netloc or "your-site.example.com"


def load_config() -> dict:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    return _CONFIG


def path(key: str) -> Path:
    """Абсолютный путь из секции paths конфига."""
    rel = load_config()["paths"][key]
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    d = ROOT / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d
