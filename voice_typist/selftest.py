"""自检工具。用法：
  .venv/bin/python run.py --selftest perms       检查辅助功能/麦克风权限
  .venv/bin/python run.py --selftest type 你好    3 秒后把“你好”打进当前光标处
  .venv/bin/python run.py --selftest asr 文件.wav 识别一个 16k wav 文件
"""
import sys
import time
import wave

import numpy as np


def check_perms():
    from .perms import accessibility_trusted
    ax = accessibility_trusted()
    if ax is None:
        print("辅助功能: 无法检测")
    elif ax:
        print("辅助功能: 已授权 ✓")
    else:
        print("辅助功能: 未授权 ✗")
        print("  → 系统设置 → 隐私与安全性 → 辅助功能，勾选你运行本程序的 App（如：终端），然后重新运行")
    try:
        import sounddevice as sd
        with sd.InputStream(samplerate=16000, channels=1, dtype="float32"):
            pass
        print("麦克风: 已授权 ✓")
    except Exception as e:
        print("麦克风: 打不开 ✗ →", e)
        print("  → 系统设置 → 隐私与安全性 → 麦克风，勾选运行本程序的 App（如：终端）")


def do_type(text):
    from . import inject
    print("3 秒后开始输入，请把光标放到任意输入框……")
    for i in (3, 2, 1):
        print(i)
        time.sleep(1)
    inject.type_text(text)
    print("已发送。若没有出现文字，请先运行 --selftest perms 授权辅助功能")


def do_asr(path):
    import pathlib

    from .asr import Recognizer
    from .config import BASE_DIR, load_config
    cfg = load_config()
    rec = Recognizer(str(BASE_DIR / cfg["model_dir"]))
    with wave.open(path) as w:
        rate = w.getframerate()
        data = (np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
                .astype(np.float32) / 32768.0)
    t0 = time.time()
    text = rec.transcribe(data, sample_rate=rate)
    print(f"识别结果（{time.time() - t0:.2f}s）：{text}")


def main(argv):
    cmd = argv[0] if argv else "perms"
    if cmd == "perms":
        check_perms()
    elif cmd == "type":
        do_type(argv[1] if len(argv) > 1 else "小删打字测试123")
    elif cmd == "asr":
        if len(argv) < 2:
            print("请给出 wav 文件路径")
        else:
            do_asr(argv[1])
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
