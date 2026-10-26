"""Обновление программы через GitHub Releases.

Каждый релиз на GitHub содержит файлы:
  DuplicatesFinder-macOS.zip    — приложение для Mac (Apple Silicon)
  DuplicatesFinder-Windows.exe  — программа для Windows
  SHA256SUMS.txt                — контрольные суммы для проверки скачанных файлов

Собранная программа (.app или .exe) скачивает свой файл, проверяет контрольную сумму,
заменяет себя и перезапускается. Если программа запущена из исходников (python main.py),
предлагается открыть страницу релиза.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from . import APP_VERSION, GITHUB_REPO

MAC_ASSET = "DuplicatesFinder-macOS.zip"
WIN_ASSET = "DuplicatesFinder-Windows.exe"
SUMS_ASSET = "SHA256SUMS.txt"

RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"
LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


class UpdateError(Exception):
    pass


# ───────────── настройки ─────────────

def config_dir():
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    d = os.path.join(base, "DuplicatesFinder")
    os.makedirs(d, exist_ok=True)
    return d


def load_config():
    try:
        with open(os.path.join(config_dir(), "settings.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        with open(os.path.join(config_dir(), "settings.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ───────────── версии и релизы ─────────────

def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4]) or (0,)


def is_newer(remote, local=APP_VERSION):
    return version_tuple(remote) > version_tuple(local)


def _get(url, timeout=30, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={
        "Accept": accept, "User-Agent": f"DuplicatesFinder/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_latest():
    """Возвращает описание последнего релиза: {version, notes, url, assets: {имя: ссылка}}."""
    try:
        data = json.loads(_get(LATEST_API))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("На GitHub пока нет опубликованных версий.")
        if e.code == 403:
            raise UpdateError("GitHub временно ограничил запросы. Попробуйте позже.")
        raise UpdateError(f"GitHub ответил ошибкой {e.code}.")
    except urllib.error.URLError as e:
        raise UpdateError(f"Нет связи с GitHub: {e.reason}")
    except ValueError:
        raise UpdateError("GitHub вернул непонятный ответ.")
    return parse_release(data)


def parse_release(data):
    return {
        "version": (data.get("tag_name") or "0").lstrip("vV"),
        "notes": (data.get("body") or "").strip(),
        "url": data.get("html_url") or RELEASES_PAGE,
        "assets": {a["name"]: a["browser_download_url"] for a in data.get("assets", [])
                   if "name" in a and "browser_download_url" in a},
    }


def parse_sums(text):
    """Разбирает SHA256SUMS.txt (формат «<хеш>  <имя файла>»)."""
    sums = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            sums[parts[-1].lstrip("*")] = parts[0].lower()
    return sums


# ───────────── установка ─────────────

def is_frozen():
    return bool(getattr(sys, "frozen", False))


def platform_asset():
    if sys.platform == "darwin":
        return MAC_ASSET
    if sys.platform.startswith("win"):
        return WIN_ASSET
    return None


def can_self_update():
    return is_frozen() and platform_asset() is not None


def current_app_bundle():
    """Путь к «…/Поиск дубликатов.app» для собранной программы на Mac."""
    p = os.path.abspath(sys.executable)
    while p and p != os.path.dirname(p):
        if p.endswith(".app"):
            return p
        p = os.path.dirname(p)
    raise UpdateError("Не удалось найти папку приложения (.app).")


def download(url, dest, progress=None):
    req = urllib.request.Request(url, headers={"User-Agent": f"DuplicatesFinder/{APP_VERSION}"})
    h = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while chunk := resp.read(256 * 1024):
                out.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done / total)
    except urllib.error.URLError as e:
        raise UpdateError(f"Не удалось скачать обновление: {getattr(e, 'reason', e)}")
    return h.hexdigest()


def download_update(release, progress=None):
    """Скачивает и проверяет файл обновления. Возвращает путь к скачанному файлу."""
    name = platform_asset()
    if name not in release["assets"]:
        raise UpdateError(f"В релизе {release['version']} нет файла {name}.")
    if SUMS_ASSET not in release["assets"]:
        raise UpdateError("В релизе нет файла контрольных сумм — установка отменена.")
    try:
        sums = parse_sums(_get(release["assets"][SUMS_ASSET], accept="*/*").decode("utf-8"))
    except (urllib.error.URLError, UnicodeDecodeError) as e:
        raise UpdateError(f"Не удалось получить контрольные суммы: {e}")
    expected = sums.get(name)
    if not expected:
        raise UpdateError(f"Для {name} нет контрольной суммы — установка отменена.")

    if sys.platform.startswith("win"):
        folder = os.path.dirname(os.path.abspath(sys.executable))
    else:
        folder = tempfile.mkdtemp(prefix="dupfinder-update-")
    dest = os.path.join(folder, name + ".download")
    try:
        actual = download(release["assets"][name], dest, progress)
    except PermissionError:
        raise UpdateError(f"Нет прав на запись в папку программы:\n{folder}")
    if actual != expected:
        os.remove(dest)
        raise UpdateError("Контрольная сумма не совпала — файл скачан с ошибкой. Попробуйте ещё раз.")
    return dest


_FROZEN_ENV_VARS = ("TCL_LIBRARY", "TK_LIBRARY", "TCLLIBPATH", "_MEIPASS2", "PYTHONHOME", "PYTHONPATH")


def clean_environment(env=None):
    """Окружение для запуска новой копии программы, собранной PyInstaller.

    Убирает служебные переменные текущего процесса (_PYI_*, _MEIPASS2, пути к Tcl/Tk)
    и просит загрузчик PyInstaller начать с чистого листа."""
    env = dict(os.environ if env is None else env)
    for key in list(env):
        if key.upper().startswith("_PYI_") or key.upper() in _FROZEN_ENV_VARS:
            del env[key]
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def install_and_restart(downloaded):
    """Заменяет программу скачанной версией и запускает её. Текущий процесс завершается."""
    if sys.platform.startswith("win"):
        exe = os.path.abspath(sys.executable)
        old = exe + ".old"
        try:
            if os.path.exists(old):
                os.remove(old)
            os.replace(exe, old)          # запущенный .exe можно переименовать
            os.replace(downloaded, exe)
        except OSError as e:
            if not os.path.exists(exe) and os.path.exists(old):
                os.replace(old, exe)
            raise UpdateError(f"Не удалось заменить программу: {e}")
        # Новая версия должна стартовать как самостоятельная программа: без «чистого»
        # окружения она решит, что она часть текущей, и будет искать свои файлы
        # (в т.ч. Tcl/Tk) во временной папке текущей, которая удаляется при выходе.
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([exe], env=clean_environment(), close_fds=True, creationflags=flags,
                         cwd=os.path.dirname(exe))
        os._exit(0)

    if sys.platform == "darwin":
        bundle = current_app_bundle()
        parent = os.path.dirname(bundle)
        if not os.access(parent, os.W_OK):
            raise UpdateError(f"Нет прав на запись в папку:\n{parent}")
        staging = tempfile.mkdtemp(prefix=".dupfinder-new-", dir=parent)
        r = subprocess.run(["ditto", "-x", "-k", downloaded, staging], capture_output=True, text=True)
        apps = [n for n in os.listdir(staging) if n.endswith(".app")] if r.returncode == 0 else []
        if not apps:
            shutil.rmtree(staging, ignore_errors=True)
            raise UpdateError("Архив обновления повреждён.")
        new_app = os.path.join(staging, apps[0])
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", new_app], capture_output=True)
        backup = os.path.join(staging, "previous.app")
        try:
            os.rename(bundle, backup)
            os.rename(new_app, bundle)
        except OSError as e:
            if not os.path.exists(bundle) and os.path.exists(backup):
                os.rename(backup, bundle)
            raise UpdateError(f"Не удалось заменить приложение: {e}")
        # старую версию удаляем и запускаем новую уже после выхода из текущей
        script = f'sleep 1; rm -rf "{staging}"; open "{bundle}"'
        subprocess.Popen(["/bin/sh", "-c", script], start_new_session=True)
        os._exit(0)

    raise UpdateError("Автообновление на этой системе не поддерживается.")


def cleanup_after_update():
    """Убирает файлы, оставшиеся после прошлого обновления."""
    if is_frozen() and sys.platform.startswith("win"):
        old = os.path.abspath(sys.executable) + ".old"
        for _ in range(5):
            try:
                if os.path.exists(old):
                    os.remove(old)
                break
            except OSError:
                time.sleep(0.5)
