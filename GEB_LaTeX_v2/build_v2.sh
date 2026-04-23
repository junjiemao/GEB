#!/usr/bin/env bash
# build_v2.sh — GEB LaTeX v2 构建脚本
#
# 用法（在 GEB_LaTeX_v2/ 目录内执行，或从任意目录执行）：
#   ./build_v2.sh                  # 全流程：pandoc → postprocess → split → 并行编译
#   ./build_v2.sh --skip-pandoc    # 跳过 pandoc（仅 postprocess → split → 编译）
#   ./build_v2.sh --skip-postprocess  # 跳过后处理（仅 split → 编译）
#   ./build_v2.sh --pandoc-only    # 只生成 GEB.tex，不做任何后续处理
#   ./build_v2.sh --compile-only   # 只编译（已有 partXX.tex 时用此选项）
#   ./build_v2.sh --part 01        # 只编译指定 part（两次 xelatex）
#
# 前提：
#   - pandoc 3.x 已安装（brew install pandoc）
#   - XeLaTeX 已安装（MacTeX / BasicTeX）
#   - 字体：Noto Serif CJK SC、Kaiti SC、Heiti SC、Palatino 已安装
#   - fonts/geb.ttf 存在
#   - Python 3 + script/postprocess_tex.py + script/split_v2.py

set -euo pipefail

# ─── 路径 ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
EPUB_DIR="$REPO_DIR/book/GEB.epub"
PACKED_EPUB="/tmp/GEB_packed.epub"
WORK_DIR="$SCRIPT_DIR"
TEX_FILE="$WORK_DIR/GEB.tex"
TEMPLATE="$WORK_DIR/geb-template.tex"
FILTER="$WORK_DIR/geb-filter.lua"
SPLIT_DIR="$WORK_DIR/split"
POSTPROCESS="$REPO_DIR/script/postprocess_tex.py"
SPLIT_SCRIPT="$REPO_DIR/script/split_v2.py"
OLD_MEDIA="$REPO_DIR/GEB_LaTeX/media"    # 已处理好的图片目录

# ─── 参数解析 ────────────────────────────────────────────────────────────
SKIP_PANDOC=0
SKIP_POSTPROCESS=0
PANDOC_ONLY=0
COMPILE_ONLY=0
SINGLE_PART=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-pandoc)        SKIP_PANDOC=1;         shift ;;
    --skip-postprocess)   SKIP_POSTPROCESS=1;    shift ;;
    --pandoc-only)        PANDOC_ONLY=1;         shift ;;
    --compile-only)       COMPILE_ONLY=1; SKIP_PANDOC=1; SKIP_POSTPROCESS=1; shift ;;
    --part)               SINGLE_PART="$2";      shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

# ─── 工具检查 ────────────────────────────────────────────────────────────
if ! command -v xelatex &>/dev/null; then
  echo "错误：未找到 xelatex，请先安装 MacTeX。" >&2; exit 1
fi
if [[ $SKIP_PANDOC -eq 0 && $COMPILE_ONLY -eq 0 ]] && ! command -v pandoc &>/dev/null; then
  echo "错误：未找到 pandoc，请先安装（brew install pandoc）。" >&2; exit 1
fi

mkdir -p "$SPLIT_DIR"

# ─── Step 1: 打包 EPUB（目录 → zip）────────────────────────────────────
if [[ $SKIP_PANDOC -eq 0 && $COMPILE_ONLY -eq 0 ]]; then
  echo "▶ [1/4] 打包 EPUB"
  if [[ ! -d "$EPUB_DIR" ]]; then
    echo "错误：未找到 EPUB 目录：$EPUB_DIR" >&2; exit 1
  fi
  cd "$EPUB_DIR"
  zip -X -r "$PACKED_EPUB" . -x "*.DS_Store" -x "__MACOSX/*" > /dev/null
  echo "  ✓ 已打包：$PACKED_EPUB"
  cd "$WORK_DIR"

  # ─── Step 2: pandoc EPUB → LaTeX ──────────────────────────────────────
  echo "▶ [2/4] pandoc: EPUB → GEB.tex"
  pandoc "$PACKED_EPUB" \
    --from epub \
    --to latex \
    --template "$TEMPLATE" \
    --lua-filter "$FILTER" \
    --extract-media="./media" \
    --toc \
    --toc-depth=2 \
    --wrap=none \
    --output "$TEX_FILE"
  echo "  ✓ 生成 GEB.tex（$(wc -l < "$TEX_FILE") 行）"
fi

[[ $PANDOC_ONLY -eq 1 ]] && { echo "仅 pandoc 模式，跳过后续步骤。"; exit 0; }

# ─── Step 3: 后处理 ──────────────────────────────────────────────────────
if [[ $SKIP_POSTPROCESS -eq 0 && $COMPILE_ONLY -eq 0 ]]; then
  echo "▶ [3/4] 后处理 GEB.tex（postprocess_tex.py）"
  COPY_MEDIA_ARG=""
  if [[ -d "$OLD_MEDIA" ]]; then
    COPY_MEDIA_ARG="--copy-media $OLD_MEDIA"
  fi
  cd "$REPO_DIR"
  python3 "$POSTPROCESS" \
    "$WORK_DIR/GEB.tex" \
    --epub "$PACKED_EPUB" \
    $COPY_MEDIA_ARG
  echo "  ✓ 后处理完成"

  echo "▶ [3.5/4] 分割 GEB.tex → partXX.tex"
  python3 "$SPLIT_SCRIPT"
  echo "  ✓ 已生成 part 文件"
  cd "$WORK_DIR"
fi

# ─── Step 4: 编译 ────────────────────────────────────────────────────────
cd "$WORK_DIR"

compile_part() {
  local part="$1"
  local tex="$WORK_DIR/part${part}.tex"
  if [[ ! -f "$tex" ]]; then
    echo "  跳过：未找到 $tex" >&2; return
  fi
  echo "  编译 part${part}…"
  for pass in 1 2; do
    xelatex \
      -interaction=nonstopmode \
      -file-line-error \
      -output-directory="$SPLIT_DIR" \
      "$tex" \
      > "/tmp/part${part}_pass${pass}.log" 2>&1 || true
  done
  local pages
  pages=$(grep "Output written" "$SPLIT_DIR/part${part}.log" 2>/dev/null \
          | grep -oE '[0-9]+ page' | grep -oE '[0-9]+' || echo "?")
  echo "    ✓ part${part}.pdf  ${pages} 页"
}

if [[ -n "$SINGLE_PART" ]]; then
  echo "▶ [4/4] 编译 part${SINGLE_PART}"
  compile_part "$SINGLE_PART"
else
  # 收集所有 partXX.tex
  PARTS=()
  for f in "$WORK_DIR"/part[0-9][0-9].tex; do
    [[ -f "$f" ]] && PARTS+=("$(basename "$f" .tex | sed 's/part//')")
  done

  if [[ ${#PARTS[@]} -eq 0 ]]; then
    echo "未找到 partXX.tex，请先运行 split_v2.py。" >&2; exit 1
  fi

  echo "▶ [4/4] 并行编译 ${#PARTS[@]} 个 part（双遍）"
  PIDS=()
  for part in "${PARTS[@]}"; do
    compile_part "$part" &
    PIDS+=($!)
  done
  for pid in "${PIDS[@]}"; do wait "$pid" || true; done
fi

echo ""
echo "═══════════════════════════════════════════════"
echo "  ✓ 构建完成：$SPLIT_DIR/partXX.pdf"
ls -lh "$SPLIT_DIR"/part*.pdf 2>/dev/null | awk '{print "    "$NF, $5}' || true
echo "═══════════════════════════════════════════════"
