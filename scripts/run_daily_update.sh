#!/bin/zsh
set -u

PROJECT_DIR="${0:A:h:h}"
DESKTOP_DIR="/Users/yangchihsesh/Desktop/claude"
PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
GIT_BIN="/usr/bin/git"

sync_desktop_copy() {
  # 使用者實際以 file:// 開啟的是桌面副本；只在工作區乾淨時快轉同步，避免覆蓋手動修改。
  if [[ ! -d "$DESKTOP_DIR/.git" ]]; then
    print -u2 "找不到桌面專案，略過本機同步：$DESKTOP_DIR"
    return 0
  fi
  if [[ -n "$($GIT_BIN -C "$DESKTOP_DIR" status --porcelain)" ]]; then
    print -u2 "桌面專案有未提交修改，略過同步以避免覆蓋"
    return 0
  fi
  $GIT_BIN -C "$DESKTOP_DIR" pull --ff-only origin main || return 1
}

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
  sync_desktop_copy
  exit 0
fi

$GIT_BIN add index.html || exit 1
$GIT_BIN commit -m "每日自動更新台股分析 ($(TZ=Asia/Taipei date +%F))" || exit 1
$GIT_BIN push origin main || exit 1
sync_desktop_copy || exit 1
