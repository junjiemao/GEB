#!/usr/bin/env python3
"""
split_tex.py — 把 pandoc 生成的单文件 GEB.tex 拆成主文件 + 分章 include 文件
用法：
  python3 split_tex.py GEB.tex          # 拆分，输出到 GEB_split/
  python3 split_tex.py GEB.tex --only 3 # 只编译第 3 块（用 \\includeonly）
"""

import re
import sys
import os
import argparse
from pathlib import Path

def split_tex(src: str, out_dir: str, only: list[int] | None = None):
    out_path = Path(out_dir)
    out_path.mkdir(exist_ok=True)

    text = Path(src).read_text(encoding="utf-8")

    # 找 \begin{document} 位置
    doc_start = text.index(r"\begin{document}")
    preamble = text[:doc_start + len(r"\begin{document}")]

    # 找 \end{document}
    doc_end = text.rindex(r"\end{document}")
    body = text[doc_start + len(r"\begin{document}"):doc_end]

    # 在正文中找所有 \section 位置（第一级）
    sec_re = re.compile(r"^\\section[\[\{]", re.MULTILINE)
    positions = [m.start() for m in sec_re.finditer(body)]

    # 前导部分（frontmatter / title / toc / mainmatter）
    prologue = body[:positions[0]] if positions else body

    # 按 section 切分
    parts = []
    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(body)
        parts.append(body[pos:end])

    print(f"共 {len(parts)} 个 section，输出到 {out_dir}/")

    # 写每个 part 文件
    part_names = []
    for i, part in enumerate(parts):
        name = f"part{i+1:02d}"
        part_names.append(name)
        (out_path / f"{name}.tex").write_text(part, encoding="utf-8")

    # 写主文件
    if only:
        only_list = ",".join(f"part{n:02d}" for n in only if 1 <= n <= len(parts))
        includeonly_line = f"\\includeonly{{{only_list}}}\n"
        print(f"\\includeonly: {only_list}")
    else:
        includeonly_line = ""

    includes = "\n".join(f"\\include{{{name}}}" for name in part_names)

    # \includeonly 必须在 \begin{document} 之前（放入 preamble 末尾）
    # preamble 末尾已含 \begin{document}，插到它前面
    if includeonly_line:
        preamble_with_only = preamble.replace(
            r"\begin{document}",
            includeonly_line + r"\begin{document}",
            1,
        )
    else:
        preamble_with_only = preamble

    main_tex = (
        preamble_with_only + "\n"
        + prologue
        + includes + "\n"
        + r"\end{document}" + "\n"
    )

    (out_path / "GEB-main.tex").write_text(main_tex, encoding="utf-8")
    print(f"主文件：{out_dir}/GEB-main.tex")
    print(f"编译：cd {out_dir} && xelatex -interaction=nonstopmode GEB-main.tex")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("src", help="输入 tex 文件")
    parser.add_argument("--out", default=None, help="输出目录（默认与 src 同目录下的 split/）")
    parser.add_argument("--only", nargs="*", type=int, default=None,
                        help="只编译指定的 part 编号（如 --only 1 2 3）")
    args = parser.parse_args()

    src_path = Path(args.src)
    out_dir = args.out or str(src_path.parent / "split")
    split_tex(args.src, out_dir, args.only)
