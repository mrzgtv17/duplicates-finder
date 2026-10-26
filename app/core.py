"""Логика поиска и удаления дубликатов (без интерфейса — удобно тестировать)."""

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

def parse_size(text: str) -> int:
    text = text.strip().upper().replace(" ", "")
    if not text:
        return 0
    units = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "КБ": 1024, "МБ": 1024 ** 2,
             "ГБ": 1024 ** 3, "B": 1, "Б": 1}
    for unit, mult in units.items():
        if text.endswith(unit):
            return int(float(text[: -len(unit)].replace(",", ".")) * mult)
    return int(float(text.replace(",", ".")))


def human(size: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ПБ"


def parse_exts(text: str):
    parts = [p.strip().lower().lstrip(".") for p in text.replace(",", " ").split()]
    return {"." + p for p in parts if p} or None


class Cancelled(Exception):
    pass


# ───────────────────────── поиск на компьютере ─────────────────────────

CHUNK = 1024 * 1024
PARTIAL = 64 * 1024
SKIP_DIRS = {"$RECYCLE.BIN", "System Volume Information", "$Recycle.Bin",
             ".Trash", ".Trashes", ".Spotlight-V100", ".fseventsd"}


def file_hash(path, limit=None, stop=None):
    h = hashlib.blake2b(digest_size=20)
    try:
        with open(path, "rb") as f:
            if limit:
                h.update(f.read(limit))
            else:
                while block := f.read(CHUNK):
                    if stop is not None and stop.is_set():
                        raise Cancelled
                    h.update(block)
    except OSError:
        return None
    return h.hexdigest()


def local_duplicates(root, min_size, exts, report, stop):
    root = os.path.abspath(root)
    by_size = defaultdict(list)
    count = 0
    report("Сканирую файлы…")
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        if stop.is_set():
            raise Cancelled
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
                if count % 2000 == 0:
                    report(f"Сканирую файлы… найдено {count}")

    candidates = [(s, p) for s, p in by_size.items() if len(p) > 1]
    total = sum(len(p) for _, p in candidates)
    report(f"Файлов: {count}. Сравниваю {total} похожих по размеру…")

    def group(paths, limit):
        g = defaultdict(list)
        for p in paths:
            if stop.is_set():
                raise Cancelled
            h = file_hash(p, limit, stop)
            if h:
                g[h].append(p)
        return [x for x in g.values() if len(x) > 1]

    result, done = [], 0
    for size, paths in candidates:
        for pg in group(paths, PARTIAL):
            if size <= PARTIAL:
                result.append((size, sorted(pg)))
            else:
                for fg in group(pg, None):
                    result.append((size, sorted(fg)))
        done += len(paths)
        report(f"Сравниваю файлы… {done} из {total}", done / total if total else 1)
    return result


# ───────────────────────── поиск на Яндекс Диске ─────────────────────────

API = "https://cloud-api.yandex.net/v1/disk/resources/files"
PAGE = 1000
FIELDS = "items.name,items.path,items.size,items.md5,items.sha256"


def api_get(params, token):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"OAuth {token}"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise RuntimeError("Токен неверный или устарел. Получите новый токен.")
            if e.code == 403:
                raise RuntimeError("У токена нет доступа к диску (нужно право cloud_api:disk.read).")
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Ошибка API {e.code}: {e.read().decode('utf-8', 'ignore')}")
        except urllib.error.URLError as e:
            if attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Нет связи с Яндекс Диском: {e.reason}")
    return {}


def normalize_folder(folder):
    folder = (folder or "").strip()
    if not folder or folder == "/":
        return None
    if folder.startswith("disk:"):
        folder = folder[5:]
    return "disk:/" + folder.strip("/") + "/"


def yandex_link(path):
    p = path[5:] if path.startswith("disk:") else path
    return "https://disk.yandex.ru/client/disk" + urllib.parse.quote(p.rsplit("/", 1)[0])


def yandex_duplicates(token, folder, min_size, exts, report, stop):
    folder = normalize_folder(folder)
    groups = defaultdict(list)
    offset = 0
    while True:
        if stop.is_set():
            raise Cancelled
        report(f"Получаю список файлов с Яндекс Диска… {offset}")
        items = api_get({"limit": PAGE, "offset": offset, "fields": FIELDS}, token).get("items", [])
        for f in items:
            path, size = f.get("path", ""), f.get("size", 0)
            if folder and not path.startswith(folder):
                continue
            if size < min_size:
                continue
            if exts and os.path.splitext(f.get("name", ""))[1].lower() not in exts:
                continue
            key = f.get("sha256") or f.get("md5")
            if key:
                groups[(size, key)].append(path)
        offset += len(items)
        if len(items) < PAGE:
            break
    return [(size, sorted(p)) for (size, _), p in groups.items() if len(p) > 1]


# ───────────────────────── удаление в корзину ─────────────────────────

def _unique_dest(folder, name):
    dest = os.path.join(folder, name)
    base, ext = os.path.splitext(name)
    n = 1
    while os.path.exists(dest):
        dest = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return dest


def move_to_trash(path):
    """Перемещает файл в Корзину системы (его можно восстановить)."""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise RuntimeError("файл уже не существует")

    if sys.platform == "darwin":
        script = ['-e', 'on run argv',
                  '-e', 'tell application "Finder" to delete (POSIX file (item 1 of argv) as alias)',
                  '-e', 'end run']
        r = subprocess.run(["osascript", *script, path], capture_output=True, text=True)
        if r.returncode != 0 and os.path.exists(path):
            # запасной вариант — перенести в ~/.Trash вручную
            import shutil
            trash = os.path.expanduser("~/.Trash")
            shutil.move(path, _unique_dest(trash, os.path.basename(path)))

    elif sys.platform.startswith("win"):
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                        ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                        ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

        FO_DELETE, FOF_ALLOWUNDO, FOF_NOCONFIRMATION, FOF_SILENT, FOF_NOERRORUI = 3, 0x40, 0x10, 0x4, 0x400
        op = SHFILEOPSTRUCTW(None, FO_DELETE, path + "\0", None,
                             FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI,
                             False, None, None)
        code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if code != 0 or op.fAnyOperationsAborted:
            raise RuntimeError(f"Windows не смог переместить файл в корзину (код {code})")

    else:
        r = subprocess.run(["gio", "trash", path], capture_output=True, text=True)
        if r.returncode != 0 and os.path.exists(path):
            import shutil
            trash = os.path.expanduser("~/.local/share/Trash/files")
            os.makedirs(trash, exist_ok=True)
            shutil.move(path, _unique_dest(trash, os.path.basename(path)))

    if os.path.exists(path):
        raise RuntimeError("не удалось переместить файл в корзину")


def yandex_trash(path, token):
    """Перемещает файл в Корзину Яндекс Диска (его можно восстановить)."""
    url = ("https://cloud-api.yandex.net/v1/disk/resources?"
           + urllib.parse.urlencode({"path": path, "permanently": "false"}))
    req = urllib.request.Request(url, method="DELETE",
                                 headers={"Authorization": f"OAuth {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60):
            pass
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return  # файла уже нет
        if e.code in (401, 403):
            raise RuntimeError("у токена нет права на изменение диска (нужно cloud_api:disk.write). "
                               "Получите токен на Полигоне заново.")
        raise RuntimeError(f"ошибка API {e.code}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"нет связи с Яндекс Диском: {e.reason}")




# ───────────────────────── отчёт ─────────────────────────

def split_path(p, source="local"):
    """Возвращает (имя файла, папка)."""
    if source == "yandex":
        name = p.rsplit("/", 1)[-1]
        return name, (p.rsplit("/", 1)[0] or "disk:/")
    return os.path.basename(p), os.path.dirname(p)


def write_csv(fname, results, source="local"):
    """Сохраняет отчёт для Excel (CSV с разделителем «;» и BOM для кириллицы)."""
    import csv
    with open(fname, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        head = ["Группа", "Имя файла", "Папка", "Полный адрес файла"]
        if source == "yandex":
            head.append("Ссылка на папку")
        w.writerow(head + ["Размер", "Размер (байт)"])
        for i, (size, paths) in enumerate(results, 1):
            for p in paths:
                name, parent = split_path(p, source)
                row = [i, name, parent, p]
                if source == "yandex":
                    row.append(yandex_link(p))
                w.writerow(row + [human(size), size])
