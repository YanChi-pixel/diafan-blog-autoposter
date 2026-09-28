"""Генерация статьи через LLM (DeepSeek API, OpenAI-совместимый endpoint).

Писатель возвращает строгий JSON: name, anons, title_meta, descr, keywords, text.
Ссылки он не ставит — это работа linker.py.
"""
from __future__ import annotations

import json
import re
import sys
import time

import requests

import settings

PROMPT_PATH = settings.ROOT / "prompts" / "writer.md"


# --------------------------------------------------------------------------
# Выбор разделов сайта под тему
# --------------------------------------------------------------------------

STOP = {
    "и", "в", "во", "на", "с", "со", "по", "для", "от", "до", "при", "из",
    "как", "что", "чем", "или", "а", "но", "не", "за", "над", "под", "без",
    "the", "and", "vs",
}


def tokens(text: str) -> set[str]:
    words = re.findall(r"[а-яёa-z0-9]{3,}", text.lower().replace("ё", "е"))
    return {w for w in words if w not in STOP}


def select_targets(topic: str, pages: list[dict], limit: int = 6) -> list[dict]:
    """Разделы сайта, наиболее близкие к теме. Хабы — с понижением приоритета."""
    tt = tokens(topic)
    scored = []
    for p in pages:
        pt = tokens(p["title"] + " " + " ".join(p.get("anchors", [])))
        overlap = len(tt & pt)
        if overlap == 0:
            continue
        score = overlap * 10 + len(p.get("anchors", []))
        if p.get("is_hub"):
            score -= 25
        scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:limit]]


def select_related(pages_news: list[dict], limit: int = 12) -> list[dict]:
    """Существующие статьи — для антидубля."""
    return pages_news[:limit]


def format_targets(targets: list[dict]) -> str:
    if not targets:
        return "(нет подходящих разделов)"
    lines = []
    for p in targets:
        lines.append("- %s | анкоры: %s" % (p["title"], "; ".join(p["anchors"][:3])))
    return "\n".join(lines)


def format_related(news: list[dict]) -> str:
    titles = [n["title"] for n in news if n.get("title")]
    if not titles:
        return "(блог пока пуст)"
    return "\n".join("- " + t for t in titles)


def format_facts(facts: dict) -> str:
    """Факт-база в компактный текст."""
    if not facts:
        return "(факт-база пуста — используй только общеизвестные нормы права)"
    lines = []

    def dump(section: str, items) -> None:
        for it in items or []:
            if isinstance(it, dict):
                claim = it.get("claim") or it.get("name") or ""
                value = it.get("value") or ""
                src = it.get("source") or ""
                conf = it.get("confidence") or ""
                if conf and conf != "high":
                    continue  # непроверенное писателю не отдаём
                lines.append("- %s%s%s" % (claim, (" — " + str(value)) if value else "",
                                           (" [%s]" % src) if src else ""))
            else:
                lines.append("- %s" % it)

    for key, title in (
        ("company", "КОМПАНИЯ"),
        ("legal", "ПРАВО"),
        ("taxes", "НАЛОГИ И ВЗНОСЫ"),
        ("labor_safety", "ОХРАНА ТРУДА"),
        ("migration", "МИГРАЦИОННЫЙ УЧЁТ"),
        ("penalties", "ОТВЕТСТВЕННОСТЬ"),
        ("market", "РЫНОК"),
    ):
        if facts.get(key):
            lines.append("\n" + title + ":")
            dump(key, facts[key])
    return "\n".join(lines) if lines else "(факт-база пуста)"


# --------------------------------------------------------------------------
# Вызов LLM
# --------------------------------------------------------------------------

def build_prompt(topic: str, targets: list[dict], related: list[dict],
                 facts: dict) -> str:
    tpl = PROMPT_PATH.read_text(encoding="utf-8")
    today = time.strftime("%d.%m.%Y")
    return (tpl
            .replace("{{TOPIC}}", topic)
            .replace("{{TARGET_PAGES}}", format_targets(targets))
            .replace("{{RELATED}}", format_related(related))
            .replace("{{FACTS}}", format_facts(facts))
            .replace("{{TODAY}}", today))


def _extract_json(raw: str) -> dict:
    """Достаёт JSON даже если модель обернула его в ```json … ```."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # частая проблема — неэкранированные переводы строк внутри строк
            fixed = re.sub(r"(?<!\\)\n", "\\\\n", candidate)
            return json.loads(fixed)
    raise ValueError("в ответе модели нет JSON")


def call_llm(prompt: str, *, provider: str | None = None,
             temperature: float | None = None) -> dict:
    cfg = settings.load_config()["llm"]
    provider = provider or cfg["provider"]

    if provider == "deepseek":
        url = settings.env("DEEPSEEK_API_URL")
        key = settings.env("DEEPSEEK_API_KEY")
        model = settings.env("DEEPSEEK_MODEL", cfg["model"])
    elif provider == "ollama":
        url = settings.env("OLLAMA_URL").rstrip("/") + "/v1/chat/completions"
        key = "ollama"
        model = settings.env("OLLAMA_MODEL", "qwen2.5:14b")
    else:
        raise ValueError("неизвестный провайдер LLM: %s" % provider)

    if not key:
        raise RuntimeError("не задан ключ LLM в .env")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Ты профессиональный редактор и SEO-копирайтер. "
                                          "Отвечаешь строго в формате JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": cfg["temperature"] if temperature is None else temperature,
        "max_tokens": cfg["max_tokens"],
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}

    last = None
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, headers=headers,
                              timeout=cfg["timeout_seconds"])
            if r.status_code >= 400:
                raise RuntimeError("HTTP %d: %s" % (r.status_code, r.text[:400]))
            data = r.json()
            raw = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            article = _extract_json(raw)
            article["_usage"] = usage
            article["_model"] = model
            return article
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(4 * (attempt + 1))
    raise RuntimeError("LLM недоступна: %s" % last)


def write_article(topic: str, targets: list[dict], related: list[dict],
                  facts: dict, provider: str | None = None,
                  correction: str | None = None,
                  previous: dict | None = None) -> dict:
    """Генерирует статью.

    Если передан `previous` — это итеративная правка: модель получает свою
    предыдущую версию и список замечаний, и должна исправить ТОЛЬКО их.
    Полная перегенерация с нуля осциллирует: каждая попытка чинит одно
    замечание и ломает ранее выполненное требование.
    """
    prompt = build_prompt(topic, targets, related, facts)
    if correction and previous:
        prev_payload = {k: previous.get(k) for k in
                        ("name", "anons", "title_meta", "descr", "keywords", "text")}
        prompt += (
            "\n\n---\n\n## ИСПРАВЛЕНИЕ\n\n"
            "Ниже — твоя предыдущая версия этой статьи. Она НЕ прошла "
            "автоматическую проверку.\n\n"
            "Исправь **только перечисленные замечания** и верни ПОЛНЫЙ JSON "
            "статьи целиком:\n\n"
            "- не сокращай текст и не убирай блоки, к которым замечаний нет;\n"
            "- сохрани объём основного текста;\n"
            "- сохрани все уже корректные блоки: лид, таблицу, список, CTA, FAQ;\n"
            "- если замечание про заголовок раздела — переименуй только его.\n\n"
            "### Замечания\n\n" + correction + "\n\n"
            "### Предыдущая версия (JSON)\n\n"
            + json.dumps(prev_payload, ensure_ascii=False)
        )
    elif correction:
        prompt += (
            "\n\n---\n\n## ИСПРАВЛЕНИЕ\n\n"
            "Предыдущая версия статьи не прошла автоматическую проверку. "
            "Перепиши статью целиком, устранив замечания:\n\n" + correction +
            "\n\nОстальные требования сохраняются полностью."
        )

    article = call_llm(prompt, provider=provider)

    required = ("name", "anons", "title_meta", "descr", "keywords", "text")
    missing = [k for k in required if not article.get(k)]
    if missing:
        raise ValueError("модель не вернула поля: %s" % ", ".join(missing))

    for key in required:
        if isinstance(article.get(key), str):
            article[key] = article[key].strip()
    return article


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    topic = sys.argv[1] if len(sys.argv) > 1 else "Как рассчитать стоимость аренды персонала"
    links = json.loads(settings.path("internal_links").read_text(encoding="utf-8"))
    cat = json.loads(settings.path("catalog").read_text(encoding="utf-8"))
    facts_file = settings.data_dir() / "facts.json"
    facts = json.loads(facts_file.read_text(encoding="utf-8")) if facts_file.exists() else {}

    t = select_targets(topic, links["pages"])
    print("Тема:", topic)
    print("Разделы-цели:")
    for p in t:
        print("   %-56s %s" % (p["title"][:54], p["anchors"][:2]))
    art = write_article(topic, t, select_related(cat["news"]), facts)
    print("\nname:", art["name"])
    print("anons:", art["anons"])
    print("title_meta:", art["title_meta"])
    print("descr:", art["descr"])
    print("words:", len(re.findall(r"\w+", re.sub(r"<[^>]+>", " ", art["text"]))))
    print("usage:", art.get("_usage"))
