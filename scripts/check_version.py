"""Проверка версии в PR (запускается GitHub Actions).

• версия не изменилась  -> предупреждение: после слияния новый релиз не появится;
• версия уменьшилась    -> ошибка;
• версия увеличилась    -> в CHANGELOG.md должен быть раздел «## <версия>».
"""
import re
import subprocess
import sys

PATTERN = r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']'


def version_of(text):
    m = re.search(PATTERN, text, re.M)
    return m.group(1) if m else "0"


def vt(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))


def main():
    base = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else "origin/main"
    new = version_of(open("app/__init__.py", encoding="utf-8").read())
    try:
        old = version_of(subprocess.check_output(["git", "show", f"{base}:app/__init__.py"], text=True))
    except subprocess.CalledProcessError:
        print(f"::notice::Версия {new} (базовой версии нет — первый релиз).")
        return 0
    if vt(new) == vt(old):
        print(f"::warning::Версия не изменилась ({new}). После слияния этого PR новый релиз "
              "НЕ будет выпущен. Если PR добавляет функцию или исправление — увеличьте "
              "APP_VERSION в app/__init__.py и добавьте раздел в CHANGELOG.md.")
        return 0
    if vt(new) < vt(old):
        print(f"::error::Версия уменьшилась: {old} -> {new}.")
        return 1
    changelog = open("CHANGELOG.md", encoding="utf-8").read()
    if not re.search(rf"^##\s*\[?{re.escape(new)}\]?", changelog, re.M):
        print(f"::error::Версия увеличена до {new}, но в CHANGELOG.md нет раздела «## {new}».")
        return 1
    print(f"::notice::Версия {old} -> {new}. После слияния будет выпущен релиз v{new}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
