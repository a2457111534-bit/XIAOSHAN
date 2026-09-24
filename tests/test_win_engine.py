"""Windows 版引擎逻辑测试（假键盘注入，不真打字；任何平台都能跑）：
  python tests/test_win_engine.py

覆盖 voice_typist_win/win_engine.py：与 mac 版 tests/test_engine.py 同一套
断言，虚拟键码换成 Windows 码，验证移植没有走样。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from voice_typist_win import win_inject
from voice_typist_win import win_text
from voice_typist.commands import Cmd
from voice_typist_win.win_engine import Engine

win_text.read_focused = lambda: (None, None, None)   # 测试默认读不到，走账本逻辑
win_text.write_focused = lambda t: False             # 测试默认UIA不可写，走退格回退路径

# Windows 虚拟键码
BK, RET, Z, AKEY = 0x08, 0x0D, 0x5A, 0x41
typed, taps, clips, pastes = [], [], [], []

win_inject.type_text = lambda text, **kw: typed.append(text) or True
win_inject.tap_key = lambda code, **kw: taps.append(
    (code, kw.get("repeat", 1), kw.get("cmd", False), kw.get("shift", False))) or True
win_inject.set_clipboard_text = lambda text, **kw: clips.append(text)
win_inject.paste_clipboard = lambda **kw: pastes.append(True)

FAILED = []


def check(name, cond, info=""):
    print(("  ok  " if cond else "FAIL  ") + name + ("" if cond else f"   {info}"))
    if not cond:
        FAILED.append(name)


def bk_taps():
    return [t for t in taps if t[0] == BK]


A, B, C = "今年以来全局工作稳步推进。", "重点抓好三件大事。", "具体安排如下。"
eng = Engine()
for s in (A, B, C):
    eng.execute_dictation(s)
check("听写缓冲(粘贴×3)", eng.session.text == A + B + C and len(pastes) == 3,
      (eng.session.text, pastes))

# 按内容删中间句：退格到句首 + 粘贴尾部
taps.clear(); clips.clear(); pastes.clear()
ok, msg = eng.execute(Cmd("delete_containing", sub="三件大事"))
check("按内容删:退格数", bk_taps()[0][1] == len(B) + len(C), taps)
check("按内容删:尾部走粘贴", clips == [C] and pastes == [True], (clips, pastes))
check("按内容删:缓冲", eng.session.text == A + C, eng.session.text)

# 删上一句（句尾删除：纯退格，无粘贴）
taps.clear(); clips.clear(); pastes.clear()
ok, msg = eng.execute(Cmd("delete_last_sentence"))
check("删上一句:纯退格", bk_taps()[0][1] == len(C) and clips == [] and pastes == [], taps)
check("删上一句:缓冲", eng.session.text == A, eng.session.text)

# 替换（粘贴 新文本+尾部）
taps.clear(); clips.clear(); pastes.clear()
ok, msg = eng.execute(Cmd("replace", old="稳步推进", new="快速推进"))
check("替换:粘贴内容", clips == ["快速推进。"], clips)
check("替换:缓冲", eng.session.text == "今年以来全局工作快速推进。", eng.session.text)

# 撤销
before = eng.session.text
eng.execute(Cmd("replace", old="快速推进", new="飞速推进"))
taps.clear()
ok, msg = eng.execute(Cmd("undo"))
check("撤销:发了Ctrl+Z", any(t[0] == Z and t[2] for t in taps), taps)
check("撤销:缓冲恢复", eng.session.text == before, eng.session.text)

# 撤回(2026-09-25修复)：账实一致时原子写回，不赌App撤销栈（退格+粘贴在撤销栈里是多个事件）
_before_replace = eng.session.text
eng.execute(Cmd("replace", old="快速推进", new="飞速推进"))
_writes_undo = []
win_text.read_focused = lambda: (eng.session.text, len(eng.session.text), 0)
win_text.write_focused = lambda t: _writes_undo.append(t) or True
taps.clear()
ok, msg = eng.execute(Cmd("undo"))
check("撤回:AX原子写回", ok and len(_writes_undo) == 1 and taps == [], (_writes_undo, taps))
check("撤回:缓冲恢复", eng.session.text == _before_replace, eng.session.text)
_engX = Engine()
ok, msg = _engX.execute(Cmd("undo"))
check("撤回:空栈拒绝", ok is False and "撤回" in msg, msg)
# 撤回：AX可读不可写（豆包等聊天框）→ 全选+粘贴快照
engU = Engine()
win_text.read_focused = lambda: (engU.session.text, len(engU.session.text), 0)
win_text.write_focused = lambda t: False
engU.execute_dictation("第一句。")
engU.execute_dictation("第二句。")
engU.execute(Cmd("delete_last_sentence"))
taps.clear(); clips.clear(); pastes.clear()
ok, msg = engU.execute(Cmd("undo"))
check("撤回:AX不可写全选重打", ok and any(t[0] == 0x41 and t[2] for t in taps)
      and clips == ["第一句。第二句。"] and pastes == [True], (taps, clips))
win_text.read_focused = lambda: (None, None, None)
win_text.read_focused = lambda: (None, None, None)
win_text.write_focused = lambda t: False

# 删N字 / 换行
taps.clear()
ok, msg = eng.execute(Cmd("delete_n_chars", n=3))
check("删N字:退格数", bk_taps()[0][1] == 3, taps)
taps.clear()
ok, msg = eng.execute(Cmd("newline"))
check("换行:回车键", any(t[0] == RET for t in taps), taps)
ok, msg = eng.execute(Cmd("send"))
check("发送:按回车", any(t[0] == RET for t in taps), taps)

# 空会话 / 超长保护
eng2 = Engine()
ok, msg = eng2.execute(Cmd("delete_last_sentence"))
check("空会话删除拒绝", ok is False and bool(msg), msg)
eng3 = Engine()
eng3.execute_dictation("字" * 4000)
ok, msg = eng3.execute(Cmd("delete_n_chars", n=3999))
check("超长退格拒绝", ok is False and "手动" in msg, msg)

# 按位置删句 / 删字
eng4 = Engine()
eng4.execute_dictation("第一句。第二句。第三句。")
eng4.execute(Cmd("delete_sentence_index", n=1, reverse=False))
check("删第一句", eng4.session.text == "第二句。第三句。", eng4.session.text)
eng4.execute(Cmd("delete_sentence_index", n=1, reverse=True))
check("删倒数第一句", eng4.session.text == "第二句。", eng4.session.text)
eng4.execute(Cmd("delete_char_position", n=2, reverse=False))
check("删第2个字", eng4.session.text == "第句。", eng4.session.text)

# 删字词（含变体）
eng5 = Engine()
eng5.execute_dictation("你好你好呀")
taps.clear(); clips.clear(); pastes.clear()
ok, msg = eng5.execute(Cmd("delete_last_of", sub="你好"))
check("删最后出现的词:退格数", bk_taps()[0][1] == 3, taps)
check("删最后出现的词:粘贴尾部", clips == ["呀"], clips)
check("删最后出现的词:缓冲", eng5.session.text == "你好呀", eng5.session.text)

# 标点
eng7 = Engine()
eng7.execute_dictation("你好，世界。")
eng7.execute(Cmd("delete_last_of", sub="，", variants=["，", ","]))
check("删标点(变体匹配)", eng7.session.text == "你好世界。", eng7.session.text)
eng7.execute(Cmd("delete_last_punct"))
check("删最后一个标点", eng7.session.text == "你好世界", eng7.session.text)
ok, msg = eng7.execute(Cmd("delete_last_punct"))
check("无标点可删", ok is False, msg)
eng7.execute_dictation("a，b。c！")
eng7.execute(Cmd("delete_all_punct"))
check("删所有标点", eng7.session.text == "你好世界abc", eng7.session.text)
eng7.execute_dictation("好吗？")
eng7.execute(Cmd("replace", old="？", new="。", old_variants=["？", "?"]))
check("替换标点(变体)", eng7.session.text == "你好世界abc好吗。", eng7.session.text)

# 实时草稿（只进悬浮窗，输入框零接触）
eng6 = Engine()
taps.clear(); clips.clear(); pastes.clear(); typed.clear()
changed = eng6.type_partial("你好")
check("草稿:零注入", changed and typed == [] and taps == [] and pastes == [],
      (typed, taps, pastes))
eng6.type_partial("你好啊")
check("草稿:可读", eng6.draft == "你好啊", eng6.draft)
eng6.commit_final("你好啊。")
check("定稿:粘贴一次", clips == ["你好啊。"] and pastes == [True], (clips, pastes))
check("定稿:缓冲计入", eng6.session.text == "你好啊。", eng6.session.text)
eng6.type_partial("测试")
taps.clear(); pastes.clear(); typed.clear()
eng6.cancel_partial()
check("取消草稿:无注入", eng6.draft == "" and taps == [] and pastes == [], taps)

# UIA对齐：账本与输入框不一致时，删除前按输入框真实内容重置（含删除后复核）
eng8 = Engine()
eng8.execute_dictation("旧账本。")
_uia_calls = {"n": 0}


def _fake_read():
    _uia_calls["n"] += 1
    if _uia_calls["n"] == 1:
        return ("旧账本。新输入框内容。", 11, 0)   # 删除前：实际比账本多
    return ("旧账本。", 4, 0)                      # 删除后复核：与预期一致


win_text.read_focused = _fake_read
taps.clear(); clips.clear(); pastes.clear()
ok, msg = eng8.execute(Cmd("delete_last_sentence"))
check("UIA对齐:按真实内容删", ok and eng8.session.text == "旧账本。",
      (msg, eng8.session.text))
check("UIA对齐:退格按真实长度", bk_taps()[0][1] == 7, taps)
win_text.read_focused = lambda: ("文字", 2, 2)
ok, msg = eng8.execute(Cmd("delete_last_sentence"))
check("有选中文字拒绝", ok is False and "选中" in msg, msg)
win_text.read_focused = lambda: ("文字", 1, 0)
ok, msg = eng8.execute(Cmd("delete_last_sentence"))
check("光标不在末尾拒绝", ok is False and "末尾" in msg, msg)
win_text.read_focused = lambda: (None, None, None)

# UIA原子写入路径：删除不发任何键盘事件
writes = []
win_text.write_focused = lambda t: writes.append(t) or True
eng9 = Engine()
eng9.execute_dictation("你好啊。你是谁呀？")
taps.clear(); pastes.clear()
ok, msg = eng9.execute(Cmd("delete_last_of", sub="你是谁呀"))
check("UIA写入:零键盘事件", taps == [] and pastes == [], (taps, pastes))
check("UIA写入:整框原子设值", writes == ["你好啊。？"], writes)
check("UIA写入:缓冲同步", eng9.session.text == "你好啊。？", eng9.session.text)

# 删除全部（UIA路径 + 回退路径）
eng9.execute_dictation("第一句。第二句。")
writes.clear()
ok, msg = eng9.execute(Cmd("delete_all"))
check("删全部:UIA原子清空", ok and writes == [""] and eng9.session.text == "",
      (msg, writes))
win_text.write_focused = lambda t: False
eng9.execute_dictation("第三句。")
taps.clear()
ok, msg = eng9.execute(Cmd("delete_all"))
check("删全部:回退Ctrl+A+退格", ok and any(t[0] == AKEY and t[2] for t in taps)
      and eng9.session.text == "", (msg, taps))
win_text.write_focused = lambda t: writes.append(t) or True

# 同音兜底：ASR把目标字听错也能删对
eng10 = Engine()
eng10.execute_dictation("今天天气很好。")
writes.clear()
ok, msg = eng10.execute(Cmd("delete_last_of", sub="号"))   # '好'被听成'号'
check("同音兜底:删字", eng10.session.text == "今天天气很。", eng10.session.text)
eng10.execute_dictation("他来到了北京。")
writes.clear()
ok, msg = eng10.execute(Cmd("replace", old="背京", new="上海"))  # '北京'被听成'背京'
check("同音兜底:替换", eng10.session.text.endswith("上海。"), eng10.session.text)

# 删除N个×（从最后往前数）
eng11 = Engine()
eng11.execute_dictation("你好。很好。真好。")
writes.clear()
ok, msg = eng11.execute(Cmd("delete_n_of", sub="。", variants=["。", "."], n=2))
check("删N个:删最后2个句号", eng11.session.text == "你好。很好真好", eng11.session.text)
ok, msg = eng11.execute(Cmd("delete_n_of", sub="句号", variants=["。"], n=5))
check("删N个:不够数时拒绝", ok is False and "不够" in msg, msg)
eng11.execute_dictation("第一句。第二句。第三句。第四句。")
writes.clear()
ok, msg = eng11.execute(Cmd("delete_n_sentences", n=2))
check("删最后N句", eng11.session.text == "你好。很好真好第一句。第二句。",
      eng11.session.text)

# 序数定位删除/替换
eng12 = Engine()
eng12.execute_dictation("你好。很好。真好。")
writes.clear()
ok, msg = eng12.execute(Cmd("delete_ordinal", sub="。", variants=["。", "."], n=2, reverse=True))
check("删倒数第2个句号", eng12.session.text == "你好。很好真好。", eng12.session.text)
ok, msg = eng12.execute(Cmd("delete_ordinal", sub="。", variants=["。"], n=5, reverse=False))
check("序数越界拒绝", ok is False and "只找到" in msg, msg)
eng12.execute_dictation("行吗？行吗？")
writes.clear()
ok, msg = eng12.execute(Cmd("replace_ordinal", old="？", old_variants=["？", "?"],
                            new="，", n=2, reverse=True))
check("替换倒数第2个问号", eng12.session.text == "你好。很好真好。行吗，行吗？",
      eng12.session.text)

# 插入（UIA路径）
eng13 = Engine()
eng13.execute_dictation("你好你是谁？")
writes.clear()
ok, msg = eng13.execute(Cmd("insert", anchor="你好", before=False, content="，"))
check("插入:你好后加逗号", eng13.session.text == "你好，你是谁？", eng13.session.text)
ok, msg = eng13.execute(Cmd("insert", anchor="李号", before=True, content="、"))  # 同音锚点
check("插入:同音锚点", ok is False and "没找到" in msg, msg)   # 文中无"李/号"锚点→拒绝
eng13.execute_dictation("同志。")
writes.clear()
ok, msg = eng13.execute(Cmd("insert_append", content="！"))
check("末尾追加", eng13.session.text == "你好，你是谁？同志。！", eng13.session.text)

# 批量删除
eng14 = Engine()
eng14.execute_dictation("额，你好，你是谁？")
writes.clear()
ok, msg = eng14.execute(Cmd("delete_batch", subs=[
    Cmd("delete_last_of", sub="额"),
    Cmd("delete_last_of", sub="，", variants=["，", ","])]))
check("批量删除两处", eng14.session.text == "，你好你是谁？", (msg, eng14.session.text))
ok, msg = eng14.execute(Cmd("delete_batch", subs=[
    Cmd("delete_last_of", sub="，", variants=["，"]),
    Cmd("delete_last_of", sub="额")]))   # 第二项不存在
check("批量:部分失败如实报", ok and "已删除1处" in msg, msg)

print()
if FAILED:
    print(f"✗ {len(FAILED)} 项失败: {FAILED}")
    sys.exit(1)
print("✓ Windows 引擎逻辑全部通过")
