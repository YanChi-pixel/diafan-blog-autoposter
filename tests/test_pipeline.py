"""Тесты конвейера: контракт вёрстки, линкер, ЧПУ, факт-база.

Запуск:  python -m pytest tests -q
     или:  python tests/test_pipeline.py     (без pytest)
"""
from __future__ import annotations

import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import linker  # noqa: E402
import settings  # noqa: E402
import slug as slug_mod  # noqa: E402
import verify  # noqa: E402

CFG = {"internal_links_min": 3, "internal_links_max": 4,
       "target_words_min": 1800, "target_words_max": 2500}


def _article(**over):
    """Минимальная статья, проходящая контракт."""
    text = (
        "<p>Стоимость аренды персонала на склад в Москве — от 380 ₽ за час "
        "работы грузчика, включая страховые взносы по тарифу 30 %. "
        "Разбираем, из чего складывается ставка и как её проверить.</p>"
        "<p>В статье — формула расчёта, сравнение форматов и типовые ошибки.</p>"
    )
    for i in range(1, 6):
        text += ("<h2>Раздел %d: как считать</h2>"
                 "<p>Первый абзац раздела отвечает сразу: срок вывода 20 человек "
                 "на объект в Москве составляет %d рабочих дня, ставка — 380 ₽ в час. "
                 "Это определение полного цикла работ.</p>"
                 "<p>Дополнительный абзац с пояснением и цифрой %d.</p>" % (i, i, i * 7))

    # анкоры, которые должен найти линкер, — каждый в своём разделе
    anchors = ["услуги грузчиков", "услуги комплектовщиков", "персонал на производство"]
    for i, anchor in enumerate(anchors, start=1):
        marker = "<p>Дополнительный абзац с пояснением и цифрой %d.</p>" % (i * 7)
        addition = (marker + "<p>Отдельно стоит разобрать, как устроены %s "
                    "и какие требования предъявляются к смене из 15 человек.</p>" % anchor)
        text = text.replace(marker, addition, 1)
    text += ('<table class="analytics-table"><thead><tr><th>Параметр</th><th>Штат</th>'
             '</tr></thead><tbody><tr><td>Ставка</td><td>520 ₽</td></tr></tbody></table>')
    text += ('<ul class="analytics-list"><li class="analytics-list-item">Первый пункт '
             'описывает процесс целиком и содержит число 10.</li>'
             '<li class="analytics-list-item">Второй пункт содержит число 20.</li>'
             '<li class="analytics-list-item">Третий пункт содержит число 30.</li></ul>')
    text += ('<div class="sfera-form sfera-wrap"> <h3>Хотите расчёт?</h3> '
             '<insert name="show_form" module="feedback" template="ask" site_id="209"> '
             '</insert> </div>')
    text += ('<h2 class="block-d__name" data-heading-tag="H2">Часто задаваемые вопросы</h2>'
             '<div class="faq-section">')
    for i in range(6):
        text += ('<div class="faq-item"><div class="faq-question">Вопрос %d?</div>'
                 '<div class="faq-answer"> Прямой ответ на вопрос номер %d. '
                 'Срок составляет %d рабочих дней по договору. Условие — объём '
                 'заявки от 5 человек на смену. </div></div>' % (i, i, i + 2))
    text += "</div>"
    text += "<h2>Практический вывод</h2><p>Итог с числом 42 и сроком 30 дней.</p>"

    # добираем объём до целевого
    filler = ("<p>Средний срок закрытия заявки на десять комплектовщиков "
              "в Московской области — пять рабочих дней при ставке 380 ₽ в час.</p>")
    body_words = len(verify.words(text))
    while body_words < 1850:
        text = text.replace("<h2>Практический вывод</h2>", filler + "<h2>Практический вывод</h2>", 1)
        body_words = len(verify.words(text))

    art = {"name": "Стоимость аренды персонала на склад",
           "anons": "Формула ставки и проверка сметы поставщика",
           "title_meta": "Стоимость аренды персонала на склад: из чего складывается ставка",
           "descr": "Разбираем, из чего складывается стоимость аренды персонала "
                    "на склад: формула, тарифы 2026, скрытые расходы и проверка сметы "
                    "поставщика на цифрах.",
           "keywords": "аренда персонала, стоимость, ставка",
           "text": text, "_config": CFG}
    art.update(over)
    return art


PAGES = [
    {"url": "https://your-site.example.com/logisticheskie-uslugi/uslugi-gruzchikov",
     "path": "logisticheskie-uslugi/uslugi-gruzchikov", "title": "Услуги грузчиков",
     "anchors": ["услуги грузчиков", "аренда грузчиков"], "is_hub": False},
    {"url": "https://your-site.example.com/logisticheskie-uslugi/uslugi-komplektovshchikov",
     "path": "logisticheskie-uslugi/uslugi-komplektovshchikov",
     "title": "Услуги комплектовщиков",
     "anchors": ["услуги комплектовщиков", "аренда комплектовщиков"], "is_hub": False},
    {"url": "https://your-site.example.com/personal-na-proizvodstvo",
     "path": "personal-na-proizvodstvo", "title": "Персонал на производство",
     "anchors": ["персонал на производство"], "is_hub": True},
]


# --------------------------------------------------------------------------

def test_contract_ok():
    rep = verify.verify(_article(), stage="draft")
    assert rep.ok, rep.errors


def test_rejects_link_in_draft():
    art = _article()
    art["text"] = art["text"].replace(
        "Это определение полного цикла работ.",
        '<a href="https://your-site.example.com/x">полного цикла работ</a>.')
    rep = verify.verify(art, stage="draft")
    assert not rep.ok
    assert any("a>" in e or "ссылок" in e for e in rep.errors)


def test_rejects_forbidden_tag():
    art = _article()
    art["text"] = art["text"].replace("Дополнительный абзац", "<span>Дополнительный абзац</span>", 1)
    rep = verify.verify(art, stage="draft")
    assert not rep.ok
    assert any("span" in e for e in rep.errors)


def test_rejects_forbidden_heading():
    art = _article()
    art["text"] = art["text"].replace("<h2>Практический вывод</h2>", "<h2>Заключение</h2>")
    rep = verify.verify(art, stage="draft")
    assert not rep.ok
    assert any("Заключение" in e for e in rep.errors)


def test_rejects_hedge():
    art = _article()
    art["text"] = art["text"].replace("Это определение", "Возможно, это определение")
    rep = verify.verify(art, stage="draft")
    assert any("хедж" in w for w in rep.warnings)


def test_rejects_short_volume():
    art = _article()
    art["text"] = art["text"][:1200]
    rep = verify.verify(art, stage="draft")
    assert not rep.ok
    assert any("объём" in e for e in rep.errors)


def test_linker_places_in_different_sections():
    art = linker.link_article(_article(), PAGES)
    assert 2 <= len(art["_links"]) <= 4
    sections = [link["section"] for link in art["_links"]]
    assert len(sections) == len(set(sections)), "две ссылки в одном разделе"


def test_linker_no_links_in_lead_or_faq():
    art = linker.link_article(_article(), PAGES)
    text = art["text"]
    lead = text[:text.find("<h2")]
    assert "<a " not in lead
    faq = text[text.find("faq-section"):]
    assert "<a " not in faq


def test_linker_respects_max():
    art = linker.link_article(_article(), PAGES, max_links=2)
    assert len(art["_links"]) <= 2


def test_linker_does_not_link_generic_to_specific():
    """«аренда персонала» не должна уходить на страницу ИТ-персонала."""
    pages = [{"url": "https://your-site.example.com/obsluzhivayushchij-personal/uslugi-it-personala",
              "path": "obsluzhivayushchij-personal/uslugi-it-personala",
              "title": "Услуги ИТ-персонала",
              "anchors": ["услуги ит-персонала", "аренда ит-персонала"], "is_hub": False}]
    art = _article()
    art["text"] = ("<h2>Раздел</h2><p>Аренда персонала в Москве стоит 380 ₽ в час, "
                   "и это выгодно.</p>")
    res = linker.link_article(art, pages)
    assert not res["_links"], "родовая фраза не должна вести на частную услугу"


def test_slug_unique_and_valid():
    taken = {"inu", "ek"}
    s1 = slug_mod.make_slug("Индивидуальные условия для работодателя", taken, "short")
    taken.add(s1)
    s2 = slug_mod.make_slug("Индивидуальные условия для работодателя", taken, "short")
    assert s1 != s2
    for s in (s1, s2):
        assert 2 <= len(s) <= 60
        assert all(c.isalnum() or c == "-" for c in s)


def test_slug_descriptive():
    s = slug_mod.make_slug("Охрана труда при аутсорсинге", set(), "descriptive")
    assert "okhrana" in s or "okhrana" in s.replace("h", "h")


# --------------------------------------------------------------------------
# Изображения: путь Pexels проверяется без реального ключа
# --------------------------------------------------------------------------

class _Resp:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code = status
        self._payload = payload
        self.content = content
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %d" % self.status_code)


def _fake_photo_bytes(w=1600, h=1000, color=(120, 140, 160)):
    import io as _io

    from PIL import Image
    buf = _io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="JPEG")
    return buf.getvalue()


def _with_env(key, value):
    class _Ctx:
        def __enter__(self):
            self.old = settings._ENV.get(key)
            settings._ENV[key] = value
        def __exit__(self, *a):
            if self.old is None:
                settings._ENV.pop(key, None)
            else:
                settings._ENV[key] = self.old
    return _Ctx()


def _with_provider(mode):
    """Временно включает режим автоподбора обложек."""
    class _Ctx:
        def __enter__(self):
            cfg = settings.load_config()
            self.old = cfg["images"].get("provider")
            cfg["images"]["provider"] = mode
        def __exit__(self, *a):
            settings.load_config()["images"]["provider"] = self.old
    return _Ctx()


def test_pexels_success_produces_800x510():
    """Успешный ответ Pexels -> корректная обложка 800x510."""
    import io as _io
    from unittest import mock

    from PIL import Image

    import images

    photo = {"src": {"large2x": "https://images.pexels.com/x.jpg",
                     "large": "https://images.pexels.com/x.jpg",
                     "original": "https://images.pexels.com/x.jpg"}}
    payload = {"photos": [photo] * 3}
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if "api.pexels.com" in url:
            return _Resp(200, payload)
        return _Resp(200, content=_fake_photo_bytes())

    with _with_env("PEXELS_API_KEY", "test-key"), _with_provider("auto"), \
            mock.patch("requests.get", side_effect=fake_get):
        cover, meta = images.make_cover("Стоимость аренды персонала", "склад персонал")

    assert meta["provider"] == "pexels", meta
    im = Image.open(_io.BytesIO(cover))
    assert im.size == (800, 510), im.size
    assert any("api.pexels.com" in c for c in calls)


def test_pexels_unauthorized_falls_back():
    """401 от Pexels не должен ломать конвейер — уходим в заглушку."""
    from unittest import mock

    import images

    with _with_env("PEXELS_API_KEY", "bad-key"), _with_provider("auto"), \
            mock.patch("requests.get", return_value=_Resp(401, {"error": "unauthorized"})):
        cover, meta = images.make_cover("Заголовок статьи", "склад персонал")

    assert meta["provider"] == "pillow_brand", meta
    assert len(cover) > 1000


def test_no_key_uses_placeholder():
    import images
    with _with_env("PEXELS_API_KEY", ""), _with_provider("auto"):
        cover, meta = images.make_cover("Заголовок статьи", "склад персонал")
    assert meta["provider"] == "pillow_brand"


def test_cover_is_always_800x510():
    import io as _io

    from PIL import Image

    import images
    # широкий, высокий и квадратный исходники — все должны стать 800x510
    for w, h in ((2000, 600), (600, 2000), (1000, 1000), (800, 510)):
        out = images.to_cover(_fake_photo_bytes(w, h))
        assert Image.open(_io.BytesIO(out)).size == (800, 510), (w, h)


def test_manual_cover_from_png():
    """Ручная картинка (PNG, как из Qwen) должна обрезаться в 800x510 JPEG."""
    import io as _io

    from PIL import Image

    import images
    buf = _io.BytesIO()
    Image.new("RGBA", (1024, 1024), (200, 120, 60, 255)).save(buf, format="PNG")
    png = buf.getvalue()

    out = images.to_cover(png)
    im = Image.open(_io.BytesIO(out))
    assert im.size == (800, 510), im.size
    assert im.format == "JPEG", im.format


def test_manual_cover_from_wide_webp():
    import io as _io

    from PIL import Image

    import images
    buf = _io.BytesIO()
    Image.new("RGB", (1920, 1080), (30, 30, 30)).save(buf, format="WEBP")
    out = images.to_cover(buf.getvalue())
    assert Image.open(_io.BytesIO(out)).size == (800, 510)


def test_provider_none_returns_placeholder():
    """При provider=none автоподбор не выполняется — только заглушка."""
    import images
    import settings
    cfg = settings.load_config()
    old = cfg["images"].get("provider")
    cfg["images"]["provider"] = "none"
    try:
        cover, meta = images.make_cover("Заголовок", "склад персонал")
    finally:
        cfg["images"]["provider"] = old
    assert meta["provider"] == "pillow_brand"
    assert meta.get("manual") is True
    assert len(cover) > 1000


# --------------------------------------------------------------------------
# Антидубль тем (регрессия: ложное срабатывание на коротком заголовке)
# --------------------------------------------------------------------------

def test_dupes_related_topic_is_not_duplicate():
    """«Аутсорсинг или аренда персонала» — НЕ дубль статьи «Аутсорсинг персонала»."""
    import dupes
    got = dupes.is_duplicate(
        "Аутсорсинг или аренда персонала: в чём разница и что выбрать заказчику",
        ["Аутсорсинг персонала"],
    )
    assert got is None, got


def test_dupes_detects_real_duplicate():
    import dupes
    assert dupes.is_duplicate("Персонал для склада и логистики",
                              ["Персонал для склада и логистики"]) is not None
    assert dupes.is_duplicate("Как рассчитать стоимость аренды персонала на производство",
                              ["Стоимость аренды персонала на производство"]) is not None


def test_dupes_handles_word_endings():
    """«склад» и «склада» должны считаться одним словом."""
    import dupes
    assert dupes.jaccard(dupes.tokens("Персонал на склад"),
                         dupes.tokens("Персонал для склада")) > 0


def test_dupes_ignores_unrelated():
    import dupes
    assert dupes.is_duplicate("Квоты на иностранный персонал в 2026 году",
                              ["Аутсорсинг персонала", "Охрана труда"]) is None


# --------------------------------------------------------------------------
# Границы валидатора
# --------------------------------------------------------------------------

def test_ten_content_sections_is_not_an_error():
    """10 контентных разделов — не брак, эталон сайта 8."""
    art = _article()
    extra = ("<h2>Дополнительный раздел</h2><p>Срок вывода 14 человек "
             "составляет 4 рабочих дня при ставке 380 ₽ в час.</p>")
    art["text"] = art["text"].replace("<h2>Практический вывод</h2>",
                                      extra * 5 + "<h2>Практический вывод</h2>", 1)
    rep = verify.verify(art, stage="draft")
    assert not any("контентных разделов" in e for e in rep.errors), rep.errors


def test_too_many_sections_is_an_error():
    art = _article()
    extra = ("<h2>Лишний раздел</h2><p>Срок 3 дня и ставка 400 ₽ в час.</p>")
    art["text"] = art["text"].replace("<h2>Практический вывод</h2>",
                                      extra * 12 + "<h2>Практический вывод</h2>", 1)
    rep = verify.verify(art, stage="draft")
    assert any("контентных разделов" in e for e in rep.errors)


# --------------------------------------------------------------------------
# Переобход в Яндексе (запросы замоканы — живых обращений нет)
# --------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _recrawl_with_temp_cache():
    """Подменяет кэш user_id/host_id на временный файл."""
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp()) / "webmaster.json"
    return tmp


def _fake_webmaster(host="your-site.example.com", verified=True, fail_post=None):
    """Фейковый API Вебмастера."""
    def handler(req, timeout=30):
        url = req.full_url
        if url.endswith("/user"):
            return _FakeResp({"user_id": 123456})
        if url.endswith("/hosts"):
            return _FakeResp({"hosts": [
                {"host_id": "https:your-site.example.com:443",
                 "unicode_host_url": "https://%s/" % host, "verified": verified},
                {"host_id": "https:other.ru:443",
                 "unicode_host_url": "https://other.ru/", "verified": True},
            ]})
        if "recrawl/queue" in url:
            if fail_post:
                raise fail_post
            return _FakeResp({})
        raise AssertionError("неожиданный URL: %s" % url)
    return handler


def _with_recrawl_env(tmp_path, token="test-token"):
    import recrawl

    class _Ctx:
        def __enter__(self):
            self.patches = [
                mock.patch.object(recrawl, "_cache_path", lambda: tmp_path),
                mock.patch.object(recrawl, "_token", lambda: token),
                mock.patch.object(recrawl, "_host", lambda: "your-site.example.com"),
            ]
            for p in self.patches:
                p.start()
            return recrawl

        def __exit__(self, *a):
            for p in self.patches:
                p.stop()
            return False
    return _Ctx()


def test_recrawl_submits_url():
    with _with_recrawl_env(_recrawl_with_temp_cache()) as rc, \
            mock.patch("urllib.request.urlopen", side_effect=_fake_webmaster()):
        res = rc.submit(["https://your-site.example.com/news/test/"])
    assert res["ok"] == 1, res
    assert not res["errors"]
    assert res["sent"] == ["https://your-site.example.com/news/test/"]


def test_recrawl_caches_host_ids():
    """Повторный вызов не должен снова запрашивать /user и /hosts."""
    calls = []

    def counting(req, timeout=30):
        calls.append(req.full_url)
        return _fake_webmaster()(req)

    with _with_recrawl_env(_recrawl_with_temp_cache()) as rc, \
            mock.patch("urllib.request.urlopen", side_effect=counting):
        rc.submit(["https://your-site.example.com/news/a/"])
        first = len(calls)
        rc.submit(["https://your-site.example.com/news/b/"])
        second = len(calls) - first

    assert first == 3, calls          # /user, /hosts, recrawl
    assert second == 1, calls         # только recrawl — id берутся из кэша


def test_recrawl_handles_quota_exceeded():
    import urllib.error
    err = urllib.error.HTTPError(url="x", code=429, msg="Too Many Requests",
                                 hdrs=None, fp=None)
    err.read = lambda: b"quota exceeded"
    with _with_recrawl_env(_recrawl_with_temp_cache()) as rc, \
            mock.patch("urllib.request.urlopen", side_effect=_fake_webmaster(fail_post=err)):
        res = rc.submit(["https://your-site.example.com/news/a/"])
    assert res["quota_exceeded"] is True
    assert res["ok"] == 0


def test_recrawl_reports_unverified_host():
    with _with_recrawl_env(_recrawl_with_temp_cache()) as rc, \
            mock.patch("urllib.request.urlopen",
                       side_effect=_fake_webmaster(verified=False)):
        try:
            rc.submit(["https://your-site.example.com/news/a/"])
            raise AssertionError("ожидалась ошибка о неподтверждённом хосте")
        except RuntimeError as e:
            assert "не подтверждён" in str(e)


def test_recrawl_quiet_does_not_raise():
    """Сбой переобхода не должен ломать публикацию."""
    import urllib.error

    def boom(req, timeout=30):
        raise urllib.error.URLError("нет сети")

    with _with_recrawl_env(_recrawl_with_temp_cache()) as rc, \
            mock.patch("urllib.request.urlopen", side_effect=boom):
        ok = rc.submit_quiet(["https://your-site.example.com/news/a/"])
    assert ok is False


def test_recrawl_quiet_without_urls():
    import recrawl
    assert recrawl.submit_quiet([]) is True


def run_all():
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed, failed = 0, []
    for name, fn in tests:
        try:
            fn()
            print("  OK   %s" % name)
            passed += 1
        except AssertionError as e:
            print("  FAIL %s: %s" % (name, e))
            failed.append(name)
        except Exception as e:  # noqa: BLE001
            print("  ERR  %s: %s: %s" % (name, type(e).__name__, e))
            failed.append(name)
    print("\n%d из %d тестов пройдено" % (passed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(run_all())
