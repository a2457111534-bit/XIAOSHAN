"""设置窗口（Windows 版）：改说话键/按键模式/指令词/反馈开关。

两种打开方式：
- 程序内（托盘/主界面）：由 win_gui 的唯一 GUI 线程调 build_settings()，
  保存后 on_save(cfg) 热应用，即时生效；
- 命令行 `小删.exe --settings`：独立进程自己开 Tk（单线程安全），
  保存只写 config.json，需重启小删。

说话键预设（内部名与 win_app._build_hotkey 的 _HOTKEY_SETS 一致）。
"""
import json
import re

from voice_typist.config import BASE_DIR

PRESETS = [
    ("right_ctrl", "右Ctrl（推荐）"),
    ("left_ctrl", "左Ctrl"),
    ("any_ctrl", "任意Ctrl键"),
    ("f5", "F5"),
    ("f6", "F6"),
]
_BY_NAME = dict(PRESETS)                                      # 内部名 → 显示名
_BY_DISP = {disp: name for name, disp in PRESETS}             # 显示名 → 内部名
_CUSTOM_DISP = "自定义…"


def hotkey_display(val):
    """hotkey 配置值 → 界面显示文字。"""
    if isinstance(val, dict):
        if "vk" in val:
            return f"自定义（键码 {val['vk']}）"
        if "key" in val:
            return f"自定义（{val['key']}）"
    disp = _BY_NAME.get(val)
    return disp if disp else str(val)


def build_settings(parent, on_save=None):
    """在 GUI 线程里构建设置窗口（parent 的 Toplevel），返回窗口。"""
    import tkinter as tk
    from tkinter import messagebox, ttk

    cfg_path = BASE_DIR / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}

    win = tk.Toplevel(parent)
    win.title("小删 · 设置")
    win.minsize(580, 330)
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    body = ttk.Frame(win, padding=20)
    body.pack(fill="both", expand=True)
    body.columnconfigure(1, weight=1)

    # ---- 说话键 ----
    cur = cfg.get("hotkey", "right_ctrl")
    custom = {"val": cur if isinstance(cur, dict) else None}
    if custom["val"] is not None:
        cur_disp = _CUSTOM_DISP
    else:
        # any_cmd 等 mac 遗留/未知值：运行时实际按右Ctrl处理（win_app.main 同款兜底）
        cur_disp = _BY_NAME.get(cur, _BY_NAME["right_ctrl"])

    ttk.Label(body, text="说话键").grid(row=0, column=0, sticky="w", pady=4)
    disp_var = tk.StringVar(value=cur_disp)
    combo = ttk.Combobox(body, textvariable=disp_var, state="readonly", width=16)
    combo["values"] = [d for _, d in PRESETS] + [_CUSTOM_DISP]
    combo.grid(row=0, column=1, sticky="w", padx=(12, 6), pady=4)

    key_lab = ttk.Label(body, text=hotkey_display(cur), foreground="#555")
    key_lab.grid(row=0, column=2, sticky="w")

    def _refresh_key_display():
        if disp_var.get() == _CUSTOM_DISP:
            key_lab.config(text=hotkey_display(custom["val"])
                           if custom["val"] else "（点“录制按键…”选择）")
        else:
            key_lab.config(text="")

    def _picked(*_):
        if disp_var.get() != _CUSTOM_DISP:
            custom["val"] = None
        _refresh_key_display()
    combo.bind("<<ComboboxSelected>>", _picked)

    def _capture_custom():
        cap = tk.Toplevel(win)
        cap.title("自定义说话键")
        cap.resizable(False, False)
        cap.grab_set()
        ttk.Label(cap, text="请按一个键作为“说话键”（按住它说话，松开结束）\n按 ESC 取消",
                  justify="left", padding=14).pack()
        got = {}

        def on_press(k):
            if not got:
                got["k"] = k
        try:
            from pynput import keyboard as kb
            listener = kb.Listener(on_press=on_press)
            listener.start()
        except Exception:
            cap.destroy()
            return

        def _finish():
            try:
                listener.stop()
            except Exception:
                pass
            cap.destroy()
            k = got.get("k")
            if k is None or k == kb.Key.esc:
                return
            if isinstance(k, kb.Key):
                custom["val"] = {"key": k.name}
            else:
                vk = getattr(k, "vk", None)
                if not vk:
                    messagebox.showwarning("小删", "这个键设不了，换一个", parent=win)
                    return
                custom["val"] = {"vk": vk}
            disp_var.set(_CUSTOM_DISP)
            _refresh_key_display()

        def poll():
            if got:
                _finish()
            else:
                body.after(80, poll)
        body.after(80, poll)
        cap.protocol("WM_DELETE_WINDOW", lambda: (got.__setitem__("k", None), _finish()))

    ttk.Button(body, text="录制按键…", command=_capture_custom).grid(
        row=0, column=3, sticky="w", padx=6, pady=4)
    _refresh_key_display()

    # ---- 按键模式 ----
    ttk.Label(body, text="按键模式").grid(row=1, column=0, sticky="w", pady=4)
    var_mode = tk.StringVar(value=cfg.get("push_mode", "hold"))
    modes = ttk.Frame(body)
    modes.grid(row=1, column=1, columnspan=3, sticky="w", padx=(12, 0), pady=4)
    ttk.Radiobutton(modes, text="按住说话", variable=var_mode, value="hold").pack(side="left")
    ttk.Radiobutton(modes, text="按一下开始 / 再按结束", variable=var_mode,
                    value="toggle").pack(side="left", padx=(8, 0))

    # ---- 指令词 ----
    ttk.Label(body, text="指令词").grid(row=2, column=0, sticky="w", pady=(10, 0))
    trig = cfg.get("trigger_word", [])
    var_trig = tk.StringVar(value="，".join(trig) if isinstance(trig, list) else str(trig))
    ttk.Entry(body, textvariable=var_trig).grid(
        row=3, column=0, columnspan=4, sticky="we", pady=(4, 0))
    ttk.Label(body, text="用逗号分隔；对它说“小删除，删除上一句”这类命令来改稿",
              foreground="#888").grid(row=4, column=0, columnspan=4, sticky="w")

    # ---- 反馈开关 ----
    row4 = ttk.Frame(body)
    row4.grid(row=5, column=0, columnspan=4, sticky="w", pady=(10, 0))
    var_tts = tk.BooleanVar(value=bool(cfg.get("tts_feedback", True)))
    var_snd = tk.BooleanVar(value=bool(cfg.get("sound_feedback", True)))
    ttk.Checkbutton(row4, text="出错时语音提示", variable=var_tts).pack(side="left")
    ttk.Checkbutton(row4, text="操作提示音", variable=var_snd).pack(side="left", padx=(10, 0))

    ttk.Label(body, text="程序内打开此窗口：保存即时生效；双击 小删设置.bat 打开：保存后需重启",
              foreground="#b45309").grid(row=6, column=0, columnspan=4,
                                         sticky="w", pady=(12, 2))

    def _save():
        if disp_var.get() == _CUSTOM_DISP and not custom["val"]:
            messagebox.showwarning(
                "小删", "选了“自定义…”但还没录制按键：\n点“录制按键…”按一个键，"
                "或从下拉框里选一个预设。", parent=win)
            return
        words = [w for w in re.split(r"[，,、\s]+", var_trig.get()) if w]
        if not words:
            messagebox.showwarning("小删", "指令词不能为空", parent=win)
            return
        cfg["trigger_word"] = words
        if disp_var.get() == _CUSTOM_DISP:
            hk = custom["val"]
        else:
            hk = _BY_DISP.get(disp_var.get(), "right_ctrl")
        cfg["hotkey"] = hk
        cfg["push_mode"] = "hold" if var_mode.get() == "hold" else "toggle"
        cfg["tts_feedback"] = bool(var_tts.get())
        cfg["sound_feedback"] = bool(var_snd.get())
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        if on_save:
            try:
                on_save(cfg)
                messagebox.showinfo("小删", "已保存，即时生效。", parent=win)
            except Exception:
                messagebox.showinfo("小删", "已保存，重启小删后生效。", parent=win)
        else:
            messagebox.showinfo("小删", "已保存，重启小删后生效。", parent=win)
        win.destroy()

    btns = ttk.Frame(body)
    btns.grid(row=7, column=0, columnspan=4, sticky="e", pady=(8, 0))
    ttk.Button(btns, text="取消", command=win.destroy).pack(side="left", padx=4)
    ttk.Button(btns, text="保存", command=_save).pack(side="left", padx=4)

    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"+{(sw - win.winfo_width()) // 2}+{(sh - win.winfo_height()) // 3}")
    return win


# ---- 独立进程入口（小删.exe --settings）：自己单开一个 Tk，安全 ----

def open_settings_blocking(on_save=None, on_ready=None):
    """独立打开设置窗口（阻塞至关闭）。供 --settings / 自动化预览用。"""
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    win = build_settings(root, on_save)
    win.protocol("WM_DELETE_WINDOW", root.destroy)
    if on_ready:
        root.after(800, lambda: on_ready(root))
    root.mainloop()


def preview_screenshot(png_path):
    """自动化预览（开发自查用）：开窗 → 截屏存 png → 自动关闭。"""
    def shot(root):
        try:
            from PIL import ImageGrab
            ImageGrab.grab().save(png_path)
        except Exception as e:
            print("截图失败:", e)
        root.after(200, root.destroy)
    open_settings_blocking(on_ready=shot)
