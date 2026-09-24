#!/bin/bash
# 用系统 TTS 生成测试音频（无需真人说话即可测识别链路）
cd "$(dirname "$0")"
V=Tingting
say -v $V -o f1.wav --data-format=LEI16@16000 "今年以来全局各项工作稳步推进"
say -v $V -o f2.wav --data-format=LEI16@16000 "小删，删除上一句"
say -v $V -o f3.wav --data-format=LEI16@16000 "小删，把稳步推进改成快速推进"
say -v $V -o f4.wav --data-format=LEI16@16000 "小山，删除含有稳步推进的那句话"
ls -la *.wav
