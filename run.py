#!/usr/bin/env python3
"""小删：本地离线语音听写 + 语音编辑命令（Mac 菜单栏程序）。

用法：
  .venv/bin/python run.py                 启动菜单栏程序
  .venv/bin/python run.py --selftest ...  自检（perms / type / asr）
"""
import sys

from voice_typist.app import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
