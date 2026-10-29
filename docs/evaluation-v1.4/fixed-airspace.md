# 0.9.7（Beta） 固定管制空域证据（本地实测）

- 目录版本：`northeast-fixed-airspace-v1`，公开数据取得日 2026-09-16
- 法规：《无人驾驶航空器飞行管理暂行条例》（国令第 761 号，2024-01-01 施行） 第十九条
- 站点总数 69：有确定几何 60，仅登记 9
- 禁入 12，须经批准 48，仅登记 9
- 已按公开依据生成圆的半径取值（m）：[500, 5000, 55000]（未出现 20000，即天气雷达探测环境保护区未充当飞行管制几何）
- `/traffic/network` 首调 0.161 s（缓存已清空后计时），整包 614 KiB，其中固定管制区 141 KiB，环顶点合计 3069
- 禁入集合面积：默认口径 163.9 km²，严格口径 20626.9 km²

## 第八条覆盖矩阵（按实际目录统计）

| 条文 | 领域 | 几何状态 | 站点 | 有几何 | 禁入 | 须批准 | 仅登记 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 第十九条第（一）项 | 民航 | PARTIALLY_PUBLISHED | 48 | 48 | 0 | 48 | 0 |
| 第十九条第（二）项 | 国防 | PERIMETER_NOT_PUBLICLY_PUBLISHED | 0 | 0 | 0 | 0 | 0 |
| 第十九条第（三）项 | 机密 | PERIMETER_NOT_PUBLICLY_PUBLISHED | 0 | 0 | 0 | 0 | 0 |
| 第十九条第（四）项 | 国防 | PARTIALLY_PUBLISHED | 2 | 2 | 2 | 0 | 0 |
| 第十九条第（五）项 | 政务 | AREA_EXTENT_REQUIRES_LOCAL_PUBLICATION | 0 | 0 | 0 | 0 | 0 |
| 第十九条第（六）项 | 科研 | PARTIALLY_PUBLISHED | 11 | 10 | 10 | 0 | 1 |
| 第十九条第（七）项 | 政务 | AREA_EXTENT_REQUIRES_LOCAL_PUBLICATION | 8 | 0 | 0 | 0 | 8 |
| 第十九条第（八）项 | 政务 | PERIMETER_NOT_PUBLICLY_PUBLISHED | 0 | 0 | 0 | 0 | 0 |

## 两种机场净空口径的真实代价（seed 42 / moving，热态串行测量）

冷进程首调 25.65 s（含导入与首次 STRtree 构建，不作为本功能成本）；下表为**热态**耗时。

| 口径 | 计划用时 | 关闭班次 | 因固定管制区关闭 | 需批准班次 | 穿越记录 | 有穿越的班次 |
| --- | --- | --- | --- | --- | --- | --- |
| APPROVAL_REQUIRED（默认） | 26.64 s | 1725 | 0 | 3289 | 4700 | 3289 |
| PROHIBITED（严格） | 19.09 s | 3677 | 2187 | 1318 | 1487 | 1318 |

### 关闭原因分布

- 默认口径：`{"CLEAR": 6008, "WEATHER_BLOCKED": 1621, "BEYOND_PLANNING_HORIZON": 87, "WEATHER_DETOUR": 27, "SEPARATION_RESOURCE_OR_TIME_LIMIT": 17}`
- 严格口径：`{"CLEAR": 4034, "STATIC_AIRSPACE_BLOCKED": 2187, "WEATHER_BLOCKED": 1439, "WEATHER_DETOUR": 49, "BEYOND_PLANNING_HORIZON": 44, "SEPARATION_RESOURCE_OR_TIME_LIMIT": 7}`

> 严格口径比默认**更快**，因为它提前关闭了 2187 个班次，省下了后续寻路与排班；这不是可依赖的收益。

> **基线本身已超 8 s 内部预算，与本功能无关**：把固定管制逻辑整体关闭后，同一计划仍为 12.61 s，且班次口径（7760 / 6986 / 774）与原因分布与开启时逐项相同（`_bench_zone_baseline.py` 实测）。对比 0.9.6（Beta） 证据（`docs/evaluation-v1.3/performance.json`：2.34—2.94 s / 2910 班次），网络规模已增长到 2.67 倍，属遗留项。

### 逐班次穿越记录样例

班次 `CAR-1-01-1-05-0-0`（沈阳 ↔ 本溪）共 2 处：

- 沈阳桃仙国际机场净空保护区域（AIRPORT，APPROVAL_REQUIRED） T+2.78—T+23.83 min，最高 500.0 m AGL；依据：《运输机场净空保护管理办法》《民用机场管理条例》第四十九条
- 沈阳桃仙国际机场净空巡视检查区域（AIRPORT，APPROVAL_REQUIRED） T+7.78—T+7.88 min，最高 500.0 m AGL；依据：各地《机场净空保护管理规定》净空保护相关用语说明第 2 条

说明：以上数字均由本次运行的真实计算得出，未使用估算值。
