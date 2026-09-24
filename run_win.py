#!/usr/bin/env python3
"""小删 Windows 版：本地离线语音听写 + 语音编辑命令（控制台程序 + 托盘）。

用法：
  python run_win.py                 启动（托盘常驻，托盘右键可暂停/设置/退出）
  python run_win.py --settings      打开设置窗口（改说话键/指令词等）
  python run_win.py --set-key       更改说话键（按一个键即存，老接口保留）
  python run_win.py --selftest ...  自检（mic / type / uia / asr）
"""
import sys


def main(argv=None):
    argv = list(argv or [])
    if "--set-key" in argv:
        if sys.platform != "win32":
            print("改键交互只能在 Windows 上运行")
            return 1
        from voice_typist_win.win_app import set_key_interactive
        return set_key_interactive()
    if "--settings" in argv:
        from voice_typist_win.win_settings import open_settings_blocking
        open_settings_blocking()
        return 0
    if "--selftest" in argv:
        from voice_typist_win import win_selftest
        return win_selftest.main([a for a in argv if a != "--selftest"])
    from voice_typist_win.win_app import main as app_main
    return app_main(argv)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        # 硬崩溃（native 段错误等）时把 Python 栈写进 crash.log，事后可查
        import faulthandler
        from voice_typist.config import BASE_DIR
        _fh = open(BASE_DIR / "crash.log", "a", encoding="utf-8")
        faulthandler.enable(_fh)
    except Exception:
        pass
    rc = main(sys.argv[1:])
    # 直接结束进程：跳过解释器收尾对 Tk 对象的跨线程 GC（会触发
    # Tcl_AsyncDelete 崩溃/报错；日志与配置均为即时落盘，无需退出清理）
    import os
    os._exit(rc)
