"""Проверка темы на дубль с уже написанным.

Раньше коэффициент считался как пересечение, делённое на длину КОРОТКОГО
заголовка. Из-за этого тема «Аутсорсинг или аренда персонала: в чём разница»
признавалась дублем статьи «Аутсорсинг персонала»: два общих слова давали
2/2 = 1.0. Теперь используется коэффициент Жаккара (пересечение к
объединению), который не взрывается на коротких заголовках.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

# Порог Жаккара: ниже — темы считаются разными.
JACCARD_THRESHOLD = 0.55
# Порог схожести строк: ловитnear-идентичные заголовки.
RATIO_THRESHOLD = 0.80


def _stem(word: str, size: int = 5) -> str:
    """Грубая основа: «склад» и «склада» должны совпасть."""
    w = word.lower().replace("ё", "е")
    return w if len(w) <= 4 else w[:size]


def tokens(text: str, min_len: int = 4) -> set[str]:
    words = re.findall(r"[а-яa-z0-9]{%d,}" % min_len, (text or "").lower().replace("ё", "е"))
    return {_stem(w) for w in words}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_duplicate(topic: str, existing: list[str],
                 jaccard_threshold: float = JACCARD_THRESHOLD,
                 ratio_threshold: float = RATIO_THRESHOLD) -> str | None:
    """Возвращает заголовок-дубль или None."""
    tt = tokens(topic)
    if not tt:
        return None
    for title in existing:
        if not title:
            continue
        if SequenceMatcher(None, topic.lower(), title.lower()).ratio() >= ratio_threshold:
            return title
        et = tokens(title)
        if jaccard(tt, et) >= jaccard_threshold:
            return title
    return None


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cases = [
        ("Аутсорсинг или аренда персонала: в чём разница и что выбрать заказчику",
         ["Аутсорсинг персонала"], False),
        ("Персонал для склада и логистики", ["Персонал для склада и логистики"], True),
        ("Персонал для склада и логистики", ["Персонал для склада и логистики "], True),
        ("Квоты на иностранный персонал в 2026 году", ["Аутсорсинг персонала"], False),
        ("Аутсорсинг или свой штат", ["Аутсорсинг персонала"], False),
        ("Как рассчитать стоимость аренды персонала на производство",
         ["Стоимость аренды персонала на производство"], True),
    ]
    bad = 0
    for topic, existing, expect in cases:
        got = is_duplicate(topic, existing)
        ok = (got is not None) == expect
        print("  %-4s %-58s -> %s" % ("OK" if ok else "FAIL", topic[:56], got))
        if not ok:
            bad += 1
    print("\nошибок: %d" % bad)
    raise SystemExit(1 if bad else 0)
