from postprocess_tex import fix_bold_braced_chars

cases = [
    (r'\textbf{ω}',                    r'\textbf{ω}',    '已加粗→不变'),
    (r'{ω}',                           r'\textbf{ω}',    '裸字→加粗'),
    (r'\rotatebox[origin=c]{180}{赫}',  r'\rotatebox[origin=c]{180}{赫}', '命令参数→不变'),
    (r'{㧟}摁',                        r'\textbf{㧟}摁', '特殊字符'),
    (r'{赋}{格}',                       r'\textbf{赋}\textbf{格}', '多个'),
    (r'{x}',                           r'{x}',           'ASCII不变'),
]

all_ok = True
for src, expected, label in cases:
    result, n = fix_bold_braced_chars(src)
    ok = result == expected
    all_ok = all_ok and ok
    print(f"{'OK' if ok else 'FAIL'}  [{label}] {src!r} => {result!r}")

print()
print('全部通过' if all_ok else '有失败！')
