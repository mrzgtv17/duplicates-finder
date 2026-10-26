"""Окно программы (tkinter)."""

import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from collections import defaultdict
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from . import APP_NAME, APP_VERSION, GITHUB_REPO
from . import updater
from .core import (Cancelled, human, local_duplicates, move_to_trash, parse_exts, parse_size,
                   split_path, write_csv, yandex_duplicates, yandex_link, yandex_trash)
from .updater import load_config, save_config


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.geometry("1000x650")
        self.minsize(760, 480)

        self.msgs = queue.Queue()
        self.stop = threading.Event()
        self.worker = None
        self.results = []      # [(size, [paths])]
        self.source = "local"  # или "yandex"
        self.row_path = {}     # id строки таблицы -> путь
        self.row_group = {}    # id строки таблицы -> номер группы (индекс в results)
        self.token = ""        # токен, с которым выполнялся поиск

        self.cfg = load_config()
        self.title(f"{APP_NAME} — версия {APP_VERSION}")
        self._build_menu()
        self._build()
        self.after(100, self._poll)
        self.after(1500, self._auto_check_update)

    # ---------- обновления ----------
    def _build_menu(self):
        bar = tk.Menu(self)
        upd = tk.Menu(bar, tearoff=False)
        upd.add_command(label="Проверить обновления…", command=lambda: self._check_update(silent=False))
        self.auto_var = tk.BooleanVar(value=self.cfg.get("auto_check", True))
        upd.add_checkbutton(label="Проверять при запуске", variable=self.auto_var,
                            command=self._toggle_auto)
        upd.add_separator()
        upd.add_command(label="Все версии на GitHub", command=lambda: webbrowser.open(updater.RELEASES_PAGE))
        upd.add_command(label="Сообщить об ошибке / предложить идею",
                        command=lambda: webbrowser.open(f"https://github.com/{GITHUB_REPO}/issues/new"))
        upd.add_command(label="О программе", command=lambda: messagebox.showinfo(
            "О программе", f"{APP_NAME}\nВерсия {APP_VERSION}\n\nhttps://github.com/{GITHUB_REPO}"))
        bar.add_cascade(label="Обновления", menu=upd)
        self.config(menu=bar)

    def _toggle_auto(self):
        self.cfg["auto_check"] = self.auto_var.get()
        save_config(self.cfg)

    def _auto_check_update(self):
        if not self.cfg.get("auto_check", True):
            return
        if time.time() - self.cfg.get("last_check", 0) < 12 * 3600:
            return
        self._check_update(silent=True)

    def _check_update(self, silent):
        def work():
            try:
                rel = updater.fetch_latest()
                self.after(0, lambda: self._on_check_result(rel, silent))
            except Exception as e:
                if not silent:
                    err = str(e)
                    self.after(0, lambda: messagebox.showerror("Обновления", err))

        threading.Thread(target=work, daemon=True).start()

    def _on_check_result(self, rel, silent):
        self.cfg["last_check"] = time.time()
        if silent and self.cfg.get("skip_version") == rel["version"]:
            return
        save_config(self.cfg)
        if not updater.is_newer(rel["version"]):
            if not silent:
                messagebox.showinfo("Обновления", f"У вас последняя версия ({APP_VERSION}).")
            return
        notes = rel["notes"] or "—"
        if len(notes) > 900:
            notes = notes[:900] + "…"
        head = f"Доступна новая версия {rel['version']} (у вас {APP_VERSION}).\n\nЧто нового:\n{notes}\n\n"
        if not updater.can_self_update():
            if messagebox.askyesno("Доступно обновление", head + "Открыть страницу загрузки?"):
                webbrowser.open(rel["url"])
            return
        answer = messagebox.askyesnocancel(
            "Доступно обновление",
            head + "Установить сейчас?\n\n«Да» — установить, «Нет» — пропустить эту версию, "
                   "«Отмена» — напомнить позже.")
        if answer is None:
            return
        if answer is False:
            self.cfg["skip_version"] = rel["version"]
            save_config(self.cfg)
            return
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Обновление", "Дождитесь окончания поиска или остановите его.")
            return
        self._install_update(rel)

    def _install_update(self, rel):
        self.start_btn.config(state="disabled")
        self.status_var.set("Скачиваю обновление…")
        self.bar.config(mode="determinate", maximum=1.0, value=0)

        def progress(frac):
            self.msgs.put(("status", f"Скачиваю обновление… {int(frac * 100)}%", frac))

        def work():
            try:
                path = updater.download_update(rel, progress)
                self.after(0, lambda: self._restart_into(path, rel["version"]))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: (self._finish(),
                                       self.status_var.set("Обновление не установлено."),
                                       messagebox.showerror("Ошибка обновления", err)))

        threading.Thread(target=work, daemon=True).start()

    def _restart_into(self, path, version):
        messagebox.showinfo("Обновление", f"Версия {version} скачана и проверена.\n"
                                          "Программа сейчас перезапустится.")
        try:
            self.destroy()
            updater.install_and_restart(path)
        except Exception as e:
            messagebox.showerror("Ошибка обновления", f"{e}\n\nСкачайте новую версию вручную:\n"
                                                      f"{updater.RELEASES_PAGE}")
            webbrowser.open(updater.RELEASES_PAGE)
            sys.exit(1)

    # ---------- интерфейс ----------
    def _build(self):
        pad = {"padx": 8, "pady": 4}

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="x", padx=10, pady=(10, 0))

        # вкладка «Папка на компьютере»
        t1 = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(t1, text="  Папка на компьютере  ")
        ttk.Label(t1, text="Папка или диск:").grid(row=0, column=0, sticky="w", **pad)
        self.folder_var = tk.StringVar()
        ttk.Entry(t1, textvariable=self.folder_var).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(t1, text="Выбрать…", command=self._choose_folder).grid(row=0, column=2, **pad)
        t1.columnconfigure(1, weight=1)

        # вкладка «Яндекс Диск»
        t2 = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(t2, text="  Яндекс Диск  ")
        ttk.Label(t2, text="OAuth-токен:").grid(row=0, column=0, sticky="w", **pad)
        self.token_var = tk.StringVar(value=os.environ.get("YANDEX_TOKEN", ""))
        ttk.Entry(t2, textvariable=self.token_var, show="•").grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(t2, text="Как получить?",
                   command=lambda: webbrowser.open("https://yandex.ru/dev/disk/poligon/")
                   ).grid(row=0, column=2, **pad)
        ttk.Label(t2, text="Папка на диске:").grid(row=1, column=0, sticky="w", **pad)
        self.yfolder_var = tk.StringVar(value="/")
        ttk.Entry(t2, textvariable=self.yfolder_var).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Label(t2, text="например /Фото/Дети  ( / — весь диск)", foreground="gray"
                  ).grid(row=1, column=2, sticky="w", **pad)
        t2.columnconfigure(1, weight=1)

        # общие настройки
        opts = ttk.Frame(self, padding=(10, 6))
        opts.pack(fill="x")
        ttk.Label(opts, text="Только расширения:").pack(side="left")
        self.ext_var = tk.StringVar()
        ttk.Entry(opts, textvariable=self.ext_var, width=22).pack(side="left", padx=(4, 2))
        ttk.Label(opts, text="(jpg png mp4; пусто — все)", foreground="gray").pack(side="left", padx=(0, 16))
        ttk.Label(opts, text="Мин. размер:").pack(side="left")
        self.min_var = tk.StringVar(value="1 КБ")
        ttk.Entry(opts, textvariable=self.min_var, width=9).pack(side="left", padx=4)

        self.start_btn = ttk.Button(opts, text="▶  Найти дубликаты", command=self._start)
        self.start_btn.pack(side="right")
        self.stop_btn = ttk.Button(opts, text="Остановить", command=self.stop.set, state="disabled")
        self.stop_btn.pack(side="right", padx=6)

        # прогресс
        prog = ttk.Frame(self, padding=(10, 0))
        prog.pack(fill="x")
        self.status_var = tk.StringVar(value="Выберите папку и нажмите «Найти дубликаты».")
        ttk.Label(prog, textvariable=self.status_var).pack(anchor="w")
        self.bar = ttk.Progressbar(prog, mode="determinate")
        self.bar.pack(fill="x", pady=(2, 6))

        # таблица результатов
        table = ttk.Frame(self, padding=(10, 0))
        table.pack(fill="both", expand=True)
        cols = ("group", "name", "folder", "size")
        self.tree = ttk.Treeview(table, columns=cols, show="headings", selectmode="extended")
        for c, title, w, anchor in (("group", "Группа", 70, "center"),
                                    ("name", "Имя файла", 240, "w"),
                                    ("folder", "Папка", 520, "w"),
                                    ("size", "Размер", 100, "e")):
            self.tree.heading(c, text=title)
            self.tree.column(c, width=w, anchor=anchor, stretch=(c in ("name", "folder")))
        self.tree.tag_configure("odd", background="#eef3fb", foreground="#000000")
        self.tree.tag_configure("even", background="#ffffff", foreground="#000000")
        sb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._open_selected())
        self.tree.bind("<Delete>", lambda e: self._delete_selected())
        self.tree.bind("<BackSpace>", lambda e: self._delete_selected())

        # контекстное меню (правая кнопка мыши)
        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label="Открыть папку с файлом", command=self._open_selected)
        self.menu.add_separator()
        self.menu.add_command(label="Оставить только этот файл, остальные копии удалить",
                              command=self._keep_only_selected)
        self.menu.add_command(label="Удалить выбранные", command=self._delete_selected)
        popup_btns = ("<Button-2>", "<Button-3>", "<Control-Button-1>") if sys.platform == "darwin" \
            else ("<Button-3>",)
        for btn in popup_btns:
            self.tree.bind(btn, self._popup)

        # панель действий с файлами
        actions = ttk.Frame(self, padding=(10, 8, 10, 0))
        actions.pack(fill="x")
        self.del_btn = ttk.Button(actions, text="🗑  Удалить выбранные",
                                  command=self._delete_selected, state="disabled")
        self.del_btn.pack(side="left")
        self.keep_btn = ttk.Button(actions, text="Оставить только выбранный",
                                   command=self._keep_only_selected, state="disabled")
        self.keep_btn.pack(side="left", padx=6)
        ttk.Button(actions, text="Открыть папку с файлом", command=self._open_selected
                   ).pack(side="left")
        ttk.Label(actions, text="Файлы перемещаются в Корзину — их можно восстановить.",
                  foreground="gray").pack(side="right")

        # нижняя панель
        bottom = ttk.Frame(self, padding=10)
        bottom.pack(fill="x")
        self.summary_var = tk.StringVar()
        ttk.Label(bottom, textvariable=self.summary_var, font=("", 10, "bold")).pack(side="left")
        self.save_btn = ttk.Button(bottom, text="Сохранить отчёт для Excel…",
                                   command=self._save_csv, state="disabled")
        self.save_btn.pack(side="right")

    # ---------- действия ----------
    def _choose_folder(self):
        d = filedialog.askdirectory(title="Выберите папку или диск")
        if d:
            self.folder_var.set(os.path.normpath(d))

    def _start(self):
        try:
            min_size = parse_size(self.min_var.get())
        except ValueError:
            messagebox.showerror("Ошибка", "Минимальный размер указан неверно. Пример: 1 МБ, 500 КБ")
            return
        exts = parse_exts(self.ext_var.get())

        if self.tabs.index(self.tabs.select()) == 0:
            folder = self.folder_var.get().strip()
            if not folder or not os.path.isdir(folder):
                messagebox.showerror("Ошибка", "Выберите существующую папку или диск.")
                return
            self.source = "local"
            job = lambda rep: local_duplicates(folder, min_size, exts, rep, self.stop)
        else:
            token = self.token_var.get().strip()
            if not token:
                messagebox.showerror("Ошибка", "Введите OAuth-токен Яндекс Диска.")
                return
            self.source = "yandex"
            self.token = token
            yfolder = self.yfolder_var.get()
            job = lambda rep: yandex_duplicates(token, yfolder, min_size, exts, rep, self.stop)

        self.tree.delete(*self.tree.get_children())
        self.row_path.clear()
        self.results = []
        self.summary_var.set("")
        self.stop.clear()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        for b in (self.save_btn, self.del_btn, self.keep_btn):
            b.config(state="disabled")
        self.bar.config(mode="indeterminate")
        self.bar.start(12)

        def report(text, frac=None):
            self.msgs.put(("status", text, frac))

        def run():
            try:
                self.msgs.put(("done", job(report)))
            except Cancelled:
                self.msgs.put(("cancel",))
            except Exception as e:
                self.msgs.put(("error", str(e)))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _poll(self):
        try:
            while True:
                msg = self.msgs.get_nowait()
                kind = msg[0]
                if kind == "status":
                    self.status_var.set(msg[1])
                    if msg[2] is not None:
                        if str(self.bar["mode"]) != "determinate":
                            self.bar.stop()
                            self.bar.config(mode="determinate", maximum=1.0)
                        self.bar["value"] = msg[2]
                elif kind == "done":
                    self._finish()
                    self._show(msg[1])
                elif kind == "cancel":
                    self._finish()
                    self.status_var.set("Поиск остановлен.")
                elif kind == "error":
                    self._finish()
                    self.status_var.set("Ошибка.")
                    messagebox.showerror("Ошибка", msg[1])
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _finish(self):
        self.bar.stop()
        self.bar.config(mode="determinate", maximum=1.0)
        self.bar["value"] = 0
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _show(self, results):
        results.sort(key=lambda x: x[0] * (len(x[1]) - 1), reverse=True)
        self.results = results
        self._render()
        if results:
            self.status_var.set("Готово. Двойной щелчок — открыть папку; выделите файлы и нажмите "
                                "«Удалить выбранные» (можно выделить несколько с Cmd/Ctrl).")
        else:
            self.status_var.set("Готово.")

    def _render(self):
        """Перерисовывает таблицу по self.results."""
        self.tree.delete(*self.tree.get_children())
        self.row_path.clear()
        self.row_group.clear()
        state = "normal" if self.results else "disabled"
        for b in (self.save_btn, self.del_btn, self.keep_btn):
            b.config(state=state)
        if not self.results:
            self.summary_var.set("Дубликатов не найдено 🎉")
            return
        wasted = 0
        for gi, (size, paths) in enumerate(self.results):
            wasted += size * (len(paths) - 1)
            tag = "odd" if gi % 2 == 0 else "even"
            for p in paths:
                name, parent = self._split(p)
                iid = self.tree.insert("", "end", values=(gi + 1, name, parent, human(size)),
                                       tags=(tag,))
                self.row_path[iid] = p
                self.row_group[iid] = gi
        self.summary_var.set(f"Групп дубликатов: {len(self.results)}   •   "
                             f"Можно освободить: {human(wasted)}")

    # ---------- удаление ----------
    def _popup(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if row not in self.tree.selection():
            self.tree.selection_set(row)
        self.menu.tk_popup(event.x_root, event.y_root)

    def _keep_only_selected(self):
        sel = self.tree.selection()
        if len(sel) != 1:
            messagebox.showinfo("Подсказка", "Выберите в таблице один файл — тот, который нужно оставить.")
            return
        keep = sel[0]
        gi = self.row_group[keep]
        others = [iid for iid, g in self.row_group.items() if g == gi and iid != keep]
        name, parent = self._split(self.row_path[keep])
        self._delete_rows(others, f"Оставить файл «{name}» в папке\n{parent}\n\n"
                                  f"и удалить остальные копии ({len(others)} шт.)?")

    def _delete_selected(self):
        sel = list(self.tree.selection())
        if not sel:
            messagebox.showinfo("Подсказка", "Сначала выберите файлы в таблице "
                                             "(несколько — с зажатой Cmd/Ctrl или Shift).")
            return
        # нельзя удалить все копии одного файла — хотя бы одна должна остаться
        by_group = defaultdict(list)
        for iid in sel:
            by_group[self.row_group[iid]].append(iid)
        for gi, rows in by_group.items():
            if len(rows) >= len(self.results[gi][1]):
                messagebox.showwarning(
                    "Нельзя удалить все копии",
                    f"В группе {gi + 1} выбраны все копии файла.\n\n"
                    "Хотя бы одна копия должна остаться — снимите выделение с той, "
                    "которую нужно сохранить.")
                return
        names = [self._split(self.row_path[i])[0] for i in sel]
        listing = "\n".join("• " + n for n in names[:10])
        if len(names) > 10:
            listing += f"\n…и ещё {len(names) - 10}"
        self._delete_rows(sel, f"Удалить {len(sel)} файл(ов)?\n\n{listing}")

    def _delete_rows(self, rows, question):
        if not rows:
            return
        where = "Корзину Яндекс Диска" if self.source == "yandex" else "Корзину"
        if not messagebox.askyesno("Подтвердите удаление",
                                   f"{question}\n\nФайлы будут перемещены в {where}, "
                                   "их можно будет восстановить.", icon="warning"):
            return
        self.config(cursor="watch")
        self.update_idletasks()
        deleted, errors = set(), []
        for n, iid in enumerate(rows, 1):
            path = self.row_path[iid]
            self.status_var.set(f"Удаляю {n} из {len(rows)}: {self._split(path)[0]}")
            self.update_idletasks()
            try:
                if self.source == "yandex":
                    yandex_trash(path, self.token)
                else:
                    move_to_trash(path)
                deleted.add(path)
            except Exception as e:
                errors.append(f"{self._split(path)[0]}: {e}")
        self.config(cursor="")

        # убираем удалённые файлы из результатов; группы с одной копией больше не дубликаты
        freed = 0
        new_results = []
        for size, paths in self.results:
            left = [p for p in paths if p not in deleted]
            freed += size * (len(paths) - len(left))
            if len(left) > 1:
                new_results.append((size, left))
        self.results = new_results
        self._render()

        msg = f"Удалено файлов: {len(deleted)}, освобождено: {human(freed)}."
        self.status_var.set(msg)
        if errors:
            messagebox.showerror("Не все файлы удалены",
                                 msg + "\n\nНе удалось удалить:\n" + "\n".join(errors[:15]))

    def _split(self, p):
        return split_path(p, self.source)

    def _open_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Подсказка", "Сначала выберите файл в таблице.")
            return
        path = self.row_path.get(sel[0])
        if not path:
            return
        if self.source == "yandex":
            webbrowser.open(yandex_link(path))
            return
        try:
            if sys.platform.startswith("win"):
                subprocess.run(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", path])
            else:
                subprocess.run(["xdg-open", os.path.dirname(path)])
        except OSError as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть папку: {e}")

    def _save_csv(self):
        fname = filedialog.asksaveasfilename(
            title="Сохранить отчёт", defaultextension=".csv", initialfile="дубликаты.csv",
            filetypes=[("Отчёт для Excel (CSV)", "*.csv")])
        if not fname:
            return
        try:
            write_csv(fname, self.results, self.source)
        except OSError as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить файл: {e}")
            return
        messagebox.showinfo("Готово", f"Отчёт сохранён:\n{fname}")


def main():
    updater.cleanup_after_update()
    App().mainloop()
