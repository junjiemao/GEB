#!/usr/bin/env python3
"""
split_v2.py — 将 GEB_LaTeX_v2/GEB.tex 按章节分割为多个独立可编译部分

生成文件：
  GEB_LaTeX_v2/part01.tex … partNN.tex   ← 各部分，可从 GEB_LaTeX_v2/ 目录独立编译
  GEB_LaTeX_v2/compile_split.sh           ← 批量编译脚本

用法：
  python3 script/split_v2.py [--batch-size N]
"""

import re
import os
import sys
import math

# ─── 路径 ────────────────────────────────────────────────────────────────────
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GEB_TEX = os.path.join(REPO, "GEB_LaTeX_v2", "GEB.tex")
OUT_DIR = os.path.join(REPO, "GEB_LaTeX_v2")          # 与 GEB.tex 同级，保证 ./media/ 路径有效
SPLIT_AUX_DIR = os.path.join(OUT_DIR, "split")        # PDF/aux 产物目录

CHAPTERS_PER_BATCH = 8   # 每批包含的章节数（含对话章节）

# ─── 解析命令行 ───────────────────────────────────────────────────────────────
for i, arg in enumerate(sys.argv[1:]):
    if arg == "--batch-size" and i + 2 < len(sys.argv):
        CHAPTERS_PER_BATCH = int(sys.argv[i + 2])


def main():
    if not os.path.exists(GEB_TEX):
        print(f"错误：找不到 {GEB_TEX}", file=sys.stderr)
        sys.exit(1)

    with open(GEB_TEX, "r", encoding="utf-8") as f:
        lines = f.readlines()

    print(f"读取 GEB.tex：{len(lines)} 行")

    # ── 定位结构标记 ─────────────────────────────────────────────────────────
    begin_doc_idx = mainmatter_idx = end_doc_idx = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s == r"\begin{document}" and begin_doc_idx is None:
            begin_doc_idx = i
        elif s == r"\mainmatter" and mainmatter_idx is None:
            mainmatter_idx = i
        elif s == r"\end{document}":
            end_doc_idx = i

    if None in (begin_doc_idx, mainmatter_idx, end_doc_idx):
        print("错误：找不到必要的文档标记", file=sys.stderr)
        sys.exit(1)

    print(f"  \\begin{{document}} : 第 {begin_doc_idx+1} 行")
    print(f"  \\mainmatter        : 第 {mainmatter_idx+1} 行")
    print(f"  \\end{{document}}   : 第 {end_doc_idx+1} 行")

    # ── 提取各段 ─────────────────────────────────────────────────────────────
    preamble = "".join(lines[:begin_doc_idx])              # 不含 \begin{document}
    frontmatter_block = "".join(lines[begin_doc_idx : mainmatter_idx + 1])  # \begin{document} … \mainmatter
    body_lines = lines[mainmatter_idx + 1 : end_doc_idx]   # 正文（\markboth 到 \end{document} 前）

    # ── 找出所有 \chapter 位置 ────────────────────────────────────────────────
    chapter_re = re.compile(r"^\\chapter")
    starred_re = re.compile(r"^\\chapter\*")
    numbered_re = re.compile(r"^\\chapter(?!\*)")

    chapter_positions = [i for i, l in enumerate(body_lines) if chapter_re.match(l)]
    print(f"  找到 {len(chapter_positions)} 章（含对话/无编号章）")

    # ── 计算分批断点（以章节为边界） ──────────────────────────────────────────
    n_batches = math.ceil(len(chapter_positions) / CHAPTERS_PER_BATCH)
    batch_start_positions = []   # 在 body_lines 中的起始行索引

    for b in range(n_batches):
        pos = chapter_positions[b * CHAPTERS_PER_BATCH]
        batch_start_positions.append(pos)

    # batch 0 从 body_lines[0] 开始（可能有 \markboth 等前导内容）
    batch_start_positions[0] = 0

    # 计算每批的 (start, end) 范围
    batches = []
    for i, start in enumerate(batch_start_positions):
        end = batch_start_positions[i + 1] if i + 1 < len(batch_start_positions) else len(body_lines)
        batches.append((start, end))

    # ── 生成各部分文件 ─────────────────────────────────────────────────────────
    os.makedirs(SPLIT_AUX_DIR, exist_ok=True)

    part_names = []
    for batch_idx, (start, end) in enumerate(batches):
        batch_body = "".join(body_lines[start:end])
        part_num = batch_idx + 1
        part_name = f"part{part_num:02d}"
        part_names.append(part_name)
        out_path = os.path.join(OUT_DIR, f"{part_name}.tex")

        # 统计本批含有哪些章节（用于注释）
        batch_chapters = [l.strip()[:80] for l in body_lines[start:end] if chapter_re.match(l)]

        # 计算本批之前已有的「有编号」章数（\chapter{} 非星号），用于 \setcounter
        prev_numbered = sum(1 for l in body_lines[:start] if numbered_re.match(l))

        print(f"\n  part{part_num:02d}.tex  body行 {start+1}–{end}  ({len(batch_chapters)} 章)")
        for ch in batch_chapters[:4]:
            print(f"    {ch}")
        if len(batch_chapters) > 4:
            print(f"    … （共 {len(batch_chapters)} 章）")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"%% GEB LaTeX v2 — Part {part_num:02d} / {n_batches}\n")
            f.write(f"%% 自动生成  split_v2.py\n")
            f.write(f"%% 独立编译（从 GEB_LaTeX_v2/ 目录）：\n")
            f.write(f"%%   xelatex -output-directory=split {part_name}.tex\n\n")

            f.write(preamble)
            f.write("\n")

            if batch_idx == 0:
                # 第一批：保留完整 frontmatter（扉页、目录、mainmatter）
                f.write(frontmatter_block)
                f.write("\\markboth{}{}\n\n")
            else:
                # 后续批次：直接进入 mainmatter，设置章节计数器
                f.write("\\begin{document}\n")
                f.write("\\mainmatter\n")
                f.write(f"\\setcounter{{chapter}}{{{prev_numbered}}}\n")
                f.write("\\markboth{}{}\n\n")

            f.write(batch_body)
            f.write("\n\\end{document}\n")

    # ── 生成批量编译脚本 ───────────────────────────────────────────────────────
    compile_sh = os.path.join(OUT_DIR, "compile_split.sh")
    with open(compile_sh, "w", encoding="utf-8") as f:
        f.write("#!/usr/bin/env bash\n")
        f.write("# compile_split.sh — 分批编译 GEB LaTeX v2\n")
        f.write("#\n")
        f.write("# 用法（从 GEB_LaTeX_v2/ 目录执行）：\n")
        f.write("#   ./compile_split.sh           # 编译全部批次\n")
        f.write("#   ./compile_split.sh 03        # 只编译 part03\n")
        f.write("#   ./compile_split.sh 02 05     # 编译 part02 和 part05\n")
        f.write("\nset -euo pipefail\n")
        f.write('SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"\n')
        f.write("cd \"$SCRIPT_DIR\"\n")
        f.write("mkdir -p split\n\n")
        f.write("XELATEX_OPTS=\"-interaction=nonstopmode -file-line-error -output-directory=split\"\n\n")
        f.write("# ── 选择要编译的批次 ──────────────────────────────────────────\n")
        f.write("if [[ $# -eq 0 ]]; then\n")
        f.write("  PARTS=(" + " ".join(part_names) + ")\n")
        f.write("else\n")
        f.write("  PARTS=()\n")
        f.write("  for n in \"$@\"; do PARTS+=(\"part$n\"); done\n")
        f.write("fi\n\n")
        f.write("TOTAL=${#PARTS[@]}\n")
        f.write("DONE=0\nFAIL=0\n\n")
        f.write("for PART in \"${PARTS[@]}\"; do\n")
        f.write('  echo ""\n')
        f.write('  echo "▶ 编译 $PART.tex  (${DONE}+1/${TOTAL})"\n')
        f.write("  if xelatex $XELATEX_OPTS \"$PART.tex\" 2>&1 | tail -8; then\n")
        f.write("    DONE=$((DONE+1))\n")
        f.write('    echo "  ✓ $PART.pdf → split/"\n')
        f.write("  else\n")
        f.write("    FAIL=$((FAIL+1))\n")
        f.write('    echo "  ✗ $PART 编译失败，查看 split/$PART.log"\n')
        f.write("  fi\n")
        f.write("done\n\n")
        f.write('echo ""\n')
        f.write('echo "════════════════════════════════"\n')
        f.write('echo "  完成 $DONE / $TOTAL   失败 $FAIL"\n')
        f.write('echo "════════════════════════════════"\n')

    os.chmod(compile_sh, 0o755)

    print(f"\n{'═'*50}")
    print(f"  分割完成：{n_batches} 个部分")
    print(f"  文件位置：{OUT_DIR}/part01.tex … part{n_batches:02d}.tex")
    print(f"  编译脚本：{compile_sh}")
    print(f"\n  用法（从 GEB_LaTeX_v2 目录）：")
    print(f"    ./compile_split.sh          # 全部批次")
    print(f"    ./compile_split.sh 01       # 仅第一批")
    print(f"{'═'*50}")


if __name__ == "__main__":
    main()
