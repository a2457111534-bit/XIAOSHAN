"""录音与断句：输入流 + silero-vad 自动分句（说完一句停顿半秒，那句立刻交出去识别）。"""
import pathlib
import time

import numpy as np
import sounddevice as sd


class Recorder:
    """持续录音，消费式取数（take_new），配合 Segmenter 实时断句。"""

    def __init__(self, sample_rate=16000):
        self.sr = sample_rate
        self._stream = None
        self._pending = []
        self.total = 0        # 本次会话累计采样数（零音频诊断用）
        self.peak = 0.0       # 本次会话最大振幅（区分数字静音/没开流）

    def start(self, fresh=False):
        self._pending = []
        self.total = 0
        self.peak = 0.0
        if fresh:
            # 上一轮疑似静音死流：先开关一次空流换新的采集会话再正式开
            try:
                warm = sd.InputStream(samplerate=self.sr, channels=1,
                                      dtype="float32")
                warm.start()
                time.sleep(0.05)
                warm.stop()
                warm.close()
                time.sleep(0.2)
            except Exception:
                pass
        self._stream = sd.InputStream(
            samplerate=self.sr, channels=1, dtype="float32",
            callback=self._cb)
        self._stream.start()

    def _cb(self, indata, frames, time_info, status):
        col = indata[:, 0].copy()
        self._pending.append(col)
        self.total += frames
        if col.size:
            p = float(np.abs(col).max())
            if p > self.peak:
                self.peak = p

    def take_new(self):
        out, self._pending = self._pending, []
        if not out:
            return np.zeros(0, dtype="float32")
        return np.concatenate(out)

    def drain_all(self):
        return self.take_new()

    def stop(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()

    def is_active(self):
        return self._stream is not None


class Segmenter:
    """silero-vad 断句（sherpa-onnx VoiceActivityDetector，听写类产品通用方案）。

    说完一句停顿≥0.5秒即交出该句；不足0.25秒的碎音自动忽略。
    注意：必须按≤512样本的小块喂（silero 窗口大小），一次喂一大段会丢音频。
    """

    CHUNK = 512

    def __init__(self, sr=16000, model_path=None,
                 min_silence=0.45, min_speech=0.25):
        import sherpa_onnx
        if model_path is None:
            from .config import BASE_DIR
            model_path = str(BASE_DIR / "models" / "silero_vad.onnx")
        cfg = sherpa_onnx.VadModelConfig()
        cfg.sample_rate = sr
        cfg.silero_vad.model = model_path
        cfg.silero_vad.threshold = 0.5
        cfg.silero_vad.min_silence_duration = min_silence
        cfg.silero_vad.min_speech_duration = min_speech
        cfg.silero_vad.max_speech_duration = 15
        self.vad = sherpa_onnx.VoiceActivityDetector(cfg)

    def current(self):
        """说到一半的这句音频（实时草稿用），没在说话时返回空数组。"""
        try:
            seg = self.vad.current_segment
            if seg is None:
                return np.zeros(0, dtype=np.float32)
            return np.asarray(seg.samples, dtype=np.float32)
        except Exception:
            return np.zeros(0, dtype=np.float32)

    def feed(self, x: np.ndarray):
        """喂入新音频，返回已说完的句子列表（通常为空或一句）。"""
        out = []
        for i in range(0, len(x), self.CHUNK):
            self.vad.accept_waveform(x[i:i + self.CHUNK])
            while not self.vad.empty():
                out.append(np.asarray(self.vad.front.samples))
                self.vad.pop()
        return out

    def flush(self):
        """录音结束：交出最后没等到停顿的半句，返回列表。"""
        try:
            self.vad.flush()
        except Exception:
            pass
        out = []
        while not self.vad.empty():
            out.append(np.asarray(self.vad.front.samples))
            self.vad.pop()
        return out
