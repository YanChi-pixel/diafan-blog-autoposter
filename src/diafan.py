"""Клиент публикатора на сайте.

Один запрос на статью. Хостинг режет частые обращения, поэтому:
  * пауза между запросами (config: site.rate_limit);
  * экспоненциальный бэкофф на 5xx и сетевые ошибки;
  * никаких параллельных вызовов.
"""
from __future__ import annotations

import json
import time
from typing import Any

import requests

import settings

_SESSION: requests.Session | None = None
_LAST_CALL = 0.0


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        s.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        s.headers["X-Publisher-Token"] = settings.env("PUBLISHER_TOKEN")
        s.auth = (settings.env("ALERT_LOGIN"), settings.env("ALERT_PASSWORD"))
        _SESSION = s
    return _SESSION


def endpoint() -> str:
    return settings.env("SITE_URL").rstrip("/") + "/" + settings.env("PUBLISHER_PATH").lstrip("/")


def _throttle() -> None:
    global _LAST_CALL
    cfg = settings.load_config()["site"]["rate_limit"]
    wait = cfg["min_seconds_between_requests"] - (time.time() - _LAST_CALL)
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL = time.time()


def _request(method: str, action: str, payload: dict | None = None,
             timeout: int = 180) -> dict[str, Any]:
    cfg = settings.load_config()["site"]["rate_limit"]
    url = endpoint() + "?action=" + action
    last: Exception | None = None

    for attempt in range(cfg["max_retries"]):
        _throttle()
        try:
            if method == "POST":
                r = _session().post(url, json=payload or {}, timeout=timeout)
            else:
                r = _session().get(url, timeout=timeout)

            if r.status_code == 403:
                raise RuntimeError("403 forbidden — проверь PUBLISHER_TOKEN в .env")
            if r.status_code >= 500:
                raise RuntimeError("HTTP %d: %s" % (r.status_code, r.text[:300]))
            try:
                return r.json()
            except ValueError:
                raise RuntimeError(
                    "ответ не JSON (HTTP %d): %s" % (r.status_code, r.text[:400])
                )
        except RuntimeError as e:
            if "403" in str(e):
                raise
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        pause = cfg["backoff_base_seconds"] * (attempt + 1)
        print("    ! %s — повтор через %d с" % (str(last)[:120], pause))
        time.sleep(pause)

    raise RuntimeError("публикатор недоступен: %s" % last)


def inspect() -> dict:
    return _request("GET", "inspect")


def publish(payload: dict) -> dict:
    return _request("POST", "publish", payload)


def update(payload: dict) -> dict:
    """Правка уже опубликованной статьи (id в payload)."""
    return _request("POST", "update", payload)


def set_image(news_id: int, image_bytes: bytes, alt: str = "",
              keep_existing: bool = False) -> dict:
    """Замена обложки опубликованной статьи."""
    import base64
    return _request("POST", "set_image", {
        "id": news_id,
        "image_base64": base64.b64encode(image_bytes).decode("ascii"),
        "image_alt": alt,
        "keep_existing": keep_existing,
    })


def delete(news_id: int) -> dict:
    """Откат публикации: запись в корзину, файлы картинок удаляются."""
    return _request("GET", "delete&id=%d" % news_id)


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    data = inspect()
    out = settings.ROOT / "output" / "inspect.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Сохранено:", out)

    for key in ("cms_version", "news_count", "rewrite_samples", "images_variations",
                "images_upload_signature", "cache_class", "writable", "news_image_dirs",
                "news_site", "admins"):
        print("\n=== %s ===" % key)
        print(json.dumps(data.get(key), ensure_ascii=False, indent=2)[:2000])
