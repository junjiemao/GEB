# 哥德尔、艾舍尔、巴赫——集异璧之大成

Douglas Hofstadter 著作 *Gödel, Escher, Bach: an Eternal Golden Braid* 的中文精排 PDF 制作工程。以 EPUB 原文为输入，经由 pandoc + XeLaTeX 流水线生成大16开印刷质量 PDF，同时发布为 Quartz 静态站点。

---

## 目录结构

```
.
├── book/                   # 源文件（GEB.epub，不纳入 git）
├── GEB/                    # Obsidian/Quartz Markdown 笔记
├── GEB_LaTeX/
│   ├── geb-template.tex    # XeLaTeX 排版模板（preamble）
│   ├── GEB.tex             # pandoc 生成 + 后处理后的主文件
│   ├── media/              # 从 EPUB 提取的图片
│   └── split/              # split_tex.py 拆分输出 + 编译结果
├── script/
│   ├── postprocess_tex.py  # GEB.tex 后处理脚本（Fix 1-17）
│   └── split_tex.py        # 将 GEB.tex 拆分为多个子文件加速编译
├── terms/                  # 各章术语表（.txt）
├── build.sh                # 一键构建脚本
└── .github/workflows/      # Cloudflare Pages 自动部署
```

---

## 环境要求

| 工具 | 版本 | 安装方式 |
|------|------|----------|
| pandoc | ≥ 3.0 | `brew install pandoc` |
| XeLaTeX | MacTeX 2023+ | `brew install --cask mactex` |
| Python | ≥ 3.10 | 系统自带或 `brew install python` |
| Git LFS | ≥ 3.0 | `brew install git-lfs` |

字体依赖（需系统已安装）：

- **思源宋体**（Noto Serif CJK SC）— 中文正文
- **黑体 / 楷体**（Heiti SC / Kaiti SC）— macOS 自带
- **Palatino** — macOS 自带

---

## 构建

```bash
# 全流程：EPUB → GEB.tex → 后处理 → 拆分 → PDF（编译两次）
./build.sh

# 跳过 pandoc（正文未变，只改了模板/样式时）
./build.sh --skip-pandoc

# 只编译第 3 个分块（快速调试单章）
./build.sh --only 3

# 只跑一次 xelatex（查错时节省时间）
./build.sh --passes 1
```

输出 PDF：`GEB_LaTeX/split/GEB-main.pdf`

### 同步模板变更到 GEB.tex

修改 `geb-template.tex` 后，用以下命令将 preamble 同步到 `GEB.tex`（无需重跑 pandoc）：

```python
python3 - << 'EOF'
template = open('GEB_LaTeX/geb-template.tex').read()
geb = open('GEB_LaTeX/GEB.tex').read()
MARKER = r'\begin{document}'
result = template[:template.index(MARKER)] + geb[geb.index(MARKER):]
open('GEB_LaTeX/GEB.tex', 'w').write(result)
EOF
```

---

## 后处理脚本（postprocess_tex.py）

`build.sh` 在 pandoc 之后自动运行，针对 pandoc 生成物的已知缺陷共实施 17 项修复：

| Fix | 说明 |
|-----|------|
| 1 | 删除 pandoc 留下的空脚注 `\footnote{}` |
| 2 | 图说裸文本 → `\begin{center}\small\textbf{…}\end{center}` |
| 3 | Georgia 缺失的 Unicode 符号 → LaTeX 命令（→ ⇔ ∧ ∨ ① … 共 50+） |
| 4 | Tai Tham 乱码字符 → 对应汉字（龙/哦/奇） |
| 5 | `\pandocbounded` 图片 + 图说 → `figure[H]` 环境 + `\caption*` + `\label` |
| 6 | Fix 5 遗留及子图图说 → `\phantomsection\label` |
| 7 | 正文 `图N` → `\hyperref[fig:N]{图N}` 可点击链接 |
| 8 | 从 EPUB 提取 duokan 脚注内容，填充空的章末注块 |
| 9 | longtable `l` 列 → 按比例 `p{}` 列，防止溢出 |
| 10 | `\section{}` 升级为 `\chapter{}` / `\part{}` |
| 11 | 插图目录编号 → `\hyperref[fig:N]{N．}` |
| 12 | 修正 pandoc 从 CSS 错误读取的三列表列宽比例 |
| 13 | 回退 Fix 12 对推导表的误改（识别 ARROW/CONTENT 表） |
| 14 | 等宽多列窄表 → `\resizebox{\linewidth}{!}{\tabular{…}}` |
| 15 | 从 EPUB 定位 duokan-footnote 锚点，插入 `\textsuperscript{N}` |
| 16 | 脚注双向超链接（上标 ↔ 章末注 `\phantomsection\label`） |
| 17 | 去除重复上标（幂等保护，防止多次运行累积） |

---

## 版式规格

- **纸张**：大16开 185 × 260 mm
- **字体**：思源宋体 12pt（正文） / Palatino（西文） / 黑体（标题）
- **行距**：1.3 倍
- **双面印刷**：奇偶页页眉对称

---

## 网站发布

推送到 `main` 分支后，GitHub Actions 自动将 `GEB/` 目录构建为 Quartz 静态站点并部署到 Cloudflare Pages。

所需 Secrets / Variables：

| 名称 | 类型 | 说明 |
|------|------|------|
| `CLOUDFLARE_API_TOKEN` | Secret | Cloudflare API 密钥 |
| `CLOUDFLARE_ACCOUNT_ID` | Secret | Cloudflare 账号 ID |
| `CLOUDFLARE_PAGES_PROJECT` | Variable | Pages 项目名称 |
| `QUARTZ_BASE_URL` | Variable | 可选，默认 `xmatrix.github.io/GEB` |

---

## Git LFS

PDF 文件通过 Git LFS 管理（`.gitattributes` 已配置 `*.pdf filter=lfs`）。首次克隆后运行：

```bash
git lfs install
git lfs pull
```
