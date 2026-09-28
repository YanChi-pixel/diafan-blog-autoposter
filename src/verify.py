"""Валидатор статьи перед публикацией.

Две группы проверок:
  * КОНТРАКТ — соответствие вёрстке сайта (жёстко, публикация блокируется);
  * AI-SEO   — чек-лист из исследования (часть блокирует, часть предупреждает).

Результат: (errors, warnings, stats). Публикуем только при пустом errors.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import settings

# --------------------------------------------------------------------------
# Разрешённая разметка — снята с реальной статьи сайта на Diafan.CMS
# --------------------------------------------------------------------------

ALLOWED_TAGS = {
    "p", "h2", "h3", "ul", "li", "strong", "table", "thead", "tbody",
    "tr", "th", "td", "div", "insert",
}

ALLOWED_CLASSES = {
    "analytics-table", "analytics-list", "analytics-list-item",
    "sfera-form sfera-wrap", "block-d__name", "faq-section", "faq-item",
    "faq-question", "faq-answer",
}

ALLOWED_ATTRS = {"class", "data-heading-tag", "name", "module", "template", "site_id", "href"}

FORBIDDEN_TAGS = {
    "h1", "h4", "h5", "h6", "a", "img", "span", "style", "script", "br", "hr",
    "blockquote", "em", "i", "b", "figure", "iframe", "form", "input", "button",
    "svg", "video", "section", "article", "header", "footer", "nav", "code", "pre",
}

# --------------------------------------------------------------------------
# Запрещённые формулировки (из исследования AI SEO)
# --------------------------------------------------------------------------

HEDGES = [
    "возможно,", "возможно ", "может быть", "как правило", "зачастую",
    "мы считаем", "в большинстве случаев", "некоторые эксперты",
    "по нашему мнению", "вероятно,", "скорее всего", "предположительно",
]

SUPERLATIVES = [
    "лучший", "лучшая", "лучшие", "самый выгодный", "уникальный", "уникальная",
    "выгоднее всех", "команда профессионалов", "гибкий подход",
    "широкий спектр услуг", "индивидуальный подход к каждому",
    "высококвалифицированные специалисты", "многолетний опыт",
    "на рынке уже более", "не имеет аналогов",
]

CLICHES = [
    "в современном мире", "не секрет, что", "стоит отметить", "важно понимать",
    "как известно", "давайте разберёмся", "давайте разберемся",
    "в условиях рыночной экономики", "ни для кого не секрет",
    "динамично развивающаяся", "играет важную роль",
]

BAD_H2 = [
    "введение", "заключение", "итоги", "итог", "общие сведения",
    "вместо заключения", "резюме", "вывод", "выводы", "заключительные мысли",
    "о чём статья", "о чем статья",
]

GENERIC_ANCHORS = {
    "здесь", "подробнее", "читать далее", "тут", "ссылка", "подробности",
    "узнать больше", "перейти", "сюда", "эта страница",
}


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors,
                "warnings": self.warnings, "stats": self.stats}


# --------------------------------------------------------------------------
# Утилиты
# --------------------------------------------------------------------------

def strip_tags(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&quot;", '"').replace("&amp;", "&")
    text = text.replace("&laquo;", "«").replace("&raquo;", "»").replace("&#039;", "'")
    return re.sub(r"\s+", " ", text).strip()


def words(html: str) -> list[str]:
    return re.findall(r"[А-Яа-яЁёA-Za-z0-9\-]+", strip_tags(html))


def h2_blocks(html: str) -> list[tuple[str, str]]:
    """[(заголовок, html блока)] — от каждого h2 до следующего h2."""
    parts = re.split(r"(?is)(?=<h2\b)", html)
    out = []
    for part in parts:
        m = re.match(r"(?is)<h2[^>]*>(.*?)</h2>", part)
        if m:
            out.append((strip_tags(m.group(1)), part))
    return out


def count_numbers(text: str) -> int:
    return len(re.findall(r"\d", text))


# --------------------------------------------------------------------------
# Проверки контракта
# --------------------------------------------------------------------------

def check_contract(html: str, r: Report, allow_links: bool = False) -> None:
    tags = re.findall(r"(?is)<(/?)([a-zA-Z0-9]+)([^>]*)>", html)

    allowed = set(ALLOWED_TAGS)
    if allow_links:
        allowed.add("a")

    for close, name, attrs in tags:
        low = name.lower()
        if low in FORBIDDEN_TAGS and not (allow_links and low == "a"):
            r.errors.append("запрещённый тег <%s>" % low)
        elif low not in allowed:
            r.errors.append("неизвестный тег <%s>" % low)

        for attr in re.findall(r'([a-zA-Z_\-]+)\s*=', attrs):
            a = attr.lower()
            if a.startswith("on"):
                r.errors.append("запрещён обработчик %s" % a)
            elif a not in ALLOWED_ATTRS:
                r.errors.append("запрещённый атрибут %s в <%s>" % (a, low))

        cls = re.search(r'class="([^"]*)"', attrs)
        if cls:
            value = re.sub(r"\s+", " ", cls.group(1).strip())
            if value not in ALLOWED_CLASSES:
                r.errors.append("запрещённый class=\"%s\"" % value)

    # баланс тегов
    stack = []
    for close, name, _ in tags:
        low = name.lower()
        if low in ("insert", "br", "img", "input", "hr"):
            continue
        if close:
            if stack and stack[-1] == low:
                stack.pop()
            else:
                r.errors.append("нарушен порядок закрытия тегов у </%s>" % low)
                break
        else:
            stack.append(low)
    if stack:
        r.errors.append("не закрыты теги: %s" % ", ".join(stack))

    # обязательные блоки
    if 'class="analytics-table"' not in html:
        r.errors.append("нет таблицы сравнения (table.analytics-table)")
    if 'class="analytics-list"' not in html:
        r.errors.append("нет списка (ul.analytics-list)")
    if 'class="faq-section"' not in html:
        r.errors.append("нет блока FAQ (div.faq-section)")
    if "sfera-form" not in html:
        r.errors.append("нет CTA-блока (div.sfera-form)")
    if "show_form" not in html or 'module="feedback"' not in html:
        r.errors.append("в CTA-блоке нет <insert name=\"show_form\" module=\"feedback\">")

    # CTA ровно один
    cta = html.count('class="sfera-form')
    if cta > 1:
        r.errors.append("CTA-блоков больше одного (%d)" % cta)

    # FAQ: количество вопросов и парность
    q = len(re.findall(r'class="faq-question"', html))
    a = len(re.findall(r'class="faq-answer"', html))
    if q != a:
        r.errors.append("в FAQ %d вопросов и %d ответов" % (q, a))
    if q < 5:
        r.errors.append("в FAQ меньше 5 вопросов (%d)" % q)
    if q > 8:
        r.warnings.append("в FAQ больше 8 вопросов (%d)" % q)

    # структура: лид до первого h2
    first_h2 = html.find("<h2")
    if first_h2 < 0:
        r.errors.append("в статье нет ни одного <h2>")
        return
    lead = html[:first_h2]
    lead_ps = re.findall(r"(?is)<p>(.*?)</p>", lead)
    if len(lead_ps) < 2:
        r.errors.append("лид должен состоять из 2 абзацев <p>, найдено %d" % len(lead_ps))


# --------------------------------------------------------------------------
# Проверки AI-SEO
# --------------------------------------------------------------------------

def check_ai_seo(article: dict, r: Report,
                 links_min: int = 3, links_max: int = 4) -> None:
    html = article.get("text", "")
    text = strip_tags(html)
    w = words(html)
    r.stats["words"] = len(w)

    cfg = article.get("_config", {})
    wmin = cfg.get("target_words_min", 1800)
    wmax = cfg.get("target_words_max", 2500)
    # недобор объёма блокирует публикацию: при переписывании по замечаниям
    # модель склонна сокращать текст, и качество статьи падает
    if len(w) < int(wmin * 0.9):
        r.errors.append("объём %d слов, минимум %d" % (len(w), int(wmin * 0.9)))
    elif len(w) < wmin:
        r.warnings.append("объём %d слов, чуть меньше целевого %d" % (len(w), wmin))
    if len(w) > wmax + 300:
        r.warnings.append("объём %d слов, заметно больше целевого максимума %d"
                          % (len(w), wmax))

    # метаданные
    name = article.get("name", "")
    tm = article.get("title_meta", "")
    ds = article.get("descr", "")
    an = article.get("anons", "")
    if not 35 <= len(name) <= 75:
        r.warnings.append("name %d знаков (норма 40-65): %s" % (len(name), name))
    if not 45 <= len(tm) <= 75:
        r.warnings.append("title_meta %d знаков (норма 50-65)" % len(tm))
    if not 120 <= len(ds) <= 180:
        r.warnings.append("descr %d знаков (норма 140-160)" % len(ds))
    if not 20 <= len(an) <= 80:
        r.warnings.append("anons %d знаков (норма 30-60)" % len(an))

    # заголовки
    blocks = h2_blocks(html)
    r.stats["h2_count"] = len(blocks)

    # контентные разделы = все, кроме FAQ и заключительного
    content_blocks = [
        (t, b) for t, b in blocks
        if "faq-section" not in b and "sfera-form" not in b
    ]
    if content_blocks and content_blocks[-1][0].strip().lower().rstrip(":.") in (
        "выводы и рекомендации", "заключение", "вывод", "итог", "итоги"
    ):
        content_blocks = content_blocks[:-1]
    r.stats["content_sections"] = len(content_blocks)

    # эталон сайта: 8 контентных разделов + FAQ + заключение = 10 <h2>
    # жёсткая граница только по краям: 10-11 разделов — не брак, а вопрос стиля
    if not 5 <= len(content_blocks) <= 12:
        r.errors.append("контентных разделов <h2> должно быть 5-12, найдено %d"
                        % len(content_blocks))
    elif len(content_blocks) > 9:
        r.warnings.append("контентных разделов %d — многовато, эталон сайта 8"
                          % len(content_blocks))
    if not content_blocks:
        r.errors.append("не найдено ни одного контентного раздела <h2>")

    for title, _ in blocks:
        if title.strip().lower().rstrip(":.") in BAD_H2:
            r.errors.append("запрещённый заголовок раздела: «%s»" % title)

    # числа в каждом разделе
    no_number = []
    for title, body in content_blocks:
        if not re.search(r"\d", strip_tags(body)):
            no_number.append(title)
    if no_number:
        r.errors.append("нет чисел в разделах: %s" % "; ".join(no_number[:4]))

    total_numbers = len(re.findall(r"\d+", text))
    r.stats["numbers"] = total_numbers
    if total_numbers < 8:
        r.errors.append("числовых фактов %d, нужно минимум 8" % total_numbers)

    # определения
    defs = len(re.findall(r"\s—\sэто\s", text))
    r.stats["definitions"] = defs
    if defs < 3:
        r.warnings.append("определений формата «X — это» только %d, нужно 3" % defs)

    # лид
    first_h2 = html.find("<h2")
    lead_ps = re.findall(r"(?is)<p>(.*?)</p>", html[:first_h2])
    if lead_ps:
        lead_words = len(words(lead_ps[0]))
        r.stats["lead_words"] = lead_words
        if not 40 <= lead_words <= 95:
            r.warnings.append("первый абзац лида %d слов (норма 50-80)" % lead_words)
        if not re.search(r"\d", strip_tags(lead_ps[0])):
            r.errors.append("в лиде нет числа — это ключевой фактор цитирования")

    # первый абзац под каждым h2
    short_lead = []
    for title, body in content_blocks:
        rest = re.sub(r"(?is)^\s*<h2[^>]*>.*?</h2>", "", body)
        ps = re.findall(r"(?is)<p>(.*?)</p>", rest)
        if ps and len(words(ps[0])) < 25:
            short_lead.append(title)
    if short_lead:
        r.warnings.append("короткий первый абзац в разделах: %s"
                          % "; ".join(short_lead[:3]))

    # запрещённые формулировки
    low = text.lower()
    for group, items, blocking in (
        ("хедж", HEDGES, False),
        ("рекламный штамп", SUPERLATIVES, False),
        ("клише", CLICHES, False),
    ):
        hits = [s for s in items if s in low]
        if hits:
            msg = "%s: %s" % (group, ", ".join(hits[:6]))
            (r.errors if blocking else r.warnings).append(msg)

    # FAQ-ответы
    answers = re.findall(r'(?is)class="faq-answer"[^>]*>(.*?)</div>', html)
    long_a, short_a = [], []
    for a in answers:
        n = len(words(a))
        if n > 95:
            long_a.append(n)
        elif n < 25:
            short_a.append(n)
    if long_a:
        r.warnings.append("длинные ответы FAQ (>95 слов): %s" % long_a)
    if short_a:
        r.warnings.append("короткие ответы FAQ (<25 слов): %s" % short_a)

    # ссылки
    anchors = re.findall(r'(?is)<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html)
    internal = [(h, strip_tags(t)) for h, t in anchors
                if h.startswith("http") and settings.site_host() in h or h.startswith("/")]
    r.stats["internal_links"] = len(internal)
    if internal and not (links_min <= len(internal) <= links_max):
        r.errors.append("внутренних ссылок %d, нужно %d-%d"
                        % (len(internal), links_min, links_max))
    if links_min <= len(internal) < cfg.get("internal_links_target", 3):
        r.warnings.append(
            "внутренних ссылок %d — мало, цель %d"
            % (len(internal), cfg.get("internal_links_target", 3)))

    # распределение ссылок по разделам
    if internal:
        positions = []
        for h, _ in internal:
            idx = html.find('href="%s"' % h)
            positions.append(idx)
        section_of = []
        for pos in positions:
            count = html[:pos].count("<h2")
            section_of.append(count)
        dupes = {s for s in section_of if section_of.count(s) > 1}
        if dupes:
            r.errors.append("несколько ссылок в одном разделе — нужно по одной в разных")
        r.stats["link_sections"] = section_of

        for _, anchor in internal:
            a = anchor.strip().lower()
            if a in GENERIC_ANCHORS:
                r.errors.append("неинформативный анкор: «%s»" % anchor)
            elif len(words(anchor)) < 2:
                r.errors.append("однословный анкор: «%s»" % anchor)
            elif len(words(anchor)) > 6:
                r.warnings.append("длинный анкор: «%s»" % anchor)


# --------------------------------------------------------------------------
# Вход
# --------------------------------------------------------------------------

def verify(article: dict, stage: str = "draft") -> Report:
    """stage='draft' — ссылок быть не должно; stage='final' — должны быть."""
    r = Report()
    html = article.get("text", "")
    if not html:
        r.errors.append("пустое поле text")
        return r
    final = stage == "final"
    check_contract(html, r, allow_links=final)
    cfg = article.get("_config") or {}
    check_ai_seo(article, r,
                 links_min=cfg.get("internal_links_min", 3),
                 links_max=cfg.get("internal_links_max", 4))
    if not final and r.stats.get("internal_links"):
        r.errors.append("в черновике не должно быть ссылок — их ставит linker")
    if final and not r.stats.get("internal_links"):
        r.errors.append("ссылки не расставлены (запусти linker)")
    return r


if __name__ == "__main__":
    import json
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if not src:
        print("использование: python verify.py <article.json>")
        raise SystemExit(2)
    data = json.loads(open(src, encoding="utf-8").read())
    rep = verify(data)
    print("OK" if rep.ok else "ЕСТЬ ОШИБКИ")
    for e in rep.errors:
        print("  ОШИБКА:", e)
    for w in rep.warnings:
        print("  предупреждение:", w)
    print("  статистика:", json.dumps(rep.stats, ensure_ascii=False))
