"""Печатает раздел CHANGELOG.md для указанной версии (текст релиза на GitHub)."""
import re
import sys

version = sys.argv[1]
text = open("CHANGELOG.md", encoding="utf-8").read()
m = re.search(rf"^##\s*\[?{re.escape(version)}\]?[^\n]*\n(.*?)(?=^##\s|\Z)", text, re.M | re.S)
print(m.group(1).strip() if m else f"Версия {version}")
