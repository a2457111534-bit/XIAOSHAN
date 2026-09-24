"""全部 GUI，一个线程，一个 Tk root（Windows 版）。

背景：此前悬浮条/主界面/设置窗各自独立 Tk 线程，Windows 的 Tcl 在多 Tk
多线程并发下会 Tcl_Panic（tcl86t.dll 0x80000003）直接崩掉整个进程
（Windows 事件日志实测三次）。mac 版单一 rumps 主循环没这个问题。

本模块是唯一建 Tk 的地方：root 常驻隐藏，主界面/悬浮条/设置/帮助都是
它的 Toplevel，创建与操作全部经由命令队列在本线程完成；外部任意线程只
调 post 系接口。GUI 失败（缺 tkinter 等）安全降级：只少窗口，听写不受影响。
"""
import queue
import threading


class Gui:
    """线程安全外壳：所有方法可从任意线程调用。"""

    def __init__(self, app):
        self.app = app
        self.q = queue.Queue()
        self._thread = None
        self._failed = False

    # ---- 对外接口（任意线程） ----
    def post(self, name, arg=None):
        if not self._failed:
            self._ensure()
            self.q.put((name, arg))

    def show_main(self):
        self.post("main_show")

    def overlay(self, text):
        self.post("overlay", text)

    def overlay_hide(self):
        self.post("overlay_hide")

    def open_settings(self, on_save):
        self.post("settings", on_save)

    def open_help(self, title, text):
        self.post("help", (title, text))

    def shutdown(self):
        self.post("quit")

    def _ensure(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    # ---- GUI 线程 ----
    def _run(self):
        try:
            import tkinter as tk
            from tkinter import scrolledtext, ttk
        except Exception:
            self._failed = True
            return
        try:
            app = self.app
            root = tk.Tk()
            root.withdraw()   # root 只做容器，永不显示

            # == 主界面 ==
            main = tk.Toplevel(root)
            main.title("小删 · 本地离线语音输入")
            main.minsize(440, 250)
            main.withdraw()
            main.protocol("WM_DELETE_WINDOW", lambda: main.withdraw())
            mbody = ttk.Frame(main, padding=22)
            mbody.pack(fill="both", expand=True)

            m_status = tk.StringVar(value="… 启动中")
            m_status_lab = tk.Label(mbody, textvariable=m_status,
                                    font=("Microsoft YaHei UI", 15, "bold"),
                                    fg="#166534", anchor="w")
            m_status_lab.pack(fill="x")
            m_key = tk.StringVar(value="说话键：右Ctrl")
            tk.Label(mbody, textvariable=m_key, font=("Microsoft YaHei UI", 11),
                     fg="#444444", anchor="w").pack(fill="x", pady=(10, 0))
            tk.Label(mbody, text="按住说话键连续说话，说完一句停半秒自动上屏；\n"
                                "改稿说「小删除，删除上一句」；ESC 作废本轮。",
                     font=("Microsoft YaHei UI", 10), fg="#777777",
                     anchor="w", justify="left").pack(fill="x", pady=(6, 12))

            def _open_settings():
                self.post("settings", app.apply_config)

            def _toggle():
                app.toggle_enabled()

            def _open_help():
                from .win_app import HELP_TEXT
                self.post("help", ("小删 · 使用帮助", HELP_TEXT))

            mbtns = ttk.Frame(mbody)
            mbtns.pack(fill="x")
            ttk.Button(mbtns, text="设置…", command=_open_settings).pack(
                side="left", padx=(0, 6))
            m_toggle = ttk.Button(mbtns, text="暂停听写", command=_toggle)
            m_toggle.pack(side="left", padx=6)
            ttk.Button(mbtns, text="使用帮助", command=_open_help).pack(
                side="left", padx=6)
            tk.Label(mbody, text="关闭本窗口＝最小化到托盘；退出请用托盘右键菜单。",
                     foreground="#aaaaaa").pack(side="bottom", anchor="w")

            def status_snapshot():
                if app.state == "loading":
                    return "… 模型加载中", "#888888"
                if app.recognizer is None:
                    return "✕ 识别模型没加载成功（详见 run.log）", "#b91c1c"
                if app.mic_ok is False:
                    return "✕ 麦克风不可用：检查麦克风连接与系统设置", "#b91c1c"
                if not app.enabled:
                    return "⏸ 已暂停", "#92400e"
                if app.state == "recording":
                    return "● 正在听…", "#166534"
                return "● 已就绪", "#166534"

            def refresh_main():
                try:
                    txt, color = status_snapshot()
                    m_status.set(txt)
                    m_status_lab.config(fg=color)
                    m_key.set(f"说话键：{app._hotkey_disp}（设置里可改）")
                    m_toggle.config(text="恢复听写" if not app.enabled
                                    else "暂停听写")
                except Exception:
                    pass
                root.after(500, refresh_main)
            refresh_main()

            def lift(win):
                win.deiconify()
                win.attributes("-topmost", True)
                win.update()
                win.after(250, lambda: win.attributes("-topmost", False))
                win.lift()
                win.focus_force()

            # == 悬浮条 ==
            ov = tk.Toplevel(root)
            ov.overrideredirect(True)
            ov.attributes("-topmost", True)
            ov.configure(bg="#1a1a1a")
            ov.withdraw()
            ov_label = tk.Label(ov, text="● 正在听…", fg="white", bg="#1a1a1a",
                                font=("Microsoft YaHei UI", 13, "bold"),
                                anchor="w", padx=18, pady=10)
            ov_label.pack(fill="both", expand=True)
            try:
                import ctypes
                ov.update_idletasks()
                hwnd = ctypes.windll.user32.GetAncestor(ov.winfo_id(), 2)  # GA_ROOT
                style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
                ctypes.windll.user32.SetWindowLongW(
                    hwnd, -20, style | 0x08000000 | 0x00000080)   # 不抢焦点
            except Exception:
                pass
            ov_drag = {"off": None, "xy": None}

            def _ov_press(e):
                ov_drag["off"] = (ov.winfo_x(), ov.winfo_y())
                ov_drag["xy"] = (e.x_root, e.y_root)

            def _ov_move(e):
                if ov_drag["off"] is None:
                    return
                ov.geometry(f"+{ov_drag['off'][0] + e.x_root - ov_drag['xy'][0]}"
                            f"+{ov_drag['off'][1] + e.y_root - ov_drag['xy'][1]}")

            def _ov_release(_e):
                ov_drag["off"] = None

            for ev, fn in (("<Button-1>", _ov_press), ("<B1-Motion>", _ov_move),
                           ("<ButtonRelease-1>", _ov_release)):
                ov_label.bind(ev, fn)

            def _ov_place():
                try:
                    sw = ov.winfo_screenwidth()
                    sh = ov.winfo_screenheight()
                    ov.update_idletasks()
                    w = max(ov_label.winfo_reqwidth(), 200)
                    h = ov_label.winfo_reqheight() + 6
                    ov.geometry(f"{w}x{h}+{(sw - w) // 2}+{int(sh * 0.12)}")
                except Exception:
                    pass

            def overlay_show(text):
                ov_label.config(text=text[:44])
                ov.update_idletasks()
                w = max(ov_label.winfo_reqwidth(), 200)
                h = ov_label.winfo_reqheight() + 6
                ov.geometry(f"{w}x{h}+{ov.winfo_x()}+{ov.winfo_y()}")
                if not ov.winfo_viewable():
                    _ov_place()
                ov.deiconify()

            # == 设置窗（同进程只开一个；重复请求=拉起已有） ==
            settings_open = {"win": None}

            def open_settings_win(on_save):
                if settings_open["win"] is not None:
                    lift(settings_open["win"])
                    return
                try:
                    from .win_settings import build_settings
                    win = build_settings(root, on_save)
                except Exception as e:
                    self._safe_log(f"设置窗口异常: {type(e).__name__}: {e}")
                    return
                settings_open["win"] = win

                def _on_close():
                    settings_open["win"] = None
                win.protocol("WM_DELETE_WINDOW",
                             lambda: (win.destroy(), _on_close()))
                win.bind("<Destroy>", lambda e: _on_close())
                lift(win)

            # == 帮助窗（同标题只开一个） ==
            help_wins = {}

            def open_help_win(title, text):
                win = help_wins.get(title)
                if win is not None and win.winfo_exists():
                    lift(win)
                    return
                win = tk.Toplevel(root)
                win.title(title)
                win.geometry("600x500")
                st = scrolledtext.ScrolledText(
                    win, font=("Microsoft YaHei UI", 11), wrap="word",
                    padx=10, pady=10)
                st.insert("1.0", text)
                st.configure(state="disabled")
                st.pack(fill="both", expand=True, padx=10, pady=10)
                help_wins[title] = win
                lift(win)

            # == 命令泵 ==
            def poll():
                try:
                    while True:
                        name, arg = self.q.get_nowait()
                        if name == "main_show":
                            lift(main)
                        elif name == "overlay":
                            overlay_show(arg)
                        elif name == "overlay_hide":
                            ov.withdraw()
                        elif name == "settings":
                            open_settings_win(arg)
                        elif name == "help":
                            open_help_win(*arg)
                        elif name == "quit":
                            root.quit()
                            return
                except queue.Empty:
                    pass
                except Exception:
                    pass
                try:
                    root.after(50, poll)
                except Exception:
                    pass
            poll()
            root.mainloop()
            # 收尾必须在 GUI 线程内完成：先销毁再就地回收 Tk 对象。
            # 否则进程退出时主线程 GC 触碰 Tcl → Tcl_AsyncDelete 崩溃（实测）。
            try:
                root.destroy()
            except Exception:
                pass
            import gc
            gc.collect()
        except Exception:
            self._failed = True

    def _safe_log(self, msg):
        try:
            from .win_app import _log
            _log(msg)
        except Exception:
            pass
