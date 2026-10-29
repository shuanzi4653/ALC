# -*- coding: utf-8 -*-
"""修「模拟气象」开关不进判定链（0.11.4 · W-25）。

现象（用户 22:52 截图后提出）：切到「模拟气象」通道后，地图上的雷达回波、
气象监测页的风场换成了虚拟通道，**而结论条、4 个 KPI、53 条走廊概率一字不变**，
副标仍写"METAR 实测"。同一屏两套天气、一个结论。

根因：`/v2/*` 只认 `scenario`（live/clear/unknown），不认 `weather_control` 的
`measured/virtual`。`virtual` 只改了 `/traffic/weather` 的数据源。

这一轮不做的事：**不让虚拟通道参与概率计算**。虚拟通道产出的是雷达回波与风场，
而走廊概率的输入是三站 METAR 的要素时序 —— 把虚拟回波硬塞进概率模型，等于
用一份没有标签的数据重新训练，产出的数字没有出处。正确做法是**把两套口径
分开写清**，这也是项目一直的纪律（观测与估算分开、缺席不得并集顶替）。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / 'backend-python' / 'traffic' / 'v2.py'
BRIEF = ROOT / 'frontend' / 'src' / 'components' / 'traffic' / 'SituationBrief.vue'

text = V2.read_text(encoding='utf-8')

# ---- 1) overview 里读出当前气象通道，并把 return 改成可追加的 result ----
old_head = """    ]
    return {
        'status': 'OK',"""
new_head = """    ]
    # 当前气象通道（measured / virtual）。**它不进概率计算**，但必须进载荷：
    # 否则页面上"METAR 实测"与"模拟通道的虚拟回波"会并排出现而不加任何说明。
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
            # 这条 note 是**两个接口的口径差**，必须随载荷走：
            'note': ('走廊概率固定按三站 METAR 实测计算，不随虚拟通道切换；'
                     '本页地图上的雷达回波与风险区来自虚拟通道，两者不同源、不可互相印证。'
                     if channel == 'virtual' else
                     '走廊概率按三站 METAR 实测计算；3–6 h 为 Open-Meteo 模式延伸。'),
        },"""
if old_head not in text:
    raise SystemExit('overview return 头部锚点不存在')
text = text.replace(old_head, new_head, 1)

# 找到 overview 的 return 收尾（紧跟 kpis 之后的那一段），把它改成 return result
old_tail = """        {'key': 'ai', 'label': '模型覆盖', 'value': ai_value, 'unit': '%',
         'baseline': ai_baseline, 'baselineReason': ai_baseline_reason,
         'direction': None, 'tone': 'info'},
    ]"""
new_tail = """        {'key': 'ai', 'label': '模型覆盖', 'value': ai_value, 'unit': '%',
         'baseline': ai_baseline, 'baselineReason': ai_baseline_reason,
         'direction': None, 'tone': 'info'},
    ]"""
if old_tail not in text:
    raise SystemExit('kpis 尾部锚点不存在')

# 在 kpis 之后、原 return 的收尾（'kpis': kpis, ... }）处补一句边界，并 return result
old_ret = """        'kpis': kpis,
    }"""
new_ret = """        'kpis': kpis,
    }
    # 模拟通道下结论条必须自报边界：否则"可按计划运行"会被读成
    # "虚拟通道里的那 16 个回波单体也被考虑过了"。
    if channel == 'virtual':
        result['conclusion']['text'] = (
            result['conclusion']['text']
            + ' 当前为模拟气象通道：走廊概率仍按三站 METAR 实测计算，'
              '与地图上的虚拟回波不是同一份气象。')
    return result"""
if old_ret not in text:
    raise SystemExit('kpis 收尾锚点不存在（可能已有 return）')
text = text.replace(old_ret, new_ret, 1)

V2.write_text(text, encoding='utf-8')
print('v2.py weatherChannel 已加')

# ---- 2) SituationBrief 副标标出通道 ----
brief = BRIEF.read_text(encoding='utf-8')
old_line = """          <span v-if="observation?.dataType">· {{ observation.dataType==='STATION_OBSERVATION_METAR'?'METAR 实测':'来源未声明' }}</span>"""
new_line = """          <span v-if="observation?.dataType">· {{ observation.dataType==='STATION_OBSERVATION_METAR'?'METAR 实测':'来源未声明' }}</span>
          <!-- 0.11.4（W-25）：模拟通道开启时必须标出来。否则这一行写"METAR 实测"，
               而地图上的回波来自虚拟通道 —— 读者会以为整页都是实测。 -->
          <span v-if="data?.weatherChannel?.mode==='virtual'" class="brief-channel" :title="data.weatherChannel.note">· 模拟通道</span>"""
if old_line not in brief:
    raise SystemExit('副标锚点不存在')
brief = brief.replace(old_line, new_line, 1)

old_css = """.brief-case-note{color:var(--alc-text-dim)}"""
new_css = """.brief-case-note{color:var(--alc-text-dim)}
/* 模拟通道标记：橙色系，与"历史回放"同一族（都是"这一屏不是实时口径"），
   但用虚线边框区分——回放是"不是此刻"，模拟是"不是实测"。 */
.brief-channel{color:#C2410C;border-bottom:1px dashed rgba(194,65,12,.55)}"""
if old_css not in brief:
    raise SystemExit('样式锚点不存在')
brief = brief.replace(old_css, new_css, 1)

BRIEF.write_text(brief, encoding='utf-8')
print('SituationBrief 副标已标通道')
