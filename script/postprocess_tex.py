#!/usr/bin/env python3
"""
postprocess_tex.py — GEB.tex 后处理脚本

将 pandoc 从 EPUB 生成的 GEB.tex 进行以下修复，使其能被 XeLaTeX 干净编译：

  1. 删除空脚注 \\footnote{}
     (pandoc 未能提取 duokan EPUB 脚注内容时留下的空壳，101 处)

  2. 图说居中加粗
     (pandoc 生成 "图N．标题" 裸文本，替换为 \\begin{center}\\small\\textbf{...}\\end{center})

  3. Unicode 符号替换 → LaTeX 命令
     (Georgia 字体缺少数学/逻辑符号、带圈数字等；在数学环境外做替换)

  4. Tai Tham 乱码字符修复
     (EPUB 提取 artifact，Tai Tham 字符实为汉字编码错误)

使用方法:
  python3 postprocess_tex.py GEB.tex
  python3 postprocess_tex.py GEB.tex --dry-run   # 只统计，不写入
  python3 postprocess_tex.py GEB.tex -o out.tex  # 输出到新文件

完整工作流:
  # 1. pandoc 生成 LaTeX
  pandoc /tmp/GEB_packed.epub -o GEB.tex --to latex \\
      --template geb-template.tex --toc --toc-depth=2 --extract-media=./media

  # 2. 后处理 (本脚本)
  python3 script/postprocess_tex.py GEB_LaTeX/GEB.tex

  # 3. 拆分 + 编译
  python3 script/split_tex.py GEB_LaTeX/GEB.tex
  cd GEB_LaTeX/split && xelatex -interaction=nonstopmode GEB-main.tex
"""

import re
import sys
import zipfile
import argparse
from pathlib import Path


# ──────────────────────────────────────────────────────────
#  Unicode → LaTeX 替换表
#  只替换数学环境外的字符（避免把 $\rightarrow$ 双包裹）
#  Georgia 字体确认缺失：→ ⇐ ⇔ ∧ ∨ ①-⑥ ⑴-⑻
#  同类逻辑符号一并处理：⇒ ← ↔ ∀ ∃ ¬ 等
# ──────────────────────────────────────────────────────────
UNICODE_MAP = {
    # ── 逻辑/命题箭头（Georgia 缺失，已从编译日志确认）
    '→':  r'$\rightarrow$',
    '←':  r'$\leftarrow$',
    '↔':  r'$\leftrightarrow$',
    '↑':  r'$\uparrow$',
    '↓':  r'$\downarrow$',
    '⇒':  r'$\Rightarrow$',
    '⇐':  r'$\Leftarrow$',
    '⇔':  r'$\Leftrightarrow$',
    '⇑':  r'$\Uparrow$',
    '⇓':  r'$\Downarrow$',

    # ── 命题逻辑运算符（确认缺失）
    '∧':  r'$\wedge$',
    '∨':  r'$\vee$',
    '¬':  r'$\lnot$',
    '∀':  r'$\forall$',
    '∃':  r'$\exists$',

    # ── 关系符号（Georgia 可能缺失）
    '≡':  r'$\equiv$',
    '≢':  r'$\not\equiv$',
    '≅':  r'$\cong$',
    '≈':  r'$\approx$',
    '≠':  r'$\neq$',
    '≤':  r'$\leq$',
    '≥':  r'$\geq$',
    '≪':  r'$\ll$',
    '≫':  r'$\gg$',
    '∝':  r'$\propto$',

    # ── 集合论（Georgia 缺失）
    '∈':  r'$\in$',
    '∉':  r'$\notin$',
    '⊂':  r'$\subset$',
    '⊃':  r'$\supset$',
    '⊆':  r'$\subseteq$',
    '⊇':  r'$\supseteq$',
    '∩':  r'$\cap$',
    '∪':  r'$\cup$',
    '∅':  r'$\emptyset$',

    # ── 运算符（Georgia 缺失部分）
    '∘':  r'$\circ$',
    '⊕':  r'$\oplus$',
    '⊗':  r'$\otimes$',
    '⊖':  r'$\ominus$',
    '√':  r'$\surd$',
    '∞':  r'$\infty$',
    '∑':  r'$\sum$',
    '∏':  r'$\prod$',
    '∫':  r'$\int$',
    '∂':  r'$\partial$',
    '∇':  r'$\nabla$',

    # ── 带圈数字 ①②… （确认缺失，来自编译日志）
    '①':  r'\textcircled{\footnotesize 1}',
    '②':  r'\textcircled{\footnotesize 2}',
    '③':  r'\textcircled{\footnotesize 3}',
    '④':  r'\textcircled{\footnotesize 4}',
    '⑤':  r'\textcircled{\footnotesize 5}',
    '⑥':  r'\textcircled{\footnotesize 6}',
    '⑦':  r'\textcircled{\footnotesize 7}',
    '⑧':  r'\textcircled{\footnotesize 8}',
    '⑨':  r'\textcircled{\footnotesize 9}',
    '⑩':  r'\textcircled{\footnotesize 10}',

    # ── 括号序号 ⑴⑵… （确认缺失，来自编译日志）
    '⑴':  r'(1)',
    '⑵':  r'(2)',
    '⑶':  r'(3)',
    '⑷':  r'(4)',
    '⑸':  r'(5)',
    '⑹':  r'(6)',
    '⑺':  r'(7)',
    '⑻':  r'(8)',
    '⑼':  r'(9)',
    '⑽':  r'(10)',

    # ── 罗马数字 Ⅰ Ⅱ Ⅲ（用大写字母代替，Georgia 无官方大写罗马数字字形）
    'Ⅰ':  'I',
    'Ⅱ':  'II',
    'Ⅲ':  'III',
    'Ⅳ':  'IV',
    'Ⅴ':  'V',
    'Ⅵ':  'VI',
    'Ⅶ':  'VII',
    'Ⅷ':  'VIII',
    'Ⅸ':  'IX',
    'Ⅹ':  'X',

    # ── 竖排/特殊标点（EPUB 提取 artifact）
    '︙':  r'\ldots',     # U+FE19 竖排省略号 → 省略号
}

# ──────────────────────────────────────────────────────────
#  Tai Tham 乱码字符修复
#  这些 Tai Tham 字符是 EPUB 提取时的编码错误，实为汉字
#  Context 分析：
#    ꪡ (U+AAA1) × 11 → 龙  （"炸脖龙" = Jabberwock；"腌龙相" = 奇异形态）
#    ꪞ (U+AA9E) × 1  → 哦  （"乌龟：{哦}不得呢" = "Oh, certainly not."）
#    ꪪ (U+AAAA) × 1  → 奇  （"般得{奇}子" = Bandersnatch，赵元任译）
#  注：如果替换不正确，可手动修改本字典或在 GEB.tex 中搜索 [TAI THAM]
# ──────────────────────────────────────────────────────────
TAI_THAM_MAP = {
    'ꪡ':  '龙',   # U+AAA1 - 炸脖龙 (Jabberwock) × 11 处
    'ꪞ':  '哦',   # U+AA9E - 乌龟对话开头感叹词 × 1 处
    'ꪪ':  '奇',   # U+AAAA - 般得奇子 (Bandersnatch) × 1 处
}


# ──────────────────────────────────────────────────────────
#  数学环境保护：替换时跳过已有的 $...$ $$...$$ \[...\] \(...\)
# ──────────────────────────────────────────────────────────
# 匹配各类 LaTeX 数学环境（按优先级从长到短）
_MATH_ENV_PAT = re.compile(
    r'\$\$.*?\$\$'                   # $$...$$（display math）
    r'|\$[^$\n]+?\$'                 # $...$（inline math）
    r'|\\\[.*?\\\]'                  # \[...\]（display math）
    r'|\\\(.*?\\\)'                  # \(...\)（inline math）
    r'|\\begin\{(equation|align|gather|math|displaymath)\*?\}.*?'
    r'\\end\{\1\*?\}',               # \begin{equation}...\end{equation} 等
    re.DOTALL
)

# 占位符标记（使用 LaTeX 不会合法包含的控制字符序列）
_PLACEHOLDER_PREFIX = '\x00MATHENV'
_PLACEHOLDER_SUFFIX = '\x00'


def _protect_math(text):
    """用占位符保护所有数学环境，返回 (protected_text, [saved_regions])。"""
    saved = []

    def _replace(m):
        saved.append(m.group())
        return f'{_PLACEHOLDER_PREFIX}{len(saved) - 1}{_PLACEHOLDER_SUFFIX}'

    protected = _MATH_ENV_PAT.sub(_replace, text)
    return protected, saved


def _restore_math(text, saved):
    """恢复被保护的数学环境。"""
    def _replace(m):
        return saved[int(m.group(1))]

    return re.sub(
        rf'{re.escape(_PLACEHOLDER_PREFIX)}(\d+){re.escape(_PLACEHOLDER_SUFFIX)}',
        _replace,
        text,
    )


def replace_unicode(text, umap):
    """在数学环境外替换 Unicode 符号为 LaTeX 命令。"""
    protected, saved = _protect_math(text)
    for char, latex in umap.items():
        protected = protected.replace(char, latex)
    return _restore_math(protected, saved)


# ──────────────────────────────────────────────────────────
#  Fix 1: 删除空脚注
# ──────────────────────────────────────────────────────────
def fix_empty_footnotes(text):
    """删除所有 \\footnote{} 空脚注（pandoc 未能提取 duokan 脚注内容留下的空壳）。"""
    before = text.count(r'\footnote{}')
    text = text.replace(r'\footnote{}', '')
    return text, before


# ──────────────────────────────────────────────────────────
#  Fix 2: 图说居中加粗
#  pandoc 将图说生成为裸文本行 "图N．标题"；
#  替换为 \begin{center}\small\textbf{图N．标题}\end{center}
# ──────────────────────────────────────────────────────────
# 匹配 "图" 后跟数字、句号（全角或半角）、标题文字
_FIG_CAPTION_PAT = re.compile(
    r'^(图\s*\d+[．.。]\s*.+)$',
    re.MULTILINE,
)

# 不重复包裹（幂等；已被替换的行包含 \begin{center}）
_FIG_ALREADY_WRAPPED = re.compile(
    r'\\begin\{center\}\\small\\textbf\{图',
)


def fix_figure_captions(text):
    """将裸图说行替换为居中加粗 LaTeX 命令。"""
    count = 0

    def _replace(m):
        nonlocal count
        line = m.group(1)
        # 幂等检查：如果已经被包裹就不再处理
        # （通过检查行内容的方式；此正则只匹配裸文本行）
        count += 1
        return (
            r'\begin{center}\small\textbf{' + line + r'}\end{center}'
        )

    text = _FIG_CAPTION_PAT.sub(_replace, text)
    return text, count


# ──────────────────────────────────────────────────────────
#  Fix 3: Unicode 逻辑/数学符号 → LaTeX
# ──────────────────────────────────────────────────────────
def fix_unicode_symbols(text):
    """将 Georgia 字体缺失的 Unicode 符号替换为 LaTeX 命令（跳过已有数学环境）。"""
    counts = {}
    for char in UNICODE_MAP:
        n = text.count(char)
        if n:
            counts[char] = n
    text = replace_unicode(text, UNICODE_MAP)
    total = sum(counts.values())
    return text, total, counts


# ──────────────────────────────────────────────────────────
#  Fix 4: Tai Tham 乱码字符
# ──────────────────────────────────────────────────────────
def fix_tai_tham(text):
    """替换 Tai Tham 字符（EPUB 提取 artifact）为对应汉字。"""
    counts = {}
    for char in TAI_THAM_MAP:
        n = text.count(char)
        if n:
            counts[char] = n
    for char, replacement in TAI_THAM_MAP.items():
        text = text.replace(char, replacement)
    total = sum(counts.values())
    return text, total, counts


# ──────────────────────────────────────────────────────────
#  Fix 5: 将「pandocbounded图片 + \begin{center}图说\end{center}」
#         包装为 figure[H] 环境，加 \caption* + \phantomsection\label
# ──────────────────────────────────────────────────────────
#
# 匹配标准图说块：\pandocbounded + （空行）+ \begin{center}\small\textbf{图N．标题}\end{center}
# 图N：N 为纯数字（不含子图后缀 (a)(b)-①等，那些单独处理）
_FIG_ENV_PAT = re.compile(
    r'(\\pandocbounded\{\\includegraphics\[keepaspectratio\]\{([^}]+)\}\})'
    r'(\s*\n[ \t]*\n?)'                              # 1~2 个空行
    r'(\\begin\{center\}\\small\\textbf\{'
    r'(图(\d+)[．.。]([^}]+))'
    r'\}\\end\{center\})',
    re.DOTALL,
)


def fix_figure_envs(text):
    r"""
    将标准图说块替换为 figure[H] 环境：

        \begin{figure}[H]
        \centering
        \pandocbounded{\includegraphics[keepaspectratio]{path}}
        \phantomsection\label{fig:N}
        \caption*{图N．标题}
        \end{figure}

    使用 [H]（需要模板中已有 \usepackage{float}）强制原地放置，
    避免浮动导致图文顺序错乱。
    \caption* 不产生 LaTeX 自动编号，保留原始"图N."文字。
    \label{fig:N} 供 \hyperref[fig:N]{图N} 交叉引用使用。
    """
    count = 0

    def _replace(m):
        nonlocal count
        img_cmd  = m.group(1)            # \pandocbounded{...}
        num_str  = m.group(6)            # "1", "2", ...
        full_cap = m.group(5)            # "图1．约翰·塞巴斯第安·巴赫"
        count += 1
        return (
            f'\\begin{{figure}}[H]\n'
            f'\\centering\n'
            f'{img_cmd}\n'
            f'\\phantomsection\\label{{fig:{num_str}}}\n'
            f'\\caption*{{{full_cap}}}\n'
            f'\\end{{figure}}'
        )

    text = _FIG_ENV_PAT.sub(_replace, text)
    return text, count


# ──────────────────────────────────────────────────────────
#  Fix 6: 为特殊图说行添加 \phantomsection\label
#         （不紧跟 pandocbounded、或带子图后缀的图说）
#
#  处理两类：
#    A. \begin{center}\small\textbf{图N…}\end{center}（Fix5 遗留，无前驱图片）
#    B. 裸文本子图说 "图33(a)．标题"（Fix2 未能匹配 / 子图后缀）
# ──────────────────────────────────────────────────────────

# A: Fix5 之后仍残存的 \begin{center}...\end{center} 图说（无 figure 环境包裹）
_LEFTOVER_CENTER_PAT = re.compile(
    r'(\\begin\{center\}\\small\\textbf\{'
    r'图(\d+)'
    r'[^}]*\}\\end\{center\})'
)

# B: 裸文本子图说行（图33(a)．/ 图35-① 等，Fix2 正则不匹配的变体）
_BARE_SUBFIG_PAT = re.compile(
    r'^(图(\d+)\([a-zA-Z]\)[．.。].+|'
    r'图(\d+)-[^\s][^\n]+)$',
    re.MULTILINE,
)


def fix_special_figure_labels(text):
    r"""
    为 Fix5 未处理的图说加上 \phantomsection\label{fig:N}，
    以便文中 \hyperref[fig:N]{图N} 超链接能正确跳转。
    """
    count = 0

    # 处理 \begin{center}...\end{center} 形式（Fix5 遗留）
    def _replace_center(m):
        nonlocal count
        num = m.group(2)
        count += 1
        return f'\\phantomsection\\label{{fig:{num}}}\n{m.group(1)}'

    text = _LEFTOVER_CENTER_PAT.sub(_replace_center, text)

    # 处理裸文本子图说行（图33(a)/图35-① 等）
    def _replace_bare(m):
        nonlocal count
        line = m.group(0)
        num = m.group(2) or m.group(3)
        count += 1
        return (
            f'\\phantomsection\\label{{fig:{num}}}\n'
            f'{{\\small\\textbf{{{line}}}}}'
        )

    text = _BARE_SUBFIG_PAT.sub(_replace_bare, text)
    return text, count


# ──────────────────────────────────────────────────────────
#  Fix 7: 文中 「图N」引用 → \hyperref[fig:N]{图N}
#         仅在正文（非 \caption/\label/\section 等命令内）替换
# ──────────────────────────────────────────────────────────

# 需要整体保护的 LaTeX 命令块（防止内部的"图N"被误替换）
_PROTECT_CMD_PAT = re.compile(
    r'\\caption\*?\{[^}]*(?:\{[^}]*\}[^}]*)*\}'   # \caption*{...} / \caption{...}
    r'|\\label\{[^}]*\}'                            # \label{...}
    r'|\\(?:sub)*section\*?\{[^}]*\}'               # \section{...}
    r'|\\chapter\*?\{[^}]*\}'                       # \chapter{...}
    r'|\\phantomsection'                             # \phantomsection（裸命令）
    r'|\\hyperref\[[^\]]*\]\{[^}]*\}'               # \hyperref[...]{...}（幂等）
    r'|\\textbf\{图\d+[^}]*\}'                      # \textbf{图N...}
    r'|\\ref\{[^}]*\}',                             # \ref{...}
    re.DOTALL,
)

_FIG_PROT_PRE = '\x00FIGP'
_FIG_PROT_SUF = '\x00'

# 图N 引用：图 + 数字，后面不紧跟 ．/。/.（那是图说标题分隔符）和 (（子图后缀）
_FIG_REF_PAT = re.compile(r'图(\d+)(?![．.。(（])')


def fix_figure_refs(text):
    r"""
    把正文中的「图N」替换为 \hyperref[fig:N]{图N}，使 PDF 中形成可点击链接。

    保护（跳过）范围：
    - \caption*{...} / \caption{...}     图说本身
    - \label{...}                         标签定义
    - \section / \chapter 标题
    - \phantomsection                     锚点命令
    - 已有的 \hyperref[...]{...}          幂等保护
    - \textbf{图N...}                     加粗图说残余
    - 图N 后接 ．/。/./(（图说分隔符或子图后缀）
    """
    saved = []

    def _protect(m):
        saved.append(m.group())
        return f'{_FIG_PROT_PRE}{len(saved)-1}{_FIG_PROT_SUF}'

    protected = _PROTECT_CMD_PAT.sub(_protect, text)

    count = 0

    def _ref_replace(m):
        nonlocal count
        n = m.group(1)
        count += 1
        return f'\\hyperref[fig:{n}]{{图{n}}}'

    replaced = _FIG_REF_PAT.sub(_ref_replace, protected)

    # 恢复保护块
    def _restore(m):
        return saved[int(m.group(1))]

    result = re.sub(
        rf'{re.escape(_FIG_PROT_PRE)}(\d+){re.escape(_FIG_PROT_SUF)}',
        _restore,
        replaced,
    )
    return result, count


# ──────────────────────────────────────────────────────────
#  Fix 8: 从 EPUB 提取脚注内容，填充空的章末注 enumerate 块
#
#  背景：
#    duokan EPUB 的脚注格式：
#      正文中  id="A_N" 的图标链接 → 被 pandoc 转成 \footnote{} → Fix1 已删除
#      章末   id="B_N" 的 <li> 内容 → 被 pandoc 转成空 enumerate 块（只有 label）
#    本 fix 从 EPUB 读取 B_N 的实际内容，以章末注形式重新填入。
#
#  输出格式（章末小字注释块）：
#    {\footnotesize\setlength{\parindent}{0pt}
#    \noindent\textcolor{rulegray}{\rule{0.35\linewidth}{0.3pt}}\par\vspace{2pt}
#    \noindent\textbf{注释}\par\vspace{3pt}
#    \begin{enumerate}
#    \item 注释内容...
#    \end{enumerate}}
# ──────────────────────────────────────────────────────────

# 匹配空的脚注 enumerate：每个 \item 仅含 \phantomsection\label{...}
_EMPTY_NOTE_ENUM_PAT = re.compile(
    r'\\begin\{enumerate\}\s*'
    r'((?:\\item\s*\\phantomsection\\label\{[^}]+\}\s*)+)'
    r'\\end\{enumerate\}',
    re.DOTALL,
)


def _load_epub_footnotes(epub_path):
    """
    从 EPUB 文件提取所有 duokan 脚注内容。
    返回：{xhtml_basename: {'B_1': text, 'B_2': text, ...}, ...}
    例如：{'Chapter07.xhtml': {'B_1': '吉奥麦·...', ...}, ...}
    """
    epub_path = Path(epub_path)
    if not epub_path.exists():
        return {}

    footnotes = {}
    note_pat = re.compile(
        r'id="(B_(\d+))"[^>]*>(.*?)(?=\s*<li\s[^>]*id="B_\d+"|</[ou]l>|</body)',
        re.DOTALL,
    )

    with zipfile.ZipFile(str(epub_path), 'r') as z:
        for name in z.namelist():
            if not name.endswith(('.xhtml', '.html')):
                continue
            try:
                content = z.read(name).decode('utf-8', errors='ignore')
            except Exception:
                continue

            if 'duokan-footnote' not in content.lower():
                # 快速跳过无脚注文件（duokan-image-* 等误报也在这里过滤）
                if 'id="B_' not in content:
                    continue

            found = {}
            for m in note_pat.finditer(content):
                bid = m.group(1)                          # 'B_1'
                raw = m.group(3)
                clean = re.sub(r'<[^>]+>', '', raw).strip()
                clean = re.sub(r'\s+', ' ', clean)
                if clean:
                    found[bid] = clean

            if found:
                base = name.split('/')[-1]                # 'Chapter07.xhtml'
                footnotes[base] = found

    return footnotes


def fix_empty_note_blocks(text, epub_path='/tmp/GEB_packed.epub'):
    """
    将空的章末注 enumerate 块填充为实际脚注内容（章末注格式）。

    匹配模式：GEB.tex 中的
        \\begin{enumerate}
        \\item \\phantomsection\\label{Chapter07.xhtml_B_1}
        ...
        \\end{enumerate}

    替换为：
        {\\footnotesize ...
        \\begin{enumerate}
        \\item 注释内容...
        \\end{enumerate}}
    """
    footnotes = _load_epub_footnotes(epub_path)
    if not footnotes:
        return text, 0

    count = 0

    def _replace(m):
        nonlocal count
        block = m.group(1)
        labels = re.findall(r'\\label\{([^}]+)\}', block)
        if not labels:
            return m.group()

        # 从第一个 label 确定 xhtml 基名
        # 格式示例：'Chapter07.xhtml_B_1'
        xhtml_match = re.match(r'(.+?\.xhtml)_B_\d+', labels[0])
        if not xhtml_match:
            return m.group()

        xhtml_base = xhtml_match.group(1)                  # 'Chapter07.xhtml'
        note_dict = footnotes.get(xhtml_base, {})
        if not note_dict:
            return m.group()

        # 构建注释列表
        items = []
        for label in labels:
            bid_m = re.search(r'_(B_\d+)$', label)
            if bid_m:
                bid = bid_m.group(1)
                content = note_dict.get(bid, '')
                # 如果内容中含 LaTeX 特殊字符，做基本转义
                content = content.replace('&', r'\&')
                items.append(f'\\item {content}' if content else '\\item')

        if not any(it != '\\item' for it in items):
            return m.group()   # 全部空，保持原样

        count += 1
        note_block = (
            '{\\footnotesize\\setlength{\\parindent}{0pt}%\n'
            '\\noindent\\textcolor{rulegray}{\\rule{0.35\\linewidth}{0.3pt}}\\par\\vspace{2pt}\n'
            '\\noindent\\textbf{注释}\\par\\vspace{3pt}\n'
            '\\begin{enumerate}\n'
            + '\n'.join(items) + '\n'
            + '\\end{enumerate}\n'
            '}'
        )
        return note_block

    text = _EMPTY_NOTE_ENUM_PAT.sub(_replace, text)
    return text, count


# ──────────────────────────────────────────────────────────
#  Fix 9: longtable 无宽度 l 列 → 按比例 p{} 列
#
#  pandoc 生成的 longtable 全部用 @{}ll@{}、@{}lll@{} 等
#  无约束列格式，在窄版心（6×9 英寸）下导致内容溢出。
#  将每个 l 替换为 p{W\linewidth}，W = 0.94 / N_cols。
# ──────────────────────────────────────────────────────────

_LONGTABLE_COL_PAT = re.compile(
    r'(\\begin\{longtable\}\[\]\{)(@\{\})(l+)(@\{\})(\})',
)


def fix_longtable_columns(text):
    """
    将 \\begin{longtable}[]{@{}ll@{}} 等无约束列格式
    替换为按比例分配宽度的 p{} 列。

    列宽策略：
    - 1列：0.94\linewidth
    - 2列：等分 0.47 各
    - 3列：0.08 / 0.50 / 0.34（编号列 + 符号串列 + 注释列）
    - 4列及以上：等分
    """
    count = 0

    # 三列非均匀比例：第一列编号窄，第二列内容宽，第三列注释中等
    _THREE_COL_WIDTHS = [0.08, 0.50, 0.34]

    def _replace(m):
        nonlocal count
        ls = m.group(3)          # 'lll' 等
        n = len(ls)
        if n == 3:
            col_spec = ' '.join(
                f'>{{\\raggedright\\arraybackslash}}p{{{w}\\linewidth}}'
                for w in _THREE_COL_WIDTHS
            )
        else:
            w = round(0.94 / n, 3)
            col_spec = ' '.join(
                [f'>{{\\raggedright\\arraybackslash}}p{{{w}\\linewidth}}'] * n
            )
        count += 1
        return f'{m.group(1)}{col_spec}{m.group(5)}'

    text = _LONGTABLE_COL_PAT.sub(_replace, text)
    return text, count


# ──────────────────────────────────────────────────────────
#  Fix 10: \section{} 章级标题 → \chapter{} / \chapter*{}
#
#  pandoc 将 EPUB 的 Chapter/Dialog/Preface/Part 全部转为
#  \section{}，需提升为 \chapter。同时删除夹在 label 与
#  \section 之间的裸文本段落（"第X章"、"导言"、"上篇"等）。
#
#  规则：
#    ChapterXX.xhtml  → \chapter{title}     （有编号）
#    Part{1,2}.xhtml  → \part{title}        （上/下篇）
#    其他（Dialog、Preface、Introduction、
#          Overview、Words_of_Thanks、
#          List_of_Illustrations）
#                     → \chapter*{title}    （无编号）
# ──────────────────────────────────────────────────────────

# 匹配：label 行 + 可选空行 + 可选裸文本段（无反斜杠）+ 可选空行 + \section{title}
_SECTION_HEADING_PAT = re.compile(
    r'(\\phantomsection\\label\{'
    r'(Chapter\d+[^.}]*|Dialog\d+[^.}]*|Part\d+[^.}]*'
    r'|Introduction[^.}]*|Preface\d*[^.}]*|Overview[^.}]*'
    r'|Words_of_Thanks[^.}]*|List_of_Illustrations[^.}]*)'
    r'\.xhtml[^}]*\}\{\})'            # e.g. {Chapter01.xhtml}{}
    r'(\s*\n(?!\\)[^\n\\][^\n]*)?'    # optional plain-text label line (no \)
    r'\s*\n\\section\{([^}]*)\}',     # \section{title}
    re.DOTALL,
)


def fix_section_to_chapter(text):
    """
    将 \\section{} 章级标题升级为 \\chapter{} 或 \\chapter*{} 或 \\part{}。
    同时删除 label 与 \\section 之间的裸文本段落。
    """
    count = 0

    def _replace(m):
        nonlocal count
        label_cmd = m.group(1)     # \phantomsection\label{...}{}
        label_type = m.group(2)    # 'Chapter01', 'Dialog03', 'Part1', etc.
        title = m.group(4)

        if label_type.startswith('Chapter'):
            cmd = '\\chapter'
        elif label_type.startswith('Part'):
            cmd = '\\part'
        else:
            cmd = '\\chapter*'

        count += 1
        return f'{label_cmd}\n\n{cmd}{{{title}}}'

    text = _SECTION_HEADING_PAT.sub(_replace, text)
    return text, count


# ──────────────────────────────────────────────────────────
#  Fix 11: 插图目录编号 → \hyperref[fig:N]{N．}
#
#  插图目录 longtable 的第一列形如 `1．`、`2．` 等，
#  缺少到实际图片的超链接，修复为 \hyperref[fig:N]{N．}。
#  仅处理 List_of_Illustrations 区段内的模式。
# ──────────────────────────────────────────────────────────

# 匹配插图目录章节：chapter* 行之后到下一个 \chapter 之间
_ILLUS_BLOCK_PAT = re.compile(
    r'(\\chapter\*\{(?:[^}]|\\.)*?插图目录(?:[^}]|\\.)*?\}[^\n]*\n)'
    r'(.*?)'
    r'(?=\\chapter|\Z)',
    re.DOTALL,
)

# 匹配 longtable 首列的无链接图号，如 `1．` 或 `23．`（后跟 & 或空格+&）
# 跳过已经包在 \hyperref{...} 里的
_ILLUS_NUM_PAT = re.compile(r'(\d+)．(?=\s*&)')


def fix_illustration_links(text):
    """
    在插图目录 longtable 中，将 `N．` 替换为 `\\hyperref[fig:N]{N．}`。
    """
    count = 0

    def _replace_block(m):
        header = m.group(1)
        body = m.group(2)

        def _repl_num(nm):
            nonlocal count
            n = nm.group(1)
            replacement = f'\\hyperref[fig:{n}]{{{n}．}}'
            # 跳过已有 hyperref 的（幂等）
            start = nm.start()
            prefix = body[max(0, start-20):start]
            if '\\hyperref' in prefix:
                return nm.group(0)
            count += 1
            return replacement

        return header + _ILLUS_NUM_PAT.sub(_repl_num, body)

    text = _ILLUS_BLOCK_PAT.sub(_replace_block, text)
    return text, count


def postprocess(text, verbose=True, epub_path='/tmp/GEB_packed.epub'):
    """对 GEB.tex 文本执行所有后处理，返回处理后的文本。"""

    # Fix 1
    text, n_footnotes = fix_empty_footnotes(text)
    if verbose:
        print(f'  [1] 空脚注删除：{n_footnotes} 处')

    # Fix 2
    text, n_captions = fix_figure_captions(text)
    if verbose:
        print(f'  [2] 图说居中：{n_captions} 处')

    # Fix 3
    text, n_unicode, unicode_detail = fix_unicode_symbols(text)
    if verbose:
        print(f'  [3] Unicode 符号替换：{n_unicode} 处')
        for char, cnt in sorted(unicode_detail.items(), key=lambda x: -x[1]):
            name = char.encode('unicode_escape').decode()
            print(f'       {char} ({name}): {cnt}')

    # Fix 4
    text, n_taitham, taitham_detail = fix_tai_tham(text)
    if verbose:
        print(f'  [4] Tai Tham 乱码修复：{n_taitham} 处')
        for char, cnt in taitham_detail.items():
            name = char.encode('unicode_escape').decode()
            repl = TAI_THAM_MAP[char]
            print(f'       {char} ({name}) → "{repl}": {cnt}')

    # Fix 5
    text, n_fig_envs = fix_figure_envs(text)
    if verbose:
        print(f'  [5] figure 环境包裹（\\caption* + \\label）：{n_fig_envs} 处')

    # Fix 6
    text, n_special_labels = fix_special_figure_labels(text)
    if verbose:
        print(f'  [6] 特殊图说标签（\\phantomsection\\label）：{n_special_labels} 处')

    # Fix 7
    text, n_fig_refs = fix_figure_refs(text)
    if verbose:
        print(f'  [7] 文中图引用（\\hyperref）：{n_fig_refs} 处')

    # Fix 8
    text, n_notes = fix_empty_note_blocks(text, epub_path=epub_path)
    if verbose:
        print(f'  [8] 章末注填充（来自 EPUB）：{n_notes} 处')

    # Fix 9
    text, n_tables = fix_longtable_columns(text)
    if verbose:
        print(f'  [9] longtable 列宽修正：{n_tables} 处')

    # Fix 10
    text, n_chapters = fix_section_to_chapter(text)
    if verbose:
        print(f'  [10] \\section→\\chapter 提升：{n_chapters} 处')

    # Fix 11
    text, n_illus = fix_illustration_links(text)
    if verbose:
        print(f'  [11] 插图目录超链接：{n_illus} 处')

    return text


def main():
    parser = argparse.ArgumentParser(
        description='GEB.tex 后处理：删除空脚注、居中图说、修复 Unicode 符号、figure 环境、图引用超链接'
    )
    parser.add_argument('input', help='输入 .tex 文件路径')
    parser.add_argument('-o', '--output', help='输出文件路径（默认原地修改）')
    parser.add_argument('--epub', default='/tmp/GEB_packed.epub',
                        help='EPUB 源文件路径，用于提取脚注内容（默认：/tmp/GEB_packed.epub）')
    parser.add_argument('--dry-run', action='store_true',
                        help='只统计，不写入文件')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='不输出详细统计')
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f'错误：文件不存在：{input_path}', file=sys.stderr)
        sys.exit(1)

    print(f'读取: {input_path}')
    text = input_path.read_text(encoding='utf-8')
    original_len = len(text)

    print('后处理中...')
    result = postprocess(text, verbose=not args.quiet, epub_path=args.epub)

    if args.dry_run:
        print(f'\n[dry-run] 未写入文件（原文 {original_len} 字符 → 后处理 {len(result)} 字符）')
        return

    output_path = Path(args.output) if args.output else input_path
    output_path.write_text(result, encoding='utf-8')
    print(f'\n写入: {output_path}  ({original_len} → {len(result)} 字符)')


if __name__ == '__main__':
    main()
