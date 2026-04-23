#!/usr/bin/env bash
# build_v2.sh — GEB LaTeX v2 构建脚本
#
# 用法（在 GEB_LaTeX_v2/ 目录内执行）：
#   ./build_v2.sh                 # 全流程：pandoc → xelatex × 2
#   ./build_v2.sh --skip-pandoc   # 跳过 pandoc（仅重新编译）
#   ./build_v2.sh --passes 1      # 只跑 1 次 xelatex
#   ./build_v2.sh --pandoc-only   # 只生成 GEB.tex，不编译
#
# 前提：
#   - pandoc 3.x 已安装（brew install pandoc）
#   - XeLaTeX 已安装（MacTeX / BasicTeX）
#   - 字体：Noto Serif CJK SC、Kaiti SC、Heiti SC、Palatino 已安装
#   - fonts/geb.ttf 存在

set -euo pipefail

# ─── 路径（脚本所在目录即工作目录）─────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
EPUB="$REPO_DIR/book/GEB.epub"
WORK_DIR="$SCRIPT_DIR"
TEX_FILE="$WORK_DIR/GEB.tex"
TEMPLATE="$WORK_DIR/geb-template.tex"
FILTER="$WORK_DIR/geb-filter.lua"
MEDIA_DIR="$WORK_DIR/media"

# ─── 参数解析 ────────────────────────────────────────────────────────────
SKIP_PANDOC=0
PANDOC_ONLY=0
PASSES=2

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-pandoc)  SKIP_PANDOC=1;  shift ;;
    --pandoc-only)  PANDOC_ONLY=1;  shift ;;
    --passes)       PASSES="$2";    shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

# ─── 工具检查 ────────────────────────────────────────────────────────────
for cmd in xelatex; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "错误：未找到 $cmd，请先安装 MacTeX。" >&2
    exit 1
  fi
done

if [[ $SKIP_PANDOC -eq 0 ]] && ! command -v pandoc &>/dev/null; then
  echo "错误：未找到 pandoc，请先安装（brew install pandoc）。" >&2
  exit 1
fi

# ─── Step 1: pandoc EPUB → LaTeX ─────────────────────────────────────────
if [[ $SKIP_PANDOC -eq 0 ]]; then
  echo "▶ [1/2] pandoc: EPUB → GEB.tex"
  
  if [[ ! -e "$EPUB" ]]; then
    echo "错误：未找到 EPUB：$EPUB" >&2
    exit 1
  fi

  cd "$WORK_DIR"

  pandoc "$EPUB" \
    --from epub \
    --to latex \
    --template "$TEMPLATE" \
    --lua-filter "$FILTER" \
    --extract-media="./media" \
    --toc \
    --toc-depth=2 \
    --top-level-division=chapter \
    --wrap=none \
    --output "$TEX_FILE"

  echo "  ✓ 生成 GEB.tex（$(wc -l < "$TEX_FILE") 行）"
fi

[[ $PANDOC_ONLY -eq 1 ]] && { echo "仅 pandoc 模式，跳过编译。"; exit 0; }

# ─── Step 2: XeLaTeX 编译 ────────────────────────────────────────────────
cd "$WORK_DIR"

echo "▶ [2/2] xelatex × ${PASSES}"
for i in $(seq 1 "$PASSES"); do
  echo "  第 $i 次编译…"
  xelatex \
    -interaction=nonstopmode \
    -file-line-error \
    -halt-on-error \
    "$TEX_FILE" \
    2>&1 | tail -30 || {
      echo "  ⚠ xelatex 第 $i 次返回非零（可能有警告，检查 GEB.log）"
    }
done

echo ""
echo "═══════════════════════════════════════════"
echo "  ✓ 构建完成：$WORK_DIR/GEB.pdf"
echo "═══════════════════════════════════════════"
