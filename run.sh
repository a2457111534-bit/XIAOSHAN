#!/bin/bash
# 首次运行自动建虚拟环境装依赖；之后直接启动
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "首次运行：创建虚拟环境并安装依赖……"
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt || exit 1
fi
exec .venv/bin/python run.py "$@"
