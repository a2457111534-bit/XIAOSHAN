"""通过辅助功能(AX)读取当前焦点文本框的真实内容和光标位置。

用途：删除/替换命令执行前，把会话缓冲区与输入框实际内容对齐，
消灭"账实不符"导致的误删。查不到时各项返回 None（调用方兜底）。

注意：systemWide 的焦点元素查询在这台机器返回 -25204，
按前台应用 PID 建 AXUIElement 再查焦点控件是通的，用这条路。
"""
import ctypes


def write_focused(text):
    """用 AX 直接把焦点文本框内容整体设为 text（原子操作，零键盘事件）。

    删除/替换的唯一安全通道：没有退格序列，不存在修饰键合并/误删。
    成功返回 True；应用不支持时返回 False（调用方回退老路径）。
    """
    try:
        import ctypes

        from AppKit import NSWorkspace
        from ApplicationServices import (
            AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
            AXUIElementSetAttributeValue, AXValueCreate,
            kAXFocusedUIElementAttribute, kAXValueAttribute,
            kAXSelectedTextRangeAttribute, kAXValueCFRangeType)

        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front is None:
            return False
        app_el = AXUIElementCreateApplication(front.processIdentifier())
        err, focused = AXUIElementCopyAttributeValue(
            app_el, kAXFocusedUIElementAttribute, None)
        if err != 0 or focused is None:
            return False
        if AXUIElementSetAttributeValue(focused, kAXValue, text) != 0:
            return False

        class _R(ctypes.Structure):
            _fields_ = [("location", ctypes.c_long), ("length", ctypes.c_long)]

        r = _R(len(text), 0)   # 光标移到末尾
        v = AXValueCreate(kAXValueCFRangeType, ctypes.byref(r))
        if v is not None:
            AXUIElementSetAttributeValue(focused, kAXSelectedTextRangeAttribute, v)
        return True
    except Exception:
        return False


def read_focused():
    """返回 (文本|None, 光标位置|None, 选中长度|None)。"""
    try:
        from AppKit import NSWorkspace
        from ApplicationServices import (
            AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
            kAXFocusedUIElementAttribute, kAXValueAttribute,
            kAXSelectedTextAttribute, kAXSelectedTextRangeAttribute)

        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front is None:
            return (None, None, None)
        app_el = AXUIElementCreateApplication(front.processIdentifier())
        err, focused = AXUIElementCopyAttributeValue(
            app_el, kAXFocusedUIElementAttribute, None)
        if err != 0 or focused is None:
            return (None, None, None)

        text = None
        err, v = AXUIElementCopyAttributeValue(focused, kAXValueAttribute, None)
        if err == 0 and v is not None:
            text = str(v)

        cursor = sel_len = None
        err, rv = AXUIElementCopyAttributeValue(
            focused, kAXSelectedTextRangeAttribute, None)
        if err == 0 and rv is not None:
            try:
                from ApplicationServices import (
                    AXValueGetValue, kAXValueCFRangeType)

                class _R(ctypes.Structure):
                    _fields_ = [("location", ctypes.c_long),
                                ("length", ctypes.c_long)]

                r = _R()
                if AXValueGetValue(rv, kAXValueCFRangeType, ctypes.byref(r)):
                    cursor, sel_len = int(r.location), int(r.length)
            except Exception:
                pass
        if cursor is None:
            err, st = AXUIElementCopyAttributeValue(
                focused, kAXSelectedTextAttribute, None)
            sel_len = len(str(st)) if (err == 0 and st) else 0
        return (text, cursor, sel_len)
    except Exception:
        return (None, None, None)
