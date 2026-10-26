#!/usr/bin/env python3
"""
Поиск дубликатов файлов на диске или в папке.

Алгоритм (быстрый даже для больших дисков):
  1. Группирует файлы по размеру — файлы разного размера не могут совпадать.
  2. Среди файлов одного размера сравнивает хеш первых 64 КБ.
  3. Для оставшихся кандидатов считает полный хеш (BLAKE2b).

Скрипт НИЧЕГО не удаляет — только выводит отчёт и (по желанию) сохраняет его в CSV.

Примеры запуска:
  python find_duplicates.py D:\\
  python find_duplicates.py /media/disk --min-size 1MB --csv report.csv
"""

import argparse
import csv
import hashlib
import os
import sys
from collections import defaultdict

CHUNK = 1024 * 1024        # блок чтения при полном хешировании
PARTIAL = 64 * 1024        # сколько байт читать для быстрого хеша

SKIP_DIRS = {
    "$RECYCLE.BIN", "System Volume Information", "$Recycle.Bin",
    ".Trash", ".Trashes", ".Spotlight-V100", ".fseventsd",
}


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


def file_hash(path: str, limit: int | None = None) -> str | None:
    h = hashlib.blake2b(digest_size=20)
    try:
        with open(path, "rb") as f:
            if limit:
                h.update(f.read(limit))
            else:
                while block := f.read(CHUNK):
                    h.update(block)
    except (OSError, PermissionError):
        return None
    return h.hexdigest()


def scan(root: str, min_size: int, exts: set[str] | None) -> dict[int, list[str]]:
    by_size: dict[int, list[str]] = defaultdict(list)
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if exts and os.path.splitext(name)[1].lower() not in exts:
                continue
            path = os.path.join(dirpath, name)
            try:
                if os.path.islink(path):
                    continue
                size = os.path.getsize(path)
            except OSError:
                continue
            if size >= min_size:
                by_size[size].append(path)
                count += 1
                if count % 5000 == 0:
                    print(f"  просканировано файлов: {count}", file=sys.stderr)
    print(f"  всего файлов: {count}", file=sys.stderr)
    return by_size


def group_by_hash(paths: list[str], limit: int | None) -> list[list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for p in paths:
        h = file_hash(p, limit)
        if h:
            groups[h].append(p)
    return [g for g in groups.values() if len(g) > 1]


def find_duplicates(root: str, min_size: int, exts: set[str] | None):
    print("Шаг 1/3: сканирую файлы…", file=sys.stderr)
    by_size = scan(root, min_size, exts)

    candidates = {s: p for s, p in by_size.items() if len(p) > 1}
    print(f"Шаг 2/3: быстрая проверка {sum(map(len, candidates.values()))} кандидатов…",
          file=sys.stderr)

    result = []
    for size, paths in candidates.items():
        for partial_group in group_by_hash(paths, PARTIAL):
            if size <= PARTIAL:
                # файл целиком уже прочитан — частичный хеш = полный
                result.append((size, partial_group))
            else:
                for full_group in group_by_hash(partial_group, None):
                    result.append((size, full_group))

    print("Шаг 3/3: готово.\n", file=sys.stderr)
    result.sort(key=lambda x: x[0] * (len(x[1]) - 1), reverse=True)
    return result


def main():
    ap = argparse.ArgumentParser(description="Поиск дубликатов файлов")
    ap.add_argument("folder", help="диск или папка, например D:\\ или /media/disk")
    ap.add_argument("--min-size", default="1KB",
                    help="игнорировать файлы меньше этого размера (по умолчанию 1KB)")
    ap.add_argument("--ext", nargs="*",
                    help="искать только эти расширения, например: --ext jpg png mp4")
    ap.add_argument("--csv", help="сохранить отчёт в CSV-файл")
    args = ap.parse_args()

    if not os.path.isdir(args.folder):
        sys.exit(f"Папка не найдена: {args.folder}")

    exts = {("." + e.lower().lstrip(".")) for e in args.ext} if args.ext else None
    root = os.path.abspath(args.folder)   # чтобы в отчёте всегда был полный адрес
    dups = find_duplicates(root, parse_size(args.min_size), exts)

    if not dups:
        print("Дубликатов не найдено.")
        return

    wasted = 0
    for i, (size, paths) in enumerate(dups, 1):
        extra = size * (len(paths) - 1)
        wasted += extra
        print(f"Группа {i}: {len(paths)} копии по {human(size)} "
              f"(лишнее: {human(extra)})")
        for p in sorted(paths):
            print(f"    {p}")
        print()

    print(f"Групп дубликатов: {len(dups)}")
    print(f"Можно освободить: {human(wasted)}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Группа", "Имя файла", "Папка", "Полный адрес файла",
                        "Размер", "Размер (байт)"])
            for i, (size, paths) in enumerate(dups, 1):
                for p in sorted(paths):
                    full = os.path.abspath(p)
                    w.writerow([i, os.path.basename(full), os.path.dirname(full),
                                full, human(size), size])
        print(f"Отчёт сохранён: {args.csv}")


if __name__ == "__main__":
    main()
