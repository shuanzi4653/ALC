# -*- coding: utf-8 -*-
"""W-15+ 附带修：概率百分比不再把 0.23% 印成 0%（复测报告 P1-4）。

`round(pMax * 100)` 把 0.0023 印成 `0`，于是结论条写出"最差为 X（0%）"——
"最差"怎么会是 0，读者只会怀疑精度。改成 <0.5% 或保留一位小数。
"""
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'backend-python' / 'traffic' / 'v2.py'
text = PATH.read_text(encoding='utf-8')

helper = '''
def _pct_text(p: Optional[float]) -> str:
    """概率 → 结论条里的百分比字符串。

    `round(p*100)` 会把 0.23% 印成 0%，于是"最差为 X（0%）"这种自相矛盾出现在
    结论条第一行。判据：**任何非零概率都不许印成 0**；四位小数以下才写 <0.1%。
    """
    if p is None:
        return '—'
    value = p * 100.0
    if value <= 0:
        return '0'
    if value < 0.1:
        return '<0.1'
    if value < 1:
        return '%.1f' % value
    return '%d' % round(value)


def _mode_total(mode: str) -> int:'''
if helper.replace('\n', '', 1) not in text.replace('\n', '', 1):
    old_head = "def _mode_total(mode: str) -> int:"
    if old_head not in text:
        raise SystemExit('_mode_total 锚点不存在')
    text = text.replace(old_head, helper.strip('\n'), 1)

pairs = [
    ("% (first['name'], len(high), vis_text, round(first['pMax'] * 100)))",
     "% (first['name'], len(high), vis_text, _pct_text(first['pMax'])))"),
    ("round(worst['pMax'] * 100), len(high), worst['corridorId']))",
     "_pct_text(worst['pMax']), len(high), worst['corridorId']))"),
    ("'当前最差为 %s（%d%%）。' % (len(watch), worst['name'], round(worst['pMax'] * 100)))",
     "'当前最差为 %s（%s%%）。' % (len(watch), worst['name'], _pct_text(worst['pMax'])))"),
    ("            worst_pct = round(worst['pMax'] * 100)",
     "            worst_pct = _pct_text(worst['pMax'])"),
]
for old, new in pairs:
    if old not in text:
        raise SystemExit('锚点不存在：' + old[:70])
    text = text.replace(old, new, 1)

# 模板里 %d%% 要跟着改成 %s%%，否则会对字符串格式化报错
text = text.replace("'未来 3 小时内，%s（%s）不可飞概率 %d%%，%d 条走廊处于禁飞级；'",
                    "'未来 3 小时内，%s（%s）不可飞概率 %s%%，%d 条走廊处于禁飞级；'", 1)
text = text.replace("'模型给出的未来 3 小时概率为 %d%% —— \"此刻已在阈值内\"与'",
                    "'模型给出的未来 3 小时概率为 %s%% —— \"此刻已在阈值内\"与'", 1)
text = text.replace("'（最差 %s），未达 50%% 处置线。观测里确实有雾，但校准后的概率没有越过阈值 —— '",
                    "'（最差 %s），未达 50%% 处置线。观测里确实有雾，但校准后的概率没有越过阈值 —— '", 1)
text = text.replace("'未来 3 小时内，%s的不可飞概率低于 50%%，可按计划运行；最差为 %s（%d%%）%s。'",
                    "'未来 3 小时内，%s的不可飞概率低于 50%%，可按计划运行；最差为 %s（%s%%）%s。'", 1)
text = text.replace("'历史回放：三站实测最低能见度 %s，模型给出的最高走廊不可飞概率 %d%%'",
                    "'历史回放：三站实测最低能见度 %s，模型给出的最高走廊不可飞概率 %s%%'", 1)

PATH.write_text(text, encoding='utf-8')
print('pct formatting patched')
