"""会话缓冲区：记住本软件打出去的全部文字。

一切语音删除/替换都建立在两个假设上：
1. 缓冲区 == 目标 App 里由小删打出的文字；
2. 光标一直停在缓冲区末尾（没被手动移动过）。

所以小删能“数着打、数着删”：删掉区间 [a,b) =
退格 (总长-a) 次，把 b 之后的内容重新打一遍。
"""
_SENTENCE_END = "。！？!?；;\n"


def fuzzy_rfind(text, sub):
    """在text里找sub最后一次出现；精确失败时按拼音(无调)匹配。
    供“删除N个X”等批量操作复用。返回(起,止)或None。"""
    i = text.rfind(sub)
    if i >= 0:
        return (i, i + len(sub))
    from pypinyin import lazy_pinyin
    n = len(sub)
    if n == 0 or len(text) < n:
        return None
    target = [lazy_pinyin(c)[0] for c in sub]
    py = [lazy_pinyin(c)[0] for c in text]
    for i in range(len(text) - n, -1, -1):
        if py[i:i + n] == target:
            return (i, i + n)
    return None


class Session:
    def __init__(self):
        self.segments = []        # 每次听写 append 一段；任何编辑后坍缩成一段
        self.undo_stack = []      # 每次改动前的快照（语音撤销时同步缓冲区）
        self.redo_stack = []

    @property
    def text(self) -> str:
        return "".join(self.segments)

    # ---- 快照 ----
    def snapshot(self):
        self.undo_stack.append(list(self.segments))
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo_snapshot(self):
        """撤销：取出上一份快照，当前内容压入重做栈。"""
        if not self.undo_stack:
            return None
        self.redo_stack.append(list(self.segments))
        return self.undo_stack.pop()

    def redo_snapshot(self):
        if not self.redo_stack:
            return None
        self.undo_stack.append(list(self.segments))
        return self.redo_stack.pop()

    def restore(self, segments):
        self.segments = list(segments)

    # ---- 记录 ----
    def add(self, text):
        if text:
            self.segments.append(text)

    def set_full_text(self, text):
        """用输入框的真实内容整体重置（AX对齐用）。"""
        self.segments = [text] if text else []

    def reset(self):
        self.segments.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()

    # ---- 定位 ----
    def sentence_spans(self):
        """按句末标点切句，返回 [(起, 止), ...]，含标点。"""
        text = self.text
        spans, start = [], 0
        for i, ch in enumerate(text):
            if ch in _SENTENCE_END:
                spans.append((start, i + 1))
                start = i + 1
        if start < len(text):
            spans.append((start, len(text)))
        return spans

    def last_sentence_span(self):
        spans = self.sentence_spans()
        return spans[-1] if spans else None

    def last_utterance_span(self):
        """最后一次口述的区间（未做过编辑时）。"""
        if not self.segments:
            return None
        before = len("".join(self.segments[:-1]))
        return (before, before + len(self.segments[-1]))

    def find_sentence_containing(self, sub):
        for a, b in reversed(self.sentence_spans()):
            if sub in self.text[a:b]:
                return (a, b)
        return None

    def find_last_occurrence(self, sub):
        i = self.text.rfind(sub)
        return None if i < 0 else (i, i + len(sub))

    def find_all_occurrences(self, sub, variants=None):
        """sub 的所有出现位置（升序）。精确为空时依次试变体、再按拼音兜底。"""
        for v in [sub] + list(variants or []):
            spans, i = [], 0
            while True:
                j = self.text.find(v, i)
                if j < 0:
                    break
                spans.append((j, j + len(v)))
                i = j + len(v)
            if spans:
                return spans
        from pypinyin import lazy_pinyin
        n = len(sub)
        if n == 0 or len(self.text) < n:
            return []
        target = [lazy_pinyin(c)[0] for c in sub]
        py = [lazy_pinyin(c)[0] for c in self.text]
        return [(i, i + n) for i in range(len(self.text) - n + 1)
                if py[i:i + n] == target]

    def find_last_occurrence_fuzzy(self, sub):
        """精确找不到时按拼音(无调)匹配——ASR把'好'听成'号'也能删对。"""
        text = self.text
        i = text.rfind(sub)
        if i >= 0:
            return (i, i + len(sub))
        from pypinyin import lazy_pinyin
        n = len(sub)
        if n == 0 or len(text) < n:
            return None
        target = [lazy_pinyin(c)[0] for c in sub]
        py = [lazy_pinyin(c)[0] for c in text]
        for i in range(len(text) - n, -1, -1):
            if py[i:i + n] == target:
                return (i, i + n)
        return None

    def find_sentence_containing_fuzzy(self, sub):
        """含sub的句子；精确失败时按拼音兜底。"""
        for a, b in reversed(self.sentence_spans()):
            if sub in self.text[a:b]:
                return (a, b)
        from pypinyin import lazy_pinyin
        n = len(sub)
        if n == 0:
            return None
        target = [lazy_pinyin(c)[0] for c in sub]
        for a, b in reversed(self.sentence_spans()):
            seg = self.text[a:b]
            if len(seg) < n:
                continue
            py = [lazy_pinyin(c)[0] for c in seg]
            for i in range(len(seg) - n, -1, -1):
                if py[i:i + n] == target:
                    return (a, b)
        return None

    # ---- 编辑 ----
    def plan_delete(self, a, b):
        """返回 (需要的退格次数, 需要重打的尾部文本)。"""
        total = self.text
        return len(total) - a, total[b:]

    def apply_delete(self, a, b):
        text = self.text[:a] + self.text[b:]
        self.segments = [text] if text else []

    def apply_replace(self, a, b, new):
        text = self.text[:a] + new + self.text[b:]
        self.segments = [text] if text else []
