# -*- coding: utf-8 -*-
"""0.11.4 收尾批（W-26）：用户 23:12 报的 6 条界面问题里的 4 条。

1. 走廊列表 `0%` 被读成"可飞概率 0%"（用户问"是不是 100% 写反了"）——
   这一格是**不可飞**概率，但屏幕上只有一个裸百分比，标签缺失。
2. 首页 `show-radar/show-fog/show-weather` 三处硬编码 false，而顶部又给了
   对应勾选框 —— 勾了没反应（"运行首页没有雷达回波，只有运行总览有"）。
3. 「实测雷达由本机浏览器代取」是 `position:fixed;left:14px;bottom:46px`，
   滚动时压住内容（用户：有点挡位置）。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORR = ROOT / 'frontend' / 'src' / 'components' / 'traffic' / 'CorridorPanel.vue'
HOME = ROOT / 'frontend' / 'src' / 'components' / 'traffic' / 'HomeStage.vue'
WORK = ROOT / 'frontend' / 'src' / 'components' / 'TrafficWorkbench.vue'

# ---- 1) 走廊列表：把"不可飞"写进那一格 ----
text = CORR.read_text(encoding='utf-8')
old = """      <span class="corr-row-p alc-num">{{ pct(row.pMax) }}</span>
      <span class="corr-row-verdict">{{ riskLabel(row.pMax) }}</span>"""
new = """      <!-- 0.11.4（W-26）：这一格是**不可飞**概率。原来只印一个裸百分比，
           用户看到「0% + 可飞」第一反应是"可飞概率 0%，那不就是 100% 不可飞？"
           —— 判定没错，错在这一格没写它是谁的概率。 -->
      <span class="corr-row-p alc-num" :title="`不可飞概率 ${pct(row.pMax)}`">{{ pct(row.pMax) }}</span>
      <span class="corr-row-verdict">{{ riskLabel(row.pMax) }}</span>"""
if old not in text:
    raise SystemExit('走廊列表锚点不存在')
text = text.replace(old, new, 1)

# 列头也补一处（如果有）
text = text.replace('<span class="corr-list-head">',
                    '<span class="corr-list-head" title="不可飞概率 = 未来 3 小时该走廊不可飞的概率">', 1)
CORR.write_text(text, encoding='utf-8')
print('走廊列表：不可飞语义已补')

# ---- 2) 首页地图接上三个图层勾选框 ----
text = HOME.read_text(encoding='utf-8')
old = """                            :show-weather="false"
                            :show-wind="!!layers.wind" :show-fixed-zones="!!layers.zones"
                            :show-radar="false"
                            :show-fog="false\""""
new = """                            <!-- 0.11.4（W-26）：这三层原来**硬编码 false**，而顶部
                                 给了对应勾选框 —— 勾了没反应，于是"首页没有雷达回波，
                                 只有运行总览有"。勾选框存在就必须生效，否则它就是装饰。 -->
                            :show-weather="!!layers.weather"
                            :show-wind="!!layers.wind" :show-fixed-zones="!!layers.zones"
                            :show-radar="!!layers.radar"
                            :show-fog="!!layers.fog\""""
if old not in text:
    raise SystemExit('首页地图图层锚点不存在')
text = text.replace(old, new, 1)
HOME.write_text(text, encoding='utf-8')
print('首页：weather/fog/radar 三层已接上勾选框')

# ---- 3) 代取角标：从 fixed 左下改成顶栏内的小胶囊 ----
text = WORK.read_text(encoding='utf-8')
old_note = """  <div class="traffic-relay-note" v-if="radarRelay.status!=='idle'" role="status" data-radar-relay :class="radarRelay.status">
    <b>实测雷达</b><span>{{radarRelay.detail}}</span>
  </div>"""
if old_note not in text:
    raise SystemExit('relay-note 锚点不存在')
text = text.replace(old_note, '', 1)

# 插到顶栏"设置"按钮之后（nav 内），成为胶囊
old_btn = """      <button class="nav-toggle" data-settings-toggle :class="{on:settings}" :aria-pressed="settings" title="运行设置：情景、重新调度、信息密度、本页可做" @click="settings=!settings">设置</button>
    </div>"""
new_btn = """      <button class="nav-toggle" data-settings-toggle :class="{on:settings}" :aria-pressed="settings" title="运行设置：情景、重新调度、信息密度、本页可做" @click="settings=!settings">设置</button>
      <!-- 0.11.4（W-26）：这条**不能只说一次就消失**（数据来源必须可核对），
           但它原来是 `position:fixed; left:14px; bottom:46px` —— 滚动时会压住
           首页底部工具栏与"放行队列"标题。改成顶栏里的一枚胶囊：位置固定、
           不盖内容，全文进 `title`，不用展开也能核对到时刻。 -->
      <span class="relay-pill" v-if="radarRelay.status!=='idle'" role="status" data-radar-relay
            :class="radarRelay.status" :title="'实测雷达' + radarRelay.detail">
        雷达 {{ radarRelay.status==='ok' ? (radarRelay.slot||'').slice(11,16) : radarRelay.status==='running' ? '代取中' : '代取失败' }}
      </span>
    </div>"""
if old_btn not in text:
    raise SystemExit('设置按钮锚点不存在')
text = text.replace(old_btn, new_btn, 1)

old_css = """.traffic-relay-note{position:fixed;left:14px;bottom:46px;z-index:60;max-width:min(520px,60vw);
  padding:5px 10px;border-radius:6px;font-size:12px;line-height:1.5;
  background:rgba(17,26,43,.94);border:1px solid var(--alc-line);color:var(--alc-text-dim)}
.traffic-relay-note b{color:var(--alc-text);margin-right:6px}"""
new_css = """.relay-pill{margin-left:10px;padding:2px 9px;border-radius:10px;font-size:11px;line-height:1.6;
  background:rgba(17,26,43,.9);border:1px solid var(--alc-line);color:var(--alc-text-dim);
  cursor:help;white-space:nowrap;font-variant-numeric:tabular-nums}
.relay-pill.ok{border-color:rgba(82,196,26,.45);color:#9fd88a}
.relay-pill.failed{border-color:rgba(214,72,54,.55);color:#f0a99e}"""
if old_css not in text:
    raise SystemExit('relay-note 样式锚点不存在')
text = text.replace(old_css, new_css, 1)
WORK.write_text(text, encoding='utf-8')
print('代取角标：已改为顶栏胶囊')
