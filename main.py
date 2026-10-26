"""Точка входа: python main.py (и для сборки .app / .exe).

Служебные режимы для автоматических проверок на GitHub (без окна программы):
  --self-test <файл>          проверить, что Tcl/Tk работает, и записать «ok» в файл
  --self-test-restart <файл>  запустить свою копию так же, как после обновления,
                              и сразу выйти; копия через 3 с проверяет Tcl/Tk
"""
import os
import subprocess
import sys
import time


def self_test(out, delay=0.0):
    time.sleep(delay)
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.update()
        root.destroy()
        result = "ok"
    except Exception as e:  # noqa: BLE001 — нужно записать любую ошибку
        result = f"error: {e}"
    with open(out, "w", encoding="utf-8") as f:
        f.write(result)
    return 0 if result == "ok" else 1


def self_test_restart(out):
    from app.updater import clean_environment
    cmd = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, os.path.abspath(__file__)]
    flags = 0x00000008 | 0x00000200 if sys.platform.startswith("win") else 0
    subprocess.Popen(cmd + ["--self-test-delayed", out], env=clean_environment(), close_fds=True,
                     creationflags=flags)
    os._exit(0)  # как при обновлении: выходим сразу, временная папка удаляется


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        sys.exit(self_test(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test-delayed":
        sys.exit(self_test(sys.argv[2], delay=3))
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test-restart":
        self_test_restart(sys.argv[2])

    from app.gui import main
    main()
