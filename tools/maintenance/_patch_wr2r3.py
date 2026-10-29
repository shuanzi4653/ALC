# -*- coding: utf-8 -*-
"""0.11.5B · W-R2（补）+ W-R3。

W-R2 的**真因不是"没触发"** —— 线上实测胶囊显示过 `雷达 13:30`，说明代取跑成过一次。
真因是：**中继 TTL 只有 600 秒，过期后没有人再去取。**
`relayNextAllowedAt` 允许在 9 分钟后重试，但重试的入口只有 `loadWeather()`，
而它只在"计划就绪 / 切城市 / 切场景"时被调用 —— 于是过期之后就永久停在
`available:false`，用户看到的是"雷达回波不可用"，和"链路没通"长得一模一样。

W-R3：把"没有"讲成"有理由的没有"。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'frontend' / 'src' / 'components' / 'TrafficWorkbench.vue'
MAP = ROOT / 'frontend' / 'src' / 'components' / 'CityTrafficMap.vue'

# ============================================================
# W-R2 补：中继过期后自动再取一次
# ============================================================
work = WORK.read_text(encoding='utf-8')
old = """async function maybeRelayRadar(value){"""
new = """// 0.11.5B（W-R2）：中继帧的 TTL 是 600 秒，过期后后端就回到"直取 → 403"。
// 原来重试的唯一入口是 `loadWeather()`（计划就绪 / 切城市 / 切场景才调用），
// 于是**过期之后没有任何人再去取**，界面永久停在"雷达回波不可用"——
// 而这与"链路根本没通"在屏幕上长得一模一样。
// 这个定时器只做一件事：到点再试一次。它不会自激：`relayNextAllowedAt` 在
// 请求**发出前**就已写死，且 `radarRelayReady(relay)` 在"中继仍有效"时返回 false。
let relayRetryTimer=null
function scheduleRelayRetry(){
  if(relayRetryTimer)clearTimeout(relayRetryTimer)
  const delay=Math.max(30_000,relayNextAllowedAt-Date.now()+1_000)
  relayRetryTimer=setTimeout(()=>{
    relayRetryTimer=null
    // 只在当前帧确实没有回波时才重试；有回波说明中继/直取已经好了，不必再打扰源站
    const radar=weather.value&&weather.value.radar
    if(radar&&radar.available===false)maybeRelayRadar(weather.value)
  },delay)
}

async function maybeRelayRadar(value){"""
if old not in work:
    raise SystemExit('maybeRelayRadar 锚点不存在')
work = work.replace(old, new, 1)

# 成功/失败后都排下一次
old_ok = """      radarRelay.value={status:'ok',slot:result.slot,detail:`由本机浏览器代取：${result.slot}（北京时）`}"""
new_ok = """      radarRelay.value={status:'ok',slot:result.slot,detail:`由本机浏览器代取：${result.slot}（北京时）`}
      scheduleRelayRetry()"""
if old_ok not in work:
    raise SystemExit('relay ok 锚点不存在')
work = work.replace(old_ok, new_ok, 1)

old_fail = """    radarRelay.value={status:'failed',slot:null,detail:'代取失败：'+(e&&e.message||e)}"""
new_fail = """    radarRelay.value={status:'failed',slot:null,detail:'代取失败：'+(e&&e.message||e)}
    scheduleRelayRetry()"""
if old_fail in work:
    work = work.replace(old_fail, new_fail, 1)

# 组件卸载时清定时器
old_unmount = "onUnmounted(()=>{"
if old_unmount in work:
    idx = work.index(old_unmount)
    insert = "onUnmounted(()=>{\n  if(relayRetryTimer)clearTimeout(relayRetryTimer)"
    work = work[:idx] + insert + work[idx + len(old_unmount):]
    print('定时器清理已挂到 onUnmounted')
else:
    print('⚠️ 未找到 onUnmounted，定时器需手工清理')
WORK.write_text(work, encoding='utf-8')
print('W-R2 补：中继过期自动重试')

# ============================================================
# W-R3：状态条把"没有"讲成"有理由的没有"
# ============================================================
mapped = MAP.read_text(encoding='utf-8')
old = """  const base=state===RADAR_STATE.READY?'风险区：雷达回波已叠加'
    :state===RADAR_STATE.QUIET?(drawn?'雷达：仅层状降水（可飞越，已标出范围）'
      :'雷达：本作业区当前无回波'):'雷达回波不可用'"""
new = """  // 0.11.5B（W-R3）：原来只写"仅层状降水（可飞越，已标出范围）"—— 那是**结果**，
  // 不是**理由**。用户（包括我们自己）看到"没橙色"的第一反应是"功能坏了"，
  // 因为屏幕上没有任何一句话说"本帧确实没有 ≥35 dBZ 的对流，所以按设计不画橙色"。
  // 补上面积与阈值，把"看不到"从缺陷变成证据。
  const stratiform=Number(radar?.summary?.bands?.STRATIFORM?.areaKm2)
  const stratArea=Number.isFinite(stratiform)?`${stratiform.toFixed(1)} km²`:''
  const base=state===RADAR_STATE.READY?'风险区：雷达回波已叠加'
    :state===RADAR_STATE.QUIET?(drawn
      ? `雷达：仅层状降水${stratArea?` ${stratArea}`:''}（15–35 dBZ，可飞越）· 本帧无 ≥35 dBZ 对流，橙色按设计不出现`
      :'雷达：本作业区当前无回波（0 块 ≥35 dBZ）'):'雷达回波不可用'"""
if old not in mapped:
    raise SystemExit('W-R3 状态条锚点不存在')
mapped = mapped.replace(old, new, 1)
MAP.write_text(mapped, encoding='utf-8')
print('W-R3：状态条已补"为什么没有橙色"')
