"""Печатает APP_VERSION (используется в сборке)."""
import os
import re
import sys

root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
text = open(os.path.join(root, "app", "__init__.py"), encoding="utf-8").read()
m = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.M)
if not m:
    sys.exit("APP_VERSION не найден")
print(m.group(1))
