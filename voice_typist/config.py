"""配置加载：项目根目录 config.json 覆盖默认值。"""
import json
import pathlib
import sys


def base_dir() -> pathlib.Path:
    """项目根目录：开发时=源码根；PyInstaller 打包后=exe 所在目录
    （config.json / models / run.log 都放 exe 旁边，整个文件夹拷走即可用）。"""
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent.parent


BASE_DIR = base_dir()

DEFAULTS = {
    "trigger_word": ["小删除", "想删除", "小山口", "小山竹", "小珊瑚", "小山虫", "小替换", "想替换", "想退换", "小退换", "大宝贝", "大宝贝儿"],  # 语音指令词：删除系/替换系/发送系（大宝贝/大宝贝儿，发送），可自定义
    "hotkey": "any_cmd",              # 说话热键：any_cmd(推荐,Win键盘=任意田字旗标键) / right_cmd / any_alt / f5 / f6
    "push_mode": "hold",              # hold=按住说话(用户定稿) / toggle=按一下开始再按结束
    "sample_rate": 16000,
    "model_dir": "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
    "num_threads": 4,
    "tts_engine": "edge",             # edge=微软神经语音(需联网,好听) / system=系统婷婷(离线)
    "tts_voice": "zh-CN-XiaoyiNeural",  # 晓伊；还有 zh-CN-XiaoxiaoNeural(晓晓) / zh-CN-YunxiNeural(云希)
    "tts_feedback": True,             # 用语音播报错误提示
    "sound_feedback": True,           # 开始录音/命令成功的提示音
}


def load_config(path=None):
    cfg = dict(DEFAULTS)
    p = pathlib.Path(path) if path else BASE_DIR / "config.json"
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    return cfg
