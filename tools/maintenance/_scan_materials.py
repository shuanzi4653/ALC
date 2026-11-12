# -*- coding: utf-8 -*-
"""提交前合规扫描：学校名 / 姓名 / 队名 / 指导教师 / 禁用数字 / 含用户名的绝对路径。

分两类目标：
  SUBMIT —— 会被原样交出去的东西（方案正文与 PDF、佐证索引、网盘命名清单）；
  INTERNAL —— 内部工作文档（00/01/03/04、答辩包）。它们**本来就**在讲"不许写什么"，
              命中属正常，结论只要求"不要把这些词转抄进 SUBMIT"。

用法：python tools/maintenance/_scan_materials.py
输出：docs/国赛-11-13/07-合规扫描-20261112.md
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs' / '国赛-11-13' / '07-合规扫描-20261112.md'

SUBMIT_GLOBS = [
    'docs/国赛-11-13/05-作品方案-正文-*.md',
    'docs/国赛-11-13/提交/*.md',
]
INTERNAL_GLOBS = [
    'docs/国赛-11-13/0[0-4]-*.md',
    'docs/国赛-11-13/06-提交前对账表-*.md',
    'docs/国赛-11-13/答辩保命包.md',
    'competition/*.md',
    'README.md',
    'tools/edge-export/*.md',
]

# (标签, 正则, 是否违规)
RULES = [
    ('学校名·东软', r'东软|Neusoft|neusoft|DNUI', True),
    ('学校名·信息学院', r'信息学院|软件学院|软件工程系', True),
    ('姓名', r'陈泽铨|泽铨', True),
    ('队名', r'知之队', True),
    ('指导教师', r'指导教师|指导老师|指导导师', True),
    ('禁用数字·3048', r'3048', True),
    ('禁用数字·2640', r'2640', True),
    ('禁用数字·3030', r'3030', True),
    ('禁用数字·3044', r'3044', True),
    ('禁用说法·240 个机场', r'240\s*个机场|240\s*机场', True),
    ('禁用说法·已获得软著', r'已获得(软件著作权|软著)|已取得(软件著作权|软著)', True),
    ('禁用说法·已实现整机硬件', r'已实现整机硬件|硬件已实现|整机已装配', True),
    ('禁用说法·ESP32 上实测', r'ESP32\s*上实测|在\s*ESP32\s*上(跑|测)', True),
    ('禁用说法·二十毫秒出结果', r'二十毫秒|20\s*ms\s*出结果|20\s*毫秒出结果', True),
    ('含用户名的绝对路径', r'C:\\\\?Users\\\\?(?!Public|All)', False),
    ('城市名·大连（良性，体系线要求）', r'大连(?!东软)', False),
]


def hits(text, pattern):
    out = []
    for m in re.finditer(pattern, text):
        line = text.count('\n', 0, m.start()) + 1
        start = text.rfind('\n', 0, m.start()) + 1
        end = text.find('\n', m.end())
        snippet = text[start: end if end > 0 else len(text)].strip()
        out.append((line, snippet[:160]))
    return out


def scan(globs):
    rows = []
    for pattern in globs:
        for path in sorted(ROOT.glob(pattern)):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue
            for label, rx, fatal in RULES:
                for line, snippet in hits(text, rx):
                    rows.append((str(path.relative_to(ROOT)), line, label, fatal, snippet))
    return rows


def main():
    submit = scan(SUBMIT_GLOBS)
    internal = scan(INTERNAL_GLOBS)
    fatal_submit = [r for r in submit if r[3]]
    benign_submit = [r for r in submit if not r[3]]

    lines = []
    lines.append('# 提交前合规扫描（2026-11-12）\n')
    lines.append('> 自动生成：`python tools/maintenance/_scan_materials.py`。')
    lines.append('> 扫描两类目标：**提交件**（方案正文/对账表/提交目录）与**内部工作文档**。')
    lines.append('> 内部文档本来就在写"不许写什么"，命中属正常；判据是**不要把这些词转抄进提交件**。\n')
    lines.append('## 一、提交件：违规命中\n')
    if fatal_submit:
        lines.append('| 文件 | 行 | 类别 | 片段 |')
        lines.append('|---|---|---|---|')
        for path, line, label, _fatal, snippet in fatal_submit:
            lines.append(f'| `{path}` | {line} | {label} | `{snippet}` |')
        lines.append('')
    else:
        lines.append('**0 处。** 学校名 / 姓名 / 队名 / 指导教师 / 禁用数字 / 禁用说法，在提交件里全部为 0。\n')

    lines.append('## 二、提交件：良性命中（保留，需知情）\n')
    if benign_submit:
        lines.append('| 文件 | 行 | 类别 | 片段 | 处置 |')
        lines.append('|---|---|---|---|---|')
        for path, line, label, _fatal, snippet in benign_submit:
            note = '城市名，需求分析"体系线"要求保留（唐山·大连·宁德）' if '大连' in label else '规则说明段落，指向内部清单'
            lines.append(f'| `{path}` | {line} | {label} | `{snippet}` | {note} |')
        lines.append('')
    else:
        lines.append('无。\n')

    lines.append('## 三、内部工作文档：命中统计（不提交，仅供知情）\n')
    if internal:
        from collections import Counter
        cnt = Counter((label, fatal) for _p, _l, label, fatal, _s in internal)
        lines.append('| 类别 | 命中条数 | 性质 |')
        lines.append('|---|---|---|')
        for (label, fatal), n in cnt.most_common():
            kind = '内部禁用清单/风险提示，正常' if fatal else '路径或城市名，良性'
            lines.append(f'| {label} | {n} | {kind} |')
        lines.append('')
        lines.append('> 这些文件不随作品提交；但**答辩口播与 PPT 制作时不得从这里直接复制粘贴数字**——')
        lines.append('> 抄一次就把废止口径带进现场。要往材料里写字，只从 `06-提交前对账表` 的 A–G 段拿。\n')
    else:
        lines.append('无。\n')

    lines.append('## 四、扫描口径说明\n')
    lines.append('| 目标 | 说明 |')
    lines.append('|---|---|')
    lines.append('| 提交件 | 方案 Markdown 源、提交前对账表、`docs/国赛-11-13/提交/` 下的导出件 |')
    lines.append('| 未覆盖 | PPT 与视频（尚未产出）。产出后须把导出的 PDF / 视频字幕文本加入本脚本的 `SUBMIT_GLOBS` 再跑一次 |')
    lines.append('| 不含 | 知网页面截图（本作品材料中禁止出现；如需证明查过文献，用自制检索统计表） |')
    lines.append('| 视频 | 录制时不得入镜命令行窗口——脚本里含 `C:\\Users\\<用户名>` 绝对路径 |')
    lines.append('')

    OUT.write_text('\n'.join(lines), encoding='utf-8')
    print('report ->', OUT)
    print('submit fatal:', len(fatal_submit), 'benign:', len(benign_submit), 'internal:', len(internal))
    return 0 if not fatal_submit else 1


if __name__ == '__main__':
    sys.exit(main())
