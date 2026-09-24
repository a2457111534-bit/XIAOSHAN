"""切换系统输入源：录音期间强制英文布局，防止中文输入法拦截/改写注入的字符。

用 ctypes 直调 Carbon TIS API，无第三方依赖。
"""
import ctypes
import ctypes.util

try:
    _carbon = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Carbon"))
    _cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))

    _kTISPropertyInputSourceID = ctypes.c_void_p.in_dll(
        _carbon, "kTISPropertyInputSourceID")
    _kTISPropertyInputSourceIsSelected = ctypes.c_void_p.in_dll(
        _carbon, "kTISPropertyInputSourceIsSelected")

    _carbon.TISCreateInputSourceList.restype = ctypes.c_void_p
    _carbon.TISCreateInputSourceList.argtypes = [ctypes.c_void_p, ctypes.c_bool]
    _carbon.TISGetInputSourceProperty.restype = ctypes.c_void_p
    _carbon.TISGetInputSourceProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _carbon.TISSelectInputSource.restype = ctypes.c_int
    _carbon.TISSelectInputSource.argtypes = [ctypes.c_void_p]

    _cf.CFStringGetCString.restype = ctypes.c_bool
    _cf.CFStringGetCString.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
    _cf.CFArrayGetCount.restype = ctypes.c_long
    _cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    _cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    _cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
    _cf.CFRelease.argtypes = [ctypes.c_void_p]

    _OK = True
except Exception:
    _OK = False

_ENGLISH_ID = "com.apple.keylayout.ABC"
_UTF8 = 0x08000100


def _id_of(src):
    cf = _carbon.TISGetInputSourceProperty(src, _kTISPropertyInputSourceID)
    buf = ctypes.create_string_buffer(256)
    if not _cf.CFStringGetCString(cf, buf, 256, _UTF8):
        return ""
    return buf.value.decode()


def current_id():
    """当前输入源ID，失败返回空串。"""
    if not _OK:
        return ""
    try:
        arr = _carbon.TISCreateInputSourceList(None, True)
        if not arr:
            return ""
        n = _cf.CFArrayGetCount(arr)
        found = ""
        for i in range(n):
            src = _cf.CFArrayGetValueAtIndex(arr, i)
            sel = _carbon.TISGetInputSourceProperty(
                src, _kTISPropertyInputSourceIsSelected)
            if bool(ctypes.c_bool.from_address(sel).value):
                found = _id_of(src)
                break
        _cf.CFRelease(arr)
        return found
    except Exception:
        return ""


def select_by_id(source_id):
    """切换输入源，成功返回 True。"""
    if not _OK or not source_id:
        return False
    try:
        arr = _carbon.TISCreateInputSourceList(None, True)
        if not arr:
            return False
        n = _cf.CFArrayGetCount(arr)
        target = None
        for i in range(n):
            src = _cf.CFArrayGetValueAtIndex(arr, i)
            if _id_of(src) == source_id:
                target = src
                break
        ok = False
        if target is not None:
            ok = _carbon.TISSelectInputSource(target) == 0
        _cf.CFRelease(arr)
        return ok
    except Exception:
        return False


def select_english():
    return select_by_id(_ENGLISH_ID)


def is_english(id_str):
    return id_str.startswith("com.apple.keylayout.")
