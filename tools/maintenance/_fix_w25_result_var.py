# -*- coding: utf-8 -*-
"""补上 overview 里 `channel` 与 `result` 的定义（前一步只加了引用）。

必须与 `return result` 同时落地 —— 只加引用不加定义，`overview` 直接 NameError 500。
这一轮已经因为"加字段不加参数"挂过一次，这里是同一类错误的第二次机会。
"""
from pathlib import Path

V2 = Path(__file__).resolve().parents[2] / 'backend-python' / 'traffic' / 'v2.py'
text = V2.read_text(encoding='utf-8')

old = """    ]
    return {
        'status': 'OK',"""
new = """    ]
    # 当前气象通道（measured / virtual）。**它不进概率计算**，但必须进载荷：
    # 否则页面上「METAR 实测」与「模拟通道的虚拟回波」会并排出现而不加任何说明。
    try:
        from . import weather_control as _wc
        channel = _wc.mode()
    except Exception:  # noqa: BLE001
        channel = 'measured'
    result = {
        'status': 'OK',
        'weatherChannel': {
            'mode': channel,
            'label': '模拟气象通道' if channel == 'virtual' else '实测气象通道',
            # 这条 note 是两个接口的口径差，必须随载荷走：
            'note': ('走廊概率固定按三站 METAR 实测计算，不随虚拟通道切换；'
                     '本页地图上的雷达回波与风险区来自虚拟通道，两者不同源、不可互相印证。'
                     if channel == 'virtual' else
                     '走廊概率按三站 METAR 实测计算；3–6 h 为 Open-Meteo 模式延伸。'),
        },"""
if old not in text:
    raise SystemExit('锚点不存在（可能已改过）')
text = text.replace(old, new, 1)

# 自检：channel 与 result 都必须在使用前定义
if text.count("channel = _wc.mode()") != 1:
    raise SystemExit('channel 定义数量异常')
if text.count("return result") < 1:
    raise SystemExit('return result 不在')

V2.write_text(text, encoding='utf-8')
print('channel / result 定义已补')
