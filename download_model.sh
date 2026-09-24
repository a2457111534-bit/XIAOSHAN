#!/bin/bash
# 下载离线模型（SenseVoice 约240MB + silero_vad 约644KB，只需一次）
set -e
cd "$(dirname "$0")"
DIR="models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2"
VAD_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"

if [ ! -d "$DIR" ]; then
  mkdir -p models && cd models
  curl -L --fail --retry 3 --connect-timeout 20 -o sense-voice.tar.bz2 "$URL" \
    || curl -L --fail --retry 3 --connect-timeout 20 -o sense-voice.tar.bz2 "https://ghfast.top/$URL"
  tar xjf sense-voice.tar.bz2 && rm sense-voice.tar.bz2
  cd ..
  echo "识别模型下载完成：$DIR"
else
  echo "识别模型已存在，跳过"
fi

if [ ! -f models/silero_vad.onnx ]; then
  curl -L --fail --retry 3 --connect-timeout 20 -o models/silero_vad.onnx "$VAD_URL" \
    || curl -L --fail --retry 3 --connect-timeout 20 -o models/silero_vad.onnx "https://ghfast.top/$VAD_URL"
  echo "断句模型下载完成：models/silero_vad.onnx"
else
  echo "断句模型已存在，跳过"
fi
