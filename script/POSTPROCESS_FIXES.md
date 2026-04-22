# postprocess_tex.py — Fix 列表与幂等性说明

所有 Fix 均设计为**幂等**：对同一文件重复运行，结果不变。

---

## Fix 1 — 删除空脚注

**函数**：`fix_empty_footnotes`  
**操作**：删除所有 `\footnote{}`（pandoc 未能提取 duokan 脚注留下的空壳）  
**幂等**：`\footnote{}` 删除后不再存在，第二次运行匹配为 0 处

---

## Fix 2 — 图说居中加粗

**函数**：`fix_figure_captions`  
**操作**：将裸图说行 `图N．标题` 包裹为 `\begin{center}\small\textbf{...}\end{center}`  
**幂等**：正则仅匹配裸文本行（不含 `\begin{center}`），已包裹的行不再命中

---

## Fix 3 — Unicode 符号 → LaTeX

**函数**：`fix_unicode_symbols`  
**操作**：将 `UNICODE_MAP` 中的符号（∀ ∃ ⇒ ∧ ∨ 等）替换为对应 LaTeX 命令  
**幂等**：替换后原字符不再出现；通过 `_protect_math` 跳过数学环境内已有的命令

---

## Fix 4 — Tai Viet 字符 → `{\gebfont X}`

**函数**：`fix_tai_tham`  
**操作**：将所有 Tai Viet 字符（U+AA80–U+AADF）包裹为 `{\gebfont X}`，使用 `geb.ttf` 渲染  
**幂等**：`{\gebfont ` 开头的内容不含裸 Tai Viet 字符，第二次运行计数为 0

---

## Fix 5 — 图片+图说 → `figure[H]` 环境

**函数**：`fix_figure_envs`  
**操作**：将 `\pandocbounded{...}` + `\begin{center}图说\end{center}` 包装为带 `\caption*` 和 `\label{fig:N}` 的 figure 环境  
**幂等**：已包裹的图片不再有 `\pandocbounded+\begin{center}` 连续结构，不会再命中

---

## Fix 6 — 补充 `\phantomsection\label` 到残余图说

**函数**：`fix_special_figure_labels`  
**操作**：为 Fix 5 未处理的 `\begin{center}...\end{center}` 图说及裸子图说行补充 `\label{fig:N}`  
**幂等**：正则通过 `(?<!\\label\{fig:)` 等 lookbehind 跳过已有 label 的行

---

## Fix 7 — 文中「图N」→ `\hyperref[fig:N]{图N}`

**函数**：`fix_figure_refs`  
**操作**：将正文中裸引用（如 `图33`）转为可跳转的超链接  
**幂等**：已有 `\hyperref[...]` 包裹的引用被正则排除（分支1跳过）

---

## Fix 8 — 从 EPUB 填充章末注内容

**函数**：`fix_empty_note_blocks`  
**操作**：解析 EPUB 中的 endnote HTML，将正文脚注内容填入 pandoc 留下的空 enumerate 块  
**幂等**：已填入内容的 enumerate 块不再是空块，不会重复匹配

---

## Fix 9 — longtable 无宽度 `l` 列 → `p{}` 列

**函数**：`fix_longtable_columns`  
**操作**：将 longtable 中的裸 `l` 列改为按比例分配宽度的 `p{0.NN\linewidth}` 列  
**幂等**：替换后列格式为 `p{...}`，不含裸 `l`，第二次运行不匹配

---

## Fix 10 — `\section` → `\chapter`

**函数**：`fix_section_to_chapter`  
**操作**：将顶层 `\section{}`/`\section*{}` 提升为 `\chapter{}`/`\chapter*{}`  
**幂等**：`\chapter` 不再是 `\section`，不会再命中

---

## Fix 11 — 插图目录编号 → `\hyperref`

**函数**：`fix_illustration_links`  
**操作**：将目录页中的 `N．` 编号替换为 `\hyperref[fig:N]{N．}` 超链接  
**幂等**：已有 `\hyperref` 的位置被正则 lookbehind 排除

---

## Fix 12 — 错误3列宽修正

**函数**：`fix_wrong_3col_widths`  
**操作**：将 pandoc 输出的错误比例 `0.08/0.50/0.34` 修正为 `0.44/0.08/0.40`  
**幂等**：修正后列格式为新值，不含旧值，第二次不匹配

---

## Fix 13 — 回退 Fix 12 误改的推导表

**函数**：`fix_misidentified_tables`  
**操作**：将 Fix 12 错误改动的"推导表"（CONTENT 表）回退为 `0.08/0.50/0.34`  
**幂等**：ARROW 表被 `is_arrow_table` 检测跳过；CONTENT 表回退后不再触发 Fix 12

---

## Fix 14 — 多列窄格表 → `resizebox+tabular`

**函数**：`fix_narrow_multicol_tables`  
**操作**：将列总宽 > 0.85 且各列等宽的表格包裹为 `\resizebox{\linewidth}{!}{...}`  
**幂等**：已包裹的表格有 `\begingroup...\endgroup` 标记，通过 `already_wrapped` 检测跳过

---

## Fix 15 — 正文插入脚注上标

**函数**：`fix_footnote_references`  
**操作**：在正文中匹配脚注锚点位置，插入 `\textsuperscript{N}` 上标  
**幂等**：目标位置已有 `\textsuperscript{N}` 或 `\hyperref[fn:...]` 时跳过

---

## Fix 16 — 脚注双向超链接

**函数**：`fix_footnote_hyperlinks`  
**操作**：为章末注 enumerate 加 `\label{fn:SEC-N}`，正文上标改为 `\hyperref` 跳转  
**幂等**：已包裹的上标位置记录在集合中跳过；`\label{fn:SEC-N}` 前60字符已存在时跳过

---

## Fix 17 — 去除重复 `\hyperref` 上标

（内联于 `postprocess`，无独立函数）  
**操作**：检测并移除因 Fix 15/16 重复运行产生的多余上标  
**幂等**：清理后不再有重复结构

---

## Fix 18 — 公式符号 → LaTeX 数学环境

**函数**：`fix_formula_notation`  
**操作**：将文本中的 `×`（乘号）、`^`（幂次）、`\textsuperscript{N}` 等格式统一为 `$...$`  
**幂等**：替换后旧字符串不再出现（`if old in text` 前置检查）；第二次运行 `old not in text`，自然跳过

---

## Fix 19 — 独立 TNT 公式行 → `$...$`

**函数**：`fix_tnt_formulas`  
**操作**：将独立的 TNT 公式行（如 `∃b:∃c:SSSSS0=(SSb·SSc)`）转为 `$...$` 内联数学  
**幂等**：已以 `$` 开头/结尾的行通过 `startswith('$')` 检测跳过

---

## Fix 20 — 括号图片 → LaTeX 花括号

**函数**：`fix_bracket_formula_images`  
**操作**：将 `Formula-right/left_bracket.png` 图片替换为 `$\left.\right\}$` / `$\left\{\right.$`，支持 N 行高度  
**幂等**：替换后不再有该图片路径，不会再匹配

---

## Fix 21 — `{单非ASCII字符}` → `\textbf{X}`

**函数**：`fix_bold_braced_chars`  
**操作**：将裸 `{X}`（X 为单个非ASCII字符）替换为 `\textbf{X}`  
**幂等**：正则分支1匹配 `\cmd{X}` 形式（含 `\textbf{X}`）后直接保留，不进入分支2

---

## Fix 22 — 媒体路径 `GEB_LaTeX/media/` → `../media/`

（内联于 `postprocess`，无独立函数）  
**操作**：将 pandoc 生成的绝对相对路径修正为相对 `split/` 目录的路径  
**幂等**：`GEB_LaTeX/media/` 替换后不再出现，第二次运行匹配为 0 处

---

## 数学环境保护（`_protect_math` / `_restore_math`）

Fix 3、Fix 18 等替换操作前调用 `_protect_math`，将所有 `$...$`、`$$...$$`、`\[...\]`、`\begin{equation}...` 替换为占位符，操作完成后恢复。确保替换不破坏已有数学公式。
