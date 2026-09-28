"""Отправка URL на переобход в Яндекс.Вебмастер.

После публикации статьи сообщаем Яндексу, что страницу нужно переобойти —
иначе новый материал может ждать обхода неделями.

Проверено: у сайта уже есть подтверждённый хост в аккаунте Вебмастера,
поэтому отдельный API создавать не нужно.

Что делает:
    1. GET /user                      -> user_id
    2. GET /user/{id}/hosts           -> host_id для домена
    3. POST /user/{id}/hosts/{hid}/recrawl/queue  {"url": "..."}

user_id и host_id кэшируются в data/webmaster.json: иначе на каждую
статью уходило бы два лишних запроса.

Ограничения API: суточная квота на переобход (при её исчерпании приходит
429). При двух статьях в день до лимита далеко.

Использование:
    python src/recrawl.py <url> [<url> ...]   # отправить ссылки
    python src/recrawl.py --pending           # отправить всё, что без отметки
    python src/recrawl.py --status            # что уже отправлено
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

import settings

API_BASE = "https://api.webmaster.yandex.net/v4"
CACHE_FILE = "webmaster.json"


# --------------------------------------------------------------------------
# Служебное
# --------------------------------------------------------------------------

def _token() -> str:
    token = settings.env("YANDEX_WEBMASTER_TOKEN")
    if not token:
        raise RuntimeError(
            "не задан YANDEX_WEBMASTER_TOKEN в .env — переобход невозможен"
        )
    return token


def _host() -> str:
    return settings.env("YANDEX_WEBMASTER_HOST") or settings.site_host()


def _cache_path():
    return settings.data_dir() / CACHE_FILE


def _load_cache() -> dict:
    p = _cache_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def _save_cache(data: dict) -> None:
    try:
        _cache_path().write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        API_BASE + path,
        data=data,
        method=method,
        headers={
            "Authorization": "OAuth " + token,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


# --------------------------------------------------------------------------
# Идентификаторы
# --------------------------------------------------------------------------

def resolve_ids(token: str | None = None, refresh: bool = False) -> tuple[str, str]:
    """Возвращает (user_id, host_id). Значения кэшируются."""
    cache = _load_cache()
    host = _host()
    if (not refresh and cache.get("user_id") and cache.get("host_id")
            and cache.get("host") == host):
        return str(cache["user_id"]), str(cache["host_id"])

    token = token or _token()
    user_id = str(_api("GET", "/user", token)["user_id"])

    data = _api("GET", "/user/%s/hosts" % user_id, token)
    host_id = None
    for h in data.get("hosts", []):
        urls = (h.get("unicode_host_url") or "", h.get("ascii_host_url") or "")
        if any(host in u for u in urls):
            if not h.get("verified"):
                raise RuntimeError("хост %s в Вебмастере не подтверждён" % host)
            host_id = h["host_id"]
            break
    if not host_id:
        raise RuntimeError(
            "домен %s не найден среди сайтов Вебмастера. "
            "Добавьте и подтвердите его: https://webmaster.yandex.ru/" % host
        )

    cache.update({"user_id": user_id, "host_id": host_id, "host": host})
    _save_cache(cache)
    return user_id, host_id


# --------------------------------------------------------------------------
# Переобход
# --------------------------------------------------------------------------

def submit(urls: list[str], token: str | None = None,
           refresh: bool = False) -> dict:
    """Отправляет ссылки на переобход.

    Возвращает {'ok': n, 'errors': [...], 'quota_exceeded': bool}.
    Никогда не бросает исключение из-за отдельной ссылки — только если
    не удалось авторизоваться или найти хост.
    """
    token = token or _token()
    user_id, host_id = resolve_ids(token, refresh=refresh)
    path = "/user/%s/hosts/%s/recrawl/queue" % (user_id, host_id)

    result = {"ok": 0, "sent": [], "errors": [], "quota_exceeded": False}
    for url in urls:
        try:
            _api("POST", path, token, {"url": url})
            result["ok"] += 1
            result["sent"].append(url)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8")[:300]
            except Exception:  # noqa: BLE001
                pass
            if e.code == 429:
                result["quota_exceeded"] = True
                result["errors"].append("%s: HTTP 429 — суточная квота исчерпана" % url)
                break
            if e.code in (400, 409) and "already" in body.lower():
                result["ok"] += 1
                result["sent"].append(url)
                continue
            result["errors"].append("%s: HTTP %d %s" % (url, e.code, body))
        except Exception as e:  # noqa: BLE001
            result["errors"].append("%s: %s" % (url, str(e)[:160]))
    return result


def submit_quiet(urls: list[str]) -> bool:
    """Обёртка для конвейера: не шумит и не роняет публикацию при сбое."""
    if not urls:
        return True
    try:
        res = submit(urls)
    except Exception as e:  # noqa: BLE001
        print("        переобход: не удалось (%s)" % str(e)[:140])
        return False
    if res["ok"]:
        print("        переобход: отправлено в Яндекс (%d)" % res["ok"])
    for err in res["errors"]:
        print("        переобход: %s" % err)
    return res["ok"] > 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def queue_status() -> dict:
    """Состояние очереди переобхода и остаток суточной квоты на стороне Яндекса."""
    token = _token()
    user_id, host_id = resolve_ids(token)
    base = "/user/%s/hosts/%s/recrawl" % (user_id, host_id)
    out = {"tasks": [], "quota": {}}
    try:
        out["tasks"] = _api("GET", base + "/queue", token).get("tasks", [])
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
    try:
        out["quota"] = _api("GET", base + "/quota", token)
    except Exception:  # noqa: BLE001
        pass
    return out


def _registry_entries():
    path = settings.path("registry")
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("published", [])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Яндекс.Вебмастер: переобход URL")
    ap.add_argument("urls", nargs="*", help="ссылки для переобхода")
    ap.add_argument("--pending", action="store_true",
                    help="отправить статьи из реестра без отметки о переобходе")
    ap.add_argument("--status", action="store_true", help="что уже отправлено")
    ap.add_argument("--queue", action="store_true",
                    help="очередь переобхода и квота на стороне Яндекса")
    ap.add_argument("--refresh", action="store_true",
                    help="перечитать user_id и host_id из API")
    args = ap.parse_args()

    if args.queue:
        data = queue_status()
        q = data.get("quota") or {}
        if q:
            print("Суточная квота: %s, остаток: %s"
                  % (q.get("daily_quota"), q.get("quota_remainder")))
        tasks = data.get("tasks") or []
        print("Задач в очереди: %d" % len(tasks))
        for t in tasks[:20]:
            print("  %-10s %-46s %s"
                  % (t.get("state"),
                     t.get("url", "").replace(settings.site_url(), ""),
                     (t.get("added_time") or "")[:19]))
        if len(tasks) > 20:
            print("  ... и ещё %d" % (len(tasks) - 20))
        if data.get("error"):
            print("ошибка: %s" % data["error"])
        return 0

    if args.status:
        entries = _registry_entries()
        done = [e for e in entries if e.get("recrawl_at")]
        todo = [e for e in entries if not e.get("recrawl_at")]
        print("Отправлено на переобход: %d" % len(done))
        for e in done:
            print("  %-46s %s" % (e["url"].replace(settings.site_url(), ""),
                                  e["recrawl_at"]))
        if todo:
            print("\nНе отправлено: %d" % len(todo))
            for e in todo:
                print("  %s" % e["url"])
            print("\nОтправить: python src\\recrawl.py --pending")
        return 0

    if args.pending:
        entries = _registry_entries()
        urls = [e["url"] for e in entries if not e.get("recrawl_at")]
        if not urls:
            print("Все статьи реестра уже отправлены на переобход.")
            return 0
        print("Отправляю %d ссылок..." % len(urls))
        res = submit(urls, refresh=args.refresh)
        for u in res["sent"]:
            print("  OK  %s" % u)
        for e in res["errors"]:
            print("  !!! %s" % e)
        # отметку ставим только тем, что реально ушли
        if res["ok"]:
            import time
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            for e in entries:
                if e["url"] in res["sent"]:
                    e["recrawl_at"] = stamp
            settings.path("registry").write_text(
                json.dumps({"published": entries}, ensure_ascii=False, indent=2),
                encoding="utf-8")
        return 0 if not res["errors"] else 1

    if not args.urls:
        ap.print_help()
        return 2

    res = submit(args.urls, refresh=args.refresh)
    for u in res["sent"]:
        print("OK  %s" % u)
    for e in res["errors"]:
        print("!!! %s" % e)
    if res["quota_exceeded"]:
        print("\nСуточная квота Вебмастера исчерпана — повторите завтра.")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
