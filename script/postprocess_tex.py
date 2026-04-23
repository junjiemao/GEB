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

  18. 公式符号转 LaTeX 数学环境
     (混用 \\textsuperscript / ×（Unicode 乘号）/ 裸幂次的数学表达式 → $...$)

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
#  Tai Viet 占位字符（来自 EPUB geb.ttf 自定义字体）
#  全部通过 {\gebfont X} 使用 geb.ttf 渲染，不做文字替换
# ──────────────────────────────────────────────────────────
TAI_THAM_MAP = {}   # 不再做文字替换


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
    """将所有 Tai Viet 字符（U+AA80–U+AADF）包裹为 {\\gebfont X}，使用 geb.ttf 渲染。
    幂等：先剥离所有已存在的 {\\gebfont X} 嵌套包裹，再统一包裹一次。"""
    counts = {}

    # Step 1: 剥离任意深度的嵌套包裹，使本函数幂等
    _unwrap_pat = re.compile(r'\{\\gebfont ([\uAA80-\uAADF])\}')
    prev = None
    while prev != text:
        prev = text
        text = _unwrap_pat.sub(r'\1', text)

    def _wrap_taiviet(s):
        result = []
        for ch in s:
            if 0xAA80 <= ord(ch) <= 0xAADF:
                result.append(r'{\gebfont ' + ch + '}')
                counts[ch] = counts.get(ch, 0) + 1
            else:
                result.append(ch)
        return ''.join(result)

    text = _wrap_taiviet(text)
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
    # 先找出所有匹配，逐一检查前向上下文（re.sub 无法做变长 lookbehind）
    def _apply_center(s):
        nonlocal count
        result = []
        last = 0
        for m in _LEFTOVER_CENTER_PAT.finditer(s):
            num = m.group(2)
            label = f'\\phantomsection\\label{{fig:{num}}}'
            # 幂等：检查紧前面（去除空白后）是否已有该 label
            before = s[last:m.start()].rstrip()
            result.append(s[last:m.start()])
            if before.endswith(label):
                result.append(m.group(1))   # 已有，不重复插入
            else:
                count += 1
                result.append(f'{label}\n{m.group(1)}')
            last = m.end()
        result.append(s[last:])
        return ''.join(result)

    text = _apply_center(text)

    # 处理裸文本子图说行（图33(a)/图35-① 等）
    # 幂等：{\small\textbf{...}} 已包裹则不重复处理
    _already_wrapped = re.compile(
        r'^\\phantomsection\\label\{fig:\d+\}\n\{\\small\\textbf\{',
        re.MULTILINE,
    )

    def _apply_bare(s):
        nonlocal count
        result = []
        last = 0
        for m in _BARE_SUBFIG_PAT.finditer(s):
            num = m.group(2) or m.group(3)
            label = f'\\phantomsection\\label{{fig:{num}}}'
            before = s[last:m.start()].rstrip()
            result.append(s[last:m.start()])
            if before.endswith(label):
                # 已处理（已有 label），只包裹文本
                result.append(f'{{\\small\\textbf{{{m.group(0)}}}}}')
            else:
                count += 1
                result.append(
                    f'{label}\n'
                    f'{{\\small\\textbf{{{m.group(0)}}}}}'
                )
            last = m.end()
        result.append(s[last:])
        return ''.join(result)

    text = _apply_bare(text)
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
    例：ll → p{0.47\\linewidth}p{0.47\\linewidth}
    """
    count = 0

    def _replace(m):
        nonlocal count
        ls = m.group(3)          # 'lll' 等
        n = len(ls)
        # 总宽略小于 \linewidth（留少量 padding），每列等分
        w = round(0.94 / n, 3)
        col_spec = ' '.join([f'>{{\\raggedright\\arraybackslash}}p{{{w}\\linewidth}}'] * n)
        count += 1
        return f'{m.group(1)}{col_spec}{m.group(5)}'

    text = _LONGTABLE_COL_PAT.sub(_replace, text)
    return text, count


# ──────────────────────────────────────────────────────────
#  Fix 12: pandoc 错误列宽 0.08/0.50/0.34 → 0.44/0.08/0.40
#
#  pandoc 从 EPUB HTML 表格 CSS 读取列宽比例，将"内容|箭头|内容"
#  3 列表生成为 p{0.08}/p{0.50}/p{0.34}（内容列只有 8%），
#  导致文字按字换行。修正为标准对称三列：0.44/0.08/0.40。
# ──────────────────────────────────────────────────────────

_WRONG_3COL = (
    r'>{\raggedright\arraybackslash}p{0.08\linewidth}'
    r' >{\raggedright\arraybackslash}p{0.50\linewidth}'
    r' >{\raggedright\arraybackslash}p{0.34\linewidth}'
)
_FIXED_3COL = (
    r'>{\raggedright\arraybackslash}p{0.44\linewidth}'
    r' >{\raggedright\arraybackslash}p{0.08\linewidth}'
    r' >{\raggedright\arraybackslash}p{0.40\linewidth}'
)


def fix_wrong_3col_widths(text):
    """
    修正 pandoc 从 EPUB 读取 CSS 列宽时产生的错误比例：
    将 0.08/0.50/0.34（内容列极窄）替换为 0.44/0.08/0.40（箭头列居中）。
    """
    n = text.count(_WRONG_3COL)
    text = text.replace(_WRONG_3COL, _FIXED_3COL)
    return text, n


# ──────────────────────────────────────────────────────────
#  Fix 13: 回退被 Fix 12 错误修改的"推导表"列宽
#
#  Fix 12 将所有 0.08/0.50/0.34 表改为 0.44/0.08/0.40，但推导表
#  （步骤号|公式|规则）的中间列是实际公式，不是箭头符号，因此
#  Fix 12 对它们的修改是错误的。
#
#  判断逻辑：
#    - 若某张 0.44/0.08/0.40 表中，所有数据行的第 2 列都是简单
#      运算符（⇔ → ← = 或全角空格等），则保留为 ARROW 表。
#    - 否则属于 CONTENT 表，回退为 0.08/0.50/0.34。
# ──────────────────────────────────────────────────────────

# 中列为纯运算符的 pattern
_ARROW_CELL_PAT = re.compile(
    r'^\s*('
    r'　*\{?\$\\(?:Left|Right|left|right)(?:right|left)?arrow\w*\$\}?　*'  # $\Leftrightarrow$ 等
    r'|[=\-\s\u3000]*'                                                       # = 或空格
    r')\s*$'
)


def _extract_col2_values(body: str) -> list:
    """从表体中提取每行第 2 列内容（跳过结构命令行和 multi* 单元格）"""
    values = []
    for row in body.split('\\\\'):
        stripped = row.strip()
        if not stripped or stripped.startswith('\\'):
            continue
        cells = stripped.split('&')
        if len(cells) < 3:
            continue
        col2 = cells[1].strip()
        if 'multicolumn' in col2 or 'multirow' in col2:
            continue
        values.append(col2)
    return values


def _is_arrow_table(body: str) -> bool:
    """所有数据行的中间列均为箭头/等号 → True（ARROW 表，保留 Fix 12 结果）"""
    vals = _extract_col2_values(body)
    if not vals:
        return False
    return all(_ARROW_CELL_PAT.match(v) for v in vals)


_FIX13_PAT = re.compile(
    r'(\\begin\{longtable\}\[\]\{\|)'
    + re.escape(_FIXED_3COL)
    + r'(\|\})'
    + r'(.*?)'
    + r'(\\end\{longtable\})',
    re.DOTALL,
)


def fix_misidentified_tables(text):
    """
    将 Fix 12 错误修改的推导表（CONTENT 表）回退为 0.08/0.50/0.34 列宽。
    ARROW 表（中列全为 ⇔/= 等运算符）保持 0.44/0.08/0.40 不变。
    """
    count = 0
    result_parts = []
    last_end = 0

    for m in _FIX13_PAT.finditer(text):
        full_body = m.group(3)
        elf_pos = full_body.find(r'\endlastfoot')
        body_only = full_body[elf_pos + 12:] if elf_pos >= 0 else full_body

        result_parts.append(text[last_end:m.start()])
        if _is_arrow_table(body_only):
            # ARROW 表，保留 Fix 12 的修改
            result_parts.append(m.group(0))
        else:
            # CONTENT 表，回退为 0.08/0.50/0.34
            replacement = (
                m.group(1)
                + _WRONG_3COL
                + m.group(2)
                + m.group(3)
                + m.group(4)
            )
            result_parts.append(replacement)
            count += 1

        last_end = m.end()

    result_parts.append(text[last_end:])
    return ''.join(result_parts), count


# ──────────────────────────────────────────────────────────
#  Fix 14: 多列窄格表溢出 → resizebox + tabular
#
#  pandoc 根据 EPUB CSS 生成等宽多列 longtable，列宽之和约 0.94\lw，
#  加上 tabcolsep 后严重超出版心。修复方法：
#    - 将 longtable → tabular（内容可在一页内容纳）
#    - 列规格 p{X\linewidth} → c（自然宽度居中）
#    - 外包 \resizebox{\linewidth}{!}{...} 缩放至版心宽度
#
#  触发条件：
#    - ≥4 列等宽 p{X\linewidth}（X < 0.20）
#    - 所有列宽之和 > 0.85（超过 tabcolsep 后一定溢出）
#    - 不被 \begingroup...\endgroup 已包裹
# ──────────────────────────────────────────────────────────

_MULTICOL_NARROW_PAT = re.compile(
    r'(?<!\{)\n?'
    r'(\\begin\{longtable\}\[\]\{)'
    r'(\|?)'
    r'((?:>\\{\\\\raggedright\\\\arraybackslash\\}p\\{[0-9.]+\\\\linewidth\\} ?)+)'
    r'(\|?)'
    r'(\})'
    r'(.*?)'
    r'(\\end\{longtable\})',
    re.DOTALL,
)

# 更简单的模式：逐段处理
_NARROW_LTABLE = re.compile(
    r'(\\begin\{longtable\}\[\]\{)'
    r'(\|?)'
    r'((?:>\\{\\\\raggedright\\\\arraybackslash\\}p\\{[0-9.]+\\\\linewidth\\}[\s]*)+)'
    r'(\|?)'
    r'(\})'
    r'([\s\S]*?)'
    r'(\\end\{longtable\})',
)

_COL_WIDTH_RE = re.compile(r'p\{([0-9.]+)\\linewidth\}')
_RAGRIGHT_COL = re.compile(
    r'>\\{raggedright\\arraybackslash\\}p\\{[0-9.]+\\linewidth\\}'
)


def fix_narrow_multicol_tables(text):
    """
    将等宽多列（≥4 列，总宽 > 0.85）的 longtable 转为
    resizebox{\\linewidth}{!} + tabular，以解决列宽超出版心的问题。
    """
    # 匹配 longtable[\{\...spec\}]...\\end{longtable}
    ltable_pat = re.compile(
        r'(\\begin\{longtable\}\[\]\{(\|?))((?:>\\{\\\\?raggedright\\\\?arraybackslash\\}p\\{[0-9.]+\\\\?linewidth\\}[\\ ]*)+)(\|?\})([\s\S]*?)(\\end\{longtable\})',
        re.DOTALL
    )

    # 改用手工分割方式，更可靠
    result = []
    count = 0
    pos = 0
    begin_marker = r'\begin{longtable}[]{|'
    end_marker = r'\end{longtable}'

    i = 0
    while i < len(text):
        # find next longtable
        bt = text.find(r'\begin{longtable}', i)
        if bt == -1:
            result.append(text[i:])
            break

        # find matching end
        et = text.find(end_marker, bt)
        if et == -1:
            result.append(text[i:])
            break

        et_end = et + len(end_marker)
        table_src = text[bt:et_end]

        # parse column spec from first line of table
        first_line_end = table_src.find('\n')
        spec_line = table_src[:first_line_end] if first_line_end > 0 else table_src

        widths = _COL_WIDTH_RE.findall(spec_line)
        if len(widths) >= 4:
            total = sum(float(w) for w in widths)
            # check if all widths equal (within 0.001)
            all_equal = max(float(w) for w in widths) - min(float(w) for w in widths) < 0.002
            # check not already wrapped in \begingroup (skip 24-col table)
            pre_context = text[max(0, bt-60):bt]
            already_wrapped = r'\begingroup' in pre_context or r'\resizebox' in pre_context

            if total > 0.85 and all_equal and not already_wrapped:
                # build new tabular spec: |c c c c c|
                ncols = len(widths)
                # check outer pipes
                has_lead_pipe = '|' in spec_line.split('{', 2)[2][:3]  # after {
                has_trail_pipe = spec_line.rstrip().endswith('|}')
                col_spec = ('|' if has_lead_pipe else '') + ' '.join(['c'] * ncols) + ('|' if has_trail_pipe else '')

                # build table body: remove \endhead and \endlastfoot lines
                body = table_src[first_line_end + 1 : -(len(end_marker))]
                body_lines = []
                skip = False
                for ln in body.split('\n'):
                    ls = ln.strip()
                    if ls == r'\endhead' or ls == r'\endlastfoot':
                        continue
                    body_lines.append(ln)

                new_table = (
                    r'\resizebox{\linewidth}{!}{\begin{tabular}{' + col_spec + '}\n'
                    + '\n'.join(body_lines)
                    + r'\end{tabular}}'
                )

                result.append(text[i:bt])
                result.append(new_table)
                count += 1
                i = et_end
                continue

        # no replacement, keep original
        result.append(text[i:bt + len(r'\begin{longtable}')])
        i = bt + len(r'\begin{longtable}')

    return ''.join(result), count


# ──────────────────────────────────────────────────────────
#  Fix 23: EPUB <p class="title"> 节标题 → \section{}
#
#  pandoc 从 EPUB 转换 LaTeX 时，将章节内的小节标题
#  <p class="title">词与符号</p> 处理为裸文本段落，
#  不生成任何 \section{} 命令。
#  本 fix 从 EPUB 提取所有 <p class="title"> 内容（仅 ChapterXX 和
#  Introduction），在 GEB.tex 中找到对应的独立文本行（前后空行，
#  行首无 \），替换为 \section{标题}。
#
#  匹配策略（规范化比较，而非字符串精确匹配）：
#    1. EPUB 端：<p class="title">内容</p> → 去除 HTML 标签 → 纯文本
#    2. GEB.tex 端：候选裸行 → 迭代去除 {\gebfont X} 包裹
#                             → LaTeX 引号 `` / '' → Unicode 引号 " / "
#    3. 两端规范化后精确匹配
#    4. 匹配则以 \section{原始行内容} 替换（使用 GEB.tex 中已有的内容）
#
#  幂等：已替换的行以 \section{ 开头（含 \），不满足"行首无 \"，跳过。
# ──────────────────────────────────────────────────────────

_EPUB_PTITLE_PAT = re.compile(
    r'<p\b[^>]+class=["\'][^"\']*\btitle\b[^"\']*["\'][^>]*>(.*?)</p>',
    re.DOTALL | re.IGNORECASE,
)
_HTML_TAG_PAT = re.compile(r'<[^>]+>')
# 匹配 {\gebfont ...}，支持一层内嵌花括号（如 {\gebfont ꪡ} 或被嵌套的版本）
_GEBFONT_UNWRAP_PAT = re.compile(
    r'\{\\gebfont\s+((?:[^{}]|\{[^{}]*\})*)\}'
)
# 匹配 \textbf{X}（X 为单个字符，Fix 21 对稀有字形的转换）
_TEXTBF_SINGLE_PAT = re.compile(r'\\textbf\{(.)\}')
# 匹配 \ldots 命令（带或不带 {} 后缀）
_LDOTS_PAT = re.compile(r'\\ldots(?:\{\}|\.\.\.|(?=[^a-zA-Z]))', re.DOTALL)


def _load_epub_title_set(epub_path):
    """
    从 EPUB 提取所有章节内 <p class="title"> 文本（去除 HTML 标签后的纯文本）。
    只处理 ChapterXX.xhtml 和 Introduction.xhtml。
    返回 set of str（Unicode 纯文本）。
    """
    chapter_file_re = re.compile(
        r'(?:Chapter\d+|Introduction)\.xhtml$', re.IGNORECASE
    )
    titles = set()
    with zipfile.ZipFile(str(epub_path), 'r') as z:
        for name in z.namelist():
            if not chapter_file_re.search(name):
                continue
            try:
                content = z.read(name).decode('utf-8', errors='ignore')
            except Exception:
                continue
            for m in _EPUB_PTITLE_PAT.finditer(content):
                plain = _HTML_TAG_PAT.sub('', m.group(1)).strip()
                if plain:
                    titles.add(plain)
    return titles


def _normalize_tex_line_for_title(line):
    """
    将 GEB.tex 中的行规范化为 EPUB 纯文本，用于与 title 集合比较：
      1. 迭代去除 {\\gebfont X} 包裹（处理 Fix 4 多次运行后的嵌套）
      2. 去除残余花括号包裹的 Tai Viet 字符（{ ꪡ} → ꪡ）
      3. 将 LaTeX 引号 `` → " 和 '' → "（恢复 pandoc quote 转换）
      4. \\ldots{} / \\ldots → … （恢复 pandoc 省略号转换）
      5. ------ → ——（恢复 pandoc 双破折号转换：U+2014×2 → 6 hyphens）
      6. \\textbf{X} → X（逆 Fix 21 对稀有字形的加粗处理）
    """
    s = line.strip()
    # 1. 迭代展开 {\gebfont ...}（每轮去一层，直到稳定）
    prev = None
    while prev != s:
        prev = s
        s = _GEBFONT_UNWRAP_PAT.sub(lambda m: m.group(1), s)
    # 2. 去除残余花括号包裹的 Tai Viet 字符：{ ꪡ} → ꪡ（多次包裹后的残留）
    s = re.sub(r'\{\s*([\uAA80-\uAADF]+)\s*\}', r'\1', s)
    # 3. LaTeX 引号 → Unicode 引号
    s = s.replace("``", '\u201c').replace("''", '\u201d')
    # 4. \ldots{} / \ldots → Unicode 省略号 …
    s = _LDOTS_PAT.sub('\u2026', s)
    # 省略号后紧接 CJK 字符时，去除多余空格（pandoc 在 \ldots 后插入空格）
    s = re.sub(r'\u2026\s+(?=[\u4e00-\u9fff\uff00-\uffef])', '\u2026', s)
    # 5. pandoc em-dash 转换：--- (3 hyphens = U+2014) → U+2014
    #    先处理 6 hyphens → ——，再处理 3 hyphens → —
    s = s.replace('------', '\u2014\u2014')
    s = s.replace('---', '\u2014')
    # 6. \textbf{X} → X（Fix 21 对稀有字形的处理）
    s = _TEXTBF_SINGLE_PAT.sub(r'\1', s)
    return s


def fix_ptitle_to_section(text, epub_path):
    """
    Fix 23: 将 EPUB <p class="title"> 对应的裸文本行替换为 \\section{}。
    466 处节标题。
    """
    epub_path = Path(epub_path)
    if not epub_path.exists():
        return text, 0

    titles = _load_epub_title_set(epub_path)
    if not titles:
        return text, 0

    lines = text.split('\n')
    count = 0
    result = []
    n = len(lines)

    for i, line in enumerate(lines):
        stripped = line.strip()
        # 候选条件：非空、不以 % 开头
        # 注意：不排除以 \ 开头的行（如 \ldots 开头的标题），
        # 但排除明确的章节命令（\section、\chapter、\begin 等）
        if stripped and not stripped.startswith('%'):
            # 快速排除已经是 LaTeX 结构命令的行
            _is_latex_cmd = re.match(
                r'\\(?:section|chapter|part|begin|end|item|label|caption|'
                r'phantom|noindent|textbf|textit|emph|footnote|hyperref|'
                r'ref|cite|includegraphics|pandocbounded)\b',
                stripped
            )
            if not _is_latex_cmd:
                # 前后均为空行（独立段落）
                prev_blank = (i == 0 or lines[i - 1].strip() == '')
                next_blank = (i == n - 1 or lines[i + 1].strip() == '')
                if prev_blank and next_blank:
                    normalized = _normalize_tex_line_for_title(stripped)
                    if normalized in titles:
                        result.append(f'\\section{{{stripped}}}')
                        count += 1
                        continue
        result.append(line)

    return '\n'.join(result), count


# ──────────────────────────────────────────────────────────
#  Fix 25: 图片字幕（duokan-image-subtitle）归并进 figure 环境
#
#  pandoc 的 EPUB reader 不保留 <p class="duokan-image-subtitle">
#  的 CSS 类，使这些字幕文本变成了 figure 环境后面的裸段落。
#
#  本 fix 从 EPUB 提取所有 duokan-image-subtitle 文本，
#  在 GEB.tex 中找到 \end{figure} 后的第一个非空段落，
#  若该段落（规范化后）与某个字幕文本匹配，则把它移入
#  figure 环境内，包裹为 \begin{imgsub}...\end{imgsub}。
#
#  幂等：移入后段落不再跟在 \end{figure} 后，不会重复处理。
# ──────────────────────────────────────────────────────────

_EPUB_SUBTITLE_PAT = re.compile(
    r'<p\b[^>]+class="[^"]*duokan-image-subtitle[^"]*"[^>]*>(.*?)</p>',
    re.DOTALL | re.IGNORECASE,
)


def _load_epub_subtitles(epub_path):
    """从 EPUB 提取所有 duokan-image-subtitle 文本，返回 set（规范化纯文本）。"""
    subtitles = set()
    with zipfile.ZipFile(str(epub_path), 'r') as z:
        for name in z.namelist():
            if not (name.endswith('.xhtml') or name.endswith('.html')):
                continue
            try:
                content = z.read(name).decode('utf-8', errors='ignore')
            except Exception:
                continue
            for m in _EPUB_SUBTITLE_PAT.finditer(content):
                plain = _HTML_TAG_PAT.sub('', m.group(1)).strip()
                if plain:
                    subtitles.add(plain)
    return subtitles


def _normalize_tex_for_subtitle(line):
    """将 GEB.tex 裸段落规范化，用于与 EPUB subtitle 文本比较。"""
    s = line.strip()
    # 展开 LaTeX 引号
    s = s.replace("``", '\u201c').replace("''", '\u201d')
    # \ldots → …
    s = re.sub(r'\\ldots(?:\{\}|\.\.\.)?', '\u2026', s)
    # --- → — 等
    s = s.replace('------', '\u2014\u2014').replace('---', '\u2014')
    # 去除 LaTeX 命令
    s = re.sub(r'\\[a-zA-Z]+\{([^}]*)\}', r'\1', s)
    s = re.sub(r'\\[a-zA-Z]+', '', s)
    # 去除多余空白
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def fix_image_subtitles(text, epub_path):
    """
    Fix 25: 将图片字幕段落移入 figure 环境内。

    模式：\\end{figure}\n\n<subtitle_paragraph>\n\n
    → \\begin{imgsub}<subtitle>\\end{imgsub}\n\\end{figure}
    """
    epub_path = Path(epub_path)
    if not epub_path.exists():
        return text, 0

    subtitles = _load_epub_subtitles(epub_path)
    if not subtitles:
        return text, 0

    # 构建规范化映射：规范化文本 → 原始文本
    normalized_map = {}
    for s in subtitles:
        normalized_map[s] = s  # 原始文本即规范化文本（来自 EPUB HTML 剥标签后）

    count = 0
    # 匹配 \end{figure} 后隔空行的段落
    fig_end_pat = re.compile(
        r'(\\end\{figure\})'          # \end{figure}
        r'(\s*\n\n)'                   # 空行
        r'([^\n\\][^\n]*)\n'           # 裸段落（行首无 \）
        r'(?=\s*\n)',                  # 后接空行
    )

    def _replace(m):
        nonlocal count
        fig_end = m.group(1)
        gap = m.group(2)
        para = m.group(3).strip()
        norm = _normalize_tex_for_subtitle(para)
        # 与 EPUB subtitles 比较（精确匹配或宽松匹配）
        if para in subtitles or norm in subtitles:
            count += 1
            return (
                f'\\begin{{imgsub}}\n{para}\n\\end{{imgsub}}\n'
                f'{fig_end}'
                f'{gap}'
            )
        # 宽松：长度 > 3 且规范化后出现在任何 subtitle 中
        for sub in subtitles:
            if len(norm) > 3 and norm == sub.strip():
                count += 1
                return (
                    f'\\begin{{imgsub}}\n{para}\n\\end{{imgsub}}\n'
                    f'{fig_end}'
                    f'{gap}'
                )
        return m.group(0)  # 不匹配，保持原样

    text = fig_end_pat.sub(_replace, text)
    return text, count


# ──────────────────────────────────────────────────────────
#  Fix 26: EPUB <p class="dialog_guided"> 段落 → dialogguide 环境
#  Fix 27: EPUB <p class="quote_text">    段落 → fsquote    环境
#
#  pandoc 从 EPUB 转换 LaTeX 时，<p class="..."> 中的 CSS class
#  信息会丢失，段落变为裸文本行。本 fix 从 EPUB 提取 fingerprint
#  （段落前 15 个字符），在 GEB.tex 中匹配对应的裸段落，包裹进
#  指定的 LaTeX 环境。
#  幂等：已包裹的段落（前一行为 \begin{env}）直接跳过。
# ──────────────────────────────────────────────────────────

_HTML_INLINE_PAT = re.compile(r'<[^>]+>')   # 已在上方定义，此处作局部引用


def _epub_para_fps(epub_path, css_class, fp_len=15):
    """
    从 EPUB 所有 xhtml 文件中提取 <p class="css_class"> 的文本指纹。
    指纹 = 去除 HTML 标签、去除首尾空白后的前 fp_len 个字符。
    返回 set of str。
    """
    class_pat = re.compile(
        r'<p\b[^>]+class=["\'][^"\']*\b' + re.escape(css_class) + r'\b[^"\']*["\'][^>]*>(.*?)</p>',
        re.DOTALL | re.IGNORECASE,
    )
    fps = set()
    try:
        with zipfile.ZipFile(str(epub_path), 'r') as z:
            for name in z.namelist():
                if not (name.endswith('.xhtml') or name.endswith('.html')):
                    continue
                try:
                    content = z.read(name).decode('utf-8', errors='ignore')
                except Exception:
                    continue
                for m in class_pat.finditer(content):
                    plain = _HTML_TAG_PAT.sub('', m.group(1)).strip()
                    if len(plain) >= 4:
                        fps.add(plain[:fp_len])
    except Exception:
        pass
    return fps


def _wrap_epub_class_paras(text, epub_path, css_class, env_name):
    """
    Fix 26/27 通用实现：将匹配 css_class 的裸段落包裹进 LaTeX 环境 env_name。
    条件：
      - 非空行
      - 不以 \\ 或 % 开头（尚未有 LaTeX 命令）
      - 行内容以 fingerprint 开头
      - 前一非空行不是 \\begin{env_name}（幂等保护）
    返回 (新文本, 替换计数)。
    """
    fps = _epub_para_fps(epub_path, css_class)
    if not fps:
        return text, 0

    begin_tok = f'\\begin{{{env_name}}}'
    end_tok   = f'\\end{{{env_name}}}'

    lines  = text.split('\n')
    result = []
    count  = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        # 幂等：已在  env 内，直接原样输出
        if stripped.startswith(begin_tok) or stripped.startswith(end_tok):
            result.append(line)
            continue

        if stripped and not stripped.startswith('\\') and not stripped.startswith('%'):
            # 前一非空行是 \begin{env}? → 已包裹，跳过
            prev_nonempty = next(
                (result[j] for j in range(len(result) - 1, -1, -1)
                 if result[j].strip()),
                ''
            )
            if prev_nonempty.strip() == begin_tok:
                result.append(line)
                continue

            for fp in fps:
                if stripped.startswith(fp):
                    result.append(begin_tok)
                    result.append(line)
                    result.append(end_tok)
                    count += 1
                    break
            else:
                result.append(line)
        else:
            result.append(line)

    return '\n'.join(result), count


def fix_dialog_guided(text, epub_path='/tmp/GEB_packed.epub'):
    """Fix 26: dialog_guided 段落 → \\begin{dialogguide}...\\end{dialogguide}"""
    return _wrap_epub_class_paras(text, epub_path, 'dialog_guided', 'dialogguide')


def fix_quote_text(text, epub_path='/tmp/GEB_packed.epub'):
    """Fix 27: quote_text 段落 → \\begin{fsquote}...\\end{fsquote}"""
    return _wrap_epub_class_paras(text, epub_path, 'quote_text', 'fsquote')


# ──────────────────────────────────────────────────────────
#  Fix 24: 清理错误的 \gebfont{非TaiViet内容} 用法
#
#  Lua filter 旧版将 <span class="rare"> 全部包裹为 \gebfont{...}，
#  但 geb.ttf 只含 Tai Viet 字形（U+AA80–U+AADF），其他字符
#  （⇔ ∀ ∃ 等逻辑符号、普通 CJK 字符）被包入 \gebfont{} 后无法
#  渲染（空白）。同时双重嵌套 <span class="rare"> 会产生
#  \gebfont{\gebfont{} 大括号不平衡，导致此后整段文本落入
#  geb.ttf 字体上下文。
#
#  本 fix 处理以下模式（在 Fix 3/Fix 4 之前运行）：
#    1. \gebfont{\gebfont{}}  → 透传内容（去除双重包裹）
#    2. \gebfont{\gebfont{}   → 删除（不平衡残留，内容已丢失）
#    3. \gebfont{X}           → {\gebfont X}（Tai Viet）或 X（其他）
#
#  幂等：清理后不再含 \gebfont{ 开头的旧格式（Fix 4 统一输出
#        {\gebfont X} 格式），第二次运行不匹配。
# ──────────────────────────────────────────────────────────

# Tai Viet 字符范围 U+AA80–U+AADF
_TAIVIET_RE = re.compile(r'[\uAA80-\uAADF]')

def _is_taiviet_only(s):
    """判断字符串是否只含 Tai Viet 字符（U+AA80–U+AADF）。"""
    return bool(s) and all(0xAA80 <= ord(c) <= 0xAADF for c in s)


def fix_gebfont_cleanup(text):
    r"""
    Fix 24: 清理旧 Lua filter 产生的错误 \gebfont{...} 用法。

    处理：
      - \gebfont{\gebfont{}} → {\gebfont X}（或去除外层重复包裹）
      - \gebfont{\gebfont{}  → 删除（大括号不平衡的空残留）
      - \gebfont{X}          → {\gebfont X}（X 为 Tai Viet 字符时保留）
                            → X（X 为其他字符时，让 Fix 3/Fix 4 处理）
    附带修复：若 preamble 中的 \newfontfamily\gebfont{geb.ttf} 已被
    旧版意外破坏为 \newfontfamilygeb.ttf，则恢复。
    """
    count = 0

    # 0. 修复被旧版 Fix 24 破坏的 preamble 字体声明
    broken_preamble = r'\newfontfamilygeb.ttf[Path=./fonts/]'
    fixed_preamble  = r'\newfontfamily\gebfont{geb.ttf}[Path=./fonts/]'
    if broken_preamble in text:
        text = text.replace(broken_preamble, fixed_preamble)
        count += 1

    # 1. 修复不平衡的 \gebfont{\gebfont{} （两开一关，内容丢失）
    #    这是双重嵌套 <span class="rare"> 产生的 artifact
    unbalanced_pat = re.compile(r'\\gebfont\{\\gebfont\{\}')
    n = len(unbalanced_pat.findall(text))
    if n:
        text = unbalanced_pat.sub('', text)
        count += n

    # 2. 修复 \gebfont{\gebfont{X}} → {\gebfont X}（双重包裹）
    #    先展开外层，再由后续逻辑处理
    double_pat = re.compile(r'\\gebfont\{\\gebfont\{([\uAA80-\uAADF])\}\}')
    n = len(double_pat.findall(text))
    if n:
        text = double_pat.sub(r'{\\gebfont \1}', text)
        count += n

    # 3. 将 \gebfont{X} 形式（Lua filter 旧格式，无外部 {}）统一为：
    #    - Tai Viet 字符 → {\gebfont X}（和 Fix 4 输出格式一致）
    #    - 其他内容      → 直接保留内容（交 Fix 3/Fix 4 处理）
    # 负向前瞻：排除 \newfontfamily\gebfont{...} 声明（preamble 中的字体定义）
    old_fmt_pat = re.compile(r'(?<!\\newfontfamily)\\gebfont\{((?:[^{}]|\{[^{}]*\})+)\}')

    def _convert(m):
        nonlocal count
        inner = m.group(1)
        count += 1
        if _is_taiviet_only(inner):
            return '{\\gebfont ' + inner + '}'
        else:
            return inner  # 透传：Fix 3 处理逻辑符号，Fix 4 处理 Tai Viet

    text = old_fmt_pat.sub(_convert, text)
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


# ──────────────────────────────────────────────────────────
#  Fix 15: 在正文中插入脚注引用上标 \textsuperscript{N}
#
#  EPUB 中 duokan 格式脚注使用 <a epub:type="noteref"><img alt="注释N"/></a>
#  作为行内标记，pandoc 丢弃了 <img> 导致正文无引用号。
#  本函数从 EPUB 提取每个标记的文本上下文（前20字 + 后15字），
#  在 GEB.tex 对应位置插入 \textsuperscript{N}。
# ──────────────────────────────────────────────────────────

_DUOKAN_ANCHOR_PAT = re.compile(
    r'<a\b[^>]*class=["\']duokan-footnote["\'][^>]*>.*?</a\s*>',
    re.DOTALL | re.IGNORECASE,
)
_FN_NUM_FROM_HREF_PAT = re.compile(r'href=["\']#B_(\d+)["\']')
_FN_NUM_FROM_ALT_PAT = re.compile(r'alt=["\']注释(\d+)["\']')
_SECTION_LABEL_XHTML_PAT = re.compile(r'\\phantomsection\\label\{([^}]+\.xhtml)\}\{\}')


def fix_footnote_references(text, epub_path='/tmp/GEB_packed.epub'):
    """
    Fix 15: 在正文中插入脚注引用上标 \\textsuperscript{N}。

    从 EPUB 中定位每个 duokan-footnote 内联锚点的文本位置，
    在 GEB.tex 对应处插入 \\textsuperscript{N}，使章末注编号与正文对应。
    """
    epub_path = Path(epub_path)
    if not epub_path.exists():
        return text, 0

    # --- 辅助函数 ---
    def strip_tags(s):
        return re.sub(r'<[^>]+>', '', s)

    def to_key(s):
        """去除空白、LaTeX 花括号、规范化引号，用于模糊比较。"""
        s = re.sub(r'\s+', '', s)
        s = s.replace('{', '').replace('}', '')
        # pandoc 将 Unicode 引号转换为 LaTeX 风格：" → `` ，" → ''
        s = s.replace('\u201c', "``").replace('\u201d', "''")
        s = s.replace('\u2018', "`").replace('\u2019', "'")
        return s

    def norm_pos_to_orig(orig, n):
        """
        将 to_key(orig) 中第 n 个非跳过字符的位置映射回 orig 的索引。
        跳过规则与 to_key 一致：所有 Unicode 空白（含 \\u3000 全角空格）及 {}。
        """
        count = 0
        for i, ch in enumerate(orig):
            if count == n:
                return i
            if ch not in '{}' and not ch.isspace():
                count += 1
        return len(orig)

    # --- 1. 构建章节边界 ---
    sec_list = []   # [(start_pos, xhtml_name)]
    for m in _SECTION_LABEL_XHTML_PAT.finditer(text):
        sec_list.append((m.start(), m.group(1)))

    # xhtml_name -> (sec_start, sec_end)，取首次出现
    sec_bounds = {}
    for i, (pos, name) in enumerate(sec_list):
        if name not in sec_bounds:
            end = sec_list[i + 1][0] if i + 1 < len(sec_list) else len(text)
            sec_bounds[name] = (pos, end)

    # --- 2. 遍历 EPUB，收集插入点 ---
    all_insertions = []   # [(abs_pos, marker_str)]
    failed = []

    try:
        zf_ctx = zipfile.ZipFile(str(epub_path), 'r')
    except Exception:
        return text, 0

    with zf_ctx as zf:
        namelist = zf.namelist()
        for xhtml_name, (sec_start, sec_end) in sorted(sec_bounds.items()):
            candidates = [n for n in namelist if n.split('/')[-1] == xhtml_name]
            if not candidates:
                continue

            content = zf.read(candidates[0]).decode('utf-8', errors='ignore')
            if 'duokan-footnote' not in content:
                continue

            anchors = list(_DUOKAN_ANCHOR_PAT.finditer(content))
            if not anchors:
                continue

            sec_text = text[sec_start:sec_end]
            sec_key = to_key(sec_text)

            for anchor_m in anchors:
                fn_m = _FN_NUM_FROM_HREF_PAT.search(anchor_m.group())
                if not fn_m:
                    fn_m = _FN_NUM_FROM_ALT_PAT.search(anchor_m.group())
                if not fn_m:
                    continue
                fn_num = fn_m.group(1)

                # 提取锚点前后各 300 字节的原始 HTML，去标签后取关键字串
                pre_raw = content[max(0, anchor_m.start() - 300): anchor_m.start()]
                post_raw = content[anchor_m.end(): anchor_m.end() + 300]

                pre_key = to_key(strip_tags(pre_raw))
                post_key = to_key(strip_tags(post_raw))

                found = False
                for blen, alen in [(20, 15), (15, 10), (12, 8), (10, 6), (8, 5)]:
                    before = pre_key[-blen:] if len(pre_key) >= blen else pre_key
                    after  = post_key[:alen] if len(post_key) >= alen else post_key
                    if not before:
                        break

                    npos = sec_key.find(before + after)
                    if npos == -1:
                        continue

                    # 定位原始文本中"before 最后一字符"的位置，插在其后
                    last_before_nidx = npos + len(before) - 1
                    orig_i = norm_pos_to_orig(sec_text, last_before_nidx)
                    abs_ins = sec_start + orig_i + 1

                    marker = f'\\textsuperscript{{{fn_num}}}'
                    all_insertions.append((abs_ins, marker))
                    found = True
                    break

                # 最后回退：仅用 before（段末脚注后跟图/表等非文字块时 after 无法匹配）
                if not found:
                    before_fb = pre_key[-15:] if len(pre_key) >= 15 else pre_key
                    if before_fb:
                        npos = sec_key.find(before_fb)
                        if npos != -1:
                            # 确保 before 末尾是中文句尾标点（。！？」），避免误插中间
                            if sec_key[npos + len(before_fb) - 1] in '。！？」』":':
                                last_before_nidx = npos + len(before_fb) - 1
                                orig_i = norm_pos_to_orig(sec_text, last_before_nidx)
                                abs_ins = sec_start + orig_i + 1
                                marker = f'\\textsuperscript{{{fn_num}}}'
                                all_insertions.append((abs_ins, marker))
                                found = True

                if not found:
                    failed.append((xhtml_name, fn_num))

    if not all_insertions:
        return text, 0

    # --- 3. 去重：跳过目标位置已存在相同标记的条目（幂等保证）---
    # 同时检查 Fix 16 已把该位置包装成 \hyperref[fn:...]{\textsuperscript{N}} 的情况
    all_insertions = [
        (pos, marker)
        for pos, marker in all_insertions
        if text[pos:pos + len(marker)] != marker          # Fix 15 未处理
        and not text[pos:pos + 14].startswith(r'\hyperref[fn:')  # Fix 16 未包裹
    ]

    if not all_insertions:
        return text, 0

    # --- 4. 从右向左应用插入（保持前面位置不变）---
    all_insertions.sort(key=lambda x: x[0], reverse=True)
    for pos, marker in all_insertions:
        text = text[:pos] + marker + text[pos:]

    return text, len(all_insertions)


# ──────────────────────────────────────────────────────────
#  Fix 16: 脚注双向超链接
#
#  为章末注 enumerate 的每个 \item 添加 \phantomsection\label{fn:SEC-N}{}，
#  并将正文中的 \textsuperscript{N} 替换为 \hyperref[fn:SEC-N]{\textsuperscript{N}}，
#  实现正文引用 ↔ 章末注双向跳转。
# ──────────────────────────────────────────────────────────

_NOTE_ENUM_BLOCK_PAT = re.compile(
    r'(\\begin\{enumerate\})(.*?)(\\end\{enumerate\})',
    re.DOTALL,
)

def fix_footnote_hyperlinks(text):
    """
    Fix 16: 为章末注 enumerate 加 \\label，正文上标加 \\hyperref 跳转。
    幂等：重复运行不会重复添加。
    """
    # --- 1. 构建章节边界 ---
    sec_list = [(m.start(), m.group(1))
                for m in _SECTION_LABEL_XHTML_PAT.finditer(text)]
    sorted_secs = []
    seen = set()
    for i, (pos, name) in enumerate(sec_list):
        if name not in seen:
            seen.add(name)
            end = sec_list[i + 1][0] if i + 1 < len(sec_list) else len(text)
            sorted_secs.append((name, pos, end))

    def get_sec_key(pos):
        for name, start, end in sorted_secs:
            if start <= pos < end:
                return re.sub(r'\.xhtml$', '', name)
        return None

    # --- 2. 找到已经被 \hyperref 包裹的上标位置（幂等）---
    already_wrapped = set()
    for m in re.finditer(
        r'\\hyperref\[[^\]]+\]\{(\\textsuperscript\{\d+\})\}', text
    ):
        already_wrapped.add(m.start(1))

    insertions = []    # (abs_pos, str_to_insert)
    replacements = []  # (start, end, new_str)

    # --- 3. 为每个章末注 \item 添加 label ---
    for bm in _NOTE_ENUM_BLOCK_PAT.finditer(text):
        # 确认是章末注（前300字符含 \footnotesize）
        pre = text[max(0, bm.start() - 350): bm.start()]
        last_fn = pre.rfind('\\footnotesize')
        if last_fn == -1:
            continue
        # 最近的 \footnotesize 后不能有另一个 \end{enumerate}（嵌套块）
        if '\\end{enumerate}' in pre[last_fn:]:
            continue

        sec_key = get_sec_key(bm.start())
        if not sec_key:
            continue

        items_body = bm.group(2)
        items_start_abs = bm.start() + len(bm.group(1))  # after \begin{enumerate}

        for i, item_m in enumerate(re.finditer(r'\\item ', items_body)):
            n = i + 1
            label = f'fn:{sec_key}-{n}'
            abs_pos = items_start_abs + item_m.start()

            # 幂等：前60字符已有 \label{fn:SEC-N} 则跳过
            pre_item = text[max(0, abs_pos - 80): abs_pos]
            if f'\\label{{{label}}}' in pre_item:
                continue

            insertions.append((abs_pos, f'\\phantomsection\\label{{{label}}}{{}}\n'))

    # --- 4. 正文上标 → \hyperref[fn:SEC-N]{\textsuperscript{N}} ---
    for sm in re.finditer(r'\\textsuperscript\{(\d+)\}', text):
        if sm.start() in already_wrapped:
            continue

        # 跳过处于 enumerate 内部的上标（如 10^m 等数学上标不在章末注里，但为安全起见）
        # 通过 sec_key 判断即可，章末注里本来没上标
        n = sm.group(1)
        sec_key = get_sec_key(sm.start())
        if not sec_key:
            continue

        label = f'fn:{sec_key}-{n}'
        replacements.append((sm.start(), sm.end(),
                              f'\\hyperref[{label}]{{\\textsuperscript{{{n}}}}}'))

    if not insertions and not replacements:
        return text, 0

    # --- 5. 从右向左应用（保持位置稳定）---
    all_changes = (
        [(pos, pos, ins) for pos, ins in insertions] +
        [(s, e, r) for s, e, r in replacements]
    )
    all_changes.sort(key=lambda x: x[0], reverse=True)

    count = 0
    for start, end, new_txt in all_changes:
        text = text[:start] + new_txt + text[end:]
        count += 1

    return text, count


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


def fix_tnt_formulas(text):
    """
    Fix 19: 将正文段落中的独立 TNT 公式行转换为 LaTeX 内联数学环境 $...$。

    检测条件（同时满足）：
      1. 前后均为空行（独立段落）
      2. 无 CJK 字符
      3. 无表格标记（& 或行末 \\\\）
      4. 未已包裹在 $...$ 中
      5. 含 TNT 公式指示符：{$\\exists$}/{$\\forall$}，
         或 ～/\\textasciitilde + 后继符号，
         或 · / • + = + 后继符号

    转换内容：
      {$\\exists$} → \\exists    {$\\forall$} → \\forall
      独立 $\\cmd$ → \\cmd       ·/• → \\cdot
      ～ (U+FF5E) → \\lnot       \\textasciitilde → \\lnot
      \\textquotesingle → '

    幂等：转换后行以 $...$ 包裹，下次运行时被 startswith('$') 检测跳过。
    """
    def _convert(line):
        s = line
        # 1. 先处理带花括号量词（避免被下面的 $\cmd$ regex 拆坏）
        s = s.replace('{$\\exists$}', '\\exists ')
        s = s.replace('{$\\forall$}', '\\forall ')
        # 2. 去除独立 $\cmd$ 的外层美元号（\wedge, \vee, \rightarrow 等）
        s = re.sub(r'\$\\([a-zA-Z]+)\$', r'\\\1 ', s)
        # 3. 乘号点（两种 Unicode）
        s = s.replace('\u00b7', '\\cdot ')     # U+00B7 MIDDLE DOT
        s = s.replace('\u2022', '\\cdot ')     # U+2022 BULLET
        # 4. 否定符（先处理带空组的形式）
        s = s.replace('\\textasciitilde{}', '\\lnot ')
        s = s.replace('\\textasciitilde', '\\lnot ')
        s = s.replace('\uff5e', '\\lnot ')     # U+FF5E FULLWIDTH TILDE
        # 5. 变量上撇（先处理带空组的形式）
        s = s.replace('\\textquotesingle{}', "'")
        s = s.replace('\\textquotesingle', "'")
        # 6. 清理多余空格
        s = re.sub(r'  +', ' ', s).strip()
        return '$' + s + '$'

    def _is_tnt(line, lines, idx):
        stripped = line.strip()
        if not stripped:
            return False
        # 已包裹
        if stripped.startswith('$') and stripped.endswith('$'):
            return False
        # 前后空行
        prev_blank = (idx == 0) or (not lines[idx - 1].strip())
        next_blank = (idx >= len(lines) - 1) or (not lines[idx + 1].strip())
        if not (prev_blank and next_blank):
            return False
        # 无 CJK
        if re.search(r'[\u4e00-\u9fff]', stripped):
            return False
        # 无表格标记
        if '&' in stripped or stripped.endswith('\\\\'):
            return False
        # 跳过 LaTeX 环境命令行（以 \ 开头但非 \textasciitilde/\{）
        if (stripped.startswith('\\') and
                not stripped.startswith('\\textasciitilde') and
                not stripped.startswith('\\{')):
            return False
        # TNT 指示符
        has_q = '{$\\exists$}' in line or '{$\\forall$}' in line
        has_neg = (('\uff5e' in line or '\\textasciitilde' in line) and
                   bool(re.search(r'S[0-9a-zA-Z(]', line)))
        has_mult = (('\u00b7' in line or '\u2022' in line) and
                    '=' in line and
                    bool(re.search(r'S[0-9a-zA-Z(]', line)))
        return has_q or has_neg or has_mult

    lines = text.split('\n')
    count = 0
    for i, line in enumerate(lines):
        if _is_tnt(line, lines, i):
            lines[i] = _convert(line)
            count += 1
    return '\n'.join(lines), count


def fix_formula_notation(text):
    """
    Fix 18: 将 GEB.tex 中混用 \\textsuperscript / ×（Unicode 乘号）/ 裸幂次 /
    \\hyperref 内嵌上标的数学表达式转换为标准 LaTeX 数学环境。

    幂等保护：每个 old 字符串替换后即不再出现，第二次运行时 `old in text` 为 False，
    自然幂等，无需检查 new 是否已在文本中（旧写法 `new not in text` 有误）。
    """
    HR3 = r'\hyperref[fn:Chapter17-3]{\textsuperscript{3}}'
    HR4 = r'\hyperref[fn:Chapter17-4]{\textsuperscript{4}}'

    replacements = [
        # ── Chapter 9 前言行：n < 10^m（单侧上界说明）
        (r'n是小于10\textsuperscript{m}的任何自然数',
         r'n是小于$10^m$的任何自然数'),

        # ── Chapter 9 WJU 规则 1：裸 10m+1 与 10×(10m+1)
        ('若有了10m+1，则还可以有10×(10m+1)',
         r'若有了$10^m+1$，则还可以有$10\times(10^m+1)$'),

        # ── Chapter 9 WJU 规则 2：\textsuperscript + × 混用
        (r'若有了3×10\textsuperscript{m}+n，则还可以有10\textsuperscript{m}×(3×10\textsuperscript{m}+n)+n',
         r'若有了$3\times10^{m}+n$，则还可以有$10^{m}\times(3\times10^{m}+n)+n$'),

        # ── Chapter 9 WJU 规则 3：\textsuperscript + × 混用
        (r'若有了k×10\textsuperscript{m+3}+111×10\textsuperscript{m}+n，则还可以有k×10\textsuperscript{m+1}+n',
         r'若有了$k\times10^{m+3}+111\times10^{m}+n$，则还可以有$k\times10^{m+1}+n$'),

        # ── Chapter 9 WJU 规则 4：裸 10(m+2) 和 10(m)
        ('若有了k×10(m+2)+n，则还可以有k×10(m)+n',
         r'若有了$k\times10^{m+2}+n$，则还可以有$k\times10^{m}+n$'),

        # ── Chapter 10 费马定理检验程序（uppercase A/B/C，无 \hyperref，3 处）
        (r'A\textsuperscript{N}+B\textsuperscript{N}=C\textsuperscript{N}',
         r'$A^N+B^N=C^N$'),

        # ── Chapter 10 BlooP 说明段落中的内联 3^n（3 处）
        (r'3\textsuperscript{n}的值，这包括n次乘法。然后，你求2的3\textsuperscript{n}次方，这包括3\textsuperscript{n}次乘法。',
         r'$3^n$的值，这包括n次乘法。然后，你求2的$3^n$次方，这包括$3^n$次乘法。'),

        # ── Chapter 13 BlooP：函数定义 蓝程序{#12}[N]=2×N
        (r'\{\#12\}{[}N{]}=2×N',
         r'\{\#12\}$[N]=2N$'),

        # ── Chapter 14 丢番图方程示例（hyperref 内嵌，两个不同脚注）
        (r'5p\hyperref[fn:Chapter14-2]{\textsuperscript{2}}+17q\hyperref[fn:Chapter14-17]{\textsuperscript{17}}-177=0',
         r'$5p^2+17q^{17}-177=0$\hyperref[fn:Chapter14-2]{\textsuperscript{2}}'),

        # ── Chapter 14 哥德尔丢番图方程（多行，\textsuperscript 含长元组）
        ('a\\textsuperscript{(123, 666, 111, 666)}+b\\textsuperscript{(123, 666,\n111, 666)}-c\\textsuperscript{(123, 666, 111, 666)}=0',
         r'$a^{(123,666,111,666)}+b^{(123,666,111,666)}-c^{(123,666,111,666)}=0$'),

        # ── Chapter 17 分化机器：莱布尼茨求和项
        (r'(-1)\textsuperscript{N}/(2N+1)',
         r'$(-1)^N/(2N+1)$'),

        # ── Chapter 17 哈代-拉玛奴衍：1729 四次方分解
        ('635318657=134' + HR4 + '+133' + HR4 + '=158' + HR4 + '+59' + HR4,
         r'$635318657=134^4+133^4=158^4+59^4$' + HR4),

        # ── Chapter 17 立方和推广（三重等号，必须在单等号版本之前处理）
        ('r' + HR3 + '+s' + HR3 + '=u' + HR3 + '+v' + HR3
         + '=x' + HR3 + '+y' + HR3,
         r'$r^3+s^3=u^3+v^3=x^3+y^3$' + HR3),

        # ── Chapter 17 立方和推广（单等号）
        ('u' + HR3 + '+v' + HR3 + '=x' + HR3 + '+y' + HR3,
         r'$u^3+v^3=x^3+y^3$' + HR3),

        # ── Chapter 17 三个立方数
        ('u' + HR3 + '+v' + HR3 + '+w' + HR3
         + '=x' + HR3 + '+y' + HR3 + '+z' + HR3,
         r'$u^3+v^3+w^3=x^3+y^3+z^3$' + HR3),

        # ── Chapter 17 四次方三重等号
        ('r' + HR4 + '+s' + HR4 + '+t' + HR4
         + '=u' + HR4 + '+v' + HR4 + '+w' + HR4
         + '=x' + HR4 + '+y' + HR4 + '+z' + HR4,
         r'$r^4+s^4+t^4=u^4+v^4+w^4=x^4+y^4+z^4$' + HR4),

        # ── Dialog 10 阿基里斯讲费马方程（hyperref 内嵌，二次方）
        (r'a\hyperref[fn:Dialog10-2]{\textsuperscript{2}}+b\hyperref[fn:Dialog10-2]{\textsuperscript{2}}=c\hyperref[fn:Dialog10-2]{\textsuperscript{2}}',
         r'$a^2+b^2=c^2$\hyperref[fn:Dialog10-2]{\textsuperscript{2}}'),

        # ── 独立行费马方程变体（先处理含"对n=0"的更长串，再处理通用串）
        ('a\\textsuperscript{n}+b\\textsuperscript{n}=c\\textsuperscript{n}\u3000\u3000对n=0',
         '$a^n+b^n=c^n$\u3000\u3000对$n=0$'),
        ('a\\textsuperscript{n}+b\\textsuperscript{n}=c\\textsuperscript{n}',
         '$a^n+b^n=c^n$'),

        # ── 食蚁兽对话中的仿费马方程
        ('2\\textsuperscript{a}+2\\textsuperscript{b}=2\\textsuperscript{c}',
         '$2^a+2^b=2^c$'),
        ('n\\textsuperscript{a}+n\\textsuperscript{b}=n\\textsuperscript{c}',
         '$n^a+n^b=n^c$'),
    ]
    count = 0
    for old, new in replacements:
        if old in text:      # 幂等：替换后 old 不再出现，第二次自然跳过
            n = text.count(old)
            text = text.replace(old, new)
            count += n
    return text, count


# ──────────────────────────────────────────────────────────
#  Fix 20: 公式括号图片 → LaTeX \left.\right\} / \left\{\right. 花括号
# ──────────────────────────────────────────────────────────
def fix_bracket_formula_images(text):
    r"""将 Formula-right_bracket.png / Formula-left_bracket.png 图片替换为
    LaTeX 数学花括号命令（\left.\right\} 或 \left\{\right.），适用于各种行数。

    幂等：图片路径替换后不再出现，第二次运行自然跳过。
    """
    count = 0

    def _half(n):
        """将 n/2 格式化为 LaTeX 系数，偶数用整数，奇数用 x.5 小数。"""
        return str(n // 2) if n % 2 == 0 else f'{n / 2:.1f}'

    def right_brace(n):
        h = _half(n)
        return (
            r'\multirow{' + str(n) + r'}{=}'
            r'{$\left.\rule[-' + h + r'\normalbaselineskip]{0pt}{'
            + str(n) + r'\normalbaselineskip}\right\}$}'
        )

    def left_brace(n):
        h = _half(n)
        return (
            r'\multirow{' + str(n) + r'}{=}'
            r'{$\left\{\rule[-' + h + r'\normalbaselineskip]{0pt}{'
            + str(n) + r'\normalbaselineskip}\right.$}'
        )

    # ① 直接嵌入的 \multirow{N}{=}{\pandocbounded{..bracket..}}
    DIRECT_PAT = re.compile(
        r'\\multirow\{(\d+)\}\{=\}\{'
        r'\\pandocbounded\{\\includegraphics\[keepaspectratio\]'
        r'\{[^}]*Formula-(right|left)_bracket[^}]*\.png\}\}'
        r'\}'
    )

    def _replace_direct(m):
        nonlocal count
        n = int(m.group(1))
        side = m.group(2)
        count += 1
        return right_brace(n) if side == 'right' else left_brace(n)

    text = DIRECT_PAT.sub(_replace_direct, text)

    # ② minipage 包裹的情形（仅出现于 longtable 中的 F(n)/M(n) 公式）
    MINI_PAT = re.compile(
        r'\\multirow\{(\d+)\}\{=\}'
        r'\{\\begin\{minipage\}[^\n]*\n\s*'
        r'\\pandocbounded\{\\includegraphics\[keepaspectratio\]'
        r'\{[^}]*Formula-(right|left)_bracket[^}]*\.png\}\}'
        r'\s*\n\s*\\end\{minipage\}\}',
        re.DOTALL
    )

    def _replace_mini(m):
        nonlocal count
        n = int(m.group(1))
        side = m.group(2)
        count += 1
        return right_brace(n) if side == 'right' else left_brace(n)

    text = MINI_PAT.sub(_replace_mini, text)

    return text, count


# ── Fix 21: {单个非ASCII字符} → \textbf{...} ─────────────────────────────────
_BOLD_BRACED_PAT = re.compile(
    # 分支1: \命令（含可选参数）后跟零或多个 {...} 参数，再跟 {非ASCII单字} → 跳过
    r'\\[A-Za-z@*]+(?:\[[^\]]*\])*(?:\{[^{}]*\})*\{[^\x00-\x7F]\}'
    # 分支2: 裸 {非ASCII单字} → 替换为 \textbf{...}
    r'|(\{([^\x00-\x7F])\})'
)


def fix_bold_braced_chars(text):
    """Fix 21: 将单独的 {X}（X 为单个非ASCII字符）替换为 \\textbf{X}。

    幂等：\\textbf{X} 已存在时由分支1跳过；\\cmd{X} 形式也跳过。
    """
    count = 0

    def _replace(m):
        nonlocal count
        if m.group(1) is not None:   # 分支2命中：裸 {X}
            count += 1
            return r'\textbf{' + m.group(2) + '}'
        return m.group(0)            # 分支1命中：\cmd{X}，保留原样

    text = _BOLD_BRACED_PAT.sub(_replace, text)
    return text, count


# ──────────────────────────────────────────────────────────
#  Fix 28: 公式图片 PNG → LaTeX 数学/排版代码
#
#  EPUB 中部分复杂公式以 PNG 图片嵌入（Formula01.png …）。
#  本 fix 将已知公式图片替换为等价 LaTeX 代码，同时保留
#  原有的 \begin{center}...\end{center} 包裹（以及 \label
#  或 \phantomsection 行，若存在于同一 center 块中）。
#
#  替换表 FORMULA_REPLACEMENTS 以 PNG 文件名为键，值为用于
#  替换 \pandocbounded{...} 整行的 LaTeX 片段。
#  策略：仅替换 \pandocbounded{...Formula##.png...} 这一行，
#  外层 center 环境保持不变。
#
#  幂等：若该行已不含 \pandocbounded，则跳过。
# ──────────────────────────────────────────────────────────

# 每个条目：'FormulaXX.png' → 替换掉 \pandocbounded{...} 整行的 LaTeX
FORMULA_REPLACEMENTS = {
    'Formula01.png': (
        r'$\begin{array}{r}'  '\n'
        r'  12 \\'            '\n'
        r'  \times 12 \\'    '\n'
        r'  \hline'           '\n'
        r'  24 \\'            '\n'
        r'  12\phantom{0} \\' '\n'
        r'  \hline'           '\n'
        r'  144'              '\n'
        r'\end{array}$'
    ),
}

_FORMULA_PNG_LINE = re.compile(
    r'\\pandocbounded\{\\includegraphics\[keepaspectratio\]\{[^}]*/Images/(Formula\d+\.png)\}\}'
)


def fix_formula_images(text):
    """Fix 28: 将已知公式 PNG 行替换为等价 LaTeX 代码。"""
    count = 0

    def _replace_line(m):
        nonlocal count
        fname = m.group(1)
        if fname in FORMULA_REPLACEMENTS:
            count += 1
            return FORMULA_REPLACEMENTS[fname]
        return m.group(0)

    text = _FORMULA_PNG_LINE.sub(_replace_line, text)
    return text, count


def fix_indentfirst_preamble(text):
    """Fix 29: 在 preamble 中注入 \\usepackage{indentfirst}（若尚未存在）。
    indentfirst 让 \\chapter* 等命令后的首段也缩进。"""
    if r'\usepackage{indentfirst}' in text:
        return text, 0
    # 插入到 \usepackage{microtype} 之后
    old = r'\usepackage{microtype}'
    new = old + '\n\\usepackage{indentfirst}   %% 章节首段也缩进'
    if old in text:
        return text.replace(old, new, 1), 1
    return text, 0


def postprocess(text, verbose=True, epub_path='/tmp/GEB_packed.epub'):
    """对 GEB.tex 文本执行所有后处理，返回处理后的文本。"""

    # Fix 29: preamble 注入 indentfirst
    text, n_indent = fix_indentfirst_preamble(text)
    if verbose:
        print(f'  [29] indentfirst preamble 注入：{n_indent} 处')

    # Fix 1
    text, n_footnotes = fix_empty_footnotes(text)
    if verbose:
        print(f'  [1] 空脚注删除：{n_footnotes} 处')

    # Fix 2
    text, n_captions = fix_figure_captions(text)
    if verbose:
        print(f'  [2] 图说居中：{n_captions} 处')

    # Fix 24（需在 Fix 3/Fix 4 之前运行，清理旧 Lua filter 遗留的 \gebfont{...}）
    text, n_gebfont = fix_gebfont_cleanup(text)
    if verbose:
        print(f'  [24] \\gebfont{{}} 用法清理（字体误包裹/不平衡）：{n_gebfont} 处')

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
            if char in TAI_THAM_MAP:
                repl = TAI_THAM_MAP[char]
                print(f'       {char} ({name}) → "{repl}": {cnt}')
            else:
                print(f'       {char} ({name}) → {{\\gebfont}}: {cnt}')

    # Fix 5
    text, n_fig_envs = fix_figure_envs(text)
    if verbose:
        print(f'  [5] figure 环境包裹（\\caption* + \\label）：{n_fig_envs} 处')

    # Fix 25: 图片字幕归并进 figure 环境（须在 Fix 5 之后运行）
    text, n_imgsubs = fix_image_subtitles(text, epub_path=epub_path)
    if verbose:
        print(f'  [25] 图片字幕（duokan-image-subtitle）归入 figure：{n_imgsubs} 处')

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

    # Fix 4b: Fix 8 从 EPUB 插入的脚注内容可能含裸 Tai Viet 字符，需再次包裹
    text, n_taitham2, _ = fix_tai_tham(text)
    if verbose and n_taitham2:
        print(f'  [4b] Tai Viet 补充包裹（章末注插入后）：{n_taitham2} 处')

    # Fix 9
    text, n_tables = fix_longtable_columns(text)
    if verbose:
        print(f'  [9] longtable 列宽修正：{n_tables} 处')

    # Fix 12
    text, n_3col = fix_wrong_3col_widths(text)
    if verbose:
        print(f'  [12] 3列表错误宽度修正：{n_3col} 处')

    # Fix 13
    text, n_revert = fix_misidentified_tables(text)
    if verbose:
        print(f'  [13] CONTENT表列宽回退：{n_revert} 处')

    # Fix 14
    text, n_narrow = fix_narrow_multicol_tables(text)
    if verbose:
        print(f'  [14] 多列窄格表→resizebox+tabular：{n_narrow} 处')

    # Fix 15
    text, n_fnrefs = fix_footnote_references(text, epub_path=epub_path)
    if verbose:
        print(f'  [15] 脚注行内引用上标插入：{n_fnrefs} 处')

    # Fix 16
    text, n_fnlinks = fix_footnote_hyperlinks(text)
    if verbose:
        print(f'  [16] 脚注双向超链接：{n_fnlinks} 处')

    # Fix 17: 去除重复的 \hyperref 上标（幂等保护）
    _dup_hyperref_pat = re.compile(
        r'(\\hyperref\[[^\]]+\]\{\\textsuperscript\{\d+\}\}){2,}'
    )
    before_dedup = text.count(r'\hyperref[fn:')
    text = _dup_hyperref_pat.sub(lambda m: m.group(1), text)
    after_dedup = text.count(r'\hyperref[fn:')
    if verbose and before_dedup != after_dedup:
        print(f'  [17] 去除重复上标：{before_dedup - after_dedup} 处')

    # Fix 18: 公式符号转 LaTeX 数学环境
    text, n_formulas = fix_formula_notation(text)
    if verbose:
        print(f'  [18] 公式符号 → LaTeX 数学环境：{n_formulas} 处')

    # Fix 19: 独立 TNT 公式行 → $...$
    text, n_tnt = fix_tnt_formulas(text)
    if verbose:
        print(f'  [19] 独立 TNT 公式行 → \\$...\\$：{n_tnt} 处')

    # Fix 20: 公式括号图片 → LaTeX 花括号
    text, n_brackets = fix_bracket_formula_images(text)
    if verbose:
        print(f'  [20] 括号图片 → LaTeX 花括号：{n_brackets} 处')

    # Fix 21: {非ASCII单字符} → \textbf{...}
    text, n_bold = fix_bold_braced_chars(text)
    if verbose:
        print(f'  [21] 非ASCII单字符加粗：{n_bold} 处')

    # Fix 28: 公式 PNG → LaTeX 数学/排版代码
    text, n_formula_imgs = fix_formula_images(text)
    if verbose:
        print(f'  [28] 公式图片 PNG → LaTeX：{n_formula_imgs} 处')

    # Fix 23: <p class="title"> 节标题裸文本行 → \section{}
    text, n_sections = fix_ptitle_to_section(text, epub_path=epub_path)
    if verbose:
        print(f'  [23] <p class="title"> → \\section{{}}：{n_sections} 处')

    # Fix 26: dialog_guided → dialogguide 环境
    text, n_dg = fix_dialog_guided(text, epub_path=epub_path)
    if verbose:
        print(f'  [26] dialog_guided → dialogguide 环境：{n_dg} 处')

    # Fix 27: quote_text → fsquote 环境
    text, n_qt = fix_quote_text(text, epub_path=epub_path)
    if verbose:
        print(f'  [27] quote_text → fsquote 环境：{n_qt} 处')

    # Fix 10
    text, n_chapters = fix_section_to_chapter(text)
    if verbose:
        print(f'  [10] \\section→\\chapter 提升：{n_chapters} 处')

    # Fix 11
    text, n_illus = fix_illustration_links(text)
    if verbose:
        print(f'  [11] 插图目录超链接：{n_illus} 处')

    # Fix 22: 媒体路径 GEB_LaTeX/media/ → ../media/（split/ 目录下编译时需要）
    n_media = text.count('GEB_LaTeX/media/')
    if n_media:
        text = text.replace('GEB_LaTeX/media/', '../media/')
    if verbose:
        print(f'  [22] 媒体路径修正：{n_media} 处')

    return text


def main():
    parser = argparse.ArgumentParser(
        description='GEB.tex 后处理：删除空脚注、居中图说、修复 Unicode 符号、figure 环境、图引用超链接'
    )
    parser.add_argument('input', help='输入 .tex 文件路径')
    parser.add_argument('-o', '--output', help='输出文件路径（默认原地修改）')
    parser.add_argument('--epub', default='/tmp/GEB_packed.epub',
                        help='EPUB 源文件路径，用于提取脚注内容（默认：/tmp/GEB_packed.epub）')
    parser.add_argument('--copy-media', metavar='SRC_MEDIA_DIR',
                        help='将指定 media 目录覆盖复制到输出 .tex 所在目录的 media/ 子目录，'
                             '例如 --copy-media /path/to/GEB_LaTeX/media')
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

    # 媒体目录复制（--copy-media SRC）
    if args.copy_media:
        import shutil
        src_media = Path(args.copy_media)
        dst_media = output_path.parent / 'media'
        if not src_media.exists():
            print(f'[警告] --copy-media 指定的目录不存在：{src_media}', file=sys.stderr)
        else:
            if dst_media.exists():
                shutil.rmtree(dst_media)
            shutil.copytree(str(src_media), str(dst_media))
            print(f'媒体目录已复制：{src_media} → {dst_media}')


if __name__ == '__main__':
    main()
