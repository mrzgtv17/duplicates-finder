#!/bin/bash
# Сборка программы для Windows: dist/DuplicatesFinder-Windows.exe
# Запуск на Windows (Git Bash): pip install pyinstaller && bash scripts/build_windows.sh
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(python scripts/get_version.py | tr -d '\r')

# сведения о версии, которые Windows показывает в свойствах файла
IFS=. read -r MA MI PA _ <<< "$VERSION.0.0"
cat > build_version.txt <<VER
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($MA, $MI, $PA, 0), prodvers=($MA, $MI, $PA, 0)),
  kids=[
    StringFileInfo([StringTable('041904B0', [
      StringStruct('FileDescription', 'Duplicates Finder'),
      StringStruct('ProductName', 'Duplicates Finder'),
      StringStruct('FileVersion', '$VERSION'),
      StringStruct('ProductVersion', '$VERSION'),
      StringStruct('OriginalFilename', 'DuplicatesFinder.exe')])]),
    VarFileInfo([VarStruct('Translation', [0x0419, 1200])])
  ]
)
VER

rm -rf build dist
python -m PyInstaller --noconfirm --onefile --windowed \
  --name DuplicatesFinder \
  --icon assets/icon.ico \
  --version-file build_version.txt \
  main.py
rm -f build_version.txt
mv dist/DuplicatesFinder.exe dist/DuplicatesFinder-Windows.exe
echo "Готово: dist/DuplicatesFinder-Windows.exe (версия $VERSION)"
