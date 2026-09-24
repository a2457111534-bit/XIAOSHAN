"""向当前焦点窗口注入键盘事件（Windows 版，SendInput）：粘贴(Ctrl+V)、退格、组合键。

接口与 mac 版 voice_typist/inject.py 保持一致，使引擎逻辑可逐行复用：
cmd 参数在 Windows 上对应 Ctrl 键。只用 ctypes，无第三方依赖。
非 Windows 平台 import 安全（真正调用时才报错），便于跨平台跑逻辑测试。
"""
import ctypes
import sys
import time

IS_WIN = sys.platform == "win32"

# Windows 虚拟键码（与 mac 版同名常量、不同值）
VK_BACKSPACE = 0x08
VK_RETURN = 0x0D
VK_END = 0x23
VK_A = 0x41
VK_V = 0x56
VK_Z = 0x5A
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12        # Alt

if IS_WIN:
    import ctypes.wintypes as wt

    _ULONG_PTR = ctypes.c_size_t

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                    ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                    ("dwExtraInfo", _ULONG_PTR)]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                    ("time", wt.DWORD), ("dwExtraInfo", _ULONG_PTR)]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wt.DWORD), ("union", _INPUTUNION)]

    _KEYEVENTF_KEYUP = 0x0002
    _KEYEVENTF_UNICODE = 0x0004
    _INPUT_KEYBOARD = 1
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    # 句柄是 64 位指针值：不声明 argtypes 时 ctypes 按 32 位 int 转换，
    # 高地址句柄（>2^31）会抛 "int too long to convert"，打字全部失败
    _kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = ctypes.c_void_p
    _kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalFree.restype = ctypes.c_void_p
    _user32.SetClipboardData.argtypes = [wt.UINT, ctypes.c_void_p]
    _user32.SetClipboardData.restype = ctypes.c_void_p
    _user32.OpenClipboard.argtypes = [ctypes.c_void_p]

    def _key(vk, up=False):
        """发一个键盘事件（按下或抬起）。"""
        inp = _INPUT(type=_INPUT_KEYBOARD)
        inp.union.ki = _KEYBDINPUT(
            wVk=vk, wScan=0,
            dwFlags=_KEYEVENTF_KEYUP if up else 0, time=0, dwExtraInfo=0)
        _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


# ---- 剪贴板 ----

_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002


def set_clipboard_text(text):
    """把文本放进系统剪贴板（CF_UNICODETEXT）。剪贴板被占用时重试约1秒。"""
    if not IS_WIN:
        raise RuntimeError("set_clipboard_text 仅 Windows 可用")
    data = text.encode("utf-16-le") + b"\x00\x00"
    last_err = None
    for _ in range(20):
        if not _user32.OpenClipboard(None):
            time.sleep(0.05)
            continue
        try:
            _user32.EmptyClipboard()
            h = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
            if not h:
                raise RuntimeError("GlobalAlloc 失败")
            p = _kernel32.GlobalLock(h)
            if not p:
                _kernel32.GlobalFree(h)
                raise RuntimeError("GlobalLock 失败")
            ctypes.memmove(p, data, len(data))
            _kernel32.GlobalUnlock(h)
            # 成功后所有权归系统，不要 GlobalFree
            if not _user32.SetClipboardData(_CF_UNICODETEXT, h):
                _kernel32.GlobalFree(h)
                raise RuntimeError("SetClipboardData 失败")
            return
        except RuntimeError as e:
            last_err = e
            time.sleep(0.05)
        finally:
            _user32.CloseClipboard()
    raise RuntimeError(f"剪贴板打不开（被其他程序占用）: {last_err}")


def paste_clipboard():
    """往当前焦点处粘贴剪贴板内容（合成 Ctrl+V，原子操作，零漂移）。"""
    if not IS_WIN:
        raise RuntimeError("paste_clipboard 仅 Windows 可用")
    time.sleep(0.05)   # 等剪贴板与焦点稳定
    _key(VK_CONTROL)
    time.sleep(0.01)
    _key(VK_V)
    time.sleep(0.01)
    _key(VK_V, up=True)
    time.sleep(0.01)
    _key(VK_CONTROL, up=True)
    time.sleep(0.02)


def type_text(text: str, delay: float = 0.0, should_abort=None) -> bool:
    """把 text 打进当前光标处。剪贴板+粘贴；剪贴板长期被占时退回逐字注入。"""
    try:
        set_clipboard_text(text)
        paste_clipboard()
    except Exception:
        type_text_unicode(text)
    return True


def type_text_unicode(text: str, delay: float = 0.003) -> bool:
    """逐字符 UNICODE 键盘事件注入：不碰剪贴板的兜底上屏（比粘贴慢但稳）。"""
    if not IS_WIN:
        raise RuntimeError("type_text_unicode 仅 Windows 可用")
    for ch in text:
        units = ([0xD800 + ((ord(ch) - 0x10000) >> 10),
                  0xDC00 + ((ord(ch) - 0x10000) & 0x3FF)]
                 if ord(ch) > 0xFFFF else [ord(ch)])   # 增补平面拆代理对
        for u in units:
            for up in (False, True):
                inp = _INPUT(type=_INPUT_KEYBOARD)
                inp.union.ki = _KEYBDINPUT(
                    wVk=0, wScan=u,
                    dwFlags=_KEYEVENTF_UNICODE | (_KEYEVENTF_KEYUP if up else 0),
                    time=0, dwExtraInfo=0)
                _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
                time.sleep(delay if up else 0.001)
    return True


def tap_key(code: int, cmd=False, shift=False, option=False, control=False,
            repeat: int = 1, delay: float = 0.005, should_abort=None) -> bool:
    """敲一次键；repeat>1 用于连发（如退格 N 次）。返回是否完整发完。

    cmd/control 都映射为 Ctrl（与 mac 版签名保持一致，引擎代码可复用）。
    修饰键用真实的按下/抬起事件包住按键。
    """
    if not IS_WIN:
        raise RuntimeError("tap_key 仅 Windows 可用")
    mods = []
    if cmd or control:
        mods.append(VK_CONTROL)
    if shift:
        mods.append(VK_SHIFT)
    if option:
        mods.append(VK_MENU)
    for m in mods:
        _key(m)
        time.sleep(0.005)
    ok = True
    try:
        for _ in range(repeat):
            if should_abort is not None and should_abort():
                ok = False
                break
            _key(code)
            if delay:
                time.sleep(delay)
            _key(code, up=True)
            if delay:
                time.sleep(delay)
    finally:
        for m in reversed(mods):
            _key(m, up=True)
            time.sleep(0.005)
    return ok
