"""Рисует иконку приложения: assets/icon.png, icon.icns (Mac), icon.ico (Windows).
Запуск: python scripts/make_icons.py   (нужен Pillow)"""
import os
from PIL import Image, ImageDraw

S = 1024
here = os.path.join(os.path.dirname(__file__), "..", "assets")
im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle((80, 80, 944, 944), radius=200, fill=(46, 110, 230))


def doc(x, y, color):
    d.rounded_rectangle((x, y, x + 380, y + 480), radius=40, fill=color)
    for i in range(4):
        d.rounded_rectangle((x + 60, y + 110 + i * 80, x + 320 - (60 if i == 3 else 0), y + 140 + i * 80),
                            radius=15, fill=(170, 190, 230))


doc(220, 200, (220, 232, 252))
doc(420, 340, (255, 255, 255))
d.ellipse((560, 560, 800, 800), outline=(255, 200, 40), width=48)
d.line((770, 770, 880, 880), fill=(255, 200, 40), width=60)
im.save(os.path.join(here, "icon.png"))
im.save(os.path.join(here, "icon.icns"))
im.save(os.path.join(here, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                               (128, 128), (256, 256)])
print("Иконки созданы в", os.path.abspath(here))
