"""读写当前焦点文本框（Windows 版，UI Automation）。

对齐 mac 版 voice_typist/axtext.py 的接口与用途：
- read_focused：删除/替换命令执行前读输入框真实内容，把会话账本与
  现实对齐（消灭"账实不符"导致的误删）；顺带读光标位置/选中长度，
  读不到时各项返回 None（调用方兜底）。
- write_focused：把焦点文本框内容整体设为 text（原子写入，零退格序列，
  物理上不可能误删），成功后把光标移到末尾。应用不支持时返回 False。

依赖 uiautomation + comtypes（见 requirements-win.txt）。
非 Windows 平台 import 安全（调用时才报错），便于跨平台跑逻辑测试。
"""
import sys

IS_WIN = sys.platform == "win32"


def _require_win():
    if not IS_WIN:
        raise RuntimeError("win_text 仅 Windows 可用")


def _init_com():
    """UIA 是 COM 接口，调用线程必须先初始化 COM（重复调用无害）。"""
    try:
        import comtypes
        comtypes.CoInitializeEx()
    except Exception:
        pass


def _focused():
    """当前焦点控件（UIA 查询，不改变焦点）。"""
    import uiautomation as auto
    ctrl = auto.GetFocusedControl()
    if ctrl is None:
        return None
    # 有些应用的焦点控件是外壳容器，真正的编辑框在下面，最多下钻 3 层
    for _ in range(3):
        if _has_text_interface(ctrl):
            return ctrl
        try:
            children = ctrl.GetChildren()
        except Exception:
            return None
        if not children:
            return ctrl   # 找不到就返回原控件，让上层 try/except 兜底
        ctrl = children[0]
    return ctrl


def _has_text_interface(ctrl):
    try:
        if ctrl.GetValuePattern() is not None:
            return True
    except Exception:
        pass
    try:
        if ctrl.GetLegacyIAccessiblePattern() is not None:
            return True
    except Exception:
        pass
    return False


def _read_value(ctrl):
    try:
        vp = ctrl.GetValuePattern()
        if vp is not None:
            v = vp.Value
            if isinstance(v, str):
                return v
    except Exception:
        pass
    try:
        lp = ctrl.GetLegacyIAccessiblePattern()
        if lp is not None:
            v = lp.Value
            if isinstance(v, str):
                return v
    except Exception:
        pass
    return None


def _set_value(ctrl, text):
    try:
        vp = ctrl.GetValuePattern()
        if vp is not None:
            vp.SetValue(text)
            return True
    except Exception:
        pass
    try:
        lp = ctrl.GetLegacyIAccessiblePattern()
        if lp is not None:
            lp.SetValue(text)
            return True
    except Exception:
        pass
    return False


def _cursor_info(ctrl):
    """尽力读光标位置与选中长度（TextPattern），失败返回 (None, None)。"""
    try:
        import uiautomation as auto
        tp = ctrl.GetTextPattern()
        if tp is None:
            return (None, None)
        sel = tp.GetSelection()
        if not sel:
            return (None, None)
        sel = sel[0]
        doc = getattr(tp, "DocumentRange", None)
        if doc is None:
            return (None, None)
        EP = auto.TextPatternRangeEndpoint
        off = sel.CompareEndpoints(EP.Start, doc, EP.Start)
        ln = sel.CompareEndpoints(EP.End, sel, EP.Start)
        return ((off if off >= 0 else None), (ln if ln >= 0 else None))
    except Exception:
        return (None, None)


def read_focused():
    """返回 (文本|None, 光标位置|None, 选中长度|None)。"""
    _require_win()
    _init_com()
    try:
        ctrl = _focused()
        if ctrl is None:
            return (None, None, None)
        text = _read_value(ctrl)
        if text is None:
            return (None, None, None)
        cursor, sel_len = _cursor_info(ctrl)
        return (text, cursor, sel_len)
    except Exception:
        return (None, None, None)


def write_focused(text):
    """把焦点文本框内容整体设为 text（原子操作）。成功返回 True。

    写入后光标位置不确定，补一个 Ctrl+End 把光标压到末尾，
    维持"光标停在口述末尾"的前提。
    """
    _require_win()
    _init_com()
    try:
        ctrl = _focused()
        if ctrl is None:
            return False
        if not _set_value(ctrl, text):
            return False
        from . import win_inject
        win_inject.tap_key(win_inject.VK_END, cmd=True)
        return True
    except Exception:
        return False
