#!/usr/bin/env bash
# build.sh — GEB LaTeX 完整构建脚本
#
# 用法：
#   ./build.sh              # 全流程：pandoc → postprocess → split → xelatex × 2
#   ./build.sh --skip-pandoc  # 跳过 pandoc（正文未变动时节省时间）
#   ./build.sh --only 3     # 只编译第 3 个 split 块（快速调试）
#   ./build.sh --passes 1   # 只跑 1 次 xelatex（默认 2 次）
#
# 前提：
#   - pandoc 已安装（brew install pandoc）
#   - XeLaTeX 已安装（MacTeX / BasicTeX）
#   - python3 已安装
#   - book/GEB.epub 存在
#   - GEB_LaTeX/geb-template.tex 存在（包含所有 preamble 设置）

set -euo pipefail

# ─── 路径 ────────────────────────────────────────────────
REPO="$(cd "$(dirname "$0")" && pwd)"
EPUB="$REPO/book/GEB.epub"
LATEX_DIR="$REPO/GEB_LaTeX"
SPLIT_DIR="$LATEX_DIR/split"
TEX_FILE="$LATEX_DIR/GEB.tex"
TEMPLATE="$LATEX_DIR/geb-template.tex"
SCRIPT_DIR="$REPO/script"

# ─── 参数解析 ────────────────────────────────────────────
SKIP_PANDOC=0
ONLY_ARG=""
PASSES=2

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-pandoc) SKIP_PANDOC=1; shift ;;
    --only) ONLY_ARG="$2"; shift 2 ;;
    --passes) PASSES="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

# ─── 工具检查 ────────────────────────────────────────────
for cmd in python3 xelatex; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "错误：未找到 $cmd，请先安装。" >&2
    exit 1
  fi
done

if [[ $SKIP_PANDOC -eq 0 ]] && ! command -v pandoc &>/dev/null; then
  echo "错误：未找到 pandoc，请先安装（brew install pandoc）。" >&2
  exit 1
fi

# ─── Step 1: pandoc ──────────────────────────────────────
if [[ $SKIP_PANDOC -eq 0 ]]; then
  if [[ ! -f "$EPUB" ]]; then
    echo "错误：EPUB 文件不存在：$EPUB" >&2
    exit 1
  fi
  if [[ ! -f "$TEMPLATE" ]]; then
    echo "错误：模板文件不存在：$TEMPLATE" >&2
    exit 1
  fi

  echo "▶ Step 1: pandoc 生成 GEB.tex"
  pandoc "$EPUB" \
    --to latex \
    --template "$TEMPLATE" \
    --toc --toc-depth=2 \
    --extract-media="$LATEX_DIR/media" \
    -o "$TEX_FILE"
  echo "  → $TEX_FILE"
else
  echo "▶ Step 1: 跳过 pandoc（--skip-pandoc）"
fi

# ─── Step 2: postprocess ─────────────────────────────────
echo "▶ Step 2: postprocess_tex.py"
python3 "$SCRIPT_DIR/postprocess_tex.py" "$TEX_FILE"

# ─── Step 3: split ───────────────────────────────────────
echo "▶ Step 3: split_tex.py"
cd "$LATEX_DIR"
if [[ -n "$ONLY_ARG" ]]; then
  python3 "$SCRIPT_DIR/split_tex.py" GEB.tex --only "$ONLY_ARG"
else
  python3 "$SCRIPT_DIR/split_tex.py" GEB.tex
fi

# ─── Step 4: xelatex ─────────────────────────────────────
cd "$SPLIT_DIR"

# 清除旧的辅助文件，防止 stale .toc/.aux 干扰
rm -f GEB-main.toc GEB-main.aux GEB-main.out GEB-main.bbl

for ((i=1; i<=PASSES; i++)); do
  echo "▶ Step 4: xelatex（第 $i / $PASSES 次）"
  xelatex -interaction=nonstopmode GEB-main.tex \
    | grep -E "^\!|^Output written|^No pages|^LaTeX Warning:" \
    || true
done

# ─── 完成 ────────────────────────────────────────────────
PDF="$SPLIT_DIR/GEB-main.pdf"
if [[ -f "$PDF" ]]; then
  PAGES=$(mdls -name kMDItemNumberOfPages "$PDF" 2>/dev/null \
    | grep -oE '[0-9]+' | head -1 || echo "?")
  echo ""
  echo "[OK] Build OK: $PDF (${PAGES} pages)"
else
  echo "[FAIL] Build failed: PDF not generated" >&2
  exit 1
fi
