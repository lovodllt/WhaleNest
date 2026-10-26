#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
for tool in python3 node npm dsh docker; do
  command -v "$tool" >/dev/null || { echo "缺少 $tool，请先按 docs/MANUAL.md 安装"; exit 1; }
done
python3 -m venv .venv
.venv/bin/python -m pip install -r config/requirements.txt
.venv/bin/python scripts/manage.py setup
.venv/bin/python scripts/manage.py plugins
.venv/bin/python scripts/manage.py wechat-package
.venv/bin/python scripts/manage.py build
.venv/bin/python scripts/manage.py start
