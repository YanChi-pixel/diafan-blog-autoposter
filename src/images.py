"""Обложка статьи: 800x510 JPEG.

Провайдеры:
  * pexels      — стоковое фото по ключевым словам темы (основной);
  * pillow_brand — фирменная заглушка, если сток недоступен (резерв).

Текущие обложки на сайте — обычные стоковые фото 800x510 без текста и
логотипов, поэтому сток воспроизводит стиль сайта один в один.
"""
from __future__ import annotations

import io
import random
import re
import sys

import requests
from PIL import Image, ImageDraw, ImageFilter

import settings

TARGET_W = 800
TARGET_H = 510

# Тема статьи -> поисковый запрос на английском (Pexels лучше ищет по-английски).
# Правило выбирается по САМОМУ ДЛИННОМУ совпавшему ключу, а не по порядку:
# иначе «охрана труда» перехватывается правилом «охран» и вместо
# безопасности на производстве подтягивается охранник у супермаркета.
QUERY_MAP = [
    # охрана труда и СИЗ — обязательно раньше «охранника»
    (("охрана труда", "техника безопасности", "несчастный случай",
      "спецодежд", "средства индивидуальной защиты", "сиз ", "каска",
      "медосмотр", "инструктаж", "наряд-допуск", "промышленная безопасность",
      "соут", "охране труда"),
     "industrial safety helmet worker"),
    (("охранник", "охран", "охрана объекта", "пропускной режим", "безопасность объекта"),
     "industrial security checkpoint"),

    (("сварщик", "сварк", "сварочн", "накс"), "welder welding metal sparks"),
    (("грузчик", "погрузк", "разгрузк", "такелаж"), "warehouse worker carrying boxes"),
    (("комплектовщик", "кладовщик", "склад", "логист", "комплектац"),
     "warehouse shelves worker picking"),
    (("водител погрузчика", "штабелер", "погрузчик", "forklift"), "forklift driver warehouse"),
    (("стройк", "строител", "монтажник", "демонтаж", "отделк", "маляр",
      "плиточник", "металлоконструкц"), "construction site workers helmets"),
    (("электрик", "электромонтаж", "электрослесар", "электрооборудован"),
     "electrician industrial panel work"),
    (("слесар", "металлообработ", "шлифов", "токар", "обрубщик", "фрезеров"),
     "metalworker lathe industrial workshop"),
    (("пищев", "повар", "фасовщик", "конвейер", "линия розлива", "общепит"),
     "food factory production line workers"),
    (("уборщ", "клининг", "уборка помещен"), "commercial cleaning staff floor"),
    (("мероприят", "ивент", "хостес", "раздач"), "event staff catering service"),
    # тема про иностранный персонал — намеренно нейтральный производственный
    # кадр: снимок с иностранными рабочими к такой статье читается двусмысленно
    (("мигрант", "квот", "патент", "иностранн", "виз"), "construction site crane industrial building"),
    (("кадров", "hr", "подбор персонала", "найм", "текучест", "аттестац", "делопроизводств"),
     "hr manager interview office"),
    # Темы про деньги и документы НЕ маппим на бумаги: сток по таким запросам
    # отдаёт налоговые формы США (W-4, 1040) и англоязычные договоры — на
    # российском B2B-сайте это выглядит абсурдно. Берём людей и производство.
    (("налог", "взнос", "ндфл", "ндс", "мрот", "тариф", "стоимость", "цена",
      "расчёт", "расчет", "смет", "экономи", "бюджет", "выгодн", "затрат"),
     "factory manager clipboard production"),
    (("договор", "документ", "допуск", "лиценз", "аккредитац", "отчётност"),
     "business handshake office meeting"),
    (("производств", "завод", "цех", "участок", "линия", "станочник"),
     "factory production line industrial"),
    (("сезон", "пиков", "нагрузк", "график", "смен"), "shift workers schedule factory"),
    (("кейс", "результат", "эффективност", "kpi", "контрол"), "business team meeting plant"),
]

# Родовые слова: почти в каждой теме блога есть «аутсорсинг» или «персонал»,
# поэтому они не должны перебивать конкретный предмет статьи. Применяются
# только если ни одно точное слово не найдено.
GENERIC_QUERIES = [
    (("аутсорс", "аутстафф", "аренда персонала", "предоставление персонала",
      "вывод за штат", "персонал", "работник", "сотрудник", "заказчик"),
     "industrial team workers plant"),
]

DEFAULT_QUERIES = [
    "industrial workers team",
    "warehouse workers",
    "factory workers teamwork",
    "business people meeting office",
]

# Слова в описании фото, по которым видно, что кадр не подходит:
# стоковые «документы» почти всегда оказываются американскими налоговыми
# формами, а «passport»/«visa» — чужими бланками с читаемым текстом.
RISKY_ALT = (
    "tax", "form", "1040", "w-4", "w-9", "invoice", "receipt", "passport",
    "visa", "contract", "document", "paperwork", "signature", "banknote",
    "dollar", "money", "currency", "book", "letter", "menu", "chart",
    "graph", "diagram", "spreadsheet", "screen", "laptop", "computer",
    "flag", "stamp", "certificate",
)


def _alt_is_risky(photo: dict) -> bool:
    alt = (photo.get("alt") or "").lower()
    if not alt:
        return False
    return any(word in alt for word in RISKY_ALT)


def suggest_query(text: str) -> str:
    """Подбирает поисковый запрос по ключевому слову темы.

    Приоритет — у слова, которое встречается РАНЬШЕ: предмет статьи обычно
    назван в начале («Охрана труда при аутсорсинге» — это про охрану труда,
    а не про аутсорсинг). При совпадении позиции выигрывает более длинный
    ключ («охранник» точнее, чем «охран»). Родовые слова вроде «аутсорсинг»
    и «персонал» рассматриваются только в последнюю очередь.
    """
    low = text.lower().replace("ё", "е")

    def best_in(mapping):
        query, pos, length = None, 10 ** 6, 0
        for keys, q in mapping:
            for k in keys:
                key = k.replace("ё", "е")
                p = low.find(key)
                if p < 0:
                    continue
                if p < pos or (p == pos and len(key) > length):
                    query, pos, length = q, p, len(key)
        return query

    return (best_in(QUERY_MAP)
            or best_in(GENERIC_QUERIES)
            or random.choice(DEFAULT_QUERIES))


# --------------------------------------------------------------------------
# Обработка
# --------------------------------------------------------------------------

def to_cover(raw: bytes) -> bytes:
    """Кроп по центру и ресайз ровно в 800x510."""
    img = Image.open(io.BytesIO(raw))
    img = img.convert("RGB")

    src_ratio = img.width / img.height
    dst_ratio = TARGET_W / TARGET_H

    if src_ratio > dst_ratio:
        new_w = int(img.height * dst_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    elif src_ratio < dst_ratio:
        new_h = int(img.width / dst_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))

    img = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)

    out = io.BytesIO()
    quality = settings.load_config()["images"]["jpeg_quality"]
    img.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def brand_placeholder(title: str) -> bytes:
    """Резерв: серо-синяя заглушка с заголовком, без брендинга конкурентов."""
    w, h = TARGET_W * 2, TARGET_H * 2
    img = Image.new("RGB", (w, h), (32, 58, 92))
    d = ImageDraw.Draw(img)
    for i in range(h):
        k = i / h
        d.line([(0, i), (w, i)], fill=(int(32 + 40 * k), int(58 + 45 * k), int(92 + 50 * k)))
    for i in range(0, w, 40):
        d.line([(i, 0), (i - h, h)], fill=(255, 255, 255, 6))
    img = img.filter(ImageFilter.GaussianBlur(1.2))

    d = ImageDraw.Draw(img)
    text = re.sub(r"\s+", " ", title).strip()
    words, lines, cur = text.split(), [], ""
    for word in words:
        probe = (cur + " " + word).strip()
        if len(probe) > 34 and cur:
            lines.append(cur)
            cur = word
        else:
            cur = probe
    if cur:
        lines.append(cur)
    lines = lines[:3]

    try:
        from PIL import ImageFont
        font = None
        for path in ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"):
            try:
                font = ImageFont.truetype(path, 54)
                break
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        font = None

    total = len(lines) * 66
    y = (h - total) // 2
    for line in lines:
        if font:
            bbox = d.textbbox((0, 0), line, font=font)
            x = (w - (bbox[2] - bbox[0])) // 2
        else:
            x = 60
        d.text((x, y), line, fill=(255, 255, 255), font=font)
        y += 66

    img = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


# --------------------------------------------------------------------------
# Провайдеры
# --------------------------------------------------------------------------

def from_pexels(query: str) -> bytes | None:
    key = settings.env("PEXELS_API_KEY")
    if not key:
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "orientation": "landscape",
                    "per_page": 12, "size": "large"},
            headers={"Authorization": key},
            timeout=30,
        )
        if r.status_code != 200:
            print("    Pexels HTTP %d: %s" % (r.status_code, r.text[:160]))
            return None
        photos = r.json().get("photos", [])
        if not photos:
            print("    Pexels: ничего не найдено по «%s»" % query)
            return None
        # отбрасываем кадры с бумагами, бланками и экранами: на них почти
        # всегда читаемый текст не на русском
        safe = [p for p in photos if not _alt_is_risky(p)]
        if not safe:
            print("    Pexels: все результаты по «%s» отфильтрованы" % query)
            return None
        # берём случайное из первой десятки — обложки не будут повторяться
        photo = random.choice(safe[:10])
        src = photo["src"].get("large2x") or photo["src"].get("large") or photo["src"]["original"]
        img = requests.get(src, timeout=60)
        img.raise_for_status()
        return to_cover(img.content)
    except Exception as e:  # noqa: BLE001
        print("    Pexels ошибка: %s" % str(e)[:160])
        return None


def from_openverse(query: str) -> bytes | None:
    """Openverse (WordPress) — реальные фото без ключа.

    Берём только cc0 и public domain mark: они не требуют указания авторства,
    в отличие от cc-by / cc-by-sa.
    """
    try:
        r = requests.get(
            "https://api.openverse.org/v1/images/",
            params={"q": query, "license": "cc0,pdm", "page_size": 20,
                    "aspect_ratio": "wide", "mature": "false"},
            headers={"User-Agent": "diafan-blog-autoposter/1.0"},
            timeout=30,
        )
        if r.status_code != 200:
            print("    Openverse HTTP %d: %s" % (r.status_code, r.text[:160]))
            return None
        results = r.json().get("results", [])
        if not results:
            print("    Openverse: ничего не найдено по «%s»" % query)
            return None
        # отбираем достаточно крупные, чтобы кроп в 800x510 не был мыльным
        good = [x for x in results if (x.get("width") or 0) >= 1000 and (x.get("height") or 0) >= 640]
        pool = good or results
        random.shuffle(pool)
        for item in pool[:6]:
            url = item.get("url")
            if not url:
                continue
            try:
                img = requests.get(url, timeout=60,
                                   headers={"User-Agent": "diafan-blog-autoposter/1.0"})
                if img.status_code != 200 or not img.content:
                    continue
                return to_cover(img.content)
            except Exception:  # noqa: BLE001
                continue
        return None
    except Exception as e:  # noqa: BLE001
        print("    Openverse ошибка: %s" % str(e)[:160])
        return None


def make_cover(title: str, topic: str = "") -> tuple[bytes, dict]:
    """Возвращает (jpeg_bytes, метаданные).

    Режимы задаются config.images.provider:

      none        — фото подбираются ВРУЧНУЮ. Автоподбор отключён, статью
                    публикуем с аккуратной заглушкой, а свою картинку
                    прикрепляем позже:  python src\\set_cover.py --id N --file путь
      auto        — автоматический подбор: Pexels (по ключу), при неудаче
                    фирменная заглушка
      pexels      — только Pexels, без заглушки
      placeholder — всегда заглушка

    Заглушка — не «фото», а нейтральная фирменная плашка с заголовком:
    она безопасна, аккуратно смотрится в списке блога и сразу видно,
    что картинку надо заменить.
    """
    provider = (settings.load_config()["images"].get("provider") or "auto").lower()
    query = suggest_query(topic or title)

    if provider in ("none", "placeholder"):
        return brand_placeholder(title), {"query": "", "provider": "pillow_brand",
                                          "manual": True}

    meta = {"query": query, "provider": None}
    allow_openverse = bool(settings.load_config()["images"].get("allow_openverse"))

    chain = []
    if provider in ("auto", "pexels"):
        chain.append(("pexels", from_pexels))
    if provider == "auto" and allow_openverse:
        chain.append(("openverse", from_openverse))

    for name, fn in chain:
        raw = fn(query)
        if raw:
            meta["provider"] = name
            return raw, meta

    if provider == "auto" and query not in DEFAULT_QUERIES:
        generic = random.choice(DEFAULT_QUERIES)
        meta["generic_query"] = generic
        for name, fn in chain:
            raw = fn(generic)
            if raw:
                meta["provider"] = name + "(generic)"
                return raw, meta

    meta["provider"] = "pillow_brand"
    meta["manual"] = True
    return brand_placeholder(title), meta


if __name__ == "__main__":

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    title = sys.argv[1] if len(sys.argv) > 1 else "Аренда персонала на конвейер"
    topic = sys.argv[2] if len(sys.argv) > 2 else title
    print("Запрос:", suggest_query(topic))
    data, meta = make_cover(title, topic)
    out = settings.ROOT / "output" / "cover_test.jpg"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(data)
    im = Image.open(io.BytesIO(data))
    print("Провайдер:", meta["provider"])
    print("Размер:", im.size, "| байт:", len(data))
    print("Сохранено:", out)
