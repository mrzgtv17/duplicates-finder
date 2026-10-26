#!/bin/bash
# Сборка приложения для Mac: dist/DuplicatesFinder-macOS.zip
# Запуск на Mac: pip install pyinstaller && bash scripts/build_macos.sh
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(python3 scripts/get_version.py)
BUNDLE_ID="io.github.mrzgtv17.duplicatesfinder"
APP_TITLE="Поиск дубликатов"

rm -rf build dist
python3 -m PyInstaller --noconfirm --windowed \
  --name DuplicatesFinder \
  --icon assets/icon.icns \
  --osx-bundle-identifier "$BUNDLE_ID" \
  main.py

APP="dist/DuplicatesFinder.app"
PLIST="$APP/Contents/Info.plist"
setp() { plutil -replace "$1" "$2" "$3" "$PLIST"; }   # setp ключ -string|-bool значение
setp CFBundleShortVersionString -string "$VERSION"
setp CFBundleVersion -string "$VERSION"
setp CFBundleDisplayName -string "$APP_TITLE"
setp NSHighResolutionCapable -bool YES
setp LSMinimumSystemVersion -string "11.0"
setp NSAppleEventsUsageDescription -string "Чтобы перемещать удалённые дубликаты в Корзину через Finder."
setp NSDesktopFolderUsageDescription -string "Чтобы искать дубликаты на Рабочем столе."
setp NSDocumentsFolderUsageDescription -string "Чтобы искать дубликаты в папке Документы."
setp NSDownloadsFolderUsageDescription -string "Чтобы искать дубликаты в папке Загрузки."
setp NSRemovableVolumesUsageDescription -string "Чтобы искать дубликаты на флешках и внешних дисках."
setp NSNetworkVolumesUsageDescription -string "Чтобы искать дубликаты на сетевых дисках."
plutil -lint "$PLIST"

# после правки Info.plist подпись нужно обновить (ad-hoc подпись, без аккаунта разработчика)
codesign --force --deep --sign - "$APP"

mv "$APP" "dist/$APP_TITLE.app"
(cd dist && ditto -c -k --sequesterRsrc --keepParent "$APP_TITLE.app" DuplicatesFinder-macOS.zip)
echo "Готово: dist/DuplicatesFinder-macOS.zip (версия $VERSION)"
