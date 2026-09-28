"""Генерация ЧПУ для статьи.

На сайте сосуществуют два стиля:
  * короткие (последние 10 статей): inu, ek, ohrana, itaut, naym, akr, gid;
  * описательные (более старые): autsorsing-ili-svoy-shtat, personal-dlya-sklada-i-logistiki.

Стиль задаётся config.slug_style: "short" (по умолчанию, как у свежих статей)
или "descriptive".
"""
from __future__ import annotations

import re

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

STOP_WORDS = {
    "и", "в", "во", "на", "с", "со", "по", "для", "от", "до", "при", "из",
    "как", "что", "чем", "или", "а", "но", "не", "за", "же", "ли", "бы",
    "это", "его", "ее", "их", "vs",
}


def translit(text: str) -> str:
    out = []
    for ch in text.lower():
        if ch in TRANSLIT:
            out.append(TRANSLIT[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        else:
            out.append("-")
    return re.sub(r"-+", "-", "".join(out)).strip("-")


def _words(title: str) -> list[str]:
    plain = re.sub(r"<[^>]+>", " ", title)
    plain = re.sub(r"[^А-Яа-яЁёA-Za-z0-9\s\-]", " ", plain)
    return [w for w in plain.split() if w.lower() not in STOP_WORDS and len(w) > 1]


def make_slug(title: str, taken: set[str], style: str = "short") -> str:
    """Уникальный ЧПУ. `taken` — множество уже занятых слагов."""
    words = _words(title)
    if not words:
        words = ["statya"]

    candidates: list[str] = []

    if style == "descriptive":
        full = "-".join(translit(w) for w in words[:8])[:60].strip("-")
        candidates.append(full)
        candidates.append("-".join(translit(w) for w in words[:5])[:45].strip("-"))
    else:
        # как на сайте: транслит первых значимых слов, коротко
        first = translit(words[0])
        candidates.append(first[:6])
        candidates.append(first[:8])
        if len(words) > 1:
            candidates.append((first[:3] + translit(words[1])[:3])[:6])
            candidates.append((translit(words[0])[:4] + translit(words[1])[:4])[:8])
        for i in range(1, min(len(words), 4)):
            candidates.append(translit(words[i])[:6])

    candidates.append((translit(words[0])[:10] + "-" + str(len(taken) % 90 + 10))[:16])

    seen = set()
    for cand in candidates:
        cand = re.sub(r"-+", "-", cand).strip("-")
        if len(cand) < 2 or cand in seen:
            continue
        seen.add(cand)
        if cand not in taken:
            return cand

    base = (translit(words[0])[:6] or "statya")
    n = 2
    while "%s-%d" % (base, n) in taken:
        n += 1
    return "%s-%d" % (base, n)


if __name__ == "__main__":
    import json
    import os
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import settings

    cat = json.loads(settings.path("catalog").read_text(encoding="utf-8"))
    taken = {n["slug"] for n in cat["news"]}
    for t in ("Как рассчитать стоимость аренды персонала на производство",
              "Охрана труда при аутсорсинге: кто отвечает за несчастный случай",
              "Аккредитация частного агентства занятости",
              "Квоты на иностранный персонал в 2026 году"):
        print("%-64s -> short=%-10s descriptive=%s"
              % (t[:62], make_slug(t, taken, "short"), make_slug(t, taken, "descriptive")))
