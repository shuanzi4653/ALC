# -*- coding: utf-8 -*-
"""W-19：把模板文本里的 Markdown 标记换成真标签（0.11.4）。

判据不是"静态扫到 0 处"，而是"页面上不出现连续两个星号"。所以这里只改
**会渲染成文本的字符串**，注释一律不动 —— 注释里的 `**加粗**` 是写给人看的，
改成 HTML 反而更难读。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'frontend' / 'src'

# (相对路径, 原文, 替换)
PAIRS = [
    ('components/OperationsConsole.vue',
     '官方固定管制区与气象派生风险区**分开报**，不合并成一个总数',
     '官方固定管制区与气象派生风险区<b>分开报</b>，不合并成一个总数'),
    ('components/OperationsConsole.vue',
     '登记数与已有几何数**不相等是正常的**',
     '登记数与已有几何数<b>不相等是正常的</b>'),
    ('components/OperationsConsole.vue',
     '本页是大模型的**证据检索**',
     '本页是大模型的<b>证据检索</b>'),
    ('components/OperationsConsole.vue',
     "?'虚拟通道沿时间轴逐帧取并集，因此**没有**\"某一帧的三档\"可报'",
     "?'虚拟通道沿时间轴逐帧取并集，因此<b>没有</b>\"某一帧的三档\"可报'"),
    ('components/traffic/MlEffectBoard.vue',
     '三列回答的**不是同一个问题**',
     '三列回答的<b>不是同一个问题</b>'),
    ('components/traffic/Track1Panel.vue',
     '模型只能把结论**变得更保守**',
     '模型只能把结论<b>变得更保守</b>'),
    ('components/traffic/DivergencePanel.vue',
     '台账按工作区隔离（`X-ALC-Workspace`）',
     '台账按工作区隔离（<code>X-ALC-Workspace</code>）'),
]

missing = []
for relative, old, new in PAIRS:
    path = ROOT / relative
    text = path.read_text(encoding='utf-8')
    if old not in text:
        missing.append((relative, old[:40]))
        continue
    path.write_text(text.replace(old, new, 1), encoding='utf-8')
    print('fixed %-44s %s' % (relative, old[:34]))

if missing:
    print('\n未命中（需人工看，不要硬改）：')
    for relative, sample in missing:
        print('  %s :: %s' % (relative, sample))
else:
    print('\n全部命中')
