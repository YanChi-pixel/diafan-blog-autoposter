"""Каталог сайта: разделы для перелинковки и существующие статьи.

Источник данных — таблица `diafan_rewrite` на сайте (через publisher.php).
Результат:
  data/internal_links.json — whitelist разделов с анкорами для linker.py
  data/catalog.json        — существующие статьи (антидубль + «читать также»)
"""
from __future__ import annotations

import json
import re
import sys

import diafan
import settings

# Служебные страницы и мусор — в перелинковку не попадают
EXCLUDE_REWRITES = {
    "", "useful", "user", "privacy", "map", "search", "feedback", "settings",
    "registration", "reminding", "anketa", "voprosy", "zayavki", "konsultatsii",
    "zakazat-zvonok", "anketa-spetsialista", "novaya-glavnaya", "clauses",
    "blog", "calc", "news",
}

# Разделы-хабы: ссылаться на них можно, но приоритет ниже, чем у услуг
HUB_REWRITES = {
    "personal-na-proizvodstvo", "logisticheskie-uslugi",
    "personal-na-stroitelnye-ob-ekty", "obsluzhivayushchij-personal",
    "autstaffing-personala", "b2b", "rabota", "personal-v-torgovye-seti",
    "personal-na-meropriyatie", "autsorsing-proizvodstva", "contact",
}


def normalize(title: str) -> str:
    """Нормализация заголовка для сравнения на дубли."""
    t = title.lower().replace("ё", "е")
    t = re.sub(r"[^а-яa-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def anchor_variants(title: str) -> list[str]:
    """Анкоры, которыми раздел естественно называть в тексте."""
    t = title.strip()
    low = t.lower()
    out = [low]

    # «Услуги грузчиков» -> «услуги грузчиков», «аренда грузчиков»
    m = re.match(r"^услуги\s+(.+)$", low)
    if m:
        out += ["услуги " + m.group(1), "аренда " + m.group(1)]
    m = re.match(r"^аутсорсинг\s+(.+)$", low)
    if m:
        out += ["аутсорсинг " + m.group(1), "услуги " + m.group(1)]
    m = re.match(r"^аренда\s+(.+)$", low)
    if m:
        out += ["аренда " + m.group(1), "услуги " + m.group(1)]
    m = re.match(r"^бригада\s+(.+)$", low)
    if m:
        out += ["бригада " + m.group(1), "услуги " + m.group(1)]
    m = re.match(r"^работа\s+(.+)$", low)
    if m:
        out += ["работа " + m.group(1)]

    # убираем описательные хвосты вроде «в Москве»
    for base in list(out):
        trimmed = re.sub(r"\s+в\s+москве$", "", base)
        if trimmed != base and len(trimmed.split()) >= 2:
            out.append(trimmed)

    seen, uniq = set(), []
    for a in out:
        a = re.sub(r"\s+", " ", a).strip()
        if len(a.split()) >= 2 and a not in seen:
            seen.add(a)
            uniq.append(a)
    return uniq


def clean_title(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("Загрузка карты ссылок с сайта ...")
    data = diafan._request("GET", "links")
    rows = data["links"]
    print("  записей: %d" % len(rows))

    # --- разделы сайта ---
    # ЧПУ статей блога: их нельзя брать как «раздел» для перелинковки
    news_prefixes = {
        (r["rewrite"] or "").strip().strip("/")
        for r in rows if r["module_name"] == "news"
    }

    pages = []
    for r in rows:
        if r["module_name"] != "site":
            continue
        rewrite = (r["rewrite"] or "").strip().strip("/")
        if rewrite in EXCLUDE_REWRITES or rewrite.startswith("/"):
            continue
        if "test" in rewrite.lower():
            continue
        # legacy-страницы, чей адрес совпадает с адресом статьи блога
        if rewrite in news_prefixes or rewrite.startswith("news/"):
            continue
        title = clean_title(r.get("name1") or "")
        if not title:
            continue
        anchors = anchor_variants(title)
        if not anchors:
            continue
        pages.append({
            "url": settings.env("SITE_URL").rstrip("/") + "/" + rewrite,
            "path": rewrite,
            "element_id": int(r["element_id"]),
            "title": title,
            "anchors": anchors,
            "is_hub": rewrite in HUB_REWRITES,
        })

    # дедуп по URL (в таблице есть дубли rewrite)
    seen, uniq_pages = set(), []
    for p in pages:
        if p["url"] in seen:
            continue
        seen.add(p["url"])
        uniq_pages.append(p)
    uniq_pages.sort(key=lambda p: (p["is_hub"], p["title"]))

    # --- существующие статьи ---
    news = []
    orphans = []
    for r in rows:
        if r["module_name"] != "news":
            continue
        rewrite = (r["rewrite"] or "").strip().strip("/")
        if not rewrite or "test" in rewrite.lower():
            continue
        title = clean_title(r.get("name1") or "")
        if not title:
            # ЧПУ без живой новости — «осиротевшая» запись, в каталог не берём
            orphans.append(rewrite)
            continue
        news.append({
            "url": settings.env("SITE_URL").rstrip("/") + "/" + rewrite,
            "path": rewrite,
            "slug": rewrite.rsplit("/", 1)[-1],
            "element_id": int(r["element_id"]),
            "title": title,
            "normalized_title": normalize(title),
        })

    news.sort(key=lambda n: n["element_id"], reverse=True)

    links_path = settings.path("internal_links")
    catalog_path = settings.path("catalog")
    links_path.write_text(
        json.dumps({"pages": uniq_pages}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    catalog_path.write_text(
        json.dumps({"news": news, "pages_count": len(uniq_pages),
                    "orphan_rewrites": orphans},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\nРазделов для перелинковки: %d" % len(uniq_pages))
    print("  хабы: %d, услуги: %d"
          % (sum(1 for p in uniq_pages if p["is_hub"]),
             sum(1 for p in uniq_pages if not p["is_hub"])))
    print("Статей в блоге: %d" % len(news))
    if orphans:
        print("Осиротевших ЧПУ (в каталог не вошли): %d — %s"
              % (len(orphans), ", ".join(orphans[:6])))
    print("\nПримеры:")
    for p in uniq_pages[:8]:
        print("  %-58s %s" % (p["title"][:56], p["anchors"][:3]))
    print("\nЗаписано:")
    print("  ", links_path)
    print("  ", catalog_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
