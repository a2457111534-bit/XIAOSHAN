# -*- mode: python ; coding: utf-8 -*-
# macOS 打包配置：.venv/bin/pyinstaller XiaoShanMac.spec
# 产物 dist/XiaoShanMac/（免安装目录）；把 models/ 与 config.json 放到该目录即可分发。
# 运行时模型/配置/日志都按 BASE_DIR（可执行文件所在目录）查找（voice_typist/config.py）。
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# 带二进制/数据文件的第三方包：全部收进包
for pkg in ('sherpa_onnx', 'sounddevice', 'pynput', 'rumps', 'pypinyin'):
    r = collect_all(pkg)
    datas += r[0]; binaries += r[1]; hiddenimports += r[2]

# pyobjc 框架包装（菜单栏/键盘注入/AX 读写）；PyInstaller 通常能自动发现，
# 这里显式收集一遍保险，缺哪个跳哪个
for pkg in ('AppKit', 'Quartz', 'ApplicationServices', 'Foundation', 'Cocoa'):
    try:
        r = collect_all(pkg)
        datas += r[0]; binaries += r[1]; hiddenimports += r[2]
    except Exception:
        pass

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='XiaoShanMac',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,             # mac 上禁用 upx（易破坏代码签名/ Mach-O）
    console=False,         # rumps 菜单栏程序，不弹终端
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='XiaoShanMac',
)
