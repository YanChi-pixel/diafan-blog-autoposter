"""Оркестратор одной статьи.

Полный цикл:
    тема -> LLM -> проверка черновика -> перелинковка -> финальная проверка
         -> обложка -> ЧПУ -> публикация -> пост-проверка -> отчёты

Идемпотентность: тема удаляется из очереди ТОЛЬКО после успешной публикации,
каждая статья имеет external_id, повторный запуск не создаёт дубль.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime

import diafan
import dupes
import images
import linker
import logsetup
import recrawl
import settings
import slug as slug_mod
import verify
import writer

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SITE_ID = int(settings.load_config()["site"]["news_site_id"])   # раздел сайта с блогом
CAT_ID = 0       # категории у модуля новостей не используются
MAX_GEN_ATTEMPTS = 5   # попытки генерации с точечными правками по замечаниям


# --------------------------------------------------------------------------
# Данные
# --------------------------------------------------------------------------

def load_json(path, default):
    p = settings.ROOT / path if not str(path).startswith(str(settings.ROOT)) else path
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def load_queue() -> list[str]:
    p = settings.path("themes")
    if not p.exists():
        return []
    lines = [line.strip() for line in p.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def save_queue(topics: list[str]) -> None:
    settings.path("themes").write_text("\n".join(topics) + "\n", encoding="utf-8")


def normalize(title: str) -> str:
    t = title.lower().replace("ё", "е")
    t = re.sub(r"[^а-яa-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_duplicate(topic: str, news: list[dict]) -> str | None:
    """Дубль темы среди существующих статей (см. src/dupes.py)."""
    titles = [n.get("title") or "" for n in news]
    title = dupes.is_duplicate(topic, titles)
    if not title:
        # работающие статьи из реестра тоже считаем написанными
        reg_titles = [e.get("name") or "" for e in
                      load_json(settings.path("registry"), {"published": []})["published"]]
        title = dupes.is_duplicate(topic, reg_titles)
    return title


# --------------------------------------------------------------------------
# Основной цикл
# --------------------------------------------------------------------------

def run_one(topic: str | None = None, publish: bool = True,
            dry_run: bool = False, provider: str | None = None) -> dict:
    cfg = settings.load_config()
    links_data = load_json(settings.path("internal_links"), {"pages": []})
    catalog = load_json(settings.path("catalog"), {"news": []})
    registry = load_json(settings.path("registry"), {"published": []})
    facts = load_json(settings.data_dir() / "facts.json", {})

    pages = links_data["pages"]
    news = catalog["news"]
    queue = load_queue()

    if topic is None:
        if not queue:
            raise RuntimeError("очередь тем пуста — заполните data/themes.txt "
                               "или запустите: python src/topics.py")
        topic = queue[0]
        from_queue = True
    else:
        from_queue = False

    if from_queue and len(queue) < 10:
        print("! ВНИМАНИЕ: в очереди осталось %d тем (~%d дней). "
              "Пополните: python src/topics.py" % (len(queue), len(queue) // 2))

    print("=" * 74)
    print("ТЕМА: %s" % topic)
    print("=" * 74)

    dup = is_duplicate(topic, news)
    if dup:
        raise RuntimeError("тема дублирует существующую статью: «%s»" % dup)

    # ---- 1. генерация ----
    targets = writer.select_targets(topic, pages)
    preferred = [p["path"] for p in targets]
    print("\n[1/7] Генерация статьи (DeepSeek)... целевых разделов: %d" % len(targets))

    article = None
    # ---- 1-4. генерация -> черновик -> перелинковка -> финал ----
    # Всё в одном цикле: если анкоров для ссылок не хватило, статья
    # перегенерируется с прямым указанием, какие формулировки употребить.
    anchor_hint = "; ".join(a for p in targets for a in p["anchors"][:2])
    link_target = cfg["content"].get("internal_links_target",
                                     cfg["content"]["internal_links_min"])
    link_min = cfg["content"]["internal_links_min"]
    link_max = cfg["content"]["internal_links_max"]
    # напоминание про объём добавляется к ЛЮБОЙ правке: при переписывании
    # по замечаниям модель склонна сокращать текст
    # Обязательный набор повторяется в каждой правке: иначе модель, исправляя
    # одно замечание, «забывает» другое требование и попытки уходят в цикл.
    volume_note = (
        "- Сохрани объём основного текста в пределах %d–%d слов. "
        "При переписывании он не должен уменьшаться.\n"
        "- Перед отправкой проверь ОБЯЗАТЕЛЬНЫЙ набор целиком: "
        "таблица <table class=\"analytics-table\"> — 1 шт.; "
        "список <ul class=\"analytics-list\"> с 3–7 пунктами — 1 шт.; "
        "CTA-блок sfera-form — 1 шт.; FAQ из 5–8 вопросов; "
        "контентных разделов <h2> — 5–9."
        % (cfg["content"]["target_words_min"], cfg["content"]["target_words_max"])
    )
    correction = None
    previous = None
    stalled = False
    rep = None
    article = None
    for attempt in range(1, MAX_GEN_ATTEMPTS + 1):
        print("\n[1/7] Генерация статьи (DeepSeek), попытка %d из %d ..."
              % (attempt, MAX_GEN_ATTEMPTS))
        if correction:
            for line in correction.splitlines()[:8]:
                print("          · %s" % line.lstrip("- "))

        # Если точечные правки перестали менять текст — переходим
        # к полной перегенерации: модель зациклилась на минимальных
        # изменениях и не выполняет требование.
        article = writer.write_article(topic, targets, writer.select_related(news),
                                       facts, provider=provider,
                                       correction=correction,
                                       previous=None if stalled else previous)
        article["_topic"] = topic
        article["_targets"] = preferred
        article["_config"] = cfg["content"]
        article["_attempt"] = attempt
        article["_mode"] = "перегенерация" if stalled else (
            "правка" if previous else "с нуля")
        print("        режим: %s" % article["_mode"])
        print("        name: %s" % article["name"])
        print("        объём: %d слов" % len(verify.words(article["text"])))

        # ---- 2. проверка черновика ----
        rep = verify.verify(article, stage="draft")
        print("        черновик: %s" % report_line(rep).strip())
        if not rep.ok:
            stalled = _is_stalled(previous, article)
            correction = volume_note + "\n" + "\n".join("- " + e for e in rep.errors)
            previous = article
            continue

        # версия без ссылок: её отправляем модели на точечную правку
        clean = dict(article)

        # ---- 3. перелинковка ----
        article = linker.link_article(
            article, pages, preferred_paths=preferred,
            max_links=link_max, min_links=link_target,
        )
        print("        ссылок: %d (цель %d, минимум %d)"
              % (len(article["_links"]), link_target, link_min))
        for link in article["_links"]:
            print("          [%s] %s -> %s"
                  % (link["section"][:32], link["anchor"], link["url"]))

        if len(article["_links"]) < link_target:
            stalled = _is_stalled(previous, clean)
            correction = volume_note + (
                "\n- в статье не хватает внутренних ссылок: сейчас %d, нужно %d.\n"
                "- Это ОБЯЗАТЕЛЬНОЕ требование. Найди в тексте место и добавь "
                "недостающие упоминания, сохранив смысл абзацев.\n"
                "- Употреби в РАЗНЫХ разделах <h2> такие формулировки "
                "(дословно, внутри обычного рассуждения, не списком): %s."
                % (len(article["_links"]), link_target, anchor_hint)
            )
            previous = clean
            continue

        # ---- 4. финальная проверка ----
        rep = verify.verify(article, stage="final")
        print("        финал: %s" % report_line(rep).strip())
        if not rep.ok:
            stalled = _is_stalled(previous, clean)
            correction = volume_note + "\n" + "\n".join("- " + e for e in rep.errors)
            previous = clean
            continue

        break
    else:
        return fail(article, topic, rep,
                    "статья не прошла проверку за %d попыток" % MAX_GEN_ATTEMPTS)

    # ---- 5. обложка ----
    print("\n[5/7] Обложка 800x510...")
    cover, cover_meta = images.make_cover(article["name"], topic)
    if cover_meta.get("manual"):
        print("        автоподбор отключён — ставлю фирменную заглушку")
        print("        свою картинку прикрепите после публикации:")
    else:
        print("        источник: %s (запрос: «%s»), %d байт"
              % (cover_meta["provider"], cover_meta.get("query"), len(cover)))

    # ---- 6. ЧПУ ----
    taken = {n["slug"] for n in news} | {r.get("slug") for r in registry["published"]}
    style = cfg.get("slug_style", "short")
    slug = slug_mod.make_slug(article["name"] or topic, taken, style)
    print("\n[6/7] ЧПУ: /news/%s (стиль: %s)" % (slug, style))

    external_id = hashlib.sha1(
        ("%s|%s" % (normalize(topic), slug)).encode("utf-8")).hexdigest()[:16]
    article["_slug"] = slug
    article["_external_id"] = external_id

    # ---- 7. публикация ----
    payload = {
        "external_id": external_id,
        "slug": slug,
        "name": article["name"],
        "anons": article["anons"],
        "text": article["text"],
        "title_meta": article["title_meta"],
        "descr": article["descr"],
        "keywords": article["keywords"],
        "cat_id": CAT_ID,
        "site_id": SITE_ID,
        "act": 1,
        "created": int(time.time()),
        "image_base64": __import__("base64").b64encode(cover).decode("ascii"),
        "image_alt": article["name"],
    }

    if not publish:
        print("\n[7/7] Публикация отключена (--no-publish). Артефакты сохранены.")
        job = save_job(article, cover, cover_meta, rep, slug, external_id)
        return {"ok": True, "published": False, "job": str(job), "slug": slug}

    if dry_run:
        payload["dry_run"] = True
    print("\n[7/7] Публикация%s..." % (" (dry-run)" if dry_run else ""))
    result = diafan.publish(payload)
    print("        ответ: %s" % json.dumps(result, ensure_ascii=False)[:400])
    if not result.get("ok"):
        return fail(article, topic, None, "публикатор вернул ошибку: %s" % result)
    if result.get("skipped"):
        print("        статья уже была опубликована — пропуск")
        return {"ok": True, "published": False, "duplicate": True}

    if dry_run:
        job = save_job(article, cover, cover_meta, rep, slug, external_id)
        return {"ok": True, "published": False, "dry_run": True, "job": str(job)}

    # ---- пост-проверка ----
    url = result.get("url")
    post = post_check(url)
    print("        пост-проверка: %s" % json.dumps(post, ensure_ascii=False)[:300])

    # ---- переобход в Яндексе ----
    # Не фатально: если Вебмастер недоступен или исчерпана квота, статья
    # всё равно опубликована, а ссылку можно отправить позже командой
    # python src\recrawl.py --pending
    recrawl_at = None
    if url:
        if recrawl.submit_quiet([url]):
            recrawl_at = datetime.now().isoformat(timespec="seconds")

    # ---- регистрация ----
    registry["published"].append({
        "external_id": external_id,
        "topic": topic,
        "name": article["name"],
        "slug": slug,
        "url": url,
        "id": result.get("id"),
        "published_at": datetime.now().isoformat(timespec="seconds"),
        "image_provider": cover_meta["provider"],
        "image_query": cover_meta["query"],
        "links": article["_links"],
        "stats": rep.stats,
        "post_check": post,
        "recrawl_at": recrawl_at,
    })
    settings.path("registry").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    # каталог пополняем сразу — чтобы следующая статья не сослалась на несуществующее
    news.append({"url": url, "path": "news/" + slug, "slug": slug,
                 "element_id": result.get("id"), "title": article["name"],
                 "normalized_title": normalize(article["name"])})
    settings.path("catalog").write_text(
        json.dumps({"news": news, "pages_count": len(pages)}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    # тема уходит из очереди только после успеха
    if from_queue and topic in queue:
        queue.remove(topic)
        save_queue(queue)

    job = save_job(article, cover, cover_meta, rep, slug, external_id, url)
    print("\nГОТОВО: %s" % url)
    if cover_meta.get("manual"):
        print("Обложка — заглушка. Прикрепить свою картинку:")
        print("  python src\\set_cover.py --id %s --file \"путь\\к\\картинке.png\""
              % result.get("id"))
    print("Артефакты: %s" % job)
    return {"ok": True, "published": True, "url": url, "id": result.get("id"),
            "slug": slug, "job": str(job)}


# --------------------------------------------------------------------------
# Вспомогательное
# --------------------------------------------------------------------------

def report_line(rep) -> str:
    if rep.ok:
        base = "        OK"
    else:
        base = "        ОШИБКИ: %s" % "; ".join(rep.errors[:6])
    if rep.warnings:
        base += " | предупреждения: %s" % "; ".join(rep.warnings[:4])
    return base


def _is_stalled(previous: dict | None, current: dict) -> bool:
    """Похоже ли, что точечные правки перестали менять статью.

    Если модель возвращает почти тот же текст, дальше просить её
    «исправить замечания» бесполезно — нужно перегенерировать с нуля.
    """
    if not previous:
        return False
    a = verify.strip_tags(previous.get("text", ""))
    b = verify.strip_tags(current.get("text", ""))
    if not a or not b:
        return False
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio() >= 0.95


def fail(article, topic, rep, message) -> dict:
    print("\nОСТАНОВ: %s" % message)
    if rep:
        for e in rep.errors:
            print("   - %s" % e)
    job = save_job(article, None, {}, rep, article.get("_slug"), article.get("_external_id"))
    return {"ok": False, "error": message, "job": str(job)}


def post_check(url: str, delay: int = 45) -> dict:
    """Проверяем, что страница живая.

    Хостинг блокирует IP после нескольких запросов подряд, а публикация —
    это уже один запрос. Поэтому: одна пауза, одна попытка, и при блокировке
    проверка откладывается (не фатально). Догоняем командой check.py.
    """
    import requests
    time.sleep(delay)
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            html = r.text
            h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", html)
            img = re.search(r'<img src="([^"]*userfls/news[^"]*)"', html)
            return {
                "status": 200,
                "h1": re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else None,
                "image": img.group(1) if img else None,
                "has_faq": "faq-section" in html,
                "has_table": "analytics-table" in html,
                "checked_at": datetime.now().isoformat(timespec="seconds"),
            }
        return {"status": r.status_code, "deferred": True,
                "note": "проверить позже командой check.py"}
    except Exception as e:  # noqa: BLE001
        return {"status": "deferred", "error": str(e)[:140],
                "note": "хостинг ограничил запросы; проверить позже командой check.py"}


def save_job(article, cover, cover_meta, rep, slug, external_id, url=None):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    job = settings.ROOT / settings.load_config()["paths"]["jobs_dir"] / (
        "%s-%s" % (stamp, slug or "draft"))
    job.mkdir(parents=True, exist_ok=True)

    (job / "article.json").write_text(
        json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
    if cover:
        (job / "cover.jpg").write_bytes(cover)
    (job / "report.json").write_text(json.dumps({
        "slug": slug, "external_id": external_id, "url": url,
        "image": cover_meta,
        "verify": rep.to_dict() if rep else None,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (job / "preview.html").write_text(
        render_preview(article, cover), encoding="utf-8")
    return job


def render_preview(article: dict, cover: bytes | None) -> str:
    """Локальный предпросмотр: структура как на сайте.

    Своя таблица стилей сайта подключается, если в config.json задан
    site.preview_css (ссылка на собранный CSS сайта).
    """
    css = settings.load_config()["site"].get("preview_css") or ""
    css_tag = ('<link rel="stylesheet" href="%s">' % css) if css else ""
    img = ""
    if cover:
        img = ('<div class="_images"><a href="cover.jpg">'
               '<img src="cover.jpg" width="800" height="510" alt="%s" title="%s">'
               '</a></div>' % (article["name"], article["name"]))
    return """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>%s</title>
%s
<style>body{max-width:900px;margin:0 auto;padding:24px;font-family:system-ui,sans-serif}
._text img{max-width:100%%}.badge{background:#eef;padding:6px 10px;border-radius:6px;
font:13px/1.4 monospace;margin-bottom:16px;display:inline-block}
table.analytics-table{border-collapse:collapse;width:100%%}
table.analytics-table th,table.analytics-table td{border:1px solid #ccc;padding:8px}
.faq-question{font-weight:700}.faq-item{margin:12px 0}</style>
</head><body>
<div class="badge">ПРЕДПРОСМОТР · %s · %d слов</div>
<h1>%s</h1>
<p>%s</p>
<section class="section-d section-d_id section-d_news section-d_news_id">
<div class="date-d">%s</div>
<div class="_text">%s</div>
%s
</section>
</body></html>""" % (
        article["name"], css_tag, article.get("_topic", ""),
        article.get("_stats_words", 0),
        article["name"], article.get("anons", ""),
        datetime.now().strftime("%d.%m.%Y"),
        article["text"], img)


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Одна статья: генерация и публикация")
    ap.add_argument("topic", nargs="?", help="тема; без неё берётся первая из очереди")
    ap.add_argument("--no-publish", action="store_true", help="только сгенерировать")
    ap.add_argument("--dry-run", action="store_true", help="проверить публикатор без записи")
    ap.add_argument("--provider", choices=["deepseek", "ollama"], default=None)
    ap.add_argument("--log", default=None, help="файл лога (UTF-8); дублирует вывод")
    args = ap.parse_args()

    original_stdout = logsetup.install(args.log)

    try:
        res = run_one(topic=args.topic, publish=not args.no_publish,
                      dry_run=args.dry_run, provider=args.provider)
    except Exception as e:  # noqa: BLE001
        print("\nОШИБКА: %s" % e)
        import traceback
        traceback.print_exc(file=sys.stdout)
        res = {"ok": False}
    finally:
        logsetup.restore(original_stdout)
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
