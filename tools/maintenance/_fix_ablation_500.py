# -*- coding: utf-8 -*-
"""紧急修复：`ablation` 字段被加到了 overview 的返回里。

overview 没有 `ablate` 参数，那行一执行就 NameError → 线上 `overview` 直接 500。
（教训：给一个函数加返回字段时，先确认那个函数的签名里有对应入参。
「加个字段」看起来最无害，而它造成的是整页打不开。）
"""
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'backend-python' / 'traffic' / 'v2.py'
text = PATH.read_text(encoding='utf-8')

old = """        'case': traffic_cases.describe(case_id) if case_id else None,
        'ablation': ({'disabled': ablate,
                     'label': {'obs': '去掉观测档', 'prob': '去掉概率层',
                               'loss': '去掉期望损失决策'}.get(ablate, '')}
                     if ablate else None),
        'timeBase':"""
new = """        'case': traffic_cases.describe(case_id) if case_id else None,
        'timeBase':"""
if old not in text:
    raise SystemExit('overview 里的 ablation 锚点不存在')
text = text.replace(old, new, 1)

old2 = "        'peakUnsafe': None if peak_p is None else round(peak_p, 4),"
new2 = ("        'peakUnsafe': None if peak_p is None else round(peak_p, 4),\n"
        "        # 消融实验的标记（0.11.4 / W-24）。非空时页面必须打标：\n"
        "        # 这是关掉某一层之后的数，不是本系统的结论。\n"
        "        'ablation': ({'disabled': ablate,\n"
        "                      'label': {'obs': '去掉观测档', 'prob': '去掉概率层',\n"
        "                                'loss': '去掉期望损失决策'}.get(ablate, '')}\n"
        "                     if ablate else None),")
if old2 not in text:
    raise SystemExit('peakUnsafe 锚点不存在')
text = text.replace(old2, new2, 1)

PATH.write_text(text, encoding='utf-8')
print('ablation 字段已挪到 counterfactual')
