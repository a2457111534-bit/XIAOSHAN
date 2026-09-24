"""命令执行（Windows 版）：把解析出的命令变成键盘事件 + 会话缓冲区修改。

本文件与 mac 版 voice_typist/engine.py 逐行对应（v2.3 实战逻辑），
仅注入层换为 win_inject（剪贴板+Ctrl+V / SendInput）、
读写焦点文本框换为 win_text（UI Automation）。
共享的命令解析/会话账本直接复用 voice_typist 包。
"""
import threading

from voice_typist.commands import PUNCT_CHARS
from voice_typist.session import Session

from . import win_inject as inject
from . import win_text as axtext

MAX_BACKSPACES = 3000   # 绝对上限
MAX_DELETE_SPAN = 150   # 单次删除的保守跨度：超过说明目标很远，拒绝防大面积误删


def _log(msg):
    import time
    try:
        from voice_typist.config import BASE_DIR
        with open(BASE_DIR / "run.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _paste_text(text):
    """剪贴板+粘贴上屏；剪贴板被长期占用时退回逐字注入，绝不向上抛异常。"""
    try:
        inject.set_clipboard_text(text)
        inject.paste_clipboard()
    except Exception as e:
        _log(f"剪贴板不可用，逐字注入兜底: {e}")
        inject.type_text_unicode(text)


class Engine:
    def __init__(self, feedback=None):
        self.session = Session()
        self.fb = feedback
        self._lock = threading.Lock()
        self._partial = ""   # 边说边上屏的实时草稿

    # ---- 实时草稿（只进悬浮窗；输入框在说话期间零接触） ----
    def type_partial(self, text) -> bool:
        """记录草稿（悬浮窗显示用），不注入任何键。返回是否有变化。"""
        with self._lock:
            if text == self._partial:
                return False
            self._partial = text
            return True

    @property
    def draft(self):
        return self._partial

    def commit_final(self, text):
        """定稿：剪贴板+Ctrl+V 一次性粘贴进输入框（原子操作，零漂移）。"""
        with self._lock:
            self._partial = ""
            if text:
                self.session.snapshot()
                _paste_text(text)
                self.session.add(text)

    def cancel_partial(self):
        """清掉草稿（命令句不上屏）。"""
        with self._lock:
            self._partial = ""

    def is_busy(self):
        """是否正在注入键盘事件（打字/退格）。热键监听据此装聋，避免自杀。"""
        return self._lock.locked()

    # ---- 听写 ----
    def execute_dictation(self, text):
        with self._lock:
            self.session.snapshot()
            _paste_text(text)
            self.session.add(text)
        return True, ""

    # ---- 命令 ----
    def execute(self, cmd):
        with self._lock:
            return self._execute_locked(cmd)

    def _execute_locked(self, cmd):
        k = cmd.kind
        ses = self.session

        if k == "help":
            return False, "请说命令"
        if k == "unknown":
            return False, "没听懂这个命令"

        # 文字修改类命令：先读输入框真实内容，把账本对齐现实（消灭账实不符的误删）
        if k not in ("newline", "paragraph", "undo", "redo", "send"):
            try:
                text, cursor, sel_len = axtext.read_focused()
                if text is not None:
                    if sel_len:
                        return False, "输入框里有选中的文字，点一下取消选中再试"
                    if cursor is not None and cursor != len(text):
                        return False, "光标不在文字末尾，请点到最后再说命令"
                    if text != ses.text:
                        _log(f"UIA对齐: 输入框{len(text)}字/账本{len(ses.text)}字，已按实际重置")
                        ses.set_full_text(text)
                else:
                    _log("UIA读不到焦点文本框，按账本兜底")
            except Exception:
                pass   # 读不到输入框就按账本兜底（老行为）

        if k == "send":
            # 发送：直接按回车把打好的内容发出去；不碰会话账本
            # （发送后输入框通常清空，下次命令会按输入框真实内容自动对齐）
            inject.tap_key(inject.VK_RETURN)
            return True, "已发送"
        if k == "newline":
            ses.snapshot()
            inject.tap_key(inject.VK_RETURN)
            ses.add("\n")
            return True, "已换行"
        if k == "paragraph":
            ses.snapshot()
            inject.tap_key(inject.VK_RETURN, repeat=2, delay=0.05)
            ses.add("\n\n")
            return True, "已另起一段"
        if k == "undo":
            snap = ses.undo_snapshot()
            if snap is None:
                return False, "没有可撤回的内容了"
            if self._restore_by_ax(snap):
                return True, "已撤回"
            inject.tap_key(inject.VK_Z, cmd=True)
            ses.restore(snap)
            return True, "已撤销"
        if k == "redo":
            snap = ses.redo_snapshot()
            if snap is None:
                return False, "没有可恢复的内容了"
            if self._restore_by_ax(snap):
                return True, "已恢复"
            inject.tap_key(inject.VK_Z, cmd=True, shift=True)
            ses.restore(snap)
            return True, "已恢复"

        if k == "delete_last_sentence":
            span = ses.last_sentence_span()
            if not span:
                return False, "还没有打出去的内容"
            return self._delete_span(*span, desc="已删除上一句")
        if k == "delete_sentence_index":
            spans = ses.sentence_spans()
            if not spans:
                return False, "还没有打出去的内容"
            idx = len(spans) - cmd.n if cmd.reverse else cmd.n - 1
            if idx < 0 or idx >= len(spans):
                return False, f"没有倒数第{cmd.n}句" if cmd.reverse else f"没有第{cmd.n}句"
            a, b = spans[idx]
            return self._delete_span(a, b, desc=f"已删除第{cmd.n}句")
        if k == "delete_char_position":
            text = ses.text
            pos = len(text) - cmd.n if cmd.reverse else cmd.n - 1
            if pos < 0 or pos >= len(text):
                return False, "没有那个位置的字"
            return self._delete_span(pos, pos + 1, desc="已删除那个字")
        if k == "delete_last_of":
            for v in [cmd.sub] + list(getattr(cmd, "variants", None) or []):
                span = ses.find_last_occurrence(v)
                if span:
                    return self._delete_span(*span, desc=f"已删除{v}")
            # 同音兜底：ASR把字听错时按拼音找
            span = ses.find_last_occurrence_fuzzy(cmd.sub)
            if span:
                hit = ses.text[span[0]:span[1]]
                _log(f"同音兜底: {cmd.sub!r} → 实删{hit!r}")
                return self._delete_span(*span, desc=f"已删除{hit}")
            return False, f"没找到{cmd.sub}"
        if k == "delete_last_punct":
            text = ses.text
            for i in range(len(text) - 1, -1, -1):
                if text[i] in PUNCT_CHARS:
                    return self._delete_span(i, i + 1, desc="已删除标点")
            return False, "没找到标点"
        if k == "delete_all_punct":
            text = ses.text
            new = "".join(c for c in text if c not in PUNCT_CHARS)
            if new == text or not text:
                return False, "没有可删的标点"
            return self._replace_span(0, len(text), new)
        if k == "delete_utterance":
            span = ses.last_utterance_span()
            if not span:
                return False, "还没有打出去的内容"
            return self._delete_span(*span, desc="已删除刚才那段")
        if k == "delete_all":
            text = ses.text
            if not text:
                return False, "没有可删的内容"
            ses.snapshot()
            if axtext.write_focused(""):   # 原子清空，零键盘事件
                ses.set_full_text("")
                _log(f"全部清空(UIA原子写入, 原{len(text)}字)")
                if self._post_verify():
                    return True, "已全部清空"
                _log("UIA清空未生效（复核不符），改用Ctrl+A+退格重做")
            _log(f"全部清空(回退Ctrl+A+退格, {len(text)}字)")
            inject.tap_key(inject.VK_A, cmd=True)          # 全选
            inject.tap_key(inject.VK_BACKSPACE, delay=0.05)  # 删除
            ses.set_full_text("")
            self._post_verify()
            return True, "已全部清空"
        if k == "insert":
            span = ses.find_last_occurrence_fuzzy(cmd.anchor)   # 锚点同音兜底
            if not span:
                return False, f"没找到{cmd.anchor}"
            pos = span[0] if cmd.before else span[1]
            new_text = ses.text[:pos] + cmd.content + ses.text[pos:]
            ses.snapshot()
            if axtext.write_focused(new_text):
                ses.set_full_text(new_text)
                _log(f"插入[{cmd.content}]@{pos} 锚点{cmd.anchor!r}")
                if self._post_verify():
                    return True, f"已加上{cmd.content}"
                _log("UIA插入未生效（复核不符），改用退格+粘贴重做")
            n_back = len(ses.text) - pos
            if n_back > MAX_DELETE_SPAN:
                return False, "位置有点远，请手动加"
            _log(f"插入[{cmd.content}]@{pos} 回退退格{n_back}+粘贴")
            inject.tap_key(inject.VK_BACKSPACE, repeat=n_back, delay=0.002)
            _paste_text(cmd.content + ses.text[pos:])
            ses.set_full_text(new_text)
            return True, f"已加上{cmd.content}"
        if k == "insert_append":
            ses.snapshot()
            _paste_text(cmd.content)
            ses.add(cmd.content)
            return True, f"已加上{cmd.content}"
        if k == "delete_batch":
            done, fails = 0, []
            for c in cmd.subs:
                ok2, msg2 = self._execute_locked(c)
                if ok2:
                    done += 1
                else:
                    fails.append(msg2)
            if done and not fails:
                return True, f"已删除{done}处"
            if done:
                return True, f"已删除{done}处；{fails[0]}"
            return False, (fails[0] if fails else "没找到要删的内容")
        if k == "delete_ordinal":
            spans = ses.find_all_occurrences(cmd.sub, getattr(cmd, "variants", None))
            if not spans:
                return False, f"没找到{cmd.sub}"
            idx = len(spans) - cmd.n if cmd.reverse else cmd.n - 1
            if idx < 0 or idx >= len(spans):
                return False, f"只找到{len(spans)}个{cmd.sub}"
            a, b = spans[idx]
            pos = f"倒数第{cmd.n}" if cmd.reverse else f"第{cmd.n}"
            return self._delete_span(a, b, desc=f"已删除{pos}个{cmd.sub}")
        if k == "replace_ordinal":
            spans = ses.find_all_occurrences(cmd.old, getattr(cmd, "old_variants", None))
            if not spans:
                return False, f"没找到{cmd.old}"
            idx = len(spans) - cmd.n if cmd.reverse else cmd.n - 1
            if idx < 0 or idx >= len(spans):
                return False, f"只找到{len(spans)}个{cmd.old}"
            a, b = spans[idx]
            return self._replace_span(a, b, cmd.new)
        if k == "delete_n_of":
            variants = [cmd.sub] + list(getattr(cmd, "variants", None) or [])
            buf = ses.text
            found = 0
            for _ in range(cmd.n):
                sp = None
                for v in variants:
                    i = buf.rfind(v)
                    if i >= 0:
                        sp = (i, i + len(v))
                        break
                if sp is None:
                    from voice_typist.session import fuzzy_rfind
                    sp = fuzzy_rfind(buf, cmd.sub)   # 同音兜底
                if sp is None:
                    break
                found += 1
                buf = buf[:sp[0]] + buf[sp[1]:]
            if found == 0:
                return False, f"没找到{cmd.sub}"
            if found < cmd.n:
                return False, f"只找到{found}个{cmd.sub}，不够{cmd.n}个"
            ses.snapshot()
            if axtext.write_focused(buf):
                ses.set_full_text(buf)
                _log(f"删N个[{cmd.sub}×{cmd.n}] UIA原子写入 → 剩{len(buf)}字")
                if self._post_verify():
                    return True, f"已删除{cmd.n}个{cmd.sub}"
                _log("UIA删N个未生效（复核不符），改用退格重打")
            if len(ses.text) > MAX_DELETE_SPAN:
                return False, "内容有点长，请手动处理"
            _log(f"删N个[{cmd.sub}×{cmd.n}] 回退全量重打")
            inject.tap_key(inject.VK_BACKSPACE, repeat=len(ses.text), delay=0.002)
            _paste_text(buf)
            ses.set_full_text(buf)
            return True, f"已删除{cmd.n}个{cmd.sub}"
        if k == "delete_n_sentences":
            spans = ses.sentence_spans()
            if not spans:
                return False, "还没有打出去的内容"
            if cmd.n > len(spans):
                return False, f"只有{len(spans)}句，不够{cmd.n}句"
            a = spans[-cmd.n][0]
            return self._delete_span(a, len(ses.text), desc=f"已删除{cmd.n}句")
        if k == "delete_n_chars":
            n = min(cmd.n, len(ses.text))
            if n <= 0:
                return False, "还没有打出去的内容"
            a = len(ses.text) - n
            return self._delete_span(a, len(ses.text), desc=f"已删除{n}个字")
        if k == "delete_containing":
            span = ses.find_sentence_containing(cmd.sub)
            if not span:
                span = ses.find_sentence_containing_fuzzy(cmd.sub)
                if span:
                    _log(f"同音兜底(含句): {cmd.sub!r}")
            if not span:
                return False, f"没找到含有{cmd.sub}的那句"
            return self._delete_span(*span, desc="已删除那句")
        if k == "replace":
            span = None
            for o in [cmd.old] + list(getattr(cmd, "old_variants", None) or []):
                span = ses.find_last_occurrence(o)
                if span:
                    break
            if not span:
                span = ses.find_last_occurrence_fuzzy(cmd.old)   # 同音兜底
                if span:
                    _log(f"替换同音兜底: {cmd.old!r} → {ses.text[span[0]:span[1]]!r}")
            if not span:
                return False, f"没找到{cmd.old}"
            return self._replace_span(span[0], span[1], cmd.new)

        return False, "未知命令"


    def _restore_by_ax(self, snap):
        """撤回/恢复：把快照文本精确写回输入框，不赌 App 的撤销栈。

        退格+粘贴式删除在 App 的撤销栈里是多个事件，Cmd+Z 一次只回退最后一个
        （实测：说撤回，结果把重打的尾部又删掉了，像"重复删除"）。
        三层策略（仅当 AX 读得到且账实一致才动手）：
        1. 可写 → 整框原子设值，一步到位；
        2. 可读不可写（豆包等聊天框）→ 全选+粘贴快照，两步，内容同样精确；
        3. 读不到/账实不符 → 返回 False，退回 Cmd+Z（老行为）。
        """
        try:
            text, _, _ = axtext.read_focused()
            if text is None or text != self.session.text:
                return False   # 读不到/手动编辑过：不敢整框覆盖
            snap_text = "".join(snap)
            self.session.restore(snap)
            if axtext.write_focused(snap_text):
                return True
            inject.tap_key(inject.VK_A, cmd=True)          # 全选
            if snap_text:
                inject.set_clipboard_text(snap_text)
                inject.paste_clipboard()                    # 快照整体重打
            else:
                inject.tap_key(inject.VK_BACKSPACE, delay=0.05)
            return True
        except Exception:
            return False

    # ---- 底层操作 ----
    def _delete_span(self, a, b, desc):
        n_back, tail = self.session.plan_delete(a, b)
        if n_back <= 0:
            return False, "没有可删除的内容"
        if n_back > MAX_BACKSPACES:
            return False, "内容太长了，请手动删除"
        if n_back > MAX_DELETE_SPAN:
            return False, "目标离结尾有点远，怕误删，请手动处理"
        self.session.snapshot()
        new_text = self.session.text[:a] + self.session.text[b:]
        if axtext.write_focused(new_text):   # UIA原子写入：零键盘事件，不可能误删
            self.session.set_full_text(new_text)
            _log(f"删除[{a}:{b}] UIA原子写入 → 剩{len(new_text)}字")
            if self._post_verify():
                return True, desc
            _log("UIA写入未生效（复核不符），改用退格重做")
            # 复核已把账本重置回真实内容，退格参数仍然有效
        _log(f"删除[{a}:{b}] UIA不可写，回退退格{n_back}次+粘贴{len(tail)}字")
        inject.tap_key(inject.VK_BACKSPACE, repeat=n_back, delay=0.002)
        if tail:
            _paste_text(tail)
        self.session.apply_delete(a, b)
        self._post_verify()
        return True, desc

    def _replace_span(self, a, b, new):
        total = self.session.text
        n_back = len(total) - a
        if n_back > MAX_BACKSPACES:
            return False, "内容太长了，请手动修改"
        if n_back > MAX_DELETE_SPAN:
            return False, "目标离结尾有点远，怕误删，请手动处理"
        self.session.snapshot()
        new_text = total[:a] + new + total[b:]
        if axtext.write_focused(new_text):
            self.session.set_full_text(new_text)
            _log(f"替换[{a}:{b}] UIA原子写入 → {len(new_text)}字")
            if self._post_verify():
                return True, "已修改"
            _log("UIA写入未生效（复核不符），改用退格重做")
        _log(f"替换[{a}:{b}] UIA不可写，回退退格{n_back}次+粘贴")
        inject.tap_key(inject.VK_BACKSPACE, repeat=n_back, delay=0.002)
        _paste_text(new + total[b:])
        self.session.apply_replace(a, b, new)
        self._post_verify()
        return True, "已修改"

    def _post_verify(self):
        """删除/替换后复核：再读一次输入框，与账本比对。

        一致（或读不到）返回 True；不符返回 False 并把账本按实际重置——
        防止 UIA SetValue 在某些应用（Electron 等）静默无效导致"假成功"。
        """
        try:
            import time as _t
            _t.sleep(0.25)   # 等写入/粘贴落地
            text, _, _ = axtext.read_focused()
            if text is not None and text != self.session.text:
                _log(f"⚠️ 复核不符: 账本{len(self.session.text)}字 输入框{len(text)}字 → "
                     f"账本={self.session.text!r} 实际={text!r}")
                self.session.set_full_text(text)   # 以实际为准重新对齐
                return False
        except Exception:
            pass
        return True
