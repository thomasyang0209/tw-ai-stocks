#!/bin/zsh
set -u

PROJECT_DIR="${0:A:h:h}"
PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
GIT_BIN="/usr/bin/git"

cd "$PROJECT_DIR" || exit 1

# 此腳本在專用自動化 clone 執行；工作區異常時停止，不覆蓋任何內容。
if [[ -n "$($GIT_BIN status --porcelain)" ]]; then
  print -u2 "自動化工作區不乾淨，停止更新"
  exit 1
fi
$GIT_BIN pull --ff-only origin main || exit 1

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
