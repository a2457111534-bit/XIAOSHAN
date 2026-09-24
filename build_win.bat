@echo off
rem 一键打包 Windows 免安装版（在装有 Python 3.10~3.12 的 Windows 10/11 上双击运行）
rem 产物：dist\XiaoShan-win-v2.3.zip（模型已内置，上传到 GitHub Releases 即可分发）
chcp 65001 >nul
cd /d %~dp0

where py >nul 2>nul
if errorlevel 1 (
  echo 没找到 Python。请先安装 Python 3.10~3.12（勾选 py launcher 和 Add to PATH）再运行本脚本。
  pause & exit /b 1
)
if not exist models\silero_vad.onnx (
  echo 缺模型文件，先运行 download_model.bat 下载模型。
  pause & exit /b 1
)

echo [1/4] 建独立构建环境 .venv-build ...
py -3 -m venv .venv-build
call .venv-build\Scripts\activate.bat
python -m pip install -q -U pip
pip install -q -r requirements-win.txt pyinstaller
if errorlevel 1 ( echo 依赖安装失败 & pause & exit /b 1 )

echo [2/4] PyInstaller 打包 ...
pyinstaller XiaoShan.spec --noconfirm
if errorlevel 1 ( echo 打包失败 & pause & exit /b 1 )

echo [3/4] 装入模型与配置 ...
xcopy /e /i /y /q models dist\XiaoShan\models\ >nul
if errorlevel 1 ( echo 复制模型失败 & pause & exit /b 1 )
copy /y config.json dist\XiaoShan\config.json >nul
rem 去掉 900MB 全精度备用模型，包内只留实际使用的 int8 版
del /q dist\XiaoShan\models\sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17\model.onnx >nul 2>nul

echo [4/4] 压缩 ...
powershell -NoProfile -Command "Compress-Archive -Path 'dist\XiaoShan' -DestinationPath 'dist\XiaoShan-win-v2.3.zip' -Force"
if errorlevel 1 ( echo 压缩失败 & pause & exit /b 1 )

echo.
echo 完成！dist\XiaoShan-win-v2.3.zip 就是 Windows 免安装版（解压后运行 XiaoShan\XiaoShan.exe）。
pause
