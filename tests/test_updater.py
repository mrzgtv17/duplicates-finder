import hashlib

import pytest

from app import updater


def test_versions():
    assert updater.version_tuple("v1.10.0") == (1, 10, 0)
    assert updater.is_newer("1.10.0", "1.9.9")
    assert not updater.is_newer("1.3.0", "1.3.0")


def test_parse_release():
    rel = updater.parse_release({
        "tag_name": "v2.0.1", "body": " Новое ", "html_url": "https://x",
        "assets": [{"name": "SHA256SUMS.txt", "browser_download_url": "https://s"}]})
    assert rel["version"] == "2.0.1" and rel["notes"] == "Новое"
    assert rel["assets"] == {"SHA256SUMS.txt": "https://s"}


def test_parse_sums():
    h = "a" * 64
    assert updater.parse_sums(f"{h}  DuplicatesFinder-Windows.exe\nmusor\n") == {
        "DuplicatesFinder-Windows.exe": h}


def _release(sums_text):
    return {"version": "9.9.9", "assets": {
        updater.MAC_ASSET: "https://example/mac.zip", updater.SUMS_ASSET: "https://example/sums"}}, sums_text


@pytest.mark.parametrize("good", [True, False])
def test_download_update_checks_sha(monkeypatch, tmp_path, good):
    payload = b"new app"
    real = hashlib.sha256(payload).hexdigest()
    sums = f"{real if good else 'b' * 64}  {updater.MAC_ASSET}\n"
    rel, _ = _release(sums)
    monkeypatch.setattr(updater, "platform_asset", lambda: updater.MAC_ASSET)
    monkeypatch.setattr(updater.sys, "platform", "darwin")
    monkeypatch.setattr(updater, "_get", lambda url, **k: sums.encode())

    def fake_download(url, dest, progress=None):
        with open(dest, "wb") as f:
            f.write(payload)
        return real

    monkeypatch.setattr(updater, "download", fake_download)
    if good:
        path = updater.download_update(rel)
        assert open(path, "rb").read() == payload
    else:
        with pytest.raises(updater.UpdateError, match="Контрольная сумма"):
            updater.download_update(rel)


def test_download_update_requires_sums(monkeypatch):
    monkeypatch.setattr(updater, "platform_asset", lambda: updater.MAC_ASSET)
    rel = {"version": "9", "assets": {updater.MAC_ASSET: "u"}}
    with pytest.raises(updater.UpdateError, match="контрольных сумм"):
        updater.download_update(rel)


def test_clean_environment():
    env = updater.clean_environment({
        "PATH": "C:\\Windows", "_PYI_APPLICATION_HOME_DIR": "C:\\Temp\\_MEI1",
        "_PYI_ARCHIVE_FILE": "x.exe", "_MEIPASS2": "C:\\Temp\\_MEI1",
        "TCL_LIBRARY": "C:\\Temp\\_MEI1\\_tcl_data", "TK_LIBRARY": "C:\\Temp\\_MEI1\\_tk_data"})
    assert env == {"PATH": "C:\\Windows", "PYINSTALLER_RESET_ENVIRONMENT": "1"}
