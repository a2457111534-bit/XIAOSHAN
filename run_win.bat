@echo off
rem 小删 Windows 版启动器（双击运行；需先按 README 安装依赖和模型）
chcp 65001 >nul
cd /d %~dp0
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 run_win.py %*
) else (
  python run_win.py %*
)
pause
