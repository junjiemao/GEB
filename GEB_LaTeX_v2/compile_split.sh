#!/usr/bin/env bash
# compile_split.sh — 分批编译 GEB LaTeX v2
#
# 用法（从 GEB_LaTeX_v2/ 目录执行）：
#   ./compile_split.sh           # 编译全部批次
#   ./compile_split.sh 03        # 只编译 part03
#   ./compile_split.sh 02 05     # 编译 part02 和 part05

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p split

XELATEX_OPTS="-interaction=nonstopmode -file-line-error -output-directory=split"

# ── 选择要编译的批次 ──────────────────────────────────────────
if [[ $# -eq 0 ]]; then
  PARTS=(part01 part02 part03 part04 part05 part06)
else
  PARTS=()
  for n in "$@"; do PARTS+=("part$n"); done
fi

TOTAL=${#PARTS[@]}
DONE=0
FAIL=0

for PART in "${PARTS[@]}"; do
  echo ""
  echo "▶ 编译 $PART.tex  (${DONE}+1/${TOTAL})"
  if xelatex $XELATEX_OPTS "$PART.tex" 2>&1 | tail -8; then
    DONE=$((DONE+1))
    echo "  ✓ $PART.pdf → split/"
  else
    FAIL=$((FAIL+1))
    echo "  ✗ $PART 编译失败，查看 split/$PART.log"
  fi
done

echo ""
echo "════════════════════════════════"
echo "  完成 $DONE / $TOTAL   失败 $FAIL"
echo "════════════════════════════════"
