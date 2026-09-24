"""把一句话解析成：普通听写文本 / 一条编辑命令。

规则：
- 只有以指令词开头（精确，或拼音相同/极其接近且后文能解析成命令）才算命令；
- 模糊命中但后文不是命令 → 按正常听写处理，避免吃掉正常口语。
"""
import re

from pypinyin import lazy_pinyin

_STRIP = "，。！？；：、,.!?;: \u3000\"'“”‘’()（）"

_SENTENCE_END = "。！？!?；;\n"


def split_sentences(text):
    """按句末标点切句（保留标点），供逐句分派命令/听写。"""
    out, start = [], 0
    for i, ch in enumerate(text):
        if ch in _SENTENCE_END:
            out.append(text[start:i + 1])
            start = i + 1
    if start < len(text):
        out.append(text[start:])
    return [s for s in out if s.strip()]


_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


class Cmd:
    def __init__(self, kind, **kw):
        self.kind = kind
        self.__dict__.update(kw)

    def __repr__(self):
        return f"Cmd({self.__dict__})"


# 句尾"未完待续"词：断在这些词上的句号降为逗号（口语停顿≠句子结束）
_CONT_ENDINGS = sorted((
    "的", "了", "着", "在", "和", "与", "或", "及", "而", "并", "地",
    "然后", "还有", "而且", "并且", "但是", "因为", "所以", "如果",
    "虽然", "比如", "例如", "接着", "就是", "或者", "同时", "另外",
    "我觉得", "你觉得", "我认为", "你觉得呢", "对吧", "是吧",
    "好不好", "对不对", "怎么样", "行不行"), key=len, reverse=True)


def smooth_punct(text):
    """断句产生的伪句号修正：句尾是未完待续词时，句号→逗号。"""
    t = text.rstrip()
    if t.endswith("。"):
        body = t[:-1]
        for w in _CONT_ENDINGS:
            if body.endswith(w):
                return body + "，"
    return text


def cn2num(s):
    """中文数字→整数（支持到几百），失败返回 None。"""
    s = s.strip()
    if re.fullmatch(r"[0-9]+", s):
        return int(s)
    total = num = 0
    for ch in s:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
        elif ch == "十":
            total += (num or 1) * 10
            num = 0
        elif ch == "百":
            total += (num or 1) * 100
            num = 0
        else:
            return None
    return total + num


def parse(raw, trigger="小删除"):
    """trigger 支持单个词或列表（如 ["小删除", "小替换"]）。

    返回 (kind, payload)：('dictate', text) 或 ('command', Cmd)。
    """
    triggers = [trigger] if isinstance(trigger, str) else [t for t in (trigger or []) if t]
    if not raw or not raw.strip():
        return ("dictate", "")
    text = raw.strip().strip(_STRIP)
    hit, rest, exact, fuzzy = None, text, False, False
    # 第一遍精确匹配（杜绝别名表顺序不确定导致的抢占）
    for t in sorted(set(triggers), key=len, reverse=True):
        if text.startswith(t):
            hit, rest, exact = t, text[len(t):], True
            break
    # 第二遍模糊（同音/近音）兜底
    if hit is None:
        for t in sorted(set(triggers), key=len, reverse=True):
            r2, e2, f2 = _strip_trigger(text, t)
            if e2 or f2:
                hit, rest, fuzzy = t, r2, True
                break
    if hit is None:
        # 触发词吞头容错：实测“小删除”常被识别成“删除”（丢“小”字）。
        # 仅当后文明是命令短语才补触发词重解析，其余仍按听写，不劫持正常句子
        r = _repair_truncated_trigger(text, triggers)
        if r is not None:
            return r
        return ("dictate", raw.strip())
    rest = rest.strip().strip(_STRIP)
    # 儿化音容错：口语“大宝贝儿发送”会被 ASR 听出“儿”字粘在命令上。
    # 只在发送专线下剥掉（“大宝贝儿”的儿是儿化音，不会是内容）；
    # 其他指令词仅在“儿”单独成句时剥（避免误伤“儿童节”这类真内容）。
    if hit in _SEND_TRIGGERS:
        rest = re.sub(r"^儿", "", rest)
    elif rest == "儿":
        rest = ""
    rest = re.sub(r"^(?:请|帮我|给我|麻烦)", "", rest).strip()
    if not rest:
        # 触发词单独成句（精确或模糊）→ 待命等命令
        return ("command", Cmd("help", trigger=hit))
    # 发送专线（用户定制）：大宝贝唯一的指令就是发送——
    # 它下面只认发送；别的说法按正常听写上屏，绝不执行删除/替换。
    # 其他指令词下“发送”不触发回车，按字面走删词等老命令。
    if hit in _SEND_TRIGGERS:
        if _RE_SEND.fullmatch(rest):
            return ("command", Cmd("send"))
        return ("dictate", raw.strip())
    # 含“改成/替换为/喂”等替换动词的句子一律优先按替换处理（先于前缀补全和兜底删词）
    cmd = None
    m = _RE_REPLACE.fullmatch(rest)
    if m and m.group(1).strip().rstrip("的"):
        cmd = Cmd("replace", old=m.group(1).strip().rstrip("的"),
                  new=m.group(2).strip())
    # 依次尝试原样 / 补“删除”“删掉”前缀：
    # 指令词以“删除”结尾时，用户往往会省略命令里的第二个“删除”（如“小删除你好”）
    # 模糊命中（小山除等发音变体）与精确命中同等对待——
    # 误命中最坏结果是播报“没找到××”，不会删错东西
    if cmd is None:
        for prefix in ("", "删除", "删掉"):
            cmd = _match(prefix + rest, allow_bare=True)
            if cmd is not None:
                break
    if cmd is None:
        if exact:
            return ("command", Cmd("unknown", heard=rest))
        # 拼音相近但后文不是命令 → 大概率是正常说话，按听写上屏
        return ("dictate", raw.strip())
    return ("command", _apply_punct(cmd))


_REPAIR_HEADS = ("删除", "删掉", "替换", "要替换", "想替换", "把", "将")
# 发送专线触发词 + 发送说法全集（只在专线触发词下生效，见 parse()）
_SEND_TRIGGERS = ("大宝贝", "大宝贝儿")   # 儿化音变体也是发送专线
_RE_SEND = re.compile(r"(?:直接|立刻|马上|就)?(?:把它|把这句|把这条|这个|这条)?"
                      r"(?:消息?|信息?|内容)?发送(?:出去|一下|了|吧)?"
                      r"|(?:把(?:它|这句|这条|这个))?发出去(?:了|吧)?|发吧|发了")
# 替换动词全集（2026-09-24 实测扩容：替换为/修改成/修改为/更改为/换为，
# 及 ASR 把“为”听成“喂”的容错；化为/变成/变为 为 09-25 Windows 真机实测变体）。
# 长词在前：lazy 匹配时先试长动词，
# 否则“你好替换为我好”会把“替换”吞进旧词变成 old=“你好替换”。
_REPLACE_VERB = (r"(?:替换成|替换喂|替换为|修改成|修改为|改成|改喂|改为"
                 r"|更改为|更换为|换成|换喂|换为|化为|变成|变为|喂|为)")
# 替换主句式：(把/将)?A 动词 B —— “把”可带可不带
_RE_REPLACE = re.compile(rf"(?:把|将)?(.{{1,30}}?){_REPLACE_VERB}(.{{0,80}})")
# 吞头容错用的结构探测（无捕获组，只判断“像不像替换句”）
_RE_REPLACE_STRUCT = re.compile(rf"(?:把|将)?.{{1,30}}?{_REPLACE_VERB}.{{0,80}}")


_REPAIR_VERBS = ("删除", "删掉", "撤回", "撤销", "收回", "反悔", "发送", "恢复", "上一句", "刚才", "最后", "倒数",
                 "第", "全部", "所有", "标点", "句号", "逗号", "问号", "问好", "逗口",
                 "叹号", "顿号", "分号", "冒号", "换行", "另起")


def _repair_truncated_trigger(text, triggers):
    """触发词吞头容错：ASR 常把「小删除/小替换」整个吞掉或听错。

    删除系（删除/删掉）：截断头后以命令动词开头（可带 请/帮我/给我/麻烦）
    且 ≤20 字才补触发词；
    替换系（替换/要替换，小→要误识）：后文必须呈「(把)A替换动词B」结构；
    裸把/将开头：要求整句就是一条 ≤40 字的替换短语（已知取舍：口述内容
    本身就是"把A改成B"形状的正文会被当命令——概率极低，换取吞头可用性）。
    解不出真命令则放弃，按听写处理。
    """
    head = next((h for h in _REPAIR_HEADS if text.startswith(h)), None)
    if head is None:
        return None
    rest = text[len(head):]
    probe = re.sub(r"^(?:请|帮我|给我|麻烦)", "", rest)
    if head in ("删除", "删掉"):
        if len(probe) > 20 or not probe.startswith(_REPAIR_VERBS):
            return None
    elif head in ("把", "将"):
        if len(rest) > 40 or not _RE_REPLACE_STRUCT.fullmatch(head + rest):
            return None
    else:   # 替换系
        if len(probe) > 40 or not _RE_REPLACE_STRUCT.fullmatch(probe):
            return None
    kind, payload = parse(triggers[0] + rest, trigger=triggers)
    if kind == "command" and payload.kind not in ("help", "unknown"):
        return (kind, payload)
    return None


def _positional_replace(cmd):
    """把 old 里带序数定位的替换（倒数第二个句号为逗号）转成 replace_ordinal。"""
    m = re.fullmatch(r"(倒数第|第)([零一二两三四五六七八九十百0-9]{1,4})个(.{1,10})", cmd.old)
    rev = n = old_sub = None
    if m:
        rev = (m.group(1) == "倒数第")
        n = cn2num(m.group(2))
        old_sub = m.group(3)
    else:
        m2 = re.fullmatch(r"最后(一)?个(.{1,10})", cmd.old)
        if m2:
            rev, n, old_sub = True, 1, m2.group(2)
    if not n or not old_sub or not old_sub.strip():
        return cmd
    vs = punct_of(old_sub)
    nv = punct_of(cmd.new)
    return Cmd("replace_ordinal", old=(vs[0] if vs else old_sub),
               old_variants=(vs or [old_sub]),
               new=(nv[0] if nv else cmd.new), n=n, reverse=rev)


def _apply_punct(cmd):
    """把命令里的标点名称换成实际字符（问号→？）；替换先做序数定位转换。"""
    if cmd.kind in ("replace", "replace_ordinal"):
        # 句尾语气词不可能是想替换上去的内容（“把A改成B吧”→B）
        if isinstance(getattr(cmd, "new", None), str):
            cmd.new = cmd.new.rstrip("吧啊呀哦呢嘛")
    if cmd.kind == "replace":
        cmd = _positional_replace(cmd)
        if cmd.kind != "replace":
            return cmd
    if cmd.kind == "delete_last_of":
        vs = punct_of(cmd.sub)
        if vs:
            return Cmd("delete_last_of", sub=vs[0], variants=vs)
    if cmd.kind == "replace":
        vo = punct_of(cmd.old)
        vn = punct_of(cmd.new)
        if vo or vn:
            return Cmd("replace", old=(vo[0] if vo else cmd.old),
                       new=(vn[0] if vn else cmd.new),
                       old_variants=(vo or [cmd.old]))
    return cmd


def _strip_trigger(text, trigger):
    """返回 (剩余部分, 精确命中, 模糊命中)。"""
    if text.startswith(trigger):
        return text[len(trigger):], True, False
    if len(text) < len(trigger) or len(trigger) < 2:
        return text, False, False
    head = text[:len(trigger)]
    if _pinyin_close(head, trigger):
        return text[len(trigger):], False, True
    return text, False, False


def _pinyin_close(a, b):
    """拼音完全相同，或整体编辑距离≤1（容纳“小删/小山”这类同音误识）。"""
    if a == b:
        return True
    pa, pb = lazy_pinyin(a), lazy_pinyin(b)
    if len(pa) != len(pb):
        return False
    sa, sb = "".join(pa), "".join(pb)
    if sa == sb:
        return True
    return _edit1(sa, sb)


def _edit1(a, b):
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = j = diff = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
        else:
            diff += 1
            if diff > 1:
                return False
            if len(a) != len(b):
                j += 1
            else:
                i += 1
                j += 1
    return True


_JU = "[句据巨具局剧锯聚拘曲去]"   # j/q声母混淆实测：句→局/曲/去   # “句”的常见同音/近音误识（局=jú实测高发）
_DUAN = "[段断]"       # “段”的常见同音误识
_YI = "[一依医衣议亦以已]"   # “一”的常见同音/声调变体
_NA = "[那拿纳哪]"     # “那”的常见同音/声调变体
_DEL = "(?:删除|删掉|擦掉|山除|闪除|删)"   # “删除”的常见同音误识（实测ASR出过“申叔”；也常丢“除”字只剩“删”，如“删上一句”）

# 标点名称→实际字符（全角优先），供“删除问号/把问号改成句号”这类口令用
PUNCT = {
    "问号": ["？", "?"],
    "句号": ["。", "."],
    "逗号": ["，", ","],
    "顿号": ["、"],
    "分号": ["；", ";"],
    "冒号": ["：", ":"],
    "叹号": ["！", "!"],
    "感叹号": ["！", "!"],
    "引号": ["”", "\"", "“"],
    "括号": ["）", "(", "（"],
}
PUNCT_CHARS = set("。，、；：！？!?,;:.…—“”\"'()'（）")


def punct_of(name):
    """标点名→字符。容忍ASR把'号'听成'好/口'：问好=问号、逗口=逗号。"""
    if name in PUNCT:
        return PUNCT[name]
    for suf in ("好", "口"):
        if name.endswith(suf):
            v = PUNCT.get(name[:-1] + "号")
            if v:
                return v
    return None


# 插入动词及口语小词：加/加上/打个/打了/补个/弄个/插入/添加…（了/个/一个可带可不带）
_INS_VERB = r"(?:添加|加入|加上?|插入|插上?|插个?|添上?|添个?|打了?|打上?|打一?个?|补上?|补个?|补充|放个?|放上?|写个?|写上?|弄个?|弄上?|整)"
_INS_M = r"(?:了一?个?|一?个?)?"


def _match(s, allow_bare=True):
    """把指令词之后的部分解析成具体命令，解析不了返回 None。

    结构字（句/段/一/那等）做同音容错；要匹配的内容保持原样。
    allow_bare=False 时不走“删掉××”兜底（供前缀补全场景调用）。
    """
    # 撤回=撤销的同义词全家桶：删错了/说错了想反悔，说的任何话都算
    if re.fullmatch(r"(?:撤回|撤销|撤消|收回|反悔|后悔了?)(?:一下|了)?(?:刚才)?"
                    r"(?:上一句|最后一句|那句?话?|这?句话?|上一步|操作|说的)?(?:吧)?", s):
        return Cmd("undo")
    if re.fullmatch(r"(恢复|重做)", s):
        return Cmd("redo")
    if re.fullmatch(r"(换行|回车|下一行)", s):
        return Cmd("newline")
    if re.fullmatch(r"(另起一段|分段|空一行|新段落|新的段落)", s):
        return Cmd("paragraph")
    # 只说“删除/删掉”两个字 = 删上一句（曾误解析成删“除”字）
    if s in ("删除", "删掉", "擦掉"):
        return Cmd("delete_last_sentence")
    # 删除标点：单个 / 全部
    m = re.fullmatch(r"(?:删除|删掉)(所有|全部)?标点(?:符号)?", s)
    if m:
        return Cmd("delete_all_punct" if m.group(1) else "delete_last_punct")

    # 插入：X后面/前面 加/打/补 Y
    m = re.fullmatch(rf"(?:在)?(.{{1,20}}?)(前面|后面){_INS_VERB}{_INS_M}(.{{1,30}})", s)
    if m:
        anchor = m.group(1).strip().rstrip("的")
        content = m.group(3).strip()
        if anchor and content:
            vs = punct_of(content)
            return Cmd("insert", anchor=anchor, before=(m.group(2) == "前面"),
                       content=(vs[0] if vs else content))
    # 插入：在X和Y之间/中间 加/打/补 Z
    m = re.fullmatch(rf"(?:在)?(.{{1,20}}?)(?:和|与)(.{{1,20}}?)(?:之间|中间){_INS_VERB}{_INS_M}(.{{1,30}})", s)
    if m:
        anchor = m.group(1).strip().rstrip("的")
        content = m.group(3).strip()
        if anchor and content:
            vs = punct_of(content)
            return Cmd("insert", anchor=anchor, before=False,
                       content=(vs[0] if vs else content))
    # 插入（倒装）：把X加在Y后面/前面
    m = re.fullmatch(rf"把(.{{1,30}}?)(?:这?个?)?(?:加|放|插|写|添|补)在(.{{1,20}}?)(?:的)?(前面|后面)", s)
    if m:
        content = m.group(1).strip()
        anchor = m.group(2).strip().rstrip("的")
        if anchor and content:
            vs = punct_of(content)
            return Cmd("insert", anchor=anchor, before=(m.group(3) == "前面"),
                       content=(vs[0] if vs else content))
    # 末尾追加：加/打个句号
    m = re.fullmatch(rf"(?:最后|末尾|结尾)?{_INS_VERB}{_INS_M}(.{{1,30}})", s)
    if m:
        content = m.group(1).strip()
        if content:
            vs = punct_of(content)
            return Cmd("insert_append", content=(vs[0] if vs else content))
    # 删除上一句 / 刚才那句 / 最后一句
    if re.fullmatch(rf"{_DEL}了?(?:[上下]|刚才{_NA}?|刚才说的|最后){_YI}?{_JU}(?:话)?", s):
        return Cmd("delete_last_sentence")
    # 删除全部
    if re.fullmatch(rf"{_DEL}了?(?:全部|所有)(?:内容|文字|文本)?", s):
        return Cmd("delete_all")
    # 删除刚才整段口述
    if re.fullmatch(rf"{_DEL}了?(?:我)?(?:刚才|上面|上一次|最后)(?:说的)?{_NA}?(?:一整{_DUAN}|一{_DUAN}|{_DUAN}话|{_DUAN})", s):
        return Cmd("delete_utterance")
    # 删除第N句 / 倒数第N句（按位置删某一句）
    m = re.fullmatch(rf"{_DEL}了?(倒数第|第)([零一二两三四五六七八九十百0-9]{{1,4}})(?:句话?|{_JU})", s)
    if m:
        n = cn2num(m.group(2))
        if n and n > 0:
            return Cmd("delete_sentence_index", n=n, reverse=(m.group(1) == "倒数第"))
    # 删除第N个字 / 倒数第N个字（按位置删某一个字）
    m = re.fullmatch(rf"{_DEL}了?(倒数第|第)([零一二两三四五六七八九十百0-9]{{1,4}})个?(?:字|字符|文字)", s)
    if m:
        n = cn2num(m.group(2))
        if n and n > 0:
            return Cmd("delete_char_position", n=n, reverse=(m.group(1) == "倒数第"))
    # 删除第N个X / 倒数第N个X（序数定位删；内容含"和/、"交给批量分支）
    m = re.fullmatch(rf"{_DEL}了?(倒数第|第)([零一二两三四五六七八九十百0-9]{{1,4}})个(.{{1,10}}?)字?", s)
    if m and not re.search(r"[和跟与、]", m.group(3)):
        n = cn2num(m.group(2))
        sub = re.sub(r"^[，,](?=.)", "", m.group(3).strip()).strip()
        if n and n > 0 and sub and sub not in ("字", "字符", "文字"):
            vs = punct_of(sub)
            return Cmd("delete_ordinal", sub=(vs[0] if vs else sub),
                       variants=(vs or []), n=n, reverse=(m.group(1) == "倒数第"))
    # 删除最后一个X
    m = re.fullmatch(rf"{_DEL}了?最后(一)?个(.{{1,10}}?)字?", s)
    if m and not re.search(r"[和跟与、]", m.group(2)):
        sub = re.sub(r"^[，,](?=.)", "", m.group(2).strip()).strip()
        if sub and sub not in ("字", "字符", "文字"):
            vs = punct_of(sub)
            return Cmd("delete_ordinal", sub=(vs[0] if vs else sub),
                       variants=(vs or []), n=1, reverse=True)
    # 删除N句 / 最后N句
    m = re.fullmatch(rf"{_DEL}了?(?:最后)?([零一二两三四五六七八九十百0-9]{{1,4}})(?:句话?|{_JU})", s)
    if m:
        n = cn2num(m.group(1))
        if n and n > 0:
            return Cmd("delete_n_sentences", n=n)
    # 删除N个××（两个句号、三个好字）——删最后N处
    m = re.fullmatch(rf"{_DEL}了?(?:最后)?([零一二两三四五六七八九十百0-9]{{1,4}})个(.{{1,10}}?)字?", s)
    if m and not re.search(r"[和跟与、]", m.group(2)):
        n = cn2num(m.group(1))
        sub = re.sub(r"^[，,](?=.)", "", m.group(2).strip()).strip()
        if n and n > 0 and sub and sub not in ("字", "字符", "文字"):
            vs = punct_of(sub)
            if vs:
                return Cmd("delete_n_of", sub=vs[0], variants=vs, n=n)
            return Cmd("delete_n_of", sub=sub, n=n)
    # 删除最后N个字（按数量）；X不是数字时按内容删：删除“好”字
    m = re.fullmatch(rf"{_DEL}了?(?:最后)?(.{{1,20}}?)(?:个|位)?(?:字|字符|文字)", s)
    if m:
        g = m.group(1)
        n = cn2num(g)
        if n and n > 0:
            return Cmd("delete_n_chars", n=n)
        sub = re.sub(r"^[那这]个?", "", g)
        if sub.endswith(("两", "二")) and len(sub) > 1:
            sub = sub[:-1]
        sub = sub.strip().rstrip("的")
        if sub and not re.fullmatch(r"[零一二两三四五六七八九十百0-9]+", sub):
            return Cmd("delete_last_of", sub=sub)
    # 删除含有××的那句话
    m = re.fullmatch(rf"{_DEL}了?(?:含有?|带有?)?(.{{1,30}}?)(?:{_NA}{_YI}?{_JU}话?|这{_YI}?{_JU}话?|该{_JU}|{_NA}{_JU})", s)
    if m and m.group(1).strip().strip("的"):
        sub = m.group(1).strip().rstrip("的")
        if sub:
            return Cmd("delete_containing", sub=sub)
    # 把××改成××（B 可为空：只说"A替换为"=删掉 A）
    m = re.fullmatch(rf"(?:把|将)(.{{1,30}}?)" + _REPLACE_VERB + r"(.{0,80})", s)
    if m and m.group(1).strip().rstrip("的"):
        return Cmd("replace", old=m.group(1).strip().rstrip("的"),
                   new=m.group(2).strip())
    # 倒装删除：把/将 X (给) 删除/删掉/删了/去掉…（实测："帮我把句号删除"）
    m = re.fullmatch(r"(?:把|将)(.{1,20}?)(?:给)?(?:删除掉|删除|删掉|删了|删"
                     r"|去掉|去除|移除|抹掉|擦掉)(?:了|一下)?", s)
    if m:
        sub = re.sub(r"^[那这把将给]个?", "", m.group(1)).strip()
        sub = re.sub(r"^[，,](?=.)", "", sub).strip().rstrip("的").strip()
        if sub:
            return Cmd("delete_last_of", sub=sub)
    # 批量删除：删除X和Y（各项按完整删除语法解析，可带序数/数量）
    m = re.fullmatch(r"(?:删除|删掉|擦掉)(.+)", s)
    if m:
        parts = [q.strip() for q in re.split(r"(?:和|跟|与|、)", m.group(1)) if q.strip()]
        if len(parts) >= 2:
            subs = []
            for q in parts:
                c = _match("删除" + q, allow_bare=True)
                if c is None or c.kind not in (
                        "delete_last_of", "delete_ordinal", "delete_n_of",
                        "delete_last_punct"):
                    subs = None
                    break
                subs.append(c)
            if subs:
                return Cmd("delete_batch", subs=subs)

    # 兜底：删掉××（删某个字或词，落在它最后一次出现的地方）
    if allow_bare:
        m = re.fullmatch(r"(?:删除|删掉|删|山除|闪除)掉?(.{1,20})", s)
        if m:
            sub = re.sub(r"^[那这把将给]个?", "", m.group(1)).strip()
            sub = re.sub(r"^[，,](?=.)", "", sub).strip().rstrip("的").strip()
            sub = re.sub(r"^最后(?:一个)?", "", sub).strip()
            if sub:
                return Cmd("delete_last_of", sub=sub)
    return None
