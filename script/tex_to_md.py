#!/usr/bin/env python3
"""
tex_to_md.py  —  Split GEB.tex by chapters and convert each to Markdown via pandoc.

Usage:
    python3 script/tex_to_md.py

Output:
    GEB/00 导言 一首音乐-逻辑的奉献.md  ...  GEB/41 六部无插入赋格.md
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

TEX_FILE = Path(__file__).parent.parent / "GEB_LaTeX" / "GEB.tex"
OUT_DIR  = Path(__file__).parent.parent / "GEB"

# ── 中文章号 ──────────────────────────────────────────────────────────────────
CHINESE_NUMS = [
    "一","二","三","四","五","六","七","八","九","十",
    "十一","十二","十三","十四","十五","十六","十七","十八","十九","二十",
]

# ── 作为独立章的 \section 标题（通常是对话章嵌在正文章里）─────────────────────
DIALOG_SECTION_TITLES: set[str] = {
    "螃蟹卡农",
    "一首无的奉献",
    "论TNT及有关系统中形式上不可判定的命题",
    "施德鲁，人设计的玩具",
}

# ── 其中需要作为「有序章」计入章号的 \section（即其实是 \chapter 但错写为 \section）
NUMBERED_DIALOG_SECTIONS: set[str] = {
    "论TNT及有关系统中形式上不可判定的命题",
}

# ── 特定章标题的前缀映射（用于 \chapter* 无章号但需要前缀的章）
CHAPTER_PREFIX: dict[str, str] = {
    "一首音乐-逻辑的奉献": "导言 ",
}

# ── 从 \chapter{}/\chapter*{}/\section[]{} 提取纯文本标题 ────────────────────
def extract_cmd_title(line: str) -> tuple[str, bool]:
    """Return (title_text, is_numbered).
    is_numbered = True only for \\chapter{} (no star).
    """
    # \section[short title]{...}  — use short title
    m = re.match(r'\\section\[([^\]]+)\]', line)
    if m:
        return _clean(m.group(1)), False

    # \section{title}
    m = re.match(r'\\section\{([^}]+)\}', line)
    if m:
        return _clean(m.group(1)), False

    # \chapter*{title}
    m = re.match(r'\\chapter\*\s*\{(.*)', line)
    if m:
        rest = m.group(1)
        return _clean(_close_brace(rest)), False

    # \chapter{title}
    m = re.match(r'\\chapter\s*\{(.*)', line)
    if m:
        rest = m.group(1)
        return _clean(_close_brace(rest)), True

    return "", False


def _close_brace(s: str) -> str:
    """Return text up to the matching closing brace (depth 1)."""
    depth = 1
    for i, ch in enumerate(s):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return s[:i]
    return s


def _clean(s: str) -> str:
    """Strip common LaTeX commands to get plain text."""
    # \texorpdfstring{display}{alt}  →  display
    s = re.sub(r'\\texorpdfstring\{([^}]*)\}\{[^}]*\}', r'\1', s)
    # \ldots / \ldots{} → … (keep tight — no trailing space)
    s = re.sub(r'\\ldots\{?\}?\s*', '…', s)
    # \hyperref[...]{...} → inner text
    s = re.sub(r'\\hyperref\[[^\]]*\]\{([^}]*)\}', r'\1', s)
    # \textsuperscript{...} → drop
    s = re.sub(r'\\textsuperscript\{[^}]*\}', '', s)
    # \emph{text} → text
    s = re.sub(r'\\emph\{([^}]*)\}', r'\1', s)
    # remaining \cmd{text} → text
    s = re.sub(r'\\[A-Za-z]+\{([^}]*)\}', r'\1', s)
    # bare \cmd  → ''
    s = re.sub(r'\\[A-Za-z]+', '', s)
    s = re.sub(r'[{}]', '', s)
    return s.strip()


# ── 提取章末尾注块，返回 {label: text} 映射，并从原文中删除该块 ─────────────
ENDNOTE_BLOCK_RE = re.compile(
    r'\{\\footnotesize.*?\\begin\{enumerate\}(.*?)\\end\{enumerate\}\s*\}',
    re.DOTALL,
)
LABEL_ITEM_RE = re.compile(
    r'\\phantomsection\s*\\label\{([^}]+)\}\{?\}?\s*\\item\s+(.*?)(?=\\phantomsection|$)',
    re.DOTALL,
)

def _clean_fn_text(s: str) -> str:
    """把脚注条目文本清理成纯 LaTeX（保留可嵌套的命令，供 pandoc 处理）。"""
    s = s.strip().rstrip('%').strip()
    # 去掉末尾空行
    s = re.sub(r'\s{2,}', ' ', s)
    return s


def extract_endnotes(tex: str) -> tuple[str, dict[str, str]]:
    """
    找到章末尾注 enumerate 块，提取 label→文本映射，
    并从 tex 中删除整个 endnote block。
    返回 (cleaned_tex, {label: footnote_text})
    """
    notes: dict[str, str] = {}

    def _handle_block(m: re.Match) -> str:
        inner = m.group(1)
        for lm in LABEL_ITEM_RE.finditer(inner):
            label = lm.group(1).strip()
            text  = _clean_fn_text(lm.group(2))
            notes[label] = text
        return ""  # 删除该块

    cleaned = ENDNOTE_BLOCK_RE.sub(_handle_block, tex)
    return cleaned, notes


def inject_footnotes(tex: str, notes: dict[str, str]) -> str:
    """
    将 \hyperref[fn:XXX]{\textsuperscript{N}} 替换为 \footnote{...}，
    以便 pandoc 生成 Obsidian 兼容的 [^N] 脚注。
    先去重相邻的重复引用，再替换。
    """
    if not notes:
        return tex

    # 1. 去除相邻重复引用：\hyperref[fn:X]{...}\hyperref[fn:X]{...} → 保留一个
    tex = re.sub(
        r'(\\hyperref\[([^\]]+)\]\{\\textsuperscript\{[^}]*\}\})'
        r'(\s*\\hyperref\[\2\]\{\\textsuperscript\{[^}]*\}\})+',
        r'\1',
        tex,
    )

    def _replace_ref(m: re.Match) -> str:
        label = m.group(1)
        text  = notes.get(label, "")
        if text:
            return rf"\footnote{{{text}}}"
        return ""  # 没找到对应脚注，删除上标引用

    # 2. \hyperref[fn:XXX]{\textsuperscript{N}} → \footnote{...}
    tex = re.sub(
        r'\\hyperref\[([^\]]+)\]\{\\textsuperscript\{[^}]*\}\}',
        _replace_ref,
        tex,
    )
    return tex


# ── 预处理 LaTeX chunk，清理 pandoc 不认识的自定义命令 ───────────────────────
def preprocess_latex(tex: str) -> str:
    # 1. 先提取脚注并注入为 \footnote{}
    tex, notes = extract_endnotes(tex)
    tex = inject_footnotes(tex, notes)

    # 2. \pandocbounded{...} → 内部内容（可能含 \includegraphics）
    tex = re.sub(r'\\pandocbounded\{((?:[^{}]|\{[^{}]*\})*)\}', r'\1', tex)

    # 3. \phantomsection\label{...}{} → 删除
    tex = re.sub(r'\\phantomsection\s*\\label\{[^}]*\}\{?\}?', '', tex)

    # 4. \hfill\break → \\
    tex = tex.replace(r'\hfill\break', r'\\')

    # 5. \hypersetup{...} → 删除
    tex = re.sub(r'\\hypersetup\{[^}]*\}', '', tex)

    # 6. \markboth{}{} → 删除
    tex = re.sub(r'\\markboth\{[^}]*\}\{[^}]*\}', '', tex)

    return tex


# ── 最小 LaTeX 文档头（让 pandoc 能识别中文内容和常见命令）────────────────────
MINI_PREAMBLE = r"""\documentclass{article}
\usepackage{amsmath,amssymb}
\newcommand{\speaker}[1]{\textbf{#1}}
\newcommand{\tightlist}{\setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}
\begin{document}
"""

MINI_POSTAMBLE = "\n\\end{document}\n"


# ── 把一段 LaTeX 内容用 pandoc 转成 Markdown ─────────────────────────────────
def latex_to_md(tex_body: str) -> str:
    cleaned = preprocess_latex(tex_body)
    # 包裹成完整文档供 pandoc 解析
    full_doc = MINI_PREAMBLE + cleaned + MINI_POSTAMBLE

    with tempfile.NamedTemporaryFile(
        suffix=".tex", mode="w", encoding="utf-8", delete=False
    ) as f:
        f.write(full_doc)
        tmp = Path(f.name)

    result = subprocess.run(
        [
            "pandoc",
            "--from", "latex",
            "--to", "markdown-raw_html+smart",
            "--wrap=none",
            "--markdown-headings=atx",
            str(tmp),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    tmp.unlink()

    md = result.stdout

    if result.returncode != 0 and not md.strip():
        # fallback: 返回 stderr 提示
        print(f"\n  [warn] pandoc stderr: {result.stderr[:200]}", end="")

    # 修正图片路径: ./media/OEBPS/Images/xxx.png  →  images/xxx.png
    md = re.sub(r'(?:\./)?media/OEBPS/Images/([^\s)\]"]+)', r'images/\1', md)

    return md


# ── 生成 YAML frontmatter ────────────────────────────────────────────────────
def make_frontmatter(title: str, volume: str) -> str:
    return (
        "---\n"
        f"title: {title}\n"
        f"volume: {volume}\n"
        "book_title: 哥德尔、艾舍尔、巴赫——集异璧之大成\n"
        "author: 〔美〕侯世达\n"
        "publisher: 商务印书馆\n"
        "language: zh\n"
        "---\n"
    )


# ── 主逻辑 ────────────────────────────────────────────────────────────────────
def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)

    lines = TEX_FILE.read_text(encoding="utf-8").splitlines(keepends=True)

    # ── 1. 找到正文起始（\part{集异璧GEB} 之后的 \chapter*{一首音乐...}）
    start_idx = 0
    for i, ln in enumerate(lines):
        if re.search(r'\\chapter\*\{一首音乐', ln):
            start_idx = i
            break

    # ── 2. 扫描行，收集分割点
    # 每个 split_point: (line_index, title, is_numbered, preceding_lines_for_label)
    # 注意 \section 型章节需要检查前几行有无 Dialog/Chapter label
    split_points: list[tuple[int, str, bool]] = []  # (idx, title, is_numbered)

    i = start_idx
    total = len(lines)
    while i < total:
        ln = lines[i].rstrip("\n")

        # \chapter 或 \chapter*
        if re.match(r'\s*\\chapter[\s*{]', ln):
            title, is_num = extract_cmd_title(ln.strip())
            if title:
                split_points.append((i, title, is_num))

        # \section — 只有当标题匹配已知对话章标题时才算章节分割
        elif re.match(r'\s*\\section[\s\[{]', ln):
            title, _ = extract_cmd_title(ln.strip())
            if title in DIALOG_SECTION_TITLES:
                # 属于 NUMBERED_DIALOG_SECTIONS 的视为有编号章
                is_num = title in NUMBERED_DIALOG_SECTIONS
                split_points.append((i, title, is_num))

        i += 1

    print(f"[info] 共找到 {len(split_points)} 个章节分割点，起始行 {start_idx + 1}")

    # ── 3. 确定卷标（\part 命令）
    part_positions: list[tuple[int, str]] = []
    for idx, ln in enumerate(lines):
        m = re.search(r'\\part\{([^}]+)\}', ln)
        if m:
            raw = m.group(1)
            if "集异璧" in raw or "GEB" in raw:
                part_positions.append((idx, "上篇：集异璧GEB"))
            elif "异集璧" in raw or "EGB" in raw:
                part_positions.append((idx, "下篇：异集璧EGB"))

    def get_volume(line_idx: int) -> str:
        vol = "上篇：集异璧GEB"
        for pos, name in part_positions:
            if pos <= line_idx:
                vol = name
        return vol

    # ── 4. 按分割点切割内容，转换并写文件
    chapter_counter = 0  # 有编号的章节计数器
    file_index = 0       # 文件序号 00, 01, ...

    for sp_i, (line_idx, raw_title, is_numbered) in enumerate(split_points):
        # 内容范围：从本章节命令行 到 下一个分割点前一行（或文件末）
        end_idx = split_points[sp_i + 1][0] if sp_i + 1 < len(split_points) else total

        # 提取内容（包含章节命令本身）
        chunk_lines = lines[line_idx:end_idx]
        tex_body = "".join(chunk_lines)

        # 章节标题与文件名
        volume = get_volume(line_idx)

        if is_numbered:
            chapter_counter += 1
            num_cn = CHINESE_NUMS[chapter_counter - 1]
            display_title = f"第{num_cn}章 {raw_title}"
        else:
            # 应用特定前缀映射（如"导言 "）
            prefix = CHAPTER_PREFIX.get(raw_title, "")
            display_title = prefix + raw_title

        # 安全文件名（macOS/Linux 下避免非法字符）
        safe_name = display_title.replace("/", "／").replace("\\", "＼").replace(":", "：")
        filename = f"{file_index:02d} {safe_name}.md"
        out_path = OUT_DIR / filename

        # pandoc 转换
        print(f"[{file_index:02d}] pandoc → {filename} ...", end=" ", flush=True)
        md_body = latex_to_md(tex_body)

        # 写文件：frontmatter + 内容
        frontmatter = make_frontmatter(display_title, volume)
        out_path.write_text(frontmatter + "\n" + md_body, encoding="utf-8")
        print(f"done ({len(md_body)} chars)")

        file_index += 1

    print(f"\n[done] 共写出 {file_index} 个 Markdown 文件到 {OUT_DIR}")


if __name__ == "__main__":
    main()
