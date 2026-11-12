# -*- coding: utf-8 -*-
"""反射率分档阈值 —— **全仓唯一来源**。

为什么单独一个模块
------------------
这些数字原来散在 5 个地方（`traffic/cma_tiles.py`、`weather/radar_public.py` 的活码、
`radar_public._band_of` 的死码、`NEXRAD_LUT` 的色板断点、前端图例），其中两份已经漂了
（雷达侧写成 32/41，权威值是 35/45）。漂移的后果不是"数字不好看"：图上颜色按一套阈值刷、
绕飞几何按另一套算，于是会出现"航线绕着一片淡绿走"、以及**已经判禁入的区域在图上不是红的**。

这个模块零 import（不依赖 numpy / shapely / httpx），因此：
  · `traffic/` 可以 `from weather.dbz import ...`（方向合法：traffic → weather）
  · `weather/radar_public.py` 也可以直接用，不会与 `traffic/radar_field.py` 形成包级环
  · 测试可以只 import 它做断言，不必拉起整条数据链
"""
from __future__ import annotations

from typing import Optional, Tuple

# 累计阈值：每档是"达到该值"，三档天然嵌套（STRONG ⊂ CONVECTIVE ⊂ WEAK）。
ECHO_FLOOR_DBZ = 15.0      # 底噪门：低于它的不是降水（含云边米色晕、地物杂波）
CONVECTIVE_DBZ = 35.0      # 对流门：中雨以上，绕飞判据
STRONG_DBZ = 45.0          # 强回波门：暴雨/冰雹核，禁入门
SEVERE_DBZ = 60.0          # 极端门：只用于图例刻度与告警分级

# (档名, 下界, 上界)。上界只用于文案与图例，判定一律用下界（累计语义）。
BAND_EDGES: Tuple[Tuple[str, float, float], ...] = (
    ('WEAK', ECHO_FLOOR_DBZ, CONVECTIVE_DBZ),
    ('CONVECTIVE', CONVECTIVE_DBZ, STRONG_DBZ),
    ('STRONG', STRONG_DBZ, SEVERE_DBZ),
)

# 档名 -> 下界。判档一律读这张表，不要在别处再打一遍数字。
BAND_FLOOR = {name: floor for name, floor, _ceil in BAND_EDGES}

# 载荷里下发的形状，与 `traffic/cma_tiles.py`、`weather_control.py`、`weather_sim.py`
# 三处既有的 `thresholdsDbz` 逐键一致（四键，不是三键 —— 少一个 severe 会打断
# `tests/test_weather_control.py` 里的 echo < convective < strong < severe 链）。
THRESHOLDS_DBZ = {
    'echo': ECHO_FLOOR_DBZ,
    'convective': CONVECTIVE_DBZ,
    'strong': STRONG_DBZ,
    'severe': SEVERE_DBZ,
}


def band_of(dbz: Optional[float]) -> Optional[str]:
    """把 dBZ 落到档名（累计语义：返回**达到的最高档**）。"""
    if dbz is None:
        return None
    value = float(dbz)
    if value >= STRONG_DBZ:
        return 'STRONG'
    if value >= CONVECTIVE_DBZ:
        return 'CONVECTIVE'
    if value >= ECHO_FLOOR_DBZ:
        return 'WEAK'
    return None
