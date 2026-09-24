"""菜单栏主程序：按住热键连续说话，边说边上屏（VAD自动断句），语音命令随时插入。"""
import asyncio
import hashlib
import pathlib
import socket
import subprocess
import sys
import threading
import time

import numpy as np
import rumps
from AppKit import NSEvent, NSMakePoint, NSView
from pynput import keyboard

from .asr import Recognizer
from .audio import Recorder, Segmenter
from .commands import parse, smooth_punct, split_sentences
from .config import BASE_DIR
from .engine import Engine
from .perms import accessibility_trusted

_SINGLE_INSTANCE_PORT = 51966

LOG_PATH = BASE_DIR / "run.log"


def _log(msg):
    """关键事件落盘，排查问题全靠它。"""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


# 热键候选。默认 any_cmd（Win键盘=两个田字旗标键，Mac键盘=左右⌘）。
# 注意避开 Option 键——豆包输入法等常占用它做语音热键。
_HOTKEY_SETS = {
    "any_cmd": lambda: {keyboard.Key.cmd_l, keyboard.Key.cmd_r},
    "right_cmd": lambda: {keyboard.Key.cmd_r},
    "right_alt": lambda: {keyboard.Key.alt_r},
    "any_alt": lambda: {keyboard.Key.alt_l, keyboard.Key.alt_r},
    "f5": lambda: {keyboard.Key.f5},
    "f6": lambda: {keyboard.Key.f6},
}

HELP_TEXT = (
    "【日常听写】\n"
    "按住 ⌘ 键（Win键盘=任意田字旗标键）说话，说完松开；\n"
    "悬浮条实时显示识别中的文字，每说完一句停顿半秒自动落进文档。\n"
    "按住期间说出的命令，松手后自动执行。\n\n"
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
    "· 小替换，稳步推进改成快速推进（“把”可省）\n"
    "· 小替换，问号改成句号（标点也认）\n"
    "· 小替换，倒数第二个句号为逗号 / 第一个问号改成句号\n"
    "· 小替换，在你好后面加逗号 / 在你好和你是谁之间加逗号\n"
    "· 小替换，你是谁前面加句号 / 加个句号（末尾追加）\n\n"
    "目标字听错音也能对上（说“号”命中“好”）；成功只轻轻“叮”一声。\n"
    "注意：手动移动过光标后删除/替换可能不准，先把光标点回文末。"
)


class Feedback:
    """语音播报：优先 edge-tts（微软神经语音，需联网），离线自动退回系统婷婷。"""

    def __init__(self, cfg):
        self.enabled = bool(cfg.get("tts_feedback", True))
        self.engine = cfg.get("tts_engine", "edge")
        self.voice = cfg.get("tts_voice", "zh-CN-XiaoyiNeural")
        self.sound_on = bool(cfg.get("sound_feedback", True))
        self._dir = BASE_DIR / ".tts-cache"
        self._lock = threading.Lock()

    def say(self, text):
        if self.enabled and text:
            threading.Thread(target=self._speak, args=(text,), daemon=True).start()

    def _speak(self, text):
        path = None
        if self.engine == "edge":
            try:
                path = self._edge_file(text)
            except Exception as e:
                _log(f"edge-tts 失败，回退系统语音: {e}")
        if path:
            subprocess.Popen(["afplay", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["say", "-v", "Tingting", text],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _edge_file(self, text):
        """生成并缓存 mp3；同一句话第二次起零延迟。"""
        self._dir.mkdir(exist_ok=True)
        key = hashlib.md5(f"{self.voice}|{text}".encode()).hexdigest() + ".mp3"
        p = self._dir / key
        if p.exists():
            return p
        with self._lock:
            if p.exists():
                return p
            import edge_tts

            async def gen():
                await edge_tts.Communicate(text, self.voice).save(str(p))
            asyncio.run(gen())
        return p if p.exists() and p.stat().st_size > 1000 else None

    def sound(self, name):
        if self.sound_on:
            subprocess.Popen(
                ["afplay", "-v", "0.35", f"/System/Library/Sounds/{name}.aiff"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class _DragView(NSView):
    """按住悬浮条任意位置拖动，移动窗口；不抢键盘焦点。"""
    _dragOrigin = None
    _winOrigin = None

    def mouseDown_(self, event):
        loc = NSEvent.mouseLocation()
        self._dragOrigin = (loc.x, loc.y)
        f = self.window().frame()
        self._winOrigin = (f.origin.x, f.origin.y)

    def mouseDragged_(self, event):
        if self._dragOrigin is None or self._winOrigin is None:
            return
        loc = NSEvent.mouseLocation()
        self.window().setFrameOrigin_(NSMakePoint(
            self._winOrigin[0] + loc.x - self._dragOrigin[0],
            self._winOrigin[1] + loc.y - self._dragOrigin[1]))

    def mouseUp_(self, event):
        self._dragOrigin = None
        self._winOrigin = None


def _build_hotkey(val):
    """hotkey 配置 → (Key集合, vk码集合, 显示名)。
    支持预设名（any_cmd…）、{"vk": 码}（自定义任意键）、{"key": "f5"}。"""
    disp_map = {"any_cmd": "田字键(⌘)", "right_cmd": "右⌘", "any_alt": "Option键",
                "right_alt": "右Option", "f5": "F5", "f6": "F6"}
    if isinstance(val, dict):
        if "vk" in val:
            return set(), {int(val["vk"])}, f"键码{val['vk']}"
        if "key" in val:
            k = getattr(keyboard.Key, str(val["key"]), None)
            return ({k} if k else set()), set(), str(val["key"])
    name = val if isinstance(val, str) else "any_cmd"
    keys = _HOTKEY_SETS.get(name, _HOTKEY_SETS["any_cmd"])()
    return keys, set(), disp_map.get(name, name)


class MicIndicator:
    """录音时屏幕上部约1/3处的悬浮条：显示“● 正在听…”和实时草稿文字。
    只能在主线程调用（由刷新定时器驱动）。"""

    W, H = 760, 52

    def __init__(self):
        self._panel = None
        self._label = None

    def _build(self):
        from AppKit import (NSColor, NSFont, NSMakeRect, NSPanel,
                            NSScreen, NSTextField)
        # NSPanel + Nonactivating：无边框、点按拖动也不会抢走打字焦点
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, self.W, self.H), 128, 2, False)
        panel.setLevel_(8)           # 悬浮在普通窗口之上
        panel.setOpaque_(False)
        panel.setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.1, 0.92))
        panel.setHasShadow_(True)
        panel.setCollectionBehavior_(1)   # CanJoinAllSpaces，每个桌面都显示
        panel.contentView().setWantsLayer_(True)
        panel.contentView().layer().setCornerRadius_(26.0)
        view = _DragView.alloc().initWithFrame_(
            NSMakeRect(0, 0, self.W, self.H))
        label = NSTextField.labelWithString_("● 正在听…")
        label.setFont_(NSFont.boldSystemFontOfSize_(17.0))
        label.setTextColor_(NSColor.whiteColor())
        label.setAlignment_(0)       # 左对齐
        label.setFrame_(NSMakeRect(22, 12, self.W - 44, 30))
        view.addSubview_(label)
        panel.setContentView_(view)
        frame = NSScreen.mainScreen().frame()
        panel.setFrameOrigin_(NSMakePoint(
            (frame.size.width - self.W) / 2,
            frame.size.height * 0.68))
        self._panel, self._label = panel, label

    def show(self, text):
        if self._panel is None:
            try:
                self._build()
            except Exception as e:
                _log(f"悬浮窗创建失败: {e}")
                self._panel = False   # 失败就不再尝试
                return
        if self._panel:
            self._label.setStringValue_(text[:44])
            self._panel.orderFrontRegardless()

    def hide(self):
        if getattr(self, "_panel", None):
            self._panel.orderOut_(None)


class VoiceTypistApp(rumps.App):
    def __init__(self, cfg):
        super().__init__(name="小删", title="小删…", quit_button=None)
        self.cfg = cfg
        self.fb = Feedback(cfg)
        self.engine = Engine(self.fb)
        self.recognizer = None
        self.recorder = Recorder(cfg.get("sample_rate", 16000))
        self.state = "loading"   # loading / idle / recording / draining / processing
        self.enabled = True
        self.push_mode = cfg.get("push_mode", "hold")
        self.ax_ok = None
        self.mic_ok = None
        self.model_error = ""
        self._discard = False
        self._mic_warned = False
        self._sent_count = 0
        self._partial_n = 0
        self._last_error_say = ""
        self._cmd_queue = []        # 按住模式：命令攒到松手后执行（避免按着⌘时发键）
        self._self_typing = False   # 自己注入打字事件时，热键监听要装聋
        self.indicator = MicIndicator()
        self.hotkey_keys, self.hotkey_vks, self._hotkey_disp = _build_hotkey(
            cfg.get("hotkey", "any_cmd"))
        self._capturing_key = False
        _log(f"启动，热键={cfg.get('hotkey', 'any_cmd')}({self._hotkey_disp})，"
             f"指令词={cfg.get('trigger_word', '小删除')}，"
             f"音色={cfg.get('tts_voice', 'zh-CN-XiaoyiNeural')}")

        self.item_enable = rumps.MenuItem("启用语音输入", callback=self._toggle_enable)
        self.item_mode = rumps.MenuItem(
            "说话方式：" + ("按一下开始，再按结束" if self.push_mode == "toggle" else "按住说话"),
            callback=self._toggle_mode)
        self.item_key = rumps.MenuItem(
            f"更改说话键（当前：{self._hotkey_disp}）…", callback=self._change_hotkey)
        self.item_tts = rumps.MenuItem("语音播报错误提示", callback=self._toggle_tts)
        self.menu = [
            self.item_enable,
            self.item_mode,
            self.item_key,
            rumps.MenuItem("测试：往当前窗口打一句话", callback=self._test_type),
            self.item_tts,
            rumps.MenuItem("命令速查", callback=self._show_help),
            rumps.MenuItem("退出", callback=lambda _: rumps.quit_application()),
        ]
        self.item_enable.state = True
        self.item_tts.state = self.fb.enabled

        threading.Thread(target=self._load_model, daemon=True).start()
        self._start_listener()
        rumps.Timer(self._refresh_title, 0.3).start()
        rumps.Timer(self._startup_check, 1).start()

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
            rumps.notification("小删", "识别模型加载失败", self.model_error)
        finally:
            self.state = "idle"
        self.ax_ok = accessibility_trusted()
        _log(f"辅助功能权限: {self.ax_ok}")
        if not self.ax_ok:
            accessibility_trusted(prompt=True)
            rumps.notification(
                "小删", "需要辅助功能权限",
                "在弹出的系统窗口里点“打开系统设置”，勾选你启动小删的程序（双击启动=“终端”），然后重新启动小删")
        try:
            import sounddevice as sd
            with sd.InputStream(samplerate=16000, channels=1, dtype="float32"):
                pass
            self.mic_ok = True
        except Exception as e:
            self.mic_ok = False
            _log(f"麦克风探测失败: {e}")
            rumps.notification(
                "小删", "需要麦克风权限",
                "系统设置 → 隐私与安全性 → 麦克风，勾选你启动小删的程序（如“终端”），然后重新启动小删")
        _log(f"麦克风权限: {self.mic_ok}")

    def _startup_check(self, timer):
        if self.ax_ok is None:
            return
        timer.stop()
        lines = []
        lines.append("✓ 识别模型已就绪" if self.recognizer is not None
                     else f"✗ 识别模型加载失败：{self.model_error}")
        lines.append("✓ 辅助功能权限（热键+打字）" if self.ax_ok
                     else "✗ 辅助功能权限 —— 系统设置 → 隐私与安全性 → 辅助功能 → 勾选“终端”")
        lines.append("✓ 麦克风权限" if self.mic_ok
                     else "✗ 麦克风权限 —— 系统设置 → 隐私与安全性 → 麦克风 → 勾选“终端”")
        if self.ax_ok and self.mic_ok and self.recognizer is not None:
            lines.append("")
            lines.append("一切就绪！按住 ⌘ 键（Win键盘=田字旗标键）连续说话，")
            lines.append("说完一句停顿半秒，文字就实时落下来（屏幕上方有“正在听”悬浮窗）。")
            lines.append("命令示例：小删除，删除上一句")
            self.fb.say("小删已就绪。按住空格右边那个键，边说边停顿，文字实时出现。")
            _log("启动自检全部通过")
        else:
            lines.append("")
            lines.append("按上面提示授权后，重新双击「启动小删」即可。")
            _log("启动自检有缺项")
        w = rumps.Window(title="小删 · 启动自检", message="\n".join(lines),
                         default_button="知道了", other_button="更改说话键")
        if w.run() == "更改说话键":
            self._change_hotkey(None)

    def _start_listener(self):
        def on_press(k):
            try:
                if getattr(self, "_capturing_key", False):
                    self._capturing_key = False
                    self._captured_key(k)
                    return
                if k == keyboard.Key.esc and self.state == "recording":
                    _log("按ESC取消本次口述")
                    self._cancel_recording()
                    return
                if (k in self.hotkey_keys
                        or (bool(self.hotkey_vks)
                            and getattr(k, "vk", None) in self.hotkey_vks)):
                    _log(f"热键按下 {k}")
                    self._hotkey(pressed=True)
                    return
                if self._self_typing or self.engine.is_busy():
                    return   # 自己打字/退格/粘贴产生的事件，忽略
                if isinstance(k, keyboard.KeyCode) and not getattr(k, "vk", None):
                    return   # 纯Unicode注入的字符事件（自己打的字），忽略
                if self.push_mode == "hold" and self.state == "recording":
                    _log(f"热键持有期间按了别的键，取消录音: {k}")
                    self._cancel_recording()
            except Exception as e:
                _log(f"on_press 异常: {e}")

        def on_release(k):
            if k in self.hotkey_keys:
                _log(f"热键松开 {k}")
                self._hotkey(pressed=False)

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()

    # ---------- 菜单 ----------
    def _toggle_enable(self, _):
        self.enabled = not self.enabled
        self.item_enable.state = self.enabled

    def _toggle_mode(self, _):
        self.push_mode = "toggle" if self.push_mode == "hold" else "hold"
        self.item_mode.title = ("说话方式：按住说话" if self.push_mode == "hold"
                                else "说话方式：按一下开始，再按结束")

    def _toggle_tts(self, _):
        self.fb.enabled = not self.fb.enabled
        self.item_tts.state = self.fb.enabled

    def _change_hotkey(self, _):
        """改键：点菜单后，下一个按下的键成为说话键（ESC取消）。"""
        self._capturing_key = True
        self.indicator.show("🖱 按一个键，把它设为说话键（按ESC取消）")
        self.fb.say("请按新的说话键")

    def _captured_key(self, k):
        if k == keyboard.Key.esc:
            self.indicator.hide()
            self.fb.say("已取消改键")
            return
        val = None
        if isinstance(k, keyboard.Key):
            val = {"key": k.name}
        else:
            vk = getattr(k, "vk", None)
            if vk:
                val = {"vk": vk}
        if val is None:
            self.fb.say("这个键设不了，换一个")
            self.indicator.hide()
            return
        try:
            import json
            p = BASE_DIR / "config.json"
            cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            cfg["hotkey"] = val
            p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                         encoding="utf-8")
            self.cfg["hotkey"] = val
        except Exception as e:
            _log(f"改键保存失败: {e}")
            self.fb.say("保存失败，看看日志")
            self.indicator.hide()
            return
        self.hotkey_keys, self.hotkey_vks, self._hotkey_disp = _build_hotkey(val)
        self.item_key.title = f"更改说话键（当前：{self._hotkey_disp}）…"
        _log(f"说话键已改为 {val} ({self._hotkey_disp})")
        self.indicator.hide()
        self.fb.say("说话键已改好")

    def _test_type(self, _):
        self.engine.execute_dictation("小删测试：如果你看到这句话，说明打字通道已通。")
        self.fb.say("打字测试完成")

    def _show_help(self, _):
        rumps.Window(title="小删 · 命令速查", message=HELP_TEXT).run()

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
            self.fb.say("识别模型没加载成功，请看通知")
            return
        try:
            self.recorder.start()
        except Exception as e:
            _log(f"麦克风打开失败: {e}")
            self.fb.say("麦克风打不开")
            rumps.notification(
                "小删", "麦克风错误",
                "请到 系统设置 → 隐私与安全性 → 麦克风，勾选运行小删的程序（如：终端），然后重启小删")
            return
        self.state = "recording"
        self._discard = False
        self._mic_warned = False
        self._sent_count = 0
        self._partial_n = 0
        self.fb.sound("Pop")
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
        try:
            while self.state == "recording":
                new = self.recorder.take_new()
                if new.size:
                    for chunk in seg.feed(new):
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
                    self._finalize_utterance(chunk)
            for chunk in seg.flush():
                self._finalize_utterance(chunk)
        except Exception as e:
            _log(f"流式循环异常: {e}")
        finally:
            if not self._discard:
                self.state = "idle"
                self._run_queued_cmds()

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
                self.fb.sound("Tink")
            elif msg:
                self._last_error_say = msg
                self.fb.say(msg)
        finally:
            self._self_typing = False

    def _update_partial(self, seg):
        """实时草稿：对说到一半的这句出识别草稿，直接打进光标处（豆包式边说边出字）。"""
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
        import re
        if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", text):
            self.engine.cancel_partial()
            return   # 空识别/杂音
        # 防复读循环：识别到的正是刚才播报的报错内容时，忽略（别让它进文档）
        err = getattr(self, "_last_error_say", "")
        _strip = "。！？!?，, \u3000"
        if err and text.strip(_strip) == err.strip(_strip):
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
                    self.fb.sound("Tink")
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
                # 按住说话时手上正按着⌘，命令攒到松手后执行，杜绝⌘+退格灾难
                self._cmd_queue.append(payload)
                _log(f"按住模式：命令{payload.kind}已排队，松手后执行")
                self.fb.sound("Pop")
            else:
                self._exec_cmd(payload)
        finally:
            self._self_typing = False

    def _refresh_title(self, _):
        title = {"loading": "小删…", "recording": "●录",
                 "draining": "…收"}.get(self.state, "小删")
        if not self.enabled:
            title = "⏸小删"
        self.title = title
        # 悬浮条：实时显示识别中的文字（说话期间输入框零接触，doubao-murmur 同款）
        try:
            if self.state == "recording":
                draft = self.engine.draft
                if draft:
                    txt = f"● {draft}"
                    if self._sent_count:
                        txt += f"（已落 {self._sent_count} 句）"
                else:
                    txt = "● 正在听…（按ESC取消）"
                self.indicator.show(txt)
            else:
                self.indicator.hide()
        except Exception:
            pass


def main(argv=None):
    argv = list(argv or [])
    if "--selftest" in argv:
        from . import selftest
        return selftest.main([a for a in argv if a != "--selftest"])
    try:
        guard = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        guard.bind(("127.0.0.1", _SINGLE_INSTANCE_PORT))
    except OSError:
        print("小删已经在运行了：菜单栏右上角已有“小删”，直接按住 ⌘ 键说话即可。")
        try:
            rumps.notification("小删", "已经在运行了",
                               "菜单栏右上角已有“小删”，按住 ⌘ 键说话即可")
        except Exception:
            pass
        return 0
    from .config import load_config
    app = VoiceTypistApp(load_config())
    app.run()
