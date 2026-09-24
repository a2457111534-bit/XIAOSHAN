@echo off
rem 下载离线模型（SenseVoice 约240MB + silero_vad 约644KB，只需一次）
rem Win10 1803+ 自带 curl 与 tar；下载不动可挂代理或用镜像
setlocal enabledelayedexpansion
cd /d %~dp0
set DIR=models\sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
set URL=https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2
set VAD_URL=https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx

if not exist %DIR% (
  if not exist models mkdir models
  cd models
  curl -L --fail --retry 3 --connect-timeout 20 -o sense-voice.tar.bz2 %URL%
  if errorlevel 1 (
    echo GitHub 直连失败，尝试镜像……
    curl -L --fail --retry 3 --connect-timeout 20 -o sense-voice.tar.bz2 https://ghfast.top/%URL%
    if errorlevel 1 ( echo 下载失败，请检查网络 & exit /b 1 )
  )
  tar xjf sense-voice.tar.bz2
  if errorlevel 1 ( echo 解压失败 & exit /b 1 )
  del sense-voice.tar.bz2
  cd ..
  echo 识别模型下载完成：%DIR%
) else (
  echo 识别模型已存在，跳过
)

if not exist models\silero_vad.onnx (
  curl -L --fail --retry 3 --connect-timeout 20 -o models\silero_vad.onnx %VAD_URL%
  if errorlevel 1 (
    curl -L --fail --retry 3 --connect-timeout 20 -o models\silero_vad.onnx https://ghfast.top/%VAD_URL%
    if errorlevel 1 ( echo 断句模型下载失败 & exit /b 1 )
  )
  echo 断句模型下载完成：models\silero_vad.onnx
) else (
  echo 断句模型已存在，跳过
)
echo 完成。
