import csv
import threading

import pytest

from app import core


def noop(*_a, **_k):
    pass


def test_parse_size():
    assert core.parse_size("1 КБ") == 1024
    assert core.parse_size("1,5 МБ") == int(1.5 * 1024 ** 2)
    assert core.parse_size("2GB") == 2 * 1024 ** 3
    assert core.parse_size("") == 0
    with pytest.raises(ValueError):
        core.parse_size("много")


def test_human():
    assert core.human(512) == "512.0 Б"
    assert core.human(2048) == "2.0 КБ"


def test_parse_exts():
    assert core.parse_exts("jpg, .PNG mp4") == {".jpg", ".png", ".mp4"}
    assert core.parse_exts("  ") is None


def test_local_duplicates(tmp_path):
    big = b"x" * 200_000
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "photo.jpg").write_bytes(big)
    (tmp_path / "b" / "copy.jpg").write_bytes(big)
    # тот же размер и начало, но другой конец — не дубликат
    (tmp_path / "b" / "other.jpg").write_bytes(b"x" * 199_999 + b"y")
    (tmp_path / "a" / "small.png").write_bytes(b"s" * 3000)
    (tmp_path / "b" / "small2.png").write_bytes(b"s" * 3000)

    res = core.local_duplicates(str(tmp_path), 1024, None, noop, threading.Event())
    sets = sorted(sorted(p.split("/")[-1] for p in paths) for _, paths in res)
    assert sets == [["copy.jpg", "photo.jpg"], ["small.png", "small2.png"]]

    only_png = core.local_duplicates(str(tmp_path), 1024, {".png"}, noop, threading.Event())
    assert len(only_png) == 1


def test_local_cancel(tmp_path):
    (tmp_path / "f").write_bytes(b"1" * 5000)
    stop = threading.Event()
    stop.set()
    with pytest.raises(core.Cancelled):
        core.local_duplicates(str(tmp_path), 0, None, noop, stop)


def test_yandex_duplicates(monkeypatch):
    items = [
        {"name": "a.jpg", "path": "disk:/Фото/Дети/a.jpg", "size": 5000, "sha256": "s1"},
        {"name": "b.jpg", "path": "disk:/Фото/Дети/2023/b.jpg", "size": 5000, "sha256": "s1"},
        {"name": "c.jpg", "path": "disk:/Работа/c.jpg", "size": 5000, "sha256": "s1"},
        {"name": "d.jpg", "path": "disk:/Фото/d.jpg", "size": 6000, "sha256": "s2"},
    ]
    monkeypatch.setattr(core, "api_get", lambda params, token: {"items": items if params["offset"] == 0 else []})
    all_ = core.yandex_duplicates("t", "/", 1024, None, noop, threading.Event())
    assert len(all_) == 1 and len(all_[0][1]) == 3
    kids = core.yandex_duplicates("t", "/Фото/Дети", 1024, None, noop, threading.Event())
    assert len(kids[0][1]) == 2


def test_split_and_link():
    assert core.split_path("disk:/Фото/a.jpg", "yandex") == ("a.jpg", "disk:/Фото")
    assert core.yandex_link("disk:/Фото/a.jpg").startswith("https://disk.yandex.ru/client/disk/")


def test_write_csv(tmp_path):
    out = tmp_path / "r.csv"
    core.write_csv(str(out), [(10, ["/x/a.txt", "/y/a.txt"])])
    rows = list(csv.reader(out.open(encoding="utf-8-sig"), delimiter=";"))
    assert rows[0][3] == "Полный адрес файла"
    assert rows[1][3] == "/x/a.txt" and rows[2][2] == "/y"


def test_move_to_trash(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    f = tmp_path / "файл.txt"
    f.write_text("hi")
    core.move_to_trash(str(f))
    assert not f.exists()
