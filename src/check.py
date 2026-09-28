"""Догоняющая проверка опубликованных статей.

Хостинг режет частые запросы, поэтому пост-проверку иногда приходится
делать отдельным запуском — например, через час после публикации.

    python src/check.py          # проверить все с отложенным статусом
    python src/check.py --all    # перепроверить все статьи из реестра
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time

import requests

import logsetup
import settings

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def extract_text_block(html: str) -> str:
    """Содержимое <div class="_text"> с балансировкой вложенных div."""
    m = re.search(r'<div class="_text">', html)
    if not m:
        return ""
    i = m.end()
    depth = 1
    j = i
    while depth > 0:
        nxt_open = html.find("<div", j)
        nxt_close = html.find("</div>", j)
        if nxt_close == -1:
            break
        if nxt_open != -1 and nxt_open < nxt_close:
            depth += 1
            j = nxt_open + 4
        else:
            depth -= 1
            j = nxt_close + 6
    return html[i:max(i, j - 6)]


def check_url(url: str) -> dict:
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    except Exception as e:  # noqa: BLE001
        return {"status": "deferred", "error": str(e)[:140]}
    if r.status_code != 200:
        return {"status": r.status_code}
    html = r.text
    h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", html)
    img = re.search(r'<img src="([^"]*userfls/news[^"]*)"', html)
    body = extract_text_block(html)
    internal = len(re.findall(
        r'href="(?:%s)?/' % re.escape(settings.site_url()), body))
    return {
        "status": 200,
        "h1": re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else None,
        "image": img.group(1) if img else None,
        "has_faq": "faq-section" in html,
        "has_table": "analytics-table" in html,
        "has_cta": "sfera-form" in html,
        "internal_links": internal,
        "words": len(re.findall(r"\w+", re.sub(r"<[^>]+>", " ", body))),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="перепроверить все статьи")
    ap.add_argument("--log", default=None, help="файл лога (UTF-8)")
    args = ap.parse_args()

    original = logsetup.install(args.log)
    try:
        return _main(args)
    except Exception as e:  # noqa: BLE001
        print("ОШИБКА: %s" % e)
        return 1
    finally:
        logsetup.restore(original)


def _main(args) -> int:

    path = settings.path("registry")
    if not path.exists():
        print("реестр пуст — нечего проверять")
        return 0
    reg = json.loads(path.read_text(encoding="utf-8"))

    todo = [e for e in reg["published"]
            if args.all or (e.get("post_check") or {}).get("status") != 200]
    if not todo:
        print("все статьи уже проверены (%d)" % len(reg["published"]))
        return 0

    print("К проверке: %d" % len(todo))
    problems = []
    deferred = []
    for i, entry in enumerate(todo):
        if i:
            time.sleep(30)  # не злим анти-флуд
        res = check_url(entry["url"])
        entry["post_check"] = res
        if res.get("status") == 200:
            print("  OK  %-56s ссылок=%s слов=%s faq=%s таблица=%s cta=%s"
                  % (entry["url"], res.get("internal_links"), res.get("words"),
                     res.get("has_faq"), res.get("has_table"), res.get("has_cta")))
        elif res.get("status") == "deferred":
            deferred.append(entry["url"])
            print("  --- %-56s отложено (хостинг ограничил запросы)"
                  % entry["url"])
        else:
            print("  !!! %-56s HTTP %s" % (entry["url"], res.get("status")))
            problems.append("%s: HTTP %s" % (entry["url"], res.get("status")))

        if res.get("status") == 200:
            if res.get("internal_links", 0) < 3:
                problems.append("%s: внутренних ссылок %s" % (entry["url"], res.get("internal_links")))
            if not res.get("has_faq"):
                problems.append("%s: не найден FAQ" % entry["url"])
            if not res.get("has_table"):
                problems.append("%s: не найдена таблица" % entry["url"])
            if not res.get("image"):
                problems.append("%s: не найдена картинка" % entry["url"])

    path.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")

    if problems:
        print("\nПРОБЛЕМЫ:")
        for p in problems:
            print("  -", p)
        return 1
    if deferred:
        print("\nНе проверено (повторите запуск позже): %d" % len(deferred))
        return 2
    print("\nВсё в порядке.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
