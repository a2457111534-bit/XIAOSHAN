"""Windows 版自检工具。用法：
  python run_win.py --selftest mic        检查麦克风
  python run_win.py --selftest type 你好  3 秒后把“你好”打进当前光标处
  python run_win.py --selftest uia        读当前焦点文本框（UIA 通道）
  python run_win.py --selftest asr 文件.wav  识别一个 16k wav 文件
"""
import sys
import time
import wave

import numpy as np


def check_mic():
    print("Windows 无需辅助功能/麦克风授权（与 mac 不同）；"
          "若下面报错：Windows 设置 → 隐私和安全性 → 麦克风，允许桌面应用访问。")
    try:
        import sounddevice as sd
        with sd.InputStream(samplerate=16000, channels=1, dtype="float32"):
            pass
        print("麦克风: 可用 ✓")
    except Exception as e:
        print("麦克风: 打不开 ✗ →", e)


def do_type(text):
    from . import win_inject
    print("3 秒后开始输入，请把光标放到任意输入框……")
    for i in (3, 2, 1):
        print(i)
        time.sleep(1)
    win_inject.set_clipboard_text(text)
    win_inject.paste_clipboard()
    print("已发送（剪贴板+Ctrl+V）。若没有出现文字，确认目标窗口不是管理员权限运行的。")


def do_uia():
    from . import win_text
    text, cursor, sel = win_text.read_focused()
    if text is None:
        print("UIA 读不到焦点文本框（该应用可能不支持；删除/替换会按会话账本兜底）")
        return
    print(f"读到 {len(text)} 字；光标位置={cursor}；选中长度={sel}")
    print(f"内容开头：{text[:60]!r}")


def do_asr(path):
    from voice_typist.asr import Recognizer
    from voice_typist.config import BASE_DIR, load_config
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
    cmd = argv[0] if argv else "mic"
    if cmd == "mic":
        check_mic()
    elif cmd == "type":
        do_type(argv[1] if len(argv) > 1 else "小删打字测试123")
    elif cmd == "uia":
        do_uia()
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
