"""语音反馈（Windows 版）：edge-tts 神经语音（对齐 mac 版晓伊）+ 系统 SAPI 兜底。

优先链：edge-tts(微软晓伊, 需联网, mp3 缓存) → 系统 SAPI 中文语音(离线, wav 缓存)
→ PowerShell 直接朗读。播报用 winmm MCI 放 mp3/wav，零第三方播放依赖。
报错才朗读，成功只叮一声；非 Windows 平台全部安全空转，便于跨平台跑逻辑测试。
"""
import ctypes
import hashlib
import itertools
import pathlib
import subprocess
import sys
import threading

IS_WIN = sys.platform == "win32"

_ALIAS_COUNTER = itertools.count(1)


def _log(msg):
    import time
    try:
        from voice_typist.config import BASE_DIR
        p = BASE_DIR / "run.log"
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _play_file_async(path):
    """winmm MCI 后台播放 mp3/wav（DirectShow 解码，系统自带）。"""
    alias = f"xshan_tts{next(_ALIAS_COUNTER)}"

    def go():
        try:
            mci = ctypes.windll.winmm.mciSendStringW
            mci.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p,
                            ctypes.c_uint, ctypes.c_void_p]
            if mci(f'open "{path}" type mpegvideo alias {alias}',
                   None, 0, None) != 0:
                return
            mci(f"play {alias} wait", None, 0, None)
            mci(f"close {alias}", None, 0, None)
        except Exception:
            pass
    threading.Thread(target=go, daemon=True).start()


def _ps_quote(s):
    return s.replace("'", "''")


class Feedback:
    """与 mac 版 app.Feedback 同接口：say(text) 异步朗读；sound(name) 提示音。"""

    def __init__(self, cfg):
        self.enabled = bool(cfg.get("tts_feedback", True))
        self.sound_on = bool(cfg.get("sound_feedback", True))
        self.engine_pref = cfg.get("tts_engine", "edge")
        self.voice = cfg.get("tts_voice", "zh-CN-XiaoyiNeural")
        from voice_typist.config import BASE_DIR
        self._dir = BASE_DIR / ".tts-cache"
        self._lock = threading.Lock()

    def say(self, text):
        if self.enabled and text:
            threading.Thread(target=self._speak, args=(text,), daemon=True).start()

    def _speak(self, text):
        if not IS_WIN:
            return
        text = text.replace("\r", " ").replace("\n", " ").strip()
        if not text:
            return
        try:
            if self.engine_pref != "system":
                p = self._edge_file(text)
                if p:
                    _play_file_async(p)
                    return
                self._prewarm_edge(text)   # 这次先用系统语音顶上，后台把晓伊版存进缓存
            p = self._sapi_file(text)
            if p:
                _play_file_async(p)
                return
        except Exception as e:
            _log(f"语音生成失败: {e}")
        # 退路：SAPI 直接朗读（阻塞发生在后台线程，可接受）
        try:
            ps = f"(New-Object -ComObject SAPI.SpVoice).Speak('{_ps_quote(text)}')"
            subprocess.run(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                 "-Command", ps],
                timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _prewarm_edge(self, text):
        """本次已回退系统语音；后台放宽超时把晓伊版合成进缓存，下次即用。"""
        threading.Thread(target=self._edge_file, args=(text,),
                         kwargs={"timeout": 20}, daemon=True).start()

    def _edge_file(self, text, timeout=4.0):
        """edge-tts 合成 mp3 并缓存；失败（未安装/断网/超时）返回 None。"""
        key = hashlib.md5(
            f"edge|{self.voice}|{text}".encode()).hexdigest() + ".mp3"
        p = self._dir / key
        if p.exists():
            return p
        with self._lock:
            if p.exists():
                return p
            try:
                import asyncio
                import edge_tts

                async def _go():
                    com = edge_tts.Communicate(text, self.voice)
                    await asyncio.wait_for(com.save(str(p)), timeout=timeout)

                self._dir.mkdir(exist_ok=True)
                asyncio.run(_go())
            except Exception as e:
                try:
                    p.unlink()
                except Exception:
                    pass
                _log(f"edge-tts 合成失败，回退系统语音: {type(e).__name__}: {e}")
                return None
        return p if p.exists() and p.stat().st_size > 500 else None

    def _sapi_file(self, text):
        """用 System.Speech 生成 wav 并缓存；失败返回 None。"""
        key = hashlib.md5(f"sapi|{text}".encode()).hexdigest() + ".wav"
        p = self._dir / key
        if p.exists():
            return p
        with self._lock:
            if p.exists():
                return p
            self._dir.mkdir(exist_ok=True)
            ps = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$v = $s.GetInstalledVoices() | Where-Object "
                "{ $_.VoiceInfo.Culture -like 'zh-*' } | Select-Object -First 1; "
                f"if ($v) {{ $s.SelectVoice($v.VoiceInfo.Name) }}; "
                f"$s.SetOutputToWaveFile('{p}'); "
                f"$s.Speak('{_ps_quote(text)}'); $s.Dispose()"
            )
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                     "-Command", ps],
                    timeout=20, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, check=True)
            except Exception:
                return None
        return p if p.exists() and p.stat().st_size > 200 else None

    _ALIAS = {"pop": "SystemExclamation", "tink": "SystemAsterisk"}

    def sound(self, name):
        if not (self.sound_on and IS_WIN):
            return
        alias = self._ALIAS.get(name, "SystemDefault")

        def _play():
            try:
                import winsound
                winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass
        threading.Thread(target=_play, daemon=True).start()
