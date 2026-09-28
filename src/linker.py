"""Детерминированная перелинковка.

Правила (по требованию заказчика и по чек-листу AI SEO):
  * не больше 4 внутренних ссылок на статью;
  * каждая ссылка — в СВОЁМ разделе <h2>, по одной на раздел;
  * только в разных частях статьи: не в лиде, не в таблице, не в FAQ, не в CTA;
  * анкор — описательная группа 2–5 слов, вплетённая в существующую фразу;
  * минимум одна ссылка ведёт на коммерческую страницу услуги, а не на блог.

Морфология: анкор ищется по основам слов, поэтому «услуги грузчиков» найдёт
и «услугам грузчиков», и «услуги грузчика».
"""
from __future__ import annotations

import re

LINK_RE = re.compile(r'(?is)<a\b[^>]*>.*?</a>')


def _stem(word: str, size: int = 5) -> str:
    w = word.lower().replace("ё", "е")
    if len(w) <= 3:
        return re.escape(w)
    return re.escape(w[:min(size, len(w) - 1)])


FUNCTION_WORDS = {
    "и", "в", "во", "на", "с", "со", "по", "для", "от", "до", "при", "из",
    "за", "над", "под", "без", "про", "или", "а", "но", "не", "же", "ли",
}

# Слова, которые сами по себе не определяют раздел. Анкор, состоящий только
# из них, не годится для мягкого поиска: «аренда персонала» нельзя привязать
# к конкретной услуге.
GENERIC_TOKENS = {
    "аренда", "аренды", "арендой", "аутсорсинг", "аутсорсинга", "услуга",
    "услуги", "услуг", "персонал", "персонала", "персоналу", "компания",
    "работа", "работы", "заказчик", "заказчика", "сотрудник", "сотрудники",
    "специалист", "специалисты", "предприятие", "производство", "бизнес",
}


def _content_words(anchor: str) -> list[str]:
    """Значимые слова анкора.

    Делим ТОЛЬКО по пробелам: дефис — часть слова, иначе «ит-персонала»
    распадается на «ит» + «персонала» и мягкий поиск начнёт привязывать
    обычный персонал к странице ИТ-услуг.
    """
    return [w for w in anchor.strip().lower().split()
            if w and w not in FUNCTION_WORDS and len(w) > 2]


def _has_distinctive(words: list[str]) -> bool:
    """Есть ли в анкоре слово, отличающее его от родового понятия."""
    return any(w not in GENERIC_TOKENS for w in words)


def anchor_patterns(anchor: str) -> list[re.Pattern]:
    """Шаблоны поиска анкора — от строгого к мягкому.

    1. Все слова по порядку, вплотную: «услуги грузчиков».
    2. Значимые слова по порядку с пропусками до 3 слов:
       «персонал на производство» найдёт «персонал для производства».
    3. Значимые слова в обратном порядке (для двухсловных анкоров):
       «производственный персонал».

    Мягкие шаблоны (2 и 3) применяются, только если в анкоре есть
    различающее слово — иначе рискуем связать родовую фразу с частной услугой.
    """
    parts = [p for p in anchor.strip().lower().split() if p]
    if not parts:
        raise ValueError("пустой анкор")

    patterns = []
    strict = r"\b" + r"[\s\-]+".join(_stem(p) + r"[а-яёa-z]*" for p in parts) + r"\b"
    patterns.append(re.compile(strict, re.IGNORECASE))

    content = _content_words(anchor)
    if len(content) >= 2 and _has_distinctive(content):
        gap = r"(?:\s+[а-яёa-z0-9\-]+){0,3}\s+"
        relaxed = r"\b" + gap.join(_stem(p) + r"[а-яёa-z]*" for p in content) + r"\b"
        patterns.append(re.compile(relaxed, re.IGNORECASE))

        if len(content) == 2:
            rev = (r"\b" + _stem(content[1]) + r"[а-яёa-z]*"
                   + r"(?:\s+[а-яёa-z0-9\-]+){0,2}\s+"
                   + _stem(content[0]) + r"[а-яёa-z]*\b")
            patterns.append(re.compile(rev, re.IGNORECASE))

    return patterns


def anchor_regex(anchor: str) -> re.Pattern:
    """Строгий шаблон (оставлен для обратной совместимости)."""
    return anchor_patterns(anchor)[0]


def _inside_tag(html: str, pos: int) -> bool:
    """Позиция внутри <...>?"""
    last_open = html.rfind("<", 0, pos)
    last_close = html.rfind(">", 0, pos)
    return last_open > last_close


def _already_linked(html: str, spans: list[tuple[int, int]], pos: int, end: int) -> bool:
    for s, e in spans:
        if pos < e and end > s:
            return True
    return False


def linked_spans(html: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in LINK_RE.finditer(html)]


def _find_phrase(section: str, anchor: str) -> tuple[int, int] | None:
    """Вхождение анкора в секцию (вне тегов и вне ссылок).

    Перебирает шаблоны от строгого к мягкому: сначала ищем точную
    формулировку, и только если её нет — более свободную.
    """
    spans = linked_spans(section)
    try:
        patterns = anchor_patterns(anchor)
    except ValueError:
        return None

    for rx in patterns:
        for m in rx.finditer(section):
            s, e = m.span()
            if _inside_tag(section, s) or _inside_tag(section, e - 1):
                continue
            if _already_linked(section, spans, s, e):
                continue
            phrase = section[s:e]
            # анкор не должен переходить через границу предложения
            if re.search(r"[.!?;:]", phrase):
                continue
            # и должен укладываться в 2-6 слов
            if not 2 <= len(re.findall(r"[А-Яа-яЁёA-Za-z0-9\-]+", phrase)) <= 6:
                continue
            return s, e
    return None


def split_sections(html: str) -> list[dict]:
    """Разбивает статью на лид и секции по <h2>."""
    parts = re.split(r"(?is)(?=<h2\b)", html)
    out = []
    for i, part in enumerate(parts):
        if not part.strip():
            continue
        title = ""
        m = re.match(r"(?is)<h2[^>]*>(.*?)</h2>", part)
        if m:
            title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        out.append({
            "index": i,
            "is_lead": m is None,
            "is_faq": "faq-section" in part,
            "is_cta": "sfera-form" in part,
            "title": title,
            "html": part,
        })
    return out


def insert_links(html: str, pages: list[dict], preferred_paths: list[str] | None = None,
                 max_links: int = 4, min_links: int = 3) -> tuple[str, list[dict]]:
    """Расставляет ссылки. Возвращает (html, список поставленных ссылок)."""
    sections = split_sections(html)
    preferred = list(preferred_paths or [])
    used_paths: set[str] = set()
    placed: list[dict] = []

    # порядок обхода: сначала предпочтительные разделы в их порядке в статье
    candidates = [s for s in sections
                  if not s["is_lead"] and not s["is_faq"] and not s["is_cta"]]

    def pick_page(section_html: str) -> tuple[dict, tuple[int, int]] | None:
        best = None
        # приоритет: страницы, предложенные писателю; затем остальные
        ordered = ([p for p in pages if p["path"] in preferred] +
                   [p for p in pages if p["path"] not in preferred])
        for page in ordered:
            if page["path"] in used_paths:
                continue
            for anchor in page.get("anchors", []):
                found = _find_phrase(section_html, anchor)
                if found is None:
                    continue
                score = 0
                if page["path"] in preferred:
                    score += 100
                if not page.get("is_hub"):
                    score += 20
                score += len(anchor.split())
                if best is None or score > best[0]:
                    best = (score, page, found)
            if best:
                break
        if best is None:
            return None
        return best[1], best[2]

    for section in candidates:
        if len(placed) >= max_links:
            break
        if LINK_RE.search(section["html"]):
            continue  # в разделе уже есть ссылка — по одной на раздел
        picked = pick_page(section["html"])
        if picked is None:
            continue
        page, (s, e) = picked
        phrase = section["html"][s:e]
        link = '<a href="%s">%s</a>' % (page["url"], phrase)
        section["html"] = section["html"][:s] + link + section["html"][e:]
        used_paths.add(page["path"])
        placed.append({
            "url": page["url"],
            "anchor": phrase,
            "section": section["title"],
        })

    result = "".join(s["html"] for s in sections)
    return result, placed


def link_article(article: dict, pages: list[dict],
                 preferred_paths: list[str] | None = None,
                 max_links: int = 4, min_links: int = 3) -> dict:
    """Мутирует копию article: ставит ссылки в text, пишет отчёт в _links."""
    html, placed = insert_links(article["text"], pages,
                                preferred_paths=preferred_paths,
                                max_links=max_links, min_links=min_links)
    article = dict(article)
    article["text"] = html
    article["_links"] = placed
    article["_links_ok"] = len(placed) >= min_links
    return article


if __name__ == "__main__":
    import json
    import sys

    sys.path.insert(0, ".")
    import settings

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    art = json.loads((settings.ROOT / "output" / "test_article.json").read_text(encoding="utf-8"))
    links = json.loads(settings.path("internal_links").read_text(encoding="utf-8"))
    art = link_article(art, links["pages"])
    print("Поставлено ссылок: %d" % len(art["_links"]))
    for link in art["_links"]:
        print("   [%s]  %-34s -> %s" % (link["section"][:32], link["anchor"], link["url"]))
