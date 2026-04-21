"""
fix13_revert_content_tables.py

Fix 12 在修正"⇔比较表"列宽时，同时错误地修改了"推导表"（步骤号|公式|规则）。
本脚本将推导表从 0.44/0.08/0.40 回退为 0.08/0.50/0.34。

判断逻辑：
  - 提取每张 0.44/0.08/0.40 表格的数据行
  - 若中间列（第2列）的每行内容都是简单运算符（⇔ → ← = 以及空白），则属于 ARROW 表，保留
  - 否则属于 CONTENT 表，回退
"""
import re, sys
from pathlib import Path


# 3 列表的两种列宽规格
ARROW_SPEC = (
    r'>{\raggedright\arraybackslash}p{0.44\linewidth}'
    r' >{\raggedright\arraybackslash}p{0.08\linewidth}'
    r' >{\raggedright\arraybackslash}p{0.40\linewidth}'
)
CONTENT_SPEC = (
    r'>{\raggedright\arraybackslash}p{0.08\linewidth}'
    r' >{\raggedright\arraybackslash}p{0.50\linewidth}'
    r' >{\raggedright\arraybackslash}p{0.34\linewidth}'
)

# 中列为纯运算符的 pattern（⇔ → ← = ------）
_ARROW_CELL = re.compile(
    r'^\s*(\{?\$\\(?:Left|Right|left|right|Up|Down)'
    r'(?:right|left|arrow|arrow)?\w*\$\}?'       # $\Leftrightarrow$ 等
    r'|[=\-\u3000\s]*'                            # = 或全角空格或空
    r'|　+\{?\$\\(?:Left|Right)\w+\$\}?\s*'      # 　{$\Leftrightarrow$}　
    r')\s*$'
)


def _extract_col2_values(body: str) -> list[str]:
    """从表体中提取每行第 2 列的内容（跳过 multicolumn/multirow 行）"""
    values = []
    for row in body.split('\\\\'):
        # 跳过 \hline, \endhead 等
        stripped = row.strip()
        if not stripped or stripped.startswith('\\'):
            continue
        cells = stripped.split('&')
        if len(cells) < 3:
            continue
        col2 = cells[1].strip()
        # 跳过包含 multicolumn/multirow 的行
        if 'multicolumn' in col2 or 'multirow' in col2:
            continue
        values.append(col2)
    return values


def is_arrow_table(body: str) -> bool:
    """所有数据行的中间列都是箭头/等号 → 是 ARROW 表"""
    vals = _extract_col2_values(body)
    if not vals:
        return False
    return all(_ARROW_CELL.match(v) for v in vals)


def fix_misidentified_tables(text: str) -> tuple[str, int]:
    """将错误修改的 CONTENT 表从 ARROW_SPEC 回退为 CONTENT_SPEC"""
    pat = re.compile(
        r'(\\begin\{longtable\}\[\]\{\|)'
        + re.escape(ARROW_SPEC)
        + r'(\|\})'
        + r'(.*?)'
        + r'(\\end\{longtable\})',
        re.DOTALL,
    )

    count = 0
    result_parts = []
    last_end = 0

    for m in pat.finditer(text):
        # 提取表体（endlastfoot 之后的部分）
        full_body = m.group(3)
        elf_pos = full_body.find(r'\endlastfoot')
        body_only = full_body[elf_pos + 12:] if elf_pos >= 0 else full_body

        if is_arrow_table(body_only):
            # ARROW 表，保留原样
            result_parts.append(text[last_end:m.end()])
        else:
            # CONTENT 表，回退列宽
            replacement = (
                m.group(1)
                + CONTENT_SPEC
                + m.group(2)
                + m.group(3)
                + m.group(4)
            )
            result_parts.append(text[last_end:m.start()])
            result_parts.append(replacement)
            count += 1

        last_end = m.end()

    result_parts.append(text[last_end:])
    return ''.join(result_parts), count


if __name__ == '__main__':
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('GEB.tex')
    text = path.read_text(encoding='utf-8')
    result, n = fix_misidentified_tables(text)
    path.write_text(result, encoding='utf-8')
    print(f'回退了 {n} 张 CONTENT 表（保留了 {text.count(ARROW_SPEC) - 0} 张 ARROW 表）')
