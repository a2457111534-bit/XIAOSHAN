"""托盘图标（Windows 版）：pystray + PIL 现画一个麦克风图标，右键菜单管理小删。

菜单：暂停/恢复听写（文字随状态切换）、设置…、使用帮助、退出。
pystray/PIL 缺失或托盘创建失败时安全空转（只少个图标，不影响听写）。
"""
import threading


def _icon_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, 63, 63), fill="#2563eb")
    # 简笔麦克风：头 + 弧形支架 + 立柱底座
    d.rounded_rectangle((24, 12, 40, 38), radius=8, fill="white")
    d.arc((17, 22, 47, 48), start=0, end=180, fill="white", width=4)
    d.line((32, 48, 32, 53), fill="white", width=4)
    d.line((24, 53, 40, 53), fill="white", width=4)
    return img


class Tray:
    def __init__(self, app):
        self.app = app
        self.icon = None
        self.ok = False

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            import pystray
            from pystray import Menu, MenuItem

            def show_main(_item):
                self.app.indicator.show_main()

            def toggle(_item):
                self.app.toggle_enabled()

            def settings(_item):
                self.app.indicator.open_settings(self.app.apply_config)

            def help_(_item):
                from .win_app import HELP_TEXT
                self.app.indicator.open_help("小删 · 使用帮助", HELP_TEXT)

            def quit_(_item):
                self.app.request_quit()

            menu = Menu(
                MenuItem("主界面", show_main, default=True),   # 左键单击托盘弹出
                MenuItem(lambda _i: "恢复听写" if not self.app.enabled else "暂停听写",
                         toggle),
                MenuItem("设置…", settings),
                MenuItem("使用帮助", help_),
                Menu.SEPARATOR,
                MenuItem("退出", quit_),
            )
            self.icon = pystray.Icon("xiaoshan", _icon_image(),
                                     "小删 · 本地离线语音输入", menu)
            self.ok = True
            self.icon.run()
        except Exception:
            self.ok = False

    def stop(self):
        try:
            if self.icon is not None:
                self.icon.stop()
        except Exception:
            pass
