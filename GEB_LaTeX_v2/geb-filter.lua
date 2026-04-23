--[[
  geb-filter.lua — GEB EPUB → LaTeX Lua 过滤器 (v2)

  职责：
    1. 把 EPUB CSS 类中有语义的 <span> / <div> 转换成对应的 LaTeX 命令
    2. 修复分离的图片说明（maintitle + subtitle → 同一 figure 环境内）
    3. 处理对话悬挂缩进行 / 楷体舞台指示 / 对话引导语等排版样式

  支持的 CSS 类映射：
    Span 类型：
      rare            → \gebfont{…}
      dialog_name     → \dialogname{…}
      dialog_name1    → \dialogname{…}
      kaiti           → \kaititext{…}
      kaiti_smalltext → \kaitismall{…}
      kaiti_bold      → \kaitibold{…}
      heiti           → \heititext{…}
      heiti_smalltext → \heitismall{…}
      emphasis        → \textbf{\sffamily …}
      emphasis1       → \textbf{\sffamily …}
      duokan-western  → \westerntext{…}
      duokan-western-italic → \westernital{…}
      zw / zw-c / zw-c1   → 直接输出（正文宋体，默认字体）
      smalltext / smalltext1 → \small{…}
      normal          → 直接输出
      part1           → 直接输出（part 副标题内 span）

    Div / Block 类型：
      hanging_indent  → 悬挂缩进对话行（含 speaker name）
      hanging_indent_1..8 → 同上，不同缩进量
      dialog_kaiti    → 楷体舞台指示（居中小字）
      dialog_guided   → 蓝色对话引导语（仿宋斜体缩进）
      dialog_indent   → 纯缩进段落
      dialog_indent1  → 1em 缩进段落
      center / center1 / centersmalltext → 居中段落
      d_indent_ / d_indent_1 / d_indent_2 / d_indent_4 → 左缩进块
      duokan-image-single   → 图片容器（figure 环境）
      duokan-image-maintitle / duokan-image-maintitle1 → 主图说（已由 pandoc 放入 caption*）
      duokan-image-subtitle / duokan-image-subtitle1   → 副图说（小楷居中/左）
      quote_text       → 仿宋引用块（使用 gebquote 环境）
      quote_text_kaiti → 楷体引用（加粗楷体引用框）
      zen_koan         → 禅宗公案块
      preface_quote    → 前言引用小字
]]

-- ─────────────────────────────────────────────────────────────────────────────
-- 工具函数
-- ─────────────────────────────────────────────────────────────────────────────

--- 把 pandoc 行内元素列表渲染成 LaTeX 原始输出
local function inlines_to_latex(inlines)
  return pandoc.write(pandoc.Pandoc({ pandoc.Para(inlines) }), 'latex')
      :gsub('^%s*(.-)%s*$', '%1') -- trim
end

--- 判断某个字符串列表中是否包含某个值
local function has_class(classes, name)
  for _, c in ipairs(classes) do
    if c == name then return true end
  end
  return false
end

--- 包裹 LaTeX 命令（行内）
local function raw(s)
  return pandoc.RawInline('latex', s)
end

--- 包裹 LaTeX 命令（块级）
local function rawblock(s)
  return pandoc.RawBlock('latex', s)
end

-- ─────────────────────────────────────────────────────────────────────────────
-- 工具：判断 UTF-8 字符串是否全为 Tai Viet 字符（U+AA80–U+AADF）
-- UTF-8 编码：U+AA80–U+AADF → EA AA [80-9F]（每字 3 字节）
-- ─────────────────────────────────────────────────────────────────────────────
local function is_pure_taiviet(s)
  if #s == 0 or #s % 3 ~= 0 then return false end
  for i = 1, #s, 3 do
    local b1 = string.byte(s, i)
    local b2 = string.byte(s, i + 1)
    local b3 = string.byte(s, i + 2)
    if b1 ~= 0xEA or b2 ~= 0xAA or b3 < 0x80 or b3 > 0x9F then
      return false
    end
  end
  return true
end

-- ─────────────────────────────────────────────────────────────────────────────
-- Span（行内）过滤器
-- ─────────────────────────────────────────────────────────────────────────────
function Span(el)
  local cls = el.classes

  -- rare：仅对纯 Tai Viet 字符（U+AA80–U+AADF）包裹 {\gebfont ...}
  -- 其他字符（⇔ ∀ ∃ 等逻辑符号、普通 CJK 等）直接透传，
  -- 由 postprocess_tex.py Fix 3/Fix 4 分别转换为 $\math_cmd$ / {\gebfont X}
  -- 这样可避免：
  --   1. 将逻辑符号包入 geb.ttf（geb.ttf 不含这些字形 → 空白）
  --   2. 双重嵌套 <span class="rare"> 产生 \gebfont{\gebfont{} 大括号不平衡
  if has_class(cls, 'rare') or has_class(cls, 'rare1') then
    local text = pandoc.utils.stringify(el)
    if is_pure_taiviet(text) then
      return { raw('{\\gebfont '), table.unpack(el.content), raw('}') }
    else
      return el.content  -- 透传
    end
  end

  -- 对话发言者名称（黑体加粗）
  if has_class(cls, 'dialog_name') or has_class(cls, 'dialog_name1') then
    return { raw('\\dialogname{'), table.unpack(el.content), raw('}') }
  end

  -- 楷体（含楷体小字、加粗楷体）
  if has_class(cls, 'kaiti_bold') then
    return { raw('\\kaitibold{'), table.unpack(el.content), raw('}') }
  end
  if has_class(cls, 'kaiti_smalltext') then
    return { raw('\\kaitismall{'), table.unpack(el.content), raw('}') }
  end
  if has_class(cls, 'kaiti') then
    return { raw('\\kaititext{'), table.unpack(el.content), raw('}') }
  end

  -- 黑体（heiti）
  if has_class(cls, 'heiti_smalltext') then
    return { raw('\\heitismall{'), table.unpack(el.content), raw('}') }
  end
  if has_class(cls, 'heiti') then
    return { raw('\\heititext{'), table.unpack(el.content), raw('}') }
  end

  -- 强调（黑体加粗）
  if has_class(cls, 'emphasis') or has_class(cls, 'emphasis1') then
    return { raw('\\heititext{'), table.unpack(el.content), raw('}') }
  end

  -- 西文 Palatino 字体
  if has_class(cls, 'duokan-western-italic') then
    return { raw('\\westernital{'), table.unpack(el.content), raw('}') }
  end
  if has_class(cls, 'duokan-western') or has_class(cls, 'duokan-western1') then
    return { raw('\\westerntext{'), table.unpack(el.content), raw('}') }
  end

  -- 小字
  if has_class(cls, 'smalltext') or has_class(cls, 'smalltext1')
      or has_class(cls, 'centersmalltext') then
    return { raw('{\\small '), table.unpack(el.content), raw('}') }
  end

  -- 下划线
  if has_class(cls, 'underline') then
    return { raw('\\underline{'), table.unpack(el.content), raw('}') }
  end

  -- 以下类强调加粗
  if has_class(cls, 'bold') then
    return { raw('\\textbf{'), table.unpack(el.content), raw('}') }
  end

  -- 宋体 / 正文默认 → 直接透传
  if has_class(cls, 'zw') or has_class(cls, 'zw-c') or has_class(cls, 'zw-c1')
      or has_class(cls, 'normal') or has_class(cls, 'part1')
      or has_class(cls, 'calibre1')  -- italic（已由 em 处理）
      then
    return el.content
  end

  -- 默认：返回 nil 让 pandoc 自行处理
  return nil
end

-- ─────────────────────────────────────────────────────────────────────────────
-- Div（块级）过滤器
-- ─────────────────────────────────────────────────────────────────────────────
function Div(el)
  local cls = el.classes

  -- ── 对话悬挂缩进行（各种 hanging_indent 变体）──────────────────────────
  local hanging_classes = {
    'hanging_indent', 'hanging_indent_1', 'hanging_indent_2',
    'hanging_indent_3', 'hanging_indent_4', 'hanging_indent_5',
    'hanging_indent_6', 'hanging_indent_7', 'hanging_indent_8',
    'hanging_indent2', 'hanging_indent_rule', 'hanging_indent_rule_',
    'hanging_indent_rule_1', 'hanging-indent-2_rule', 'h_indent_3_rule',
    'h_indent_4_rule', 'hanging_indent_',
  }
  for _, hc in ipairs(hanging_classes) do
    if has_class(cls, hc) then
      -- 保留段落内容，但用 \hangingDialogLine 包裹
      local result = {}
      for _, block in ipairs(el.content) do
        table.insert(result, rawblock('\\begin{hangdialog}'))
        table.insert(result, block)
        table.insert(result, rawblock('\\end{hangdialog}'))
      end
      return result
    end
  end

  -- ── 楷体舞台指示 ──────────────────────────────────────────────────────
  if has_class(cls, 'dialog_kaiti') then
    local result = {}
    for _, block in ipairs(el.content) do
      table.insert(result, rawblock('\\begin{stagedir}'))
      table.insert(result, block)
      table.insert(result, rawblock('\\end{stagedir}'))
    end
    return result
  end

  -- ── 对话引导语（蓝色仿宋斜体） ──────────────────────────────────────
  if has_class(cls, 'dialog_guided') then
    local result = {}
    for _, block in ipairs(el.content) do
      table.insert(result, rawblock('\\begin{dialogguide}'))
      table.insert(result, block)
      table.insert(result, rawblock('\\end{dialogguide}'))
    end
    return result
  end

  -- ── 对话缩进 ─────────────────────────────────────────────────────────
  if has_class(cls, 'dialog_indent') then
    local result = { rawblock('\\begin{adjustwidth}{2em}{0em}') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{adjustwidth}'))
    return result
  end
  if has_class(cls, 'dialog_indent1') then
    local result = { rawblock('\\begin{adjustwidth}{1em}{0em}') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{adjustwidth}'))
    return result
  end

  -- ── 居中 ──────────────────────────────────────────────────────────────
  if has_class(cls, 'center') or has_class(cls, 'center1')
      or has_class(cls, 'dialog_sub') or has_class(cls, 'dialog_sub_or') then
    local result = { rawblock('\\begin{center}') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{center}'))
    return result
  end

  -- centersmalltext
  if has_class(cls, 'centersmalltext') then
    local result = { rawblock('\\begin{center}\\small') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{center}'))
    return result
  end

  -- ── 左缩进块 ─────────────────────────────────────────────────────────
  -- d_indent_ (2em), d_indent_1 (2em), d_indent_2 (4em), d_indent_4 (6em)
  if has_class(cls, 'd_indent_') or has_class(cls, 'd_indent_1') then
    local result = { rawblock('\\begin{adjustwidth}{2em}{0em}') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{adjustwidth}'))
    return result
  end
  if has_class(cls, 'd_indent_2') then
    local result = { rawblock('\\begin{adjustwidth}{4em}{0em}') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{adjustwidth}'))
    return result
  end
  if has_class(cls, 'd_indent_3') then
    -- small, no extra indent
    local result = { rawblock('{\\small') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('}'))
    return result
  end
  if has_class(cls, 'd_indent_4') then
    local result = { rawblock('\\begin{adjustwidth}{6em}{0em}') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{adjustwidth}'))
    return result
  end

  -- ── 引用块（quote_text → 仿宋引用） ─────────────────────────────────
  if has_class(cls, 'quote_text') or has_class(cls, 'quote_text-indent')
      or has_class(cls, 'quote_text_') then
    local result = { rawblock('\\begin{fsquote}') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{fsquote}'))
    return result
  end

  -- quote_text_kaiti → 楷体引用框
  if has_class(cls, 'quote_text_kaiti') then
    local result = { rawblock('\\begin{ktquote}') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{ktquote}'))
    return result
  end

  -- preface_quote
  if has_class(cls, 'preface_quote') then
    local result = { rawblock('\\begin{adjustwidth}{2em}{0em}\\small') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{adjustwidth}') )
    return result
  end

  -- ── 禅宗公案 ─────────────────────────────────────────────────────────
  if has_class(cls, 'zen_koan') or has_class(cls, 'zen_koan1') then
    local result = { rawblock('\\begin{zenkoan}') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{zenkoan}'))
    return result
  end
  if has_class(cls, 'zen_koan-poem') then
    local result = { rawblock('\\begin{zenkoanpoem}') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{zenkoanpoem}'))
    return result
  end

  -- ── 图片副说明（duokan-image-subtitle → 左对齐/居中小楷） ────────────
  if has_class(cls, 'duokan-image-subtitle') or has_class(cls, 'duokan-image-subtitle1')
      or has_class(cls, 'duokan-image-subtitle2') or has_class(cls, 'duokan-image-subtitle3') then
    local result = { rawblock('\\begin{imgsub}') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{imgsub}'))
    return result
  end

  -- ── 对话诗歌 ─────────────────────────────────────────────────────────
  if has_class(cls, 'dialog_poem') or has_class(cls, 'dialog_poem1')
      or has_class(cls, 'dialog_poem2') then
    local result = { rawblock('\\begin{dialogpoem}') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{dialogpoem}'))
    return result
  end

  -- ── 悬挂缩进各种变体（duiweicangtou 等） ─────────────────────────────
  if has_class(cls, 'duiweicangtou') then
    local result = {}
    for _, block in ipairs(el.content) do
      table.insert(result, rawblock('\\begin{hangdialog}'))
      table.insert(result, block)
      table.insert(result, rawblock('\\end{hangdialog}'))
    end
    return result
  end

  -- ── 对话题目（dialog / dialog1 h1 已由 pandoc 转为 chapter*，不再重复处理）
  -- ── 不识别的类：透传
  return nil
end

-- ─────────────────────────────────────────────────────────────────────────────
-- Header 过滤器：处理章节数字 chapter_number 类（出现在 <p> 中，被 div 包裹）
-- ─────────────────────────────────────────────────────────────────────────────
-- 注意：pandoc 读取 EPUB 时，<p class="chapter_number"> 会成为
--   Div(["chapter_number"]) [Para [...]]
-- 我们把它输出成 \chapterpreheader{}
function Div_chapter(el)
  local cls = el.classes
  if has_class(cls, 'chapter_number') then
    local result = { rawblock('\\begin{chappreheader}') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{chappreheader}'))
    return result
  end
  if has_class(cls, 'part_number') then
    local result = { rawblock('\\begin{partpreheader}') }
    for _, block in ipairs(el.content) do
      table.insert(result, block)
    end
    table.insert(result, rawblock('\\end{partpreheader}'))
    return result
  end
end

-- 合并两个 Div 函数
local orig_Div = Div
function Div(el)
  local r1 = Div_chapter(el)
  if r1 then return r1 end
  return orig_Div(el)
end

-- ─────────────────────────────────────────────────────────────────────────────
-- Image 过滤器：把内联 Plain 格式图片转换成浮动 figure
-- ─────────────────────────────────────────────────────────────────────────────
-- 注意：pandoc 通常已经处理了 figure，这里只针对 Plain(..) 中的裸图片
function Plain(el)
  -- 如果段落只含一个图片，加上浮动图形环境
  if #el.content == 1 and el.content[1].tag == 'Image' then
    local img = el.content[1]
    local src = img.src
    local caption_inlines = img.caption
    if #caption_inlines == 0 then
      -- 无标题，直接输出，不包装
      return nil
    end
  end
  return nil
end
