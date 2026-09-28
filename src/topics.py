"""Пополнение очереди тем.

43 темы в data/themes.txt — это примерно три недели при двух статьях в день,
поэтому очередь нужно периодически пополнять.

Генератор намеренно НЕ делает перестановки ключевых слов: по исследованию
AI SEO (и по прямой формулировке Google про scaled content abuse) страницы
под каждую вариацию запроса вредят сайту. Поэтому модель получает каталог
разделов и список уже написанного, и предлагает только самостоятельные темы,
каждая из которых закрывает отдельный вопрос клиента.

    python src/topics.py            # добавить 20 тем
    python src/topics.py --count 30
    python src/topics.py --show     # только показать, не записывать
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from difflib import SequenceMatcher

import dupes
import settings
import writer

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Пример отраслевой настройки: B2B-услуги для промышленных предприятий.
# Под свою отрасль меняется только этот блок — механика генерации универсальна.
PROMPT = """Ты — редактор корпоративного блога B2B-компании.
Компания оказывает услуги промышленным предприятиям: производство, логистика
и склады, строительство, обслуживающий персонал, торговые сети, кадровое
администрирование.

## Уже опубликованные статьи (эти темы НЕ предлагать и не повторять по смыслу)
{existing}

## Темы, уже стоящие в очереди (их тоже не предлагать)
{queued}

## Разделы сайта, на которые можно ссылаться из статей
{sections}

## Задача

Предложи {count} новых тем для статей.

Требования к каждой теме:
1. Это отдельный вопрос или задача реального клиента — руководителя
   производства, HR-директора, начальника склада, главного инженера.
2. Тема НЕ является перестановкой слов из уже написанного. Нужен новый
   содержательный угол, а не «то же самое другими словами».
3. Тема допускает конкретику: числа, сроки, статьи законов, тарифы,
   сравнение вариантов. Темы вида «что такое аутсорсинг» не подходят.
4. Темы не пересекаются между собой.
5. Практическая польза, а не общие рассуждения.

Покрой разные кластеры: склад и логистика, производство, стройка, общепит,
право и налоги, охрана труда, миграционный учёт, экономика аутсорсинга,
подбор и удержание персонала.

Верни СТРОГО JSON без markdown:
{{"topics": ["тема 1", "тема 2", ...]}}"""


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def is_duplicate(topic: str, existing: list[str], threshold: float = 0.72) -> bool:
    """Дубль темы — общая реализация из src/dupes.py."""
    return dupes.is_duplicate(topic, existing) is not None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--show", action="store_true", help="не записывать в файл")
    args = ap.parse_args()

    queue_path = settings.path("themes")
    queued = [line.strip() for line in queue_path.read_text(encoding="utf-8").splitlines()
              if line.strip() and not line.strip().startswith("#")]

    catalog = json.loads(settings.path("catalog").read_text(encoding="utf-8"))
    news_titles = [n["title"] for n in catalog["news"] if n.get("title")]

    registry_path = settings.path("registry")
    published = []
    if registry_path.exists():
        reg = json.loads(registry_path.read_text(encoding="utf-8"))
        published = [e["name"] for e in reg.get("published", [])]

    existing = news_titles + published
    links = json.loads(settings.path("internal_links").read_text(encoding="utf-8"))
    sections = ", ".join(p["title"] for p in links["pages"] if not p.get("is_hub"))

    prompt = (PROMPT
              .replace("{existing}", "\n".join("- " + t for t in existing) or "(пока нет)")
              .replace("{queued}", "\n".join("- " + t for t in queued) or "(пусто)")
              .replace("{sections}", sections)
              .replace("{count}", str(args.count)))

    print("Запрос к DeepSeek: %d тем ..." % args.count)
    result = writer.call_llm(prompt, temperature=0.9)
    topics = result.get("topics") or []
    if not isinstance(topics, list):
        print("модель вернула не список тем:", str(result)[:200])
        return 1

    print("Получено тем: %d" % len(topics))

    known = existing + queued
    fresh, rejected = [], []
    for t in topics:
        t = re.sub(r"\s+", " ", str(t)).strip().strip('"').strip()
        if not t or len(t) < 15:
            continue
        if is_duplicate(t, known + fresh):
            rejected.append(t)
            continue
        fresh.append(t)

    print("\n=== Принято: %d ===" % len(fresh))
    for t in fresh:
        print("  +", t)
    if rejected:
        print("\n=== Отклонено как повтор: %d ===" % len(rejected))
        for t in rejected:
            print("  -", t)

    if args.show or not fresh:
        return 0

    with open(queue_path, "a", encoding="utf-8") as fh:
        for t in fresh:
            fh.write(t + "\n")
    print("\nДобавлено в %s. Всего в очереди: %d"
          % (queue_path, len(queued) + len(fresh)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
