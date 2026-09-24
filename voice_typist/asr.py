"""SenseVoice 离线识别封装（sherpa-onnx），完全本地，不出电脑。"""
import re
from pathlib import Path

import numpy as np
import sherpa_onnx


class Recognizer:
    def __init__(self, model_dir: str, num_threads: int = 4):
        d = Path(model_dir)
        model = d / "model.int8.onnx"
        if not model.exists():
            model = d / "model.onnx"
        tokens = d / "tokens.txt"
        if not model.exists() or not tokens.exists():
            raise FileNotFoundError(
                f"在 {d} 下没找到 SenseVoice 模型（model.int8.onnx / tokens.txt），"
                "请先运行 ./download_model.sh")
        self.rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model), tokens=str(tokens),
            num_threads=num_threads, use_itn=True,
            language="zh")   # 锁定中文：自动猜语言曾把杂音猜成韩语

    def transcribe(self, samples: np.ndarray, sample_rate: int = 16000) -> str:
        """samples: float32 单声道；返回识别文本（含标点）。"""
        if samples is None or samples.size == 0:
            return ""
        stream = self.rec.create_stream()
        stream.accept_waveform(sample_rate, samples)
        self.rec.decode_stream(stream)
        text = stream.result.text.strip()
        # 兼容个别版本在开头带 <|zh|><|NEUTRAL|> 标记的情况
        text = re.sub(r"^(<\|[^|]*\|>)+", "", text)
        return text.strip()
