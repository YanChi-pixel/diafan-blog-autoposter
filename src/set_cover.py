"""Обложки статей: прикрепить свою картинку или заменить автоматическую.

Автоподбор фото отключён (config.images.provider = "none"): статьи выходят
с нейтральной фирменной заглушкой, а настоящую картинку вы генерируете сами
и прикрепляете этим скриптом. Картинка автоматически обрезается ровно
в 800x510 — готовить размер заранее не нужно, подойдёт любой формат,
который читает Pillow (png, jpg, webp).

Использование:
    python src\\set_cover.py --list                     что опубликовано
    python src\\set_cover.py --id 25 --file C:\\img.png  прикрепить картинку
    python src\\set_cover.py --from-dir covers          все из папки по слагам
    python src\\set_cover.py --auto --placeholders      вернуть автоподбор (Pexels)

Для пакетного режима положите файлы в папку и назовите их по слагу статьи:
    covers/kvoty.png     -> /news/kvoty/
    covers/autsor.jpg    -> /news/autsor/
Слаги видны в --list.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import diafan
import images
import settings

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EG = ("png", "jpg", "jpeg", "webp", "bmp", "tiff")


def load_registry() -> dict:
    path = settings.path("registry")
    if not path.exists():
        return {"published": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_registry(reg: dict) -> None:
    settings.path("registry").write_text(
        json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def short(url: str) -> str:
    return url.replace(settings.site_url(), "")


def attach_file(entry: dict, path: Path) -> bool:
    """Прикрепляет локальный файл к статье (с кропом в 800x510)."""
    try:
        raw = path.read_bytes()
        cover = images.to_cover(raw)
    except Exception as e:  # noqa: BLE001
        print("    ошибка чтения %s: %s" % (path.name, str(e)[:120]))
        return False

    res = diafan.set_image(entry["id"], cover, alt=entry["name"])
    if not res.get("ok"):
        print("    сервер вернул ошибку: %s" % json.dumps(res, ensure_ascii=False)[:200])
        return False

    variations = (res.get("image") or {}).get("variations") or {}
    print("    прикреплено: %s (%d байт) -> %s"
          % (path.name, len(raw), ", ".join(sorted(variations)) or "—"))
    entry["image_provider"] = "manual"
    entry["image_query"] = ""
    entry["image_file"] = path.name
    entry["image_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return True


def find_file_in_dir(directory: Path, slug: str) -> Path | None:
    for ext in EG:
        for name in ("%s.%s" % (slug, ext), "%s.%s" % (slug, ext.upper())):
            p = directory / name
            if p.is_file():
                return p
    return None


def needs_cover(entry: dict) -> bool:
    """Нужна ли статье картинка (заглушка вместо фото или сток на замену)."""
    return entry.get("image_provider") != "manual"


def status_of(entry: dict) -> str:
    prov = entry.get("image_provider") or "—"
    if prov == "manual":
        return "своя"
    if prov == "pillow_brand":
        return "ЗАГЛУШКА"
    return "авто"


def cmd_list(published: list) -> int:
    if not published:
        print("реестр пуст")
        return 0

    print("%-5s %-10s %-14s %-10s %s"
          % ("id", "слаг", "обложка", "статус", "статья"))
    print("-" * 96)
    for e in published:
        print("%-5s %-10s %-14s %-10s %s"
              % (e.get("id"), e.get("slug"), e.get("image_provider") or "—",
                 status_of(e), (e.get("name") or "")[:42]))

    manual = [e for e in published if e.get("image_provider") == "manual"]
    auto = [e for e in published if e.get("image_provider") not in ("manual", "pillow_brand")]
    empty = [e for e in published if e.get("image_provider") == "pillow_brand"]

    print()
    print("Своих картинок: %d | автоматических: %d | заглушек: %d"
          % (len(manual), len(auto), len(empty)))
    if auto:
        print("Автоматические можно заменить: положите файл в covers\\ с именем слага")
    if empty:
        print("Для заглушек картинки нет совсем — их заменить нужно")
    if manual or auto or empty:
        print()
        print("  python src\\set_cover.py --from-dir covers          # заменить по файлам из папки")
        print("  python src\\set_cover.py --id <id> --file <файл>     # заменить одну")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Обложки статей блога")
    ap.add_argument("--list", action="store_true", help="что опубликовано")
    ap.add_argument("--id", type=int, help="id статьи")
    ap.add_argument("--file", help="локальный файл картинки")
    ap.add_argument("--from-dir", help="папка с картинками, имена = слаги")
    ap.add_argument("--auto", action="store_true",
                    help="подобрать автоматически (Pexels), а не вручную")
    ap.add_argument("--placeholders", action="store_true",
                    help="с --auto: обработать все заглушки")
    args = ap.parse_args()

    reg = load_registry()
    published = reg.get("published", [])

    if args.list or (not args.id and not args.from_dir):
        return cmd_list(published)

    if args.from_dir:
        directory = Path(args.from_dir)
        if not directory.is_dir():
            print("папка не найдена: %s" % directory)
            return 2
        # файл ищем для ЛЮБОЙ статьи реестра: если вы положили картинку,
        # значит хотите заменить текущую — неважно, сток там или заглушка
        targets = published
        print("Ищу картинки для %d статей в %s" % (len(targets), directory))
        done, missing = 0, []
        for e in targets:
            f = find_file_in_dir(directory, e.get("slug") or "")
            if not f:
                missing.append(e.get("slug"))
                continue
            print("  %s  %s" % (short(e["url"]), e.get("name", "")[:40]))
            if attach_file(e, f):
                done += 1
            time.sleep(8)
        if done:
            save_registry(reg)
        print("\nЗаменено: %d" % done)
        if done == 0:
            print("Не нашлось ни одного файла. Ожидаются имена по слагам:")
            print("  %s" % ", ".join("%s.png" % s for s in missing[:8]))
        return 0

    if not args.id:
        print("укажите --id или --from-dir")
        return 2

    entry = next((e for e in published if e.get("id") == args.id), None)
    if not entry:
        print("id %d не найден в реестре" % args.id)
        return 1

    print("Статья %s — %s" % (entry.get("id"), entry.get("name")))
    print("  сейчас: %s" % (entry.get("image_provider") or "—"))

    if args.file:
        path = Path(args.file)
        if not path.is_file():
            print("файл не найден: %s" % path)
            return 2
        ok = attach_file(entry, path)
    elif args.auto:
        cover, meta = images.make_cover(entry["name"], entry.get("topic") or entry["name"])
        print("  автоподбор: %s" % meta.get("provider"))
        if meta.get("provider") == "pillow_brand":
            print("  провайдер вернул заглушку — ничего не меняю")
            return 0
        res = diafan.set_image(entry["id"], cover, alt=entry["name"])
        ok = bool(res.get("ok"))
        print("  %s" % json.dumps(res, ensure_ascii=False)[:200])
        if ok:
            entry["image_provider"] = meta.get("provider")
            entry["image_query"] = meta.get("query")
    else:
        print("укажите --file (своя картинка) или --auto (подобрать автоматически)")
        return 2

    if ok:
        save_registry(reg)
        print("\nРеестр обновлён. Проверить: python src\\check.py --all")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
