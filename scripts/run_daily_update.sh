#!/bin/zsh
set -u

PROJECT_DIR="/Users/yangchihsesh/Desktop/claude"
PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
GIT_BIN="/usr/bin/git"

cd "$PROJECT_DIR" || exit 1

# 有其他人工修改時不拉遠端，避免覆蓋使用者內容；更新程式只會改 MARKET 區塊。
if [[ -z "$($GIT_BIN status --porcelain)" ]]; then
  $GIT_BIN pull --ff-only origin main || true
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

"$PYTHON_BIN" scripts/update_daily.py || exit 1
"$PYTHON_BIN" -m py_compile scripts/update_daily.py || exit 1

if $GIT_BIN diff --quiet -- index.html; then
  exit 0
fi

$GIT_BIN add index.html || exit 1
$GIT_BIN commit -m "每日自動更新台股分析 ($(TZ=Asia/Taipei date +%F))" || exit 1
$GIT_BIN push origin main || exit 1
