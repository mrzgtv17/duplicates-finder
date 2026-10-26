#!/usr/bin/env python3
"""
Поиск дубликатов файлов на Яндекс Диске через API — без скачивания файлов.

Яндекс хранит для каждого файла контрольные суммы (MD5 и SHA-256).
Скрипт получает список всех файлов с этими суммами и находит одинаковые.
Ничего не удаляет и не изменяет — только читает список и делает отчёт.

Нужен OAuth-токен Яндекса с правом чтения диска (cloud_api:disk.read).
Токен можно передать параметром --token или через переменную окружения YANDEX_TOKEN.

Примеры запуска:
  python yandex_duplicates.py --token ВАШ_ТОКЕН --csv report.csv
  python yandex_duplicates.py --token ВАШ_ТОКЕН --folder "/Фото/Дети" --csv report.csv
  python yandex_duplicates.py --token ВАШ_ТОКЕН --ext jpg png mp4 --min-size 1MB
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

API = "https://cloud-api.yandex.net/v1/disk/resources/files"
PAGE = 1000
FIELDS = "items.name,items.path,items.size,items.md5,items.sha256"


def parse_size(text: str) -> int:
    text = text.strip().upper()
    units = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "B": 1}
    for unit, mult in units.items():
        if text.endswith(unit):
            return int(float(text[: -len(unit)]) * mult)
    return int(text)


def human(size: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ПБ"


def api_get(params: dict, token: str) -> dict:
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"OAuth {token}"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                sys.exit("Ошибка 401: токен неверный или устарел. Получите новый токен.")
            if e.code == 403:
                sys.exit("Ошибка 403: у токена нет доступа к диску (нужно право cloud_api:disk.read).")
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            sys.exit(f"Ошибка API {e.code}: {e.read().decode('utf-8', 'ignore')}")
        except urllib.error.URLError as e:
            if attempt < 4:
                time.sleep(2 ** attempt)
                continue
            sys.exit(f"Нет связи с Яндекс Диском: {e.reason}")
    return {}


def list_all_files(token: str):
    """Постранично получает список всех файлов на диске."""
    offset = 0
    while True:
        data = api_get({"limit": PAGE, "offset": offset, "fields": FIELDS}, token)
        items = data.get("items", [])
        yield from items
        offset += len(items)
        print(f"  получено файлов: {offset}", file=sys.stderr)
        if len(items) < PAGE:
            break


def normalize_folder(folder: str | None) -> str | None:
    """'/Фото/Дети' или 'Фото/Дети' -> 'disk:/Фото/Дети/'"""
    if not folder:
        return None
    folder = folder.strip()
    if folder.startswith("disk:"):
        folder = folder[5:]
    folder = "/" + folder.strip("/")
    return "disk:" + (folder if folder == "/" else folder + "/")


def web_link(path: str) -> str:
    """Ссылка, по которой файл открывается в браузере в вашем Яндекс Диске."""
    p = path[5:] if path.startswith("disk:") else path
    folder = p.rsplit("/", 1)[0]
    return "https://disk.yandex.ru/client/disk" + urllib.parse.quote(folder)


def find_duplicates(files, folder, min_size, exts):
    groups = defaultdict(list)
    total = 0
    for f in files:
        path, size = f.get("path", ""), f.get("size", 0)
        if folder and not path.startswith(folder):
            continue
        if size < min_size:
            continue
        if exts and os.path.splitext(f.get("name", ""))[1].lower() not in exts:
            continue
        key = f.get("sha256") or f.get("md5")
        if not key:
            continue
        total += 1
        groups[(size, key)].append(path)
    print(f"  файлов проверено: {total}", file=sys.stderr)
    dups = [(size, sorted(paths)) for (size, _), paths in groups.items() if len(paths) > 1]
    dups.sort(key=lambda x: x[0] * (len(x[1]) - 1), reverse=True)
    return dups


def main():
    ap = argparse.ArgumentParser(description="Поиск дубликатов на Яндекс Диске")
    ap.add_argument("--token", default=os.environ.get("YANDEX_TOKEN"),
                    help="OAuth-токен (или переменная окружения YANDEX_TOKEN)")
    ap.add_argument("--folder", help='проверить только эту папку, например "/Фото/Дети"')
    ap.add_argument("--min-size", default="1KB",
                    help="игнорировать файлы меньше этого размера (по умолчанию 1KB)")
    ap.add_argument("--ext", nargs="*",
                    help="искать только эти расширения, например: --ext jpg png mp4")
    ap.add_argument("--csv", help="сохранить отчёт в CSV-файл для Excel")
    args = ap.parse_args()

    if not args.token:
        sys.exit("Укажите токен: --token ВАШ_ТОКЕН (или переменную окружения YANDEX_TOKEN)")

    exts = {("." + e.lower().lstrip(".")) for e in args.ext} if args.ext else None
    folder = normalize_folder(args.folder)

    print("Шаг 1/2: получаю список файлов с Яндекс Диска…", file=sys.stderr)
    files = list(list_all_files(args.token))
    print("Шаг 2/2: ищу дубликаты…\n", file=sys.stderr)
    dups = find_duplicates(files, folder, parse_size(args.min_size), exts)

    if not dups:
        print("Дубликатов не найдено.")
        return

    wasted = 0
    for i, (size, paths) in enumerate(dups, 1):
        extra = size * (len(paths) - 1)
        wasted += extra
        print(f"Группа {i}: {len(paths)} копии по {human(size)} (лишнее: {human(extra)})")
        for p in paths:
            print(f"    {p}")
        print()

    print(f"Групп дубликатов: {len(dups)}")
    print(f"Можно освободить: {human(wasted)}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Группа", "Имя файла", "Папка", "Полный адрес файла",
                        "Ссылка на папку", "Размер", "Размер (байт)"])
            for i, (size, paths) in enumerate(dups, 1):
                for p in paths:
                    name = p.rsplit("/", 1)[-1]
                    parent = p.rsplit("/", 1)[0] or "disk:/"
                    w.writerow([i, name, parent, p, web_link(p), human(size), size])
        print(f"Отчёт сохранён: {args.csv}")


if __name__ == "__main__":
    main()
