"""向当前焦点窗口注入键盘事件：粘贴（⌘V）、退格、组合键。

文字上屏一律走“剪贴板+⌘V 粘贴”（原子操作，零漂移）；
只有删除需要连发退格。依赖辅助功能权限。
"""
import time

import Quartz

VK_BACKSPACE = 0x33
VK_RETURN = 0x24
VK_Z = 0x06
VK_V = 0x09
VK_A = 0x00


def set_clipboard_text(text):
    from AppKit import NSPasteboard
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, "public.utf8-plain-text")


def paste_clipboard():
    """往当前焦点处粘贴剪贴板内容（合成 ⌘V，标志位挂在事件自身，安全）。"""
    time.sleep(0.05)   # 等剪贴板与焦点稳定
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, VK_V, down)
        Quartz.CGEventSetFlags(ev, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.01)
    time.sleep(0.02)


# CGEventKeyboardSetUnicodeString 单个事件最多可靠携带约 20 个 UTF-16 字符
_CHUNK = 20


def _post_unicode_chunk(chunk: str) -> None:
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
        Quartz.CGEventSetFlags(ev, 0)   # 显式清零，防全局修饰键卡死时变成快捷键
        Quartz.CGEventKeyboardSetUnicodeString(ev, len(chunk), chunk)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def type_text(text: str, delay: float = 0.012, should_abort=None) -> bool:
    """把 text “打”进当前光标处。返回是否完整打完。"""
    for i in range(0, len(text), _CHUNK):
        if should_abort is not None and should_abort():
            return False
        _post_unicode_chunk(text[i:i + _CHUNK])
        if delay:
            time.sleep(delay)
    return True


def _flags(cmd=False, shift=False, option=False, control=False):
    f = 0
    if cmd:
        f |= Quartz.kCGEventFlagMaskCommand
    if shift:
        f |= Quartz.kCGEventFlagMaskShift
    if option:
        f |= Quartz.kCGEventFlagMaskAlternate
    if control:
        f |= Quartz.kCGEventFlagMaskControl
    return f


def tap_key(code: int, cmd=False, shift=False, option=False, control=False,
            repeat: int = 1, delay: float = 0.005, should_abort=None) -> bool:
    """敲一次键；repeat>1 用于连发（如退格 N 次）。返回是否完整发完。

    事件 flags 一律显式设置（无修饰键时清零）：CGEvent 不显式设 flags
    会继承系统当前修饰键状态——一旦全局 Cmd/Option 卡住（如程序在按住
    热键期间崩溃退出），退格会被合并成 ⌘+退格删整行（实测 2026-09-25）。
    """
    flags = _flags(cmd, shift, option, control)
    for _ in range(repeat):
        if should_abort is not None and should_abort():
            return False
        ev = Quartz.CGEventCreateKeyboardEvent(None, code, True)
        Quartz.CGEventSetFlags(ev, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        if delay:
            time.sleep(delay)
        ev = Quartz.CGEventCreateKeyboardEvent(None, code, False)
        Quartz.CGEventSetFlags(ev, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        if delay:
            time.sleep(delay)
    return True
