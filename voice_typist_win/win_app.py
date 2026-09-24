"""Windows 版主程序：按住热键连续说话，边说边上屏（VAD自动断句），语音命令随时插入。

状态机与交互语义和 mac 版 voice_typist/app.py 逐行对应（v2.3）：
按住说话 → 悬浮条实时草稿 → 每句停顿0.45s定稿粘贴上屏 →
命令在按住期间排队、松手后执行（避免按着Ctrl时发键）→ ESC作废本轮。
差异只在：菜单栏 → 控制台状态行 + 悬浮条；注入/UIA/TTS 用 Windows 层。
"""
import pathlib
import re
import socket
import sys
import threading
import time

import numpy as np
from pynput import keyboard

from voice_typist.asr import Recognizer
from voice_typist.audio import Recorder, Segmenter
from voice_typist.commands import parse, smooth_punct, split_sentences
from voice_typist.config import BASE_DIR

from .win_engine import Engine
from .win_gui import Gui
from .win_tray import Tray
from .win_tts import Feedback

IS_WIN = sys.platform == "win32"
_SINGLE_INSTANCE_PORT = 51966

LOG_PATH = BASE_DIR / "run.log"


def _log(msg):
    """关键事件落盘，排查问题全靠它。"""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


# 热键候选。默认 right_ctrl（与 mac 版"田字键"一样，是打字时最闲的修饰键；
# Win 键按下会弹开始菜单，不能用；Ctrl+V 粘贴与按住右Ctrl天然兼容）。
_HOTKEY_SETS = {
    "right_ctrl": lambda: {keyboard.Key.ctrl_r},
    "left_ctrl": lambda: {keyboard.Key.ctrl_l},
    "any_ctrl": lambda: {keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
    "f5": lambda: {keyboard.Key.f5},
    "f6": lambda: {keyboard.Key.f6},
}

HELP_TEXT = (
    "【日常听写】\n"
    "按住 右Ctrl 键说话，说完松开；\n"
    "悬浮条实时显示识别中的文字，每说完一句停顿半秒自动落进文档。\n"
    "按住期间说出的命令，松手后自动执行。按ESC作废本轮。\n\n"
    "【删除命令】先说指令词「小删除」，再说命令：\n"
    "· 小删除，删除上一句（说“小删除，删除”/“小删除，上一句”也行）\n"
    "· 小删除，删除第三句 / 倒数第二句 / 最后两句\n"
    "· 小删除，删除第五个字 / 倒数第三个字\n"
    "· 小删除，删除“好”字 / 删掉你好 / 小删除你好\n"
    "· 小删除，删除两个句号 / 三个好字（删最后N处）\n"
    "· 小删除，删除第一个句号 / 倒数第二个句号 / 最后一个问号 / 第一个“我”\n"
    "· 小删除，删除含有××的那句话\n"
    "· 小删除，删除问号 / 句号 / 逗号（删最后一个该标点）\n"
    "· 小删除，删除标点（最后一个）/ 删除所有标点\n"
    "· 小删除全部（清空全部文字）\n"
    "· 小删除，撤销 / 恢复\n\n"
    "【替换命令】指令词「小替换」：\n"
    "· 小替换，把稳步推进改成快速推进\n"
    "· 小替换，问号改成句号（标点也认）\n"
    "· 小替换，在你好后面加逗号 / 在你好和你是谁之间加逗号\n\n"
    "目标字听错音也能对上（说“号”命中“好”）；成功只轻轻“叮”一声。\n"
    "注意：手动移动过光标后删除/替换可能不准，先把光标点回文末。\n"
    "改说话键：python run_win.py --set-key"
)


def _build_hotkey(val):
    """hotkey 配置 → (Key集合, vk码集合, 显示名)。
    支持预设名（right_ctrl…）、{"vk": 码}（自定义任意键）、{"key": "f5"}。"""
    disp_map = {"right_ctrl": "右Ctrl", "left_ctrl": "左Ctrl",
                "any_ctrl": "任意Ctrl键", "f5": "F5", "f6": "F6"}
    if isinstance(val, dict):
        if "vk" in val:
            return set(), {int(val["vk"])}, f"键码{val['vk']}"
        if "key" in val:
            k = getattr(keyboard.Key, str(val["key"]), None)
            return ({k} if k else set()), set(), str(val["key"])
    name = val if isinstance(val, str) else "right_ctrl"
    keys = _HOTKEY_SETS.get(name, _HOTKEY_SETS["right_ctrl"])()
    return keys, set(), disp_map.get(name, name)


def _set_console_title(title):
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(title)
    except Exception:
        pass


class VoiceTypistWinApp:
    def __init__(self, cfg):
        self.cfg = cfg
        self.fb = Feedback(cfg)
        self.engine = Engine(self.fb)
        self.recognizer = None
        self.recorder = Recorder(cfg.get("sample_rate", 16000))
        self.state = "loading"   # loading / idle / recording / draining
        self.enabled = True
        self.push_mode = cfg.get("push_mode", "hold")
        self.mic_ok = None
        self.model_error = ""
        self._discard = False
        self._mic_warned = False
        self._sent_count = 0
        self._partial_n = 0
        self._last_error_say = ""
        self._cmd_queue = []        # 按住模式：命令攒到松手后执行（避免按着Ctrl时发键）
        self._self_typing = False   # 自己注入键盘事件时，热键监听要装聋
        self._quit = threading.Event()
        self.indicator = Gui(self)   # 全部 GUI（主界面/悬浮条/设置/帮助）单线程
        self.hotkey_keys, self.hotkey_vks, self._hotkey_disp = _build_hotkey(
            cfg.get("hotkey", "right_ctrl"))
        _log(f"[win] 启动，热键={cfg.get('hotkey', 'right_ctrl')}({self._hotkey_disp})，"
             f"指令词={cfg.get('trigger_word', '小删除')}")

        threading.Thread(target=self._load_model, daemon=True).start()
        self._start_listener()
        threading.Thread(target=self._refresh_loop, daemon=True).start()
        self.tray = Tray(self)
        self.tray.start()
        self.indicator.show_main()   # 启动即见面（关闭=最小化到托盘）

    def toggle_enabled(self):
        """托盘菜单：暂停/恢复听写。"""
        self.enabled = not self.enabled
        state = "恢复" if self.enabled else "暂停"
        _log(f"托盘：{state}听写")
        self.fb.say(f"已{state}")
        self.fb.sound("tink" if self.enabled else "pop")

    def request_quit(self):
        """托盘菜单：退出（叫醒主循环）。"""
        self._quit.set()

    def apply_config(self, cfg):
        """设置窗口保存后热应用：热键/指令词/模式/反馈即时生效（线程数等仍需重启）。"""
        self.cfg.update(cfg)
        self.hotkey_keys, self.hotkey_vks, self._hotkey_disp = _build_hotkey(
            cfg.get("hotkey", "right_ctrl"))
        self.push_mode = cfg.get("push_mode", "hold")
        self.fb.enabled = bool(cfg.get("tts_feedback", True))
        self.fb.sound_on = bool(cfg.get("sound_feedback", True))
        self.fb.voice = cfg.get("tts_voice", "zh-CN-XiaoyiNeural")
        self.fb.engine_pref = cfg.get("tts_engine", "edge")
        self.fb.say(f"说话键已切换为{self._hotkey_disp}")
        _log(f"设置已热应用：热键={self._hotkey_disp}，指令词={cfg.get('trigger_word')}")

    # ---------- 启动自检 ----------
    def _load_model(self):
        try:
            self.recognizer = Recognizer(
                str(BASE_DIR / self.cfg["model_dir"]),
                num_threads=self.cfg.get("num_threads", 4))
            _log("识别模型加载完成")
        except Exception as e:
            self.model_error = str(e)[:180]
            _log(f"识别模型加载失败: {self.model_error}")
            print(f"✗ 识别模型加载失败：{self.model_error}")
        finally:
            self.state = "idle"
        try:
            import sounddevice as sd
            with sd.InputStream(samplerate=16000, channels=1, dtype="float32"):
                pass
            self.mic_ok = True
        except Exception as e:
            self.mic_ok = False
            _log(f"麦克风探测失败: {e}")
        _log(f"麦克风可用: {self.mic_ok}")
        if self.recognizer is not None and self.mic_ok:
            print("一切就绪！按住 " + self._hotkey_disp + " 连续说话；"
                  "命令示例：小删除，删除上一句。Ctrl+C 退出。")
            self.fb.say("小删已就绪。按住右Ctrl键，边说边停顿，文字实时出现。")
            _log("[win] 启动自检全部通过")
        else:
            if not self.mic_ok:
                print("✗ 麦克风打不开 → Windows 设置 → 隐私和安全性 → 麦克风，"
                      "允许桌面应用访问麦克风")
            print("按上面提示处理后，重新运行 run_win.py。")

    # ---------- 热键监听 ----------
    def _start_listener(self):
        held = set()   # 物理按住时键盘会自动重复发 press 事件，只认首次

        def _matched(k):
            return (k in self.hotkey_keys
                    or (bool(self.hotkey_vks)
                        and getattr(k, "vk", None) in self.hotkey_vks))

        def on_press(k):
            try:
                if k == keyboard.Key.esc and self.state == "recording":
                    _log("按ESC取消本次口述")
                    self._cancel_recording()
                    return
                if _matched(k):
                    if k in held:
                        return
                    held.add(k)
                    _log(f"热键按下 {k}")
                    self._hotkey(pressed=True)
                    return
                if self._self_typing or self.engine.is_busy():
                    return   # 自己注入的打字/退格/粘贴事件，忽略
                if self.push_mode == "hold" and self.state == "recording":
                    _log(f"热键持有期间按了别的键，取消录音: {k}")
                    self._cancel_recording()
            except Exception as e:
                _log(f"on_press 异常: {e}")

        def on_release(k):
            if _matched(k):
                held.discard(k)
                _log(f"热键松开 {k}")
                self._hotkey(pressed=False)

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()

    # ---------- 热键与录音 ----------
    def _hotkey(self, pressed):
        if not self.enabled:
            return
        if pressed:
            if self.push_mode == "hold":
                self._start_recording()
            elif self.state == "recording":
                self._finish_recording()
            else:
                self._start_recording()
        elif self.push_mode == "hold" and self.state == "recording":
            self._finish_recording()

    def _start_recording(self):
        if self.state == "loading":
            self.fb.say("模型还在加载，稍等")
            return
        if self.state != "idle":
            return
        if self.recognizer is None:
            self.fb.say("识别模型没加载成功，请看控制台")
            return
        try:
            # 上一轮疑似死流 → 先开关一次空流换新的采集会话再正式录
            self.recorder.start(fresh=getattr(self, "_mic_dead", False))
        except Exception as e:
            _log(f"麦克风打开失败: {e}")
            self.fb.say("麦克风打不开")
            return
        self.state = "recording"
        self._discard = False
        self._mic_warned = False
        self._sent_count = 0
        self._partial_n = 0
        threading.Thread(target=self._stream_loop, daemon=True).start()

    def _finish_recording(self):
        """松开热键：停录，循环线程自己把最后的半句收尾上屏。"""
        self.state = "draining"
        try:
            self.recorder.stop()
        except Exception:
            pass

    def _cancel_recording(self):
        self._discard = True
        try:
            self.recorder.stop()
        except Exception:
            pass
        self.state = "idle"

    def _stream_loop(self):
        """持续取音频：silero断句 → 每句定稿上屏；句中每0.6秒出一次实时草稿。"""
        seg = Segmenter(self.recorder.sr)
        self._partial_n = 0
        last_partial_t = 0.0
        finalized = 0
        try:
            while self.state == "recording":
                new = self.recorder.take_new()
                if new.size:
                    for chunk in seg.feed(new):
                        finalized += 1
                        self._finalize_utterance(chunk)
                now = time.time()
                if now - last_partial_t >= 0.6:
                    last_partial_t = now
                    self._update_partial(seg)
                time.sleep(0.04)
            if self._discard:
                self.engine.cancel_partial()
                return
            self.state = "draining"
            tail = self.recorder.drain_all()
            if tail.size:
                for chunk in seg.feed(tail):
                    finalized += 1
                    self._finalize_utterance(chunk)
            for chunk in seg.flush():
                finalized += 1
                self._finalize_utterance(chunk)
            if finalized == 0:
                # 零产出诊断：峰值区分「音频流没打开 / 数字静音(死流) / VAD判非语音」
                secs = self.recorder.total / float(self.recorder.sr or 16000)
                peak = getattr(self.recorder, "peak", 0.0)
                _log(f"本次口述零产出: 采集{secs:.1f}s 峰值{peak:.4f}"
                     f"（0s=流没打开；峰值<0.0015=数字静音死流；其余=判非语音）")
                if secs > 0.5 and peak < 0.0015:
                    # 采集会话交上来全是零：标记死流，下一轮自动换新采集会话
                    self._mic_dead = True
                    _log("判定为麦克风死流，下一轮录音将重建采集会话")
                    self.fb.say("麦克风收不到声音，再说一遍试试")
            else:
                self._mic_dead = False
        except Exception as e:
            _log(f"流式循环异常: {type(e).__name__}: {e}")
        finally:
            if not self._discard:
                self.state = "idle"
                try:
                    self._run_queued_cmds()
                except Exception as e:
                    _log(f"排队命令执行链异常: {type(e).__name__}: {e}")

    def _run_queued_cmds(self):
        """按住模式下攒下的命令，在松手后（无修饰键按下）依次执行。"""
        while self._cmd_queue:
            cmd = self._cmd_queue.pop(0)
            self._exec_cmd(cmd)

    def _exec_cmd(self, payload):
        self._self_typing = True
        try:
            ok, msg = self.engine.execute(payload)
            self._sent_count += 1
            _log(f"命令 {payload.kind} → {'成功' if ok else '未执行'}: {msg}")
            if ok:
                self.fb.sound("tink")
            elif msg:
                self._last_error_say = msg
                self.fb.say(msg)
        except Exception as e:
            # 执行层任何异常都不能静默：否则命令消失且无线索（实测踩过）
            _log(f"命令 {payload.kind} 执行异常: {type(e).__name__}: {e}")
            self.fb.say("命令执行出错了，请看日志")
        finally:
            self._self_typing = False

    def _update_partial(self, seg):
        """实时草稿：对说到一半的这句出识别草稿，进悬浮窗（输入框零接触）。"""
        self._self_typing = True
        try:
            cur = seg.current()
            if cur.size < 0.35 * self.recorder.sr or cur.size > 12 * self.recorder.sr:
                return
            text = self.recognizer.transcribe(cur)
            if not text:
                return
            kind, _ = parse(text, self.cfg.get("trigger_word", "小删除"))
            if kind == "command":
                return   # 听起来像命令就不打草稿，免得闪来闪去
            if self.engine.type_partial(text):
                self._partial_n += 1
        except Exception as e:
            _log(f"草稿更新异常: {e}")
        finally:
            self._self_typing = False

    def _finalize_utterance(self, samples):
        """一句说完（检测到停顿）：定稿替换草稿；若这句是命令则执行。"""
        dur = samples.size / float(self.recorder.sr)
        if dur < 0.25:
            return
        self._self_typing = True
        try:
            self._finalize_locked(samples)
        finally:
            self._self_typing = False

    def _finalize_locked(self, samples):
        dur = samples.size / float(self.recorder.sr)
        if dur < 0.25:
            return
        try:
            if float(np.max(np.abs(samples))) < 0.0015:
                if not self._mic_warned:
                    self._mic_warned = True
                    _log("录音为数字静音，疑似无可用麦克风")
                    self.fb.say("麦克风收不到声音。请检查麦克风是否插好")
                return
            text = self.recognizer.transcribe(samples)
        except Exception as e:
            _log(f"识别异常: {e}")
            self.engine.cancel_partial()
            return
        _log(f"识别({dur:.1f}s): {text!r}")
        if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", text):
            self.engine.cancel_partial()
            return   # 空识别/杂音
        # 防复读循环：识别到的正是刚才播报的报错内容（整句或其片段）时忽略
        err = getattr(self, "_last_error_say", "")
        _strip = "。！？!?，, \u3000"
        e2, t2 = err.strip(_strip), text.strip(_strip)
        if e2 and (t2 == e2 or (len(t2) >= 2 and t2 in e2)):
            _log("识别到的是报错复读，忽略")
            self._last_error_say = ""
            self.engine.cancel_partial()
            return
        sents = split_sentences(text)
        if not sents:
            self.engine.cancel_partial()
            return
        trigger = self.cfg.get("trigger_word", "小删除")
        # 触发词待命：上一句只说了触发词（自然停顿被切开），接下来4秒内的
        # 下一句自动补上触发词按命令处理
        armed = getattr(self, "_armed", None)
        if armed and (time.time() - armed[1]) < 4.0:
            self._armed = None
            if parse(text, trigger)[0] == "dictate":
                joined = f"{armed[0]}，{text}"
                if parse(joined, trigger)[0] == "command":
                    _log(f"待命接续: {text!r} → 按命令处理")
                    text = joined
        else:
            self._armed = None
        sents = split_sentences(text)
        has_cmd = any(parse(s, trigger)[0] == "command" for s in sents)
        if has_cmd:
            self.engine.cancel_partial()   # 命令句不上屏
            # 单独一句触发词 → 待命4秒等命令（不播报"请说命令"）
            if len(sents) == 1:
                _, p0 = parse(sents[0], trigger)
                if p0.kind == "help":
                    self._armed = (getattr(p0, "trigger", None)
                                   or (trigger[0] if isinstance(trigger, list) else trigger),
                                   time.time())
                    _log(f"触发词单独成句→待命4秒({self._armed[0]})")
                    self.fb.sound("tink")
                    self._partial_n = 0
                    return
            for s in sents:
                self._dispatch(s)
            self._partial_n = 0
        else:
            final = smooth_punct("".join(sents))
            self.engine.commit_final(final)
            self._sent_count += len(sents)
            _log(f"定稿上屏 {len(final)} 字（草稿{self._partial_n}轮）")
            self._partial_n = 0

    def _dispatch(self, text):
        self._self_typing = True
        try:
            kind, payload = parse(text, self.cfg.get("trigger_word", "小删除"))
            if kind == "dictate":
                if not payload:
                    return
                self.engine.execute_dictation(payload)
                self._sent_count += 1
                _log(f"上屏 {len(payload)} 字")
            elif (self.push_mode == "hold"
                  and self.state in ("recording", "draining")):
                # 按住说话时手上正按着Ctrl，命令攒到松手后执行，杜绝Ctrl+退格灾难
                self._cmd_queue.append(payload)
                _log(f"按住模式：命令{payload.kind}已排队，松手后执行")
            else:
                self._exec_cmd(payload)
        finally:
            self._self_typing = False

    # ---------- 状态行/悬浮条 ----------
    def _refresh_loop(self):
        while True:
            title = {"loading": "小删…", "recording": "●录", "draining": "…收"}.get(
                self.state, "小删")
            if not self.enabled:
                title = "⏸小删"
            _set_console_title(title)
            try:
                if self.state == "recording":
                    draft = self.engine.draft
                    if draft:
                        txt = f"● {draft}"
                        if self._sent_count:
                            txt += f"（已落 {self._sent_count} 句）"
                    else:
                        txt = "● 正在听…（按ESC取消）"
                    self.indicator.overlay(txt)
                else:
                    self.indicator.overlay_hide()
            except Exception:
                pass
            time.sleep(0.25)

    def run(self):
        try:
            while not self._quit.wait(1.0):
                pass
        except KeyboardInterrupt:
            pass
        print("退出小删")
        if self.state == "recording":
            self._cancel_recording()
        self.indicator.overlay_hide()
        self.indicator.shutdown()
        time.sleep(0.4)   # 给 GUI 线程一点时间完成 Tk 收尾（防跨线程 GC 崩溃）
        self.tray.stop()


def main(argv=None):
    if not IS_WIN:
        print("本程序只能在 Windows 上运行（mac 版请用 run.py）")
        return 1
    try:
        guard = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        guard.bind(("127.0.0.1", _SINGLE_INSTANCE_PORT))
    except OSError:
        # 已在运行：把已开实例的主界面叫出来（UDP 唤醒），然后本进程退出
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto(b"show", ("127.0.0.1", _SINGLE_INSTANCE_PORT))
            s.close()
        except Exception:
            pass
        print("小删已经在运行：已把主界面调出来（托盘里也找得到它）。")
        return 0
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # 高分屏字体清晰
        except Exception:
            pass
        # 打包成 exe 后隐藏黑色控制台：界面全在托盘，避免误关黑窗=误退程序
        if getattr(sys, "frozen", False):
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)   # SW_HIDE
    except Exception:
        pass
    from voice_typist.config import load_config
    cfg = load_config()
    if cfg.get("hotkey", "right_ctrl") == "any_cmd":
        cfg["hotkey"] = "right_ctrl"   # mac 配置带过来时换默认
    print(f"小删（Windows 版）启动中… 说话键："
          f"{_build_hotkey(cfg.get('hotkey', 'right_ctrl'))[2]}，Ctrl+C 退出")
    app = VoiceTypistWinApp(cfg)

    def _watch_show():
        """再双击 exe 时由第二个进程唤醒：弹出主界面。"""
        while True:
            try:
                data, _ = guard.recvfrom(64)
                if data == b"show":
                    app.indicator.show_main()
            except Exception:
                return
    threading.Thread(target=_watch_show, daemon=True).start()
    app.run()
    return 0


def set_key_interactive():
    """python run_win.py --set-key：按一个键存为说话键。"""
    from voice_typist.config import load_config
    cfg = load_config()
    app = VoiceTypistWinApp.__new__(VoiceTypistWinApp)   # 不走完整启动
    got = {}

    def on_press(k):
        if not got:
            got["k"] = k
            listener.stop()

    print("请按一个键作为“说话键”（按住它说话，松开结束）。ESC 取消…")
    from pynput import keyboard as kb
    listener = kb.Listener(on_press=on_press)
    listener.start()
    for _ in range(100):   # 最多等 10 秒
        if got:
            break
        time.sleep(0.1)
    listener.stop()
    if not got:
        print("超时未按键，未修改。")
        return 1
    k = got["k"]
    if k == kb.Key.esc:
        print("已取消。")
        return 0
    if isinstance(k, kb.Key):
        val = {"key": k.name}
    else:
        vk = getattr(k, "vk", None)
        if not vk:
            print("这个键设不了，换一个")
            return 1
        val = {"vk": vk}
    import json
    p = BASE_DIR / "config.json"
    full = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    full["hotkey"] = val
    p.write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"说话键已设为 {val}，重启小删后生效。")
    return 0
