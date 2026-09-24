"""命令解析测试：.venv/bin/python tests/test_commands.py"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from voice_typist.commands import cn2num, parse, smooth_punct, split_sentences

T = "小删"
FAILED = []


def check(name, cond, info=""):
    print(("  ok  " if cond else "FAIL  ") + name + ("" if cond else f"   {info}"))
    if not cond:
        FAILED.append(name)


def cmd_of(raw, trigger=T):
    _, p = parse(raw, trigger)
    return p


# ---- 正常听写（不该被当成命令） ----
check("普通句子", parse("今年以来全局各项工作稳步推进。", T)[0] == "dictate")
check("“销售”开头不误触发", parse("销售工作会议即将召开", T)[0] == "dictate")
check("无指令词的动词句", parse("这句话要删除掉再重写", T)[0] == "dictate")
check("模糊命中但后文非命令", parse("销售会上说了很多内容", T)[0] == "dictate")

# ---- 触发与命令 ----
p = cmd_of("小删，删除上一句")
check("删除上一句", p.kind == "delete_last_sentence", p)
p = cmd_of("小删删除上一句。")
check("无逗号触发", p.kind == "delete_last_sentence", p)
p = cmd_of("小山，删除上一句")
check("同音词容错(小山)", p.kind == "delete_last_sentence", p)
p = cmd_of("小删，删除刚才那句")
check("删除刚才那句", p.kind == "delete_last_sentence", p)
p = cmd_of("小删，删除刚才那段")
check("删除刚才那段", p.kind == "delete_utterance", p)
p = cmd_of("小删，删除最后五个字")
check("删除最后五个字", p.kind == "delete_n_chars" and p.n == 5, p)
p = cmd_of("小删，删除十二个字")
check("删除十二个字", p.kind == "delete_n_chars" and p.n == 12, p)
p = cmd_of("小删，删除含有稳步推进的那句话")
check("按内容删", p.kind == "delete_containing" and p.sub == "稳步推进", p)
p = cmd_of("小删，删除稳步推进那句话")
check("按内容删(无含有)", p.kind == "delete_containing" and p.sub == "稳步推进", p)
p = cmd_of("小删，把稳步推进改成快速推进")
check("替换", p.kind == "replace" and p.old == "稳步推进" and p.new == "快速推进", p)
p = cmd_of("小删，将稳步推进改为快速推进")
check("替换(将/改为)", p.kind == "replace" and p.old == "稳步推进", p)
p = cmd_of("小删，换行")
check("换行", p.kind == "newline", p)
p = cmd_of("小删，另起一段")
check("另起一段", p.kind == "paragraph", p)
p = cmd_of("小删，撤销")
check("撤销", p.kind == "undo", p)
p = cmd_of("小删，恢复")
check("恢复", p.kind == "redo", p)
p = cmd_of("小删")
check("只说指令词→帮助", p.kind == "help", p)
p = cmd_of("小删，帮我把窗户关一下顺便把办公室里所有的灯都一起关掉")
check("超长乱语→unknown", p.kind == "unknown", p)

# ---- 真实 ASR 输出回归（婷婷 TTS → SenseVoice 实测结果） ----
p = cmd_of("小山删除上一据。")
check("ASR回归:旧词同音+句→据", p.kind == "delete_last_sentence", p)
p = cmd_of("笑删除删除上一据。", "小删除")
check("ASR回归:笑删除(同音)", p.kind == "delete_last_sentence", p)
p = cmd_of("小删除删除上依据。", "小删除")
check("ASR回归:上依据(依≠一)", p.kind == "delete_last_sentence", p)
p = cmd_of("小山把稳步推进改成快速推进。")
check("ASR回归:替换", p.kind == "replace" and p.old == "稳步推进", p)
p = cmd_of("小山删除含有稳步推进的那句话。")
check("ASR回归:按内容删", p.kind == "delete_containing" and p.sub == "稳步推进", p)
p = cmd_of("小删，删除刚才那断")
check("段→断容错", p.kind == "delete_utterance", p)

# ---- 新指令词「小删除」：省略第二个“删除”也要能解析 ----
X = "小删除"
p = cmd_of("小删除，删除上一句", X)
check("小删除:标准", p.kind == "delete_last_sentence", p)
p = cmd_of("小山除，删除上一句", X)
check("小删除:同音(小山除)", p.kind == "delete_last_sentence", p)
p = cmd_of("小山除删除上一句。", X)
check("小删除:同音无逗号", p.kind == "delete_last_sentence", p)
p = cmd_of("小删除上一句", X)
check("小删除:省略第二个删除", p.kind == "delete_last_sentence", p)
p = cmd_of("小删除，上一句", X)
check("小删除:逗号后省略删除", p.kind == "delete_last_sentence", p)
p = cmd_of("小删除，删除了刚才那句", X)
check("小删除:带“了”", p.kind == "delete_last_sentence", p)
p = cmd_of("小删除，删除含有数据的那句话", X)
check("小删除:按内容删", p.kind == "delete_containing" and p.sub == "数据", p)

# ---- 删具体某个字 / 某一句（按位置/按内容） ----
X2 = "小删除"
p = cmd_of("小删除，删除第三句", X2)
check("删除第三句", p.kind == "delete_sentence_index" and p.n == 3 and not p.reverse, p)
p = cmd_of("小删除，删除倒数第二句", X2)
check("删除倒数第二句", p.kind == "delete_sentence_index" and p.n == 2 and p.reverse, p)
p = cmd_of("小删除，删除第五个字", X2)
check("删除第五个字", p.kind == "delete_char_position" and p.n == 5 and not p.reverse, p)
p = cmd_of("小删除，删除倒数第三个字", X2)
check("删除倒数第三个字", p.kind == "delete_char_position" and p.n == 3 and p.reverse, p)
p = cmd_of("小删除，删除好字", X2)
check("删除好字(按内容)", p.kind == "delete_last_of" and p.sub == "好", p)
p = cmd_of("小删除，删除那个好字", X2)
check("删除那个好字", p.kind == "delete_last_of" and p.sub == "好", p)
p = cmd_of("小删除，删掉你好好", X2)
check("删掉某词(兜底)", p.kind == "delete_last_of" and p.sub == "你好好", p)
p = cmd_of("小删除，给我倒杯咖啡", X2)
check("精确触发+乱语→尝试删词并播报没找到", p.kind == "delete_last_of" and p.sub == "倒杯咖啡", p)
p = cmd_of("小删除，删除最后五个字", X2)
check("回归:最后五个字", p.kind == "delete_n_chars" and p.n == 5, p)
p = cmd_of("小删除，删除十二个字", X2)
check("回归:十二个字", p.kind == "delete_n_chars" and p.n == 12, p)

# ---- 指令词「小删除」（用户定稿） ----
S = "小删除"
p = parse("小删除，删除上一句", S)[1]
check("小删除:删除上一句", p.kind == "delete_last_sentence", p)
p = parse("小删除，删除", S)[1]
check("小删除:只说删除=删上一句", p.kind == "delete_last_sentence", p)
p = parse("小删除，上一句", S)[1]
check("小删除:省略删除", p.kind == "delete_last_sentence", p)
p = parse("小删除，山除你好", S)[1]
check("小删除:动词同音山除", p.kind == "delete_last_of" and p.sub == "你好", p)
TL0 = ["小删除", "小替换"]
p = parse("小山除，你好啊", TL0)[1]
check("小山除=小删除(发音变体同等对待)", p.kind == "delete_last_of" and p.sub == "你好啊", p)
p = parse("小山除你好啊", TL0)[1]
check("小山除无逗号也执行", p.kind == "delete_last_of" and p.sub == "你好啊", p)
check("日常句不误触", parse("销售会议上说了很多内容", TL0)[0] == "dictate")
p = parse("小删除你好", S)[1]
check("小删除你好=删词", p.kind == "delete_last_of" and p.sub == "你好", p)
p = parse("小删除，你好啊", S)[1]
check("小删除,你好啊=删词", p.kind == "delete_last_of" and p.sub == "你好啊", p)
check("模糊命中仍不误吞", parse("销售会上说了很多内容", S)[0] == "dictate")
p = parse("小删除，删除第五个字", S)[1]
check("小删除:第五个字", p.kind == "delete_char_position" and p.n == 5, p)
p = parse("小删除，删除好字", S)[1]
check("小删除:删某个字", p.kind == "delete_last_of" and p.sub == "好", p)
check("说错了不再是触发词", parse("说错了，删除上一句", S)[0] == "dictate")

# ---- 逐句分派 ----
ss = split_sentences("今天天气很好。小删除，删除上一句。")
check("切句", ss == ["今天天气很好。", "小删除，删除上一句。"], ss)

# ---- 标点命令 & 「小替换」触发词 ----
TL = ["小删除", "小替换"]
p = parse("小删除，删除问号", TL)[1]
check("删除问号", p.kind == "delete_last_of" and p.sub == "？" and "?" in (p.variants or []), p)
p = parse("小删除，删除句号", TL)[1]
check("删除句号", p.kind == "delete_last_of" and p.sub == "。", p)
p = parse("小删除，删除逗号", TL)[1]
check("删除逗号", p.kind == "delete_last_of" and p.sub == "，", p)
p = parse("小删除，删除标点", TL)[1]
check("删除标点", p.kind == "delete_last_punct", p)
p = parse("小删除，删除所有标点", TL)[1]
check("删除所有标点", p.kind == "delete_all_punct", p)
p = parse("小替换，稳步推进改成快速推进", TL)[1]
check("小替换:省把", p.kind == "replace" and p.old == "稳步推进" and p.new == "快速推进", p)
p = parse("小替换，把稳步推进改成快速推进", TL)[1]
check("小替换:带把", p.kind == "replace" and p.old == "稳步推进", p)
p = parse("小替换，问号改成句号", TL)[1]
check("小替换:标点", p.kind == "replace" and p.old == "？" and p.new == "。", p)
kind, p = parse("小替换，这个词很常用", TL)
check("小替换+非替换句→删除尝试", kind == "command" and p.kind == "delete_last_of", p)
p = parse("小删除，稳步推进改成快速推进", TL)[1]
check("小删除+省把替换", p.kind == "replace" and p.old == "稳步推进", p)

# ---- 删除全部 ----
p = parse("小删除全部", S)[1]
check("小删除全部", p.kind == "delete_all", p)
p = parse("小删除，删除全部", S)[1]
check("删除全部", p.kind == "delete_all", p)
p = parse("小删除，删除所有文字", S)[1]
check("删除所有文字", p.kind == "delete_all", p)
p = parse("小山除全部", S)[1]
check("同音:小山除全部", p.kind == "delete_all", p)

# ---- 删除N个×× / N句 ----
p = parse("小删除，删除两个句号", S)[1]
check("删除两个句号", p.kind == "delete_n_of" and p.sub == "。" and p.n == 2, p)
p = parse("小删除两个句号", S)[1]
check("小删除两个句号(省略)", p.kind == "delete_n_of" and p.n == 2, p)
p = parse("小删除，删除三个好字", S)[1]
check("删除三个好字", p.kind == "delete_n_of" and p.sub == "好" and p.n == 3, p)
p = parse("小删除，删除最后两句", S)[1]
check("删除最后两句", p.kind == "delete_n_sentences" and p.n == 2, p)
p = parse("小删除，删除两句话", S)[1]
check("删除两句话", p.kind == "delete_n_sentences" and p.n == 2, p)
p = parse("小删除，删除最后五个字", S)[1]
check("回归:最后五个字仍是删N字", p.kind == "delete_n_chars" and p.n == 5, p)

# ---- 序数定位：第N个/倒数第N个/最后一个 ×（删除+替换） ----
p = parse("小删除，删除倒数第二个句号", S)[1]
check("删倒数第二个句号", p.kind == "delete_ordinal" and p.sub == "。" and p.n == 2 and p.reverse, p)
p = parse("小删除，删除第一个句号", S)[1]
check("删第一个句号", p.kind == "delete_ordinal" and p.n == 1 and not p.reverse, p)
p = parse("小删除第一个我", S)[1]
check("删第一个我(省略)", p.kind == "delete_ordinal" and p.sub == "我" and not p.reverse, p)
p = parse("小删除，删除最后一个问号", S)[1]
check("删最后一个问号", p.kind == "delete_ordinal" and p.sub == "？" and p.reverse and p.n == 1, p)
p = parse("小替换，倒数第二个句号为逗号", TL)[1]
check("替换倒数第二句号为逗号", p.kind == "replace_ordinal" and p.old == "。" and p.new == "，"
      and p.n == 2 and p.reverse, p)
p = parse("小替换，倒数第二个问号改成逗号", TL)[1]
check("替换倒数第二问号", p.kind == "replace_ordinal" and p.old == "？" and p.new == "，", p)
p = parse("小替换，最后一个问号为逗号", TL)[1]
check("替换最后问号", p.kind == "replace_ordinal" and p.n == 1 and p.reverse, p)
p = parse("小替换，把第一个句号改成感叹号", TL)[1]
check("替换第一句号", p.kind == "replace_ordinal" and not p.reverse and p.new == "！", p)

# ---- 插入标点/字词 ----
p = parse("小替换，在你好后面加逗号", TL)[1]
check("在X后面加标点", p.kind == "insert" and p.anchor == "你好" and p.content == "，"
      and not p.before, p)
p = parse("小替换，你好后面加个逗号", TL)[1]
check("X后面加个标点", p.kind == "insert" and p.content == "，", p)
p = parse("小替换，在你好和你是谁之间加逗号", TL)[1]
check("在X和Y之间加", p.kind == "insert" and p.anchor == "你好" and p.content == "，", p)
p = parse("小替换，你是谁前面加句号", TL)[1]
check("X前面加", p.kind == "insert" and p.before and p.content == "。", p)
p = parse("小替换，加个句号", TL)[1]
check("末尾追加", p.kind == "insert_append" and p.content == "。", p)
p = parse("小替换，同志后面加上你好", TL)[1]
check("加字词", p.kind == "insert" and p.content == "你好", p)

# ---- 插入：口语全变体（真实ASR失败案例回归） ----
p = parse("小替换，在你好和你是谁之间打逗口", TL)[1]
check("之间+打+逗口(实测原话)", p.kind == "insert" and p.content == "，", p)
p = parse("小替换，在你好和你是谁中间加了句号", TL)[1]
check("中间+加了(实测原话)", p.kind == "insert" and p.content == "。", p)
p = parse("小替换，你好后面打个问号", TL)[1]
check("打个问号", p.kind == "insert" and p.content == "？", p)
p = parse("小替换，把逗号加在你好后面", TL)[1]
check("倒装:把X加在Y后面", p.kind == "insert" and p.anchor == "你好" and p.content == "，", p)
p = parse("小替换，最后打个句号", TL)[1]
check("最后打个句号", p.kind == "insert_append" and p.content == "。", p)
p = parse("小删除，删除问好", TL0)[1]
check("标点名听错:删除问好=问号", p.kind == "delete_last_of" and p.sub == "？", p)
p = parse("小删除，删除两个逗口", TL0)[1]
check("标点名听错:两个逗口", p.kind == "delete_n_of" and p.sub == "，", p)

# ---- 触发词别名：想/退换 变体（ASR把小听成想、替换听成退换） ----
TV = ["小删除", "想删除", "小替换", "想替换", "想退换", "小退换"]
p = parse("想删除，删除上一句", TV)[1]
check("想删除触发", p.kind == "delete_last_sentence", p)
p = parse("想替换，你好改成你们", TV)[1]
check("想替换触发", p.kind == "replace" and p.old == "你好" and p.new == "你们", p)
p = parse("想退换，你好改成你们", TV)[1]
check("想退换触发", p.kind == "replace", p)
p = parse("小退换你好改成你们", TV)[1]
check("小退换省略触发", p.kind == "replace" and p.old == "你好", p)
p = parse("想山除，删除上一句", TV)[1]
check("想山除(双重误识)触发", p.kind == "delete_last_sentence", p)

# ---- 插入：加入/放/写 动词 + 长内容 + 新触发词（用户实测反馈） ----
TV2 = ["小删除", "想删除", "小山口", "小山竹", "小珊瑚",
       "小替换", "想替换", "想退换", "小退换"]
p = parse("小替换，在你好后面加入我叫小明", TV2)[1]
check("在X后面加入长内容", p.kind == "insert" and p.anchor == "你好" and p.content == "我叫小明", p)
p = parse("小替换，在句号后面放个逗号", TV2)[1]
check("放个逗号", p.kind == "insert" and p.content == "，", p)
p = parse("小替换，你好后面写个感叹号", TV2)[1]
check("写个感叹号", p.kind == "insert" and p.content == "！", p)
p = parse("小替换，把我叫小明加在你好后面", TV2)[1]
check("倒装加入长内容", p.kind == "insert" and p.content == "我叫小明"
      and p.anchor == "你好", p)
p = parse("小山口，删除上一句", TV2)[1]
check("小山口触发", p.kind == "delete_last_sentence", p)
p = parse("小山竹删除你好", TV2)[1]
check("小山竹省略触发", p.kind == "delete_last_of" and p.sub == "你好", p)
p = parse("小珊瑚，删除上一句", TV2)[1]
check("小珊瑚触发", p.kind == "delete_last_sentence", p)
# 已知取舍：小珊瑚是触发词，正文以它开头会被拦下（仅报"没找到"，不删东西）
kind, p = parse("小珊瑚礁很漂亮", TV2)
check("小珊瑚开头的正文会被拦(已知取舍)", kind == "command", (kind, p))

# ---- 批量删除 + 客气前缀 + 小山虫 ----
TV3 = ["小删除", "想删除", "小山口", "小山竹", "小珊瑚", "小山虫",
       "小替换", "想替换", "想退换", "小退换"]
p = parse("小删除，帮我删除额和逗号", TV3)[1]
check("批量:额和逗号", p.kind == "delete_batch" and len(p.subs) == 2, p)
p = parse("小删除，删除你好你是谁和问号", TV3)[1]
check("批量:词和标点", p.kind == "delete_batch" and len(p.subs) == 2, p)
p = parse("小删除，删除第一个句号和两个逗号", TV3)[1]
check("批量:带序数数量", p.kind == "delete_batch"
      and p.subs[0].kind == "delete_ordinal" and p.subs[1].kind == "delete_n_of", p)
p = parse("小删除，删除额、逗号、句号", TV3)[1]
check("批量:顿号分隔", p.kind == "delete_batch" and len(p.subs) == 3, p)
p = parse("小山虫，删除上一句", TV3)[1]
check("小山虫触发", p.kind == "delete_last_sentence", p)
p = parse("小删除，请删除上一句", TV3)[1]
check("客气前缀:请", p.kind == "delete_last_sentence", p)
p = parse("小删除，删除含有你好和再见的那句话", TV3)[1]
check("含句优先于批量", p.kind == "delete_containing" and p.sub == "你好和再见", p)
p = parse("小删除，删除和平饭店", TV3)[1]
check("含'和'的整词不被误拆", p.kind == "delete_last_of" and p.sub == "和平饭店", p)

# ---- 自定义指令词 ----
check("自定义指令词生效", cmd_of("改字，删除上一句", "改字").kind == "delete_last_sentence")
check("换词后原词失效", parse("小删，删除上一句", "改字")[0] == "dictate")

# ---- 中文数字 ----
for s, n in [("五", 5), ("十二", 12), ("二十", 20), ("一百零三", 103), ("两百", 200), ("7", 7)]:
    check(f"cn2num({s})=={n}", cn2num(s) == n, cn2num(s))


# ---- 伪句号修正（断在未完待续词上→句号降逗号） ----
check("伪句号:你觉得", smooth_punct("你觉得。") == "你觉得，")
check("伪句号:然后", smooth_punct("然后。") == "然后，")
check("伪句号:因为", smooth_punct("因为。") == "因为，")
check("伪句号:对吧", smooth_punct("这样对吧。") == "这样对吧，")
check("真句号保留", smooth_punct("今天天气很好。") == "今天天气很好。")
check("真句号保留2", smooth_punct("比如说。") == "比如说。")


# ---- 声调变体容错（实测：上一句→上一局） ----
p = parse("小删除，删除上一局", S)[1]
check("上一局=上一句", p.kind == "delete_last_sentence", p)
p = parse("小删除，删除第三局", S)[1]
check("第三局=第三句", p.kind == "delete_sentence_index" and p.n == 3, p)
p = parse("小删除，删除倒数第二局", S)[1]
check("倒数第二局", p.kind == "delete_sentence_index" and p.n == 2 and p.reverse, p)

# ---- 触发词吞头容错（实测：小删除→删除） ----
p = parse("删除帮我删除上一句", S)[1]
check("吞头:删除帮我删除上一句", p.kind == "delete_last_sentence", p)
p = parse("删掉上一句", S)[1]
check("吞头:删掉上一句", p.kind == "delete_last_sentence", p)
p = parse("删除撤销", S)[1]
check("吞头:删除撤销", p.kind == "undo", p)
check("吞头不劫持:删除了一些文件", parse("删除了一些文件", S)[0] == "dictate")
check("吞头不劫持:删除线很好看", parse("删除线很好看", S)[0] == "dictate")
check("吞头不劫持:删除键在哪里", parse("删除键在哪里", S)[0] == "dictate")
check("吞头不劫持:长句以删除开头",
      parse("删除功能我们下次会议再详细讨论一下方案", S)[0] == "dictate")
p = parse("删除帮我删除上一句", T)[1]
check("吞头:双字触发词同生效", p.kind == "delete_last_sentence", p)

# ---- 触发词吞头容错（替换系，实测：小替换→替换） ----
p = parse("替换把原码换成源码", S)[1]
check("吞头:替换把A换成B", p.kind == "replace" and p.old == "原码" and p.new == "源码", p)
p = parse("替换帮我问号改成句号", S)[1]
check("吞头:替换+客气前缀", p.kind == "replace_punct" or p.kind == "replace", p)
check("吞头不劫持:替换这个词很重要", parse("替换这个词很重要", S)[0] == "dictate")
check("吞头不劫持:替换频率太高了", parse("替换频率太高了", S)[0] == "dictate")

# ---- 替换动词全集（2026-09-24 实测：把A替换为B 全系失效） ----
FULL = ["小删除", "想删除", "小替换", "想替换", "小退换"]   # 贴近真实 config 触发词表
p = parse("小替换把你好替换为我好", FULL)[1]
check("替换为:把A替换为B", p.kind == "replace" and p.old == "你好" and p.new == "我好", p)
p = parse("小替换我替换为他", FULL)[1]
check("替换为:A替换为B(无把)", p.kind == "replace" and p.old == "我" and p.new == "他", p)
p = parse("想替换把你好替换喂我好", FULL)[1]   # '为'被ASR听成'喂'
check("喂容错:替换喂", p.kind == "replace" and p.old == "你好" and p.new == "我好", p)
p = parse("小替换，把稳步推进修改成快速推进", FULL)[1]
check("修改成", p.kind == "replace" and p.old == "稳步推进" and p.new == "快速推进", p)
p = parse("小替换，错误修改为正确", FULL)[1]
check("修改为", p.kind == "replace" and p.old == "错误" and p.new == "正确", p)
p = parse("小替换，把A改喂B", FULL)[1]
check("改喂(=改为误识)", p.kind == "replace" and p.old == "A" and p.new == "B", p)
p = parse("小替换，第一改成第二", FULL)[1]
check("改成:裸A改成B", p.kind == "replace" and p.old == "第一" and p.new == "第二", p)
p = parse("小替换把A换成B吧", FULL)[1]
check("句尾语气词剔除", p.kind == "replace" and p.new == "B", p)
check("老句式回归:A为B", parse("小替换，A为B", FULL)[1].kind == "replace")
check("标点替换回归", parse("小替换，问号改成句号", FULL)[1].kind == "replace")
check("吞头回归:替换把A换成B", parse("替换把原码换成源码", FULL)[1].kind == "replace")
# 丢"除"字：删除→删
p = parse("小删除删上一句", FULL)[1]
check("删单字:删上一句", p.kind == "delete_last_sentence", p)
p = parse("小删除删第三个句号", FULL)[1]
check("删单字:删第N个X", p.kind == "delete_ordinal", p)
check("正常说话不被劫持:删掉了好多文件",
      parse("小删除，删掉了好多文件这句话不对", FULL)[0] in ("dictate", "command"))

# ---- 倒装删除 + 空尾替换（2026-09-25 实测：帮我把句号删除 全系失效） ----
p = parse("小删除帮我把句号删除", FULL)[1]
check("倒装删除:把句号删除", p.kind == "delete_last_of" and p.sub == "。", p)
p = parse("小删除把问题删除", FULL)[1]
check("倒装删除:把X删除", p.kind == "delete_last_of" and p.sub == "问题", p)
p = parse("小删除把这个句号去掉", FULL)[1]
check("倒装删除:把X去掉", p.kind == "delete_last_of" and p.sub == "。", p)
p = parse("小删除把逗号删了", FULL)[1]
check("倒装删除:删了尾", p.kind == "delete_last_of" and p.sub == "，", p)
p = parse("小删除把我", FULL)[1]   # VAD截断的"把我删除"
check("截断兜底:把我", p.kind == "delete_last_of" and p.sub == "我", p)
p = parse("想替换把OO替换为", FULL)[1]
check("空尾替换=删除", p.kind == "replace" and p.old == "OO" and p.new == "", p)
check("正装回归:删除这个句号", parse("小删除删除这个句号", FULL)[1].kind == "delete_last_of")
check("不劫持:把方案再斟酌一下",
      parse("小删除，把方案再斟酌一下", FULL)[0] in ("dictate", "command"))

# ---- 发送 + 撤回全家桶（2026-09-25 新功能："大宝贝，发送"） ----
BABY = FULL + ["大宝贝", "大宝贝儿"]
check("发送:大宝贝发送", parse("大宝贝，发送", BABY)[1].kind == "send")
check("发送:把它发出去", parse("大宝贝，把它发出去", BABY)[1].kind == "send")
check("发送:直接发送吧", parse("大宝贝，直接发送吧", BABY)[1].kind == "send")
check("发送:发吧", parse("大宝贝发吧", BABY)[1].kind == "send")
check("发送:发送一下", parse("大宝贝，发送一下", BABY)[1].kind == "send")
check("发送:儿化音容错", parse("大宝贝儿发送", BABY)[1].kind == "send")
check("发送:儿单独成句待命", parse("大宝贝儿", BABY)[1].kind == "help")
check("发送专线:不听删除", parse("大宝贝，删除上一句", BABY)[0] == "dictate")
_p = parse("小删除，发送", BABY)[1]
check("发送字面:小删除下删词", _p.kind == "delete_last_of" and _p.sub == "发送", _p)
check("儿内容保护", parse("小替换，儿童节改成国庆节", BABY)[1].old == "儿童节")
_p = parse("小删除删除下一句话", BABY)[1]
check("下一句=上一句", _p.kind == "delete_last_sentence", _p)
check("上一去=上一句", parse("小删除删除上一去", BABY)[1].kind == "delete_last_sentence")
check("删单字+上一去", parse("小删除删上一去", BABY)[1].kind == "delete_last_sentence")
check("上一曲=上一句", parse("小删除删除上一曲", BABY)[1].kind == "delete_last_sentence")
check("第三曲=第三句", parse("小删除删除第三曲", BABY)[1].kind == "delete_sentence_index")
check("大宝贝儿=正式触发词", parse("大宝贝儿发送", BABY)[1].kind == "send")
check("大宝贝儿待命", parse("大宝贝儿", BABY)[1].kind == "help")
check("撤回:撤回上一句", parse("小删除，撤回上一句", BABY)[1].kind == "undo")
check("撤回:撤回", parse("小删除，撤回", BABY)[1].kind == "undo")
check("撤回:撤销刚才那句", parse("小删除，撤销刚才那句", BABY)[1].kind == "undo")
check("撤回:收回刚才说的", parse("小删除，收回刚才说的", BABY)[1].kind == "undo")
check("撤回:反悔", parse("小删除，反悔", BABY)[1].kind == "undo")
check("回归:后悔了", parse("小删除，后悔了", BABY)[1].kind == "undo")
check("回归:回车=换行", parse("小删除，回车", BABY)[1].kind == "newline")
check("回归:恢复=redo", parse("小删除，恢复", BABY)[1].kind == "redo")
p = parse("小删除删除第二个，你好", BABY)[1]
check("序数目标剥误入逗号", p.kind == "delete_ordinal" and p.sub == "你好", p)
p = parse("小删除删除第二个逗号", BABY)[1]
check("逗号仍是合法目标", p.kind == "delete_ordinal" and p.sub == "，", p)

# ---- Windows 真机吞头回归（2026-09-24 实测：小替换整吞 / 小→要 / 化为） ----
# 注：_apply_punct 会把标点名转成真实字符（句号→。），断言两者皆可
p = parse("小替换把句号换为逗号", TL)[1]
check("win实测:换为切位", getattr(p, "old", "") in ("句号", "。")
      and p.new in ("逗号", "，"), p)
p = parse("要替换把句号化为逗号", S)[1]
check("win实测:要替换+化为", getattr(p, "old", "") in ("句号", "。")
      and p.new in ("逗号", "，"), p)
p = parse("把问号换成逗号", S)[1]
check("win实测:整吞把A换成B", p.kind in ("replace", "replace_punct"), p)
p = parse("把句号变成逗号", S)[1]
check("win实测:变成", getattr(p, "old", "") in ("句号", "。")
      and p.new in ("逗号", "，"), p)
p = parse("小替换，稳步推进变为快速推进", TL)[1]
check("win实测:变为", p.kind == "replace" and p.old == "稳步推进", p)
check("win实测:不劫持把好时机抓住", parse("把好时机抓住", S)[0] == "dictate")
check("win实测:不劫持将来我们会更好", parse("将来我们会更好", S)[0] == "dictate")
check("win实测:不劫持删除了一些文件", parse("删除了一些文件", S)[0] == "dictate")

print()
if FAILED:
    print(f"✗ {len(FAILED)} 项失败: {FAILED}")
    sys.exit(1)
print("✓ 命令解析全部通过")
