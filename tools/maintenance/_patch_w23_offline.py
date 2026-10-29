# -*- coding: utf-8 -*-
"""W-23 可做的一半（0.11.4）：`?offline=1` 离线演示兜底。

现场断网时，底图要等 **30 秒**超时才降级（W-12 的 `loadDeadline`），
而答辩只有 5 分钟。这个开关让它**立即**走离线底图，并跳过"浏览器代取雷达"
（取不到就别在台上等 8 秒超时）。

不做的事：不伪造雷达回波。offline 下雷达层直接声明不可用 —— 那比等一次超时
再报错更诚实，也更省时间。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'frontend' / 'src' / 'traffic' / 'runtime.js'
MAP = ROOT / 'frontend' / 'src' / 'components' / 'CityTrafficMap.vue'
WORK = ROOT / 'frontend' / 'src' / 'components' / 'TrafficWorkbench.vue'

# ---- 1) runtime.js 导出 isOfflineMode ----
text = RUNTIME.read_text(encoding='utf-8')
anchor = "/** 分组的默认子视图（第一个）。 */"
addition = '''/**
 * 离线演示模式（0.11.4 / W-23）：`?offline=1`。
 *
 * 它不是"降级开关"，是**演出开关**：现场断网时底图要等 30 秒超时才挂离线层，
 * 而答辩只有 5 分钟。打开它，底图立刻用离线层，雷达层直接声明不可用 ——
 * 不用在台上等一次超时。
 *
 * 与其他开关一样读 URL，不写 localStorage：刷新就回到正常模式，
 * 不然"昨天开着 offline、今天忘了关"会被当成系统坏了。
 */
export function isOfflineMode() {
  try {
    return new URLSearchParams(window.location.search).get('offline') === '1'
  } catch (_) {
    return false
  }
}

/** 分组的默认子视图（第一个）。 */'''
if anchor not in text:
    raise SystemExit('visibleSubs 锚点不存在')
text = text.replace(anchor, addition, 1)
RUNTIME.write_text(text, encoding='utf-8')
print('runtime.isOfflineMode 已导出')

# ---- 2) CityTrafficMap：offline 时立即降级，不等 30 秒 ----
text = MAP.read_text(encoding='utf-8')
old = """    loadDeadline=setTimeout(()=>{
      if(basemapChannel.value!==BASEMAP_CHANNEL_PENDING)return
      basemapChannel.value=BASEMAP_CHANNEL_OFFLINE
      mapStatus.value=basemapStatusText(BASEMAP_CHANNEL_OFFLINE,{})
    },30000)"""
new = """    // 0.11.4（W-23）：`?offline=1` 直接进离线通道，不排那个 30 秒定时器。
    // 现场断网时这 30 秒就是"评委看着空地图等你"。
    if(isOfflineMode()){
      basemapChannel.value=BASEMAP_CHANNEL_OFFLINE
      mapStatus.value=basemapStatusText(BASEMAP_CHANNEL_OFFLINE,{})
    }else{
      loadDeadline=setTimeout(()=>{
        if(basemapChannel.value!==BASEMAP_CHANNEL_PENDING)return
        basemapChannel.value=BASEMAP_CHANNEL_OFFLINE
        mapStatus.value=basemapStatusText(BASEMAP_CHANNEL_OFFLINE,{})
      },30000)
    }"""
if old not in text:
    raise SystemExit('loadDeadline 锚点不存在')
text = text.replace(old, new, 1)

# import
old_imp = "vehicleLabelText,vehicleLabel,selectVehicleLabels,routeBasisNote,alertEventLayer,observationPoints}"
new_imp = "vehicleLabelText,vehicleLabel,selectVehicleLabels,routeBasisNote,alertEventLayer,observationPoints,isOfflineMode}"
if old_imp not in text:
    raise SystemExit('CityTrafficMap import 锚点不存在')
text = text.replace(old_imp, new_imp, 1)
MAP.write_text(text, encoding='utf-8')
print('CityTrafficMap：offline 立即降级')

# ---- 3) TrafficWorkbench：offline 时不发起雷达代取 ----
text = WORK.read_text(encoding='utf-8')
old_relay = "  radarRelay.value={status:'running',slot:null,detail:'正在由本机浏览器代取瓦片…'}"
new_relay = """  // 0.11.4（W-23）：离线演示模式不发这个请求。取不到的时候在台上等 8 秒超时，
  // 比直接说"本模式不取实测雷达"更糟 —— 后者至少是实话。
  if(isOfflineMode()){
    radarRelay.value={status:'failed',slot:null,detail:'离线演示模式：未取实测雷达'}
    return
  }
  radarRelay.value={status:'running',slot:null,detail:'正在由本机浏览器代取瓦片…'}"""
if old_relay not in text:
    raise SystemExit('relay 运行态锚点不存在')
text = text.replace(old_relay, new_relay, 1)

# import isOfflineMode
old_wimp = "SECTION_NAMES,DENSITY_TIERS,NAV_GROUPS,visibleSubs"
if old_wimp in text:
    text = text.replace(old_wimp, old_wimp + ",isOfflineMode", 1)
else:
    raise SystemExit('workbench runtime import 锚点不存在')
WORK.write_text(text, encoding='utf-8')
print('TrafficWorkbench：offline 跳过雷达代取')
