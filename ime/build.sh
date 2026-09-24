#!/bin/bash
# 构建并安装小删输入法到 ~/Library/Input Methods/
set -e
cd "$(dirname "$0")/.."
APP="小删输入法.app"
rm -rf "ime/build/$APP"
mkdir -p "ime/build/$APP/Contents/MacOS" "ime/build/$APP/Contents/Resources"
cp ime/Info.plist "ime/build/$APP/Contents/"
clang -O -fobjc-arc \
    ime/XiaoShanIME.m -o "ime/build/$APP/Contents/MacOS/XiaoShanIME" \
    -framework Cocoa -framework InputMethodKit
# 图标：先用系统图标占位
ICON="/System/Library/CoreServices/CoreTypes.app/Contents/Resources/public.icns"
[ -f "$ICON" ] && cp "$ICON" "ime/build/$APP/Contents/Resources/icon.icns"
codesign --force -s - "ime/build/$APP"
rm -rf "$HOME/Library/Input Methods/$APP"
cp -R "ime/build/$APP" "$HOME/Library/Input Methods/"
echo "已安装到 ~/Library/Input Methods/$APP"
echo "请到：系统设置 → 键盘 → 输入法 → 编辑 → 添加 → 简体中文 → 小删 启用"
