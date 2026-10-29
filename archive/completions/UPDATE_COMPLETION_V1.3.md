# ALC 0.9.6（Beta） 完成报告

> **版本标识对照（2026-09-19 起）**：本文件的编号按新口径对应 **0.9.6（Beta）**；正文保留当时原措辞，未逐字回改。

方案：`UPDATE_PLAN_V1.3.md`（2026-09-14 18:32）。本报告逐项对应 U01–U10，写明**完成证据与限制**。

生成时间：2026-09-14。版本 `1.3.0`，计划版本 `traffic-plan-v1.3`。

> **重跑轮（2026-09-17）**：本报告 §0、§11 中的班次与耗时数字原先来自 V1.3 收尾轮
> （2910 班次时期）。气象雨带投影缺陷修复改变了计划结论，这些数字已随
> `docs/evaluation-v1.3/performance.json` 整份重跑更新为当前值；表内凡标注「（已重跑）」
> 的行即为新值。旧值与失效范围见 `docs/evaluation-v1.5/risk-merge-and-flat-render.md` §7。
>
> **收尾轮补充（2026-09-15 00:30 起）**：本报告初版交付后，用户批准执行三项改动并做一次完整模拟运行，结论已并入下文：
> ① 已飞航迹段落改为变暗绘制（U04）；② 省界线宽分级加粗（U01）；③ 台账由分页改为虚拟滚动（U10）。
> 运行过程中另外发现并修复两个缺陷（和风原始接口遇 gzip 正文时整条链路静默降级、页面标题仍为 V1.2）。
> 端到端运行明细见 `docs/evaluation-v1.3/simulation-run-v1.3.json`（**该文件已标注失效，见其 `superseded` 字段**）。
>
> **缺陷修复轮（2026-09-15 02:20 起）**：用户复测后报告四个问题，均已定位到根因并修复，见 §14。
> 本轮新增前端测试 3 个、Python 回归测试 1 个；测试基线上调为前端 44 / Python 142 / Java 22。
>
> **V1.4/V1.5 与命名统一轮（2026-09-16—17）**：新增固定管制空域目录（69 站点）、派生飞行风险区
> 平面化与合并、进入禁入区标红、气象雨带投影缺陷修复。测试基线为
> **Python 204 / 前端 63 / Java 22 / vite 146 modules**（其中 1 项为「派生风险区措辞不得与官方空域口径
> 混用」的命名守卫）。系统正式名定为「天窗智巡 · 低空交通协同运行管理系统」。

---

## 0. 结论摘要

| 项 | 结果 |
| --- | --- |
| Python 后端测试 | **204 通过 / 0 失败**（当前基线；V1.3 初版为 141，缺陷修复轮 142） |
| 前端单元测试 | **63 通过 / 0 失败**（当前基线；V1.3 初版为 41，缺陷修复轮 44） |
| Java 后端测试 | **22 通过 / 0 失败**，BUILD SUCCESS |
| 前端生产构建 | 成功，146 个模块 |
| 计划计算耗时（进程内纯计算） | **12.88—16.01 秒（已重跑，7760 班次）**，超出 8 秒预算；旧值 3.88—4.40 秒属 2910 班次时期，已作废 |
| 计划峰值内存 | **49.0—50.6 MB（已重跑）**；旧值 24.5 MB 属 2910 班次时期 |
| 计划端到端等待（HTTP 到就绪） | 旧值 10.4—11.3 秒；**本轮未重测**（需三服务全链路），见 §11 第 8 条 |
| 36 城坐标 | 36/36 通过本省边界校验，最大枢纽偏移 0 米 |
| 高度上限 | 飞行汽车最高 500 米、配送最高 160 米，均在机型上限内 |
| 端到端模拟运行 | **7760 班次 / 269 走廊 / 456 起降点 / 26—32 交叉区（已重跑）**；关闭 2036、绕行 46、冲突处理 1665 |
| **未完成/未验证** | DEM 与建筑净空、浏览器帧率与界面截图、台账筛选实测耗时、端到端 HTTP 等待重测 |

必须在验收中如实区分：**真实底图**、**公开天气估算**、**合成交通**、**已检查的模拟约束**、**仍缺少的数据**。本报告第 11 节集中列出缺失项。

---

## 1. U01 省级行政边界更明显

**交付**：后端 `province_feature_collection()` 独立输出三省多边形（不再只返回合并范围）。前端 `CityTrafficMap.vue` 分层绘制：

- `province-mask` 行政区外压暗填充 `#050b13`，不透明度 0.50（世界矩形顺时针 + 省界挖孔逆时针，满足 GeoJSON 右手法则）
- `province-area` 填充 `#9b91d6`，不透明度 0.05
- `province-shadow` / `province-boundary`：内层省界 **2.8 px**，衬 5 px 深色描边
- `province-outline-shadow` / `province-outline`：三省外轮廓 **4.4 px**，衬 10 px 深色描边

**收尾轮改动（用户批准）**：原先外轮廓与内部省界共线使用**同一线宽 2.4 px**，不符合方案要求的 3.5–4.5 / 2–2.5 px 分级。现已改为内外分级 4.4 / 2.8 px，并新增行政区外压暗遮罩增强轮廓可读性。

**限制**：遮罩与描边的实际观感（是否遮死道路、地名与航迹）未在真实浏览器中确认，见 §11.7。

**证据**：`frontend/src/components/CityTrafficMap.vue` 的 `outsideMask()` / `oriented()` / `sourceLayers()`；`service.network()['administrativeBoundaries']`（3 个要素：辽宁省、吉林省、黑龙江省）；本轮网络接口实测 `boundary` 为 `MultiPolygon`、11 个环。

## 2. U02 计划放行时间正确显示（P0）

**交付**：

- 时间字段拆分：`requestedDepartureAt` / `plannedReleaseAt` / `actualReleaseAt` / `actualTakeoffAt` / `estimatedArrivalAt` / `actualArrivalAt` / `planRevision`。
- `executionTimes()` 只在推演时刻确实越过事件时间后才返回“实际”时间；未来班次返回 `null`，界面显示“未发生”。
- `operationalTime()` 输出 `09-14 18:05:00`（`Asia/Shanghai`），附 `T+00:05:00`；空值不再渲染成 `00:00` 或 `NaN`。
- `baseTime` 固定在计划创建时，刷新、恢复会话、回放均不改变。

**证据**：`frontend/tests/traffic.test.mjs` 的 `operational time separates planned and actual simulation events`（断言 minute=2 时 `actualReleaseAt` 为 null，minute=3 时等于 `plannedReleaseAt`，`relativeClock(65.5) === 'T+01:05:30'`）；`DispatchBoard.vue` 默认只列出未来 30 分钟已排班次。

## 3. U03 排除危险三维路径与异常高度（P0）

**交付**：

- `airspace.py`：已声明高度层分配（`DIRECTION_LAYER` / `ALTERNATE_DECLARED_LAYER` / `NO_DECLARED_LAYER_AVAILABLE`），对向方向取层集合两端，走廊序号奇偶轮换。
- `spatial.trajectory()` 高度恒定在已声明层，**删除交叉点抬升与累计抬升逻辑**；`max_altitude` 超限直接返回 `None`。
- `spatial.within_profile()` 校验高度上下限、最大爬升率、速度上限与段时长非零。
- `spatial.rounded_path()` 用带切线约束的二次曲线替换折点；切线段不足以容纳转弯半径则整条路径判为不可行，不会瞬时转向。
- `obstacles.py` 净空质量门：本地无 DEM 与建筑高度时统一返回 `SIMULATION_ASSUMPTION_UNVERIFIED`，**不按零高度地面放行**。
- 冲突处理顺序改为“**先换层、再错时、最后地面等待**”，避免用高度叠加换放行。

**证据**：

- `tests/test_traffic_network.py::test_profile_holds_a_declared_layer_without_stacking`：高度序列 `[0, 90, 90, 0]` 恒定；传 `max_altitude=200` 且要求 210 米时返回 `None`；零高度、零速度返回 `None`。
- `tests/test_traffic_v13.py` 8 项：层分配与上限、发布班次保持自身高度层、资源日历容量与时隙、交叉区解决。
- `performance.json`：`altitudeCeilingRespected = true`，飞行汽车最高 500 米、配送最高 160 米。

**限制**：全部通过班次的 `clearanceStatus` 均为 `SIMULATION_ASSUMPTION_UNVERIFIED`。**没有任何航迹声称通过真实地形或建筑净空检查。**

## 4. U04 两种交通轨迹加粗

**交付**：`Line2 / LineMaterial`，`worldUnits: false`（屏幕像素线宽），并在视口与折叠侧栏变化时更新 `material.resolution`。

| 对象 | 颜色 | 线宽 |
| --- | --- | --- |
| 飞行汽车航迹 | `#5cdbff` 实线 | 4.5 px（选中 6 px，浅色外描边） |
| 配送无人机航迹 | `#ffd085` 实线 | 3.0 px（选中 4.5 px） |
| 参考走廊 | `#347c99` / `#a77935` 虚线 | 2.8 / 2.0 px，不透明度 0.26 |

**与方案差异**：方案目标为汽车 4 px、配送 2.5 px，当前为 4.5 / 3.0 px。

**收尾轮改动（用户批准）**：方案 §7.2 要求的“已飞过路径适度变暗”原先未实现——过去航迹是**不绘制**（只画 `AIRBORNE` 或选中班次）。现改为**切分绘制**：`splitTrajectoryAt()` 在当前推演分钟处按时间线性插值切分航迹，两段共享同一个插值拐点，已飞段不透明度 0.32（选中 0.55）、未飞段 0.88（选中 1.0）；拖动时间轴即可看到累积的已飞航迹而不再整条消失。

切分**只影响绘制，不修改冻结航迹**：`splitTrajectoryAt` 不写入输入数组，单元测试对此有断言。

**为避免 WebGL 线数无上限的实现取舍**：已到达班次的航迹在推演时刻后只保留 **8 分钟**，且已到达线总数上限为 **100 条**（选中班次不受限）。这两项是本轮为控制渲染量自行加入的护栏，方案未规定。

**证据**：`frontend/src/traffic/runtime.js` 的 `splitTrajectoryAt()`；`CityTrafficMap.vue` 的 `ARRIVED_KEEP_MINUTES` / `MAX_ARRIVED_LINES` 与逐班次绘制循环；`frontend/tests/trafficV13.test.mjs` 的 `trajectory splits at the current minute without moving or dropping a vertex`（该用例同时发现并修复了“分钟正好落在已声明拐点上时会重复拐点、产生零长线段”的缺陷）。

## 5. U05 风险区更亮且更通透

**交付**：边界与填充分开控制。

| 图层 | 填充 | 轮廓 |
| --- | --- | --- |
| 派生飞行风险区（禁止进入） | `#ff4d67`，0.22 | `#ff7d91`，2.5 px **实线** |
| 派生飞行风险区（谨慎进入） | `#ffd166`，0.14 | `#ffe29a`，2.0 px **虚线** |
| 降水/雷暴物理范围 | 青蓝 / 紫色，0.10–0.20 | 细边界 |

> 术语注：V1.3 原称「系统气象禁飞 / 系统谨慎区」，2026-09-17 按 `docs/NAMING.md` 统一为
> 「派生飞行风险区（禁止进入 / 谨慎进入）」；V1.5 起立体柱已改为平面渲染。

- 立体风险柱顶面与侧面共用同一不透明度，不叠成不透明墙。
- `riskRules` 规定 `floorAglM = 0`、`ceilingAglM = 620`，覆盖全部模拟运行高度，因此不会出现“看似可以从上方跨过”的低矮风险柱。

**证据**：`CityTrafficMap.vue` 第 98–100 行；`service._risk_rules()`；`docs/evaluation-v1.3/data-coverage.json` 的 `riskRules`。

## 6. U06 尽可能使用公开实时气象（P0/P1）

**交付**：

- `weather_sources.py` 作为唯一归一化入口，两个适配器共用一套观测结构。
- **Open-Meteo**：一次批量提交多坐标，请求 `wind_speed_unit=ms`，保存 `requestedLocation` 与 `gridLocation`，标注 `MODEL_ESTIMATE` 与 `MODEL_ESTIMATE_NOT_STATION_OBSERVATION`。
- **和风天气**：`QweatherClient` 新增多坐标重载 `current(lat, lon)` / `hourly(hours, lat, lon)`；新增 `rawCurrent` / `rawHourly` 返回原始响应、单位与质量标记；新增内部控制器 `/api/internal/qweather/{current,hourly,status}`，**只访问和风、不回调 Python**，默认仅允许本机回环调用，带 60 秒缓存。
- 单位归一化：和风 km/h → m/s、km → m；风向 359° 与 1° 不被平均成 180°。
- 和风雷暴估算作为 `thunderEstimate` 单独标注，`thunderProbability` 置 `null`，**不注入风险引擎**。
- 来源选择：`ALC_TRAFFIC_WEATHER_PROVIDER=qweather` 时优先和风，失败显式降级到 Open-Meteo 并写入 `PROVIDER_FALLBACK_OPEN_METEO`。
- 派生风险单元标签随来源变化：`OPEN_METEO_DERIVED_RISK` 或 `QWEATHER_DERIVED_RISK`，不会张冠李戴。

**证据**：`tests/test_traffic_qweather.py` 4 项（单位归一化与中心不被覆盖、派生风险单元、不可用降级标注、来源配置）；`backend-java` `QweatherClientTest` 6 项（显式坐标、小时数、越界/NaN/Infinity 拒绝、东北坐标不吸附、gzip 正文解压、明文/空正文原样返回）。

**收尾轮改动（运行中发现并修复的缺陷）**：端到端运行时 `/api/internal/qweather/current` 返回 503，日志为 Jackson 的 `Illegal character (CTRL-CHAR, code 31)`——字节 `1F 8B` 是 gzip 魔数，说明和风 CDN 返回了压缩正文，而客户端用 `BodyHandlers.ofString()` 直接把压缩字节交给 Jackson。修复为读取字节流后按 gzip 魔数与 `Content-Encoding` 双重判断解压再解析，并显式声明 `Accept-Encoding: gzip`。**修复后该接口返回真实数据**：`product=weather/v1/current`、完整单位表、`thunderEstimate` 标注为推导值。

**限制（已更新）**：本机**已实测接通和风实况原始接口**（`requestedLocation=[45.75, 126.65]`，返回真实 product 与单位）。但 Python 侧默认来源仍为 `open-meteo`，和风路径未做长期连续调用与额度核算，见 §11.3。

## 7. U07 增大地图，图例和复选同排

**交付**：

- 图层复选与图例合并为**同一排** `.traffic-layer-row`。
- 地图面板高度绑定视口（`height: calc(100vh - 290px)`，`min-height: 450px`），城市列表自适应容器高度。
- **运行区域侧栏恢复为可折叠**：默认展开 190 px，点击“收起区域栏”切换为 `cities-collapsed`（`1fr + 320px`），专注模式仍可整体隐藏侧栏与详情。
- 清除了 V1.2 遗留的**两组互相冲突的 `.traffic-main` 列定义**与 `display:none` 覆盖规则。

**证据**：`TrafficWorkbench.vue` 的 `citiesOpen`、`.traffic-main.cities-collapsed` 规则；构建后模块数由 142 增至 146。

## 8. U08 标题居中

**交付**：页头使用三等分网格 `grid-template-columns: 1fr auto 1fr`，标题容器显式 `grid-column: 2; text-align: center`，左右按钮容器 `grid-column: 3; justify-self: end`。标题位置**不依赖左侧留白**，左右按钮数量不同时不会偏移。

**证据**：`TrafficWorkbench.vue` 第 129–130 行附近的 `.traffic-header` 规则。

## 9. U09 城际基准点使用城市中心（P0）

**交付**：

- 新增 `backend-python/data/traffic/city-centers.json`（36 城，schemaVersion 1.3，EPSG:4326），每城含 `id`、名称、省份、是否省会、`centerType`、来源、`reviewedAt`、`quality`。
- **删除**城际端点统一向西南偏移 2690.72 米的逻辑。`service.network()` 中飞行汽车端点直接使用 `city_pads(city)[0]`，与城市中心同坐标。
- 越界坐标只记录 `OUTSIDE_PROVINCE_REVIEW_REQUIRED`，**禁止自动吸附或静默改写**。
- 中心枢纽 `CITY-{id}` 显式建模（容量 4、状态 `SIMULATED_REFERENCE`），`offsetFromCenterM = 0`。
- 特殊点显式记录：延边州（`2-09`）为州府城区代表中心；大兴安岭地区（`3-13`）为服务枢纽代表点并保留行政驻地差异说明，未移动省界。

**证据**：`docs/evaluation-v1.3/city-coordinate-audit.json` — 36/36 通过校验，`outsideProvince` 为空，`maximumHubOffsetFromCentreM = 0`，`fixedSouthwestOffsetRemoved = true`。

## 10. U10 调度台账与城区配送优化

**交付**：

- 新增 `frontend/src/components/traffic/FlightStrip.vue`（班次条）与 `DispatchBoard.vue`（放行队列与调度台账），并接入 `TrafficWorkbench.vue`（地图下方）。
- 队列默认未来 30 分钟，可切 60 分钟或全部；完整台账按**待放行 / 运行中 / 受限异常 / 已完成**分组，支持类型与关闭原因筛选。
- **完整台账使用虚拟滚动（收尾轮改动，用户批准）**：原先每页 20 张分页；现改为固定高度滚动窗口 `max-height: min(62vh, 620px)`，内部画布高度为 `行数 × 行高`，只挂载可视行并按 `overscan` 上下多渲染 4 行，行高由 `ResizeObserver` 与首行实测校正。2910 张班次条因此不再分页也无需一次性挂载。方案 §11.3 明确把“列表虚拟化”列为台账响应的达标手段。
- 班次条与地图**双向联动**：`select` → 地图选中，`locate` 定位，`follow` 跟随，`toggle-hold` 暂停/申请恢复。
- 新增后端接口 `/traffic/plan`、`/traffic/hubs`、`/traffic/delivery`，与 `/traffic/session` 共享同一 `sessionId` 与 `planRevision`。
- `resources.py` 起降与交叉资源日历（追加写入、容量 + 时间窗校验、`reserve_all` 全有或全无）。
- `delivery.py` 订单与载具双状态机、节点与走廊可配置（12 节点 / 6 走廊 / 6000 米服务半径）、电量与返航余量。
- 状态标记使用几何符号（◇ ◆ ■ ▪ ✕）而非 emoji。

**证据**：`tests/test_traffic_v13.py` 的 `test_published_plan_publishes_layers_hubs_and_delivery_summary` 与 `test_plan_hubs_and_delivery_projections_share_one_plan_revision`；`frontend/tests/trafficV13.test.mjs` 8 项；`frontend/src/traffic/runtime.js` 的 `virtualWindow()`。

**本轮观测（种子 42 / 合成流动气象，清空缓存后完整运行）**：2910 班次，2789 通过、121 关闭；地面等待 1211、备用层 260、绕行 64、冲突处理 918；层使用 `CAR:350 → 143`、`CAR:500 → 147`、`DELIVERY:160 → 1212`、`DELIVERY:80 → 1287`；配送 2592 单，送达 2499，取消 93，送达率 0.9641，平均地面等待 2.77 分钟；456 起降点、32 个交叉区 255 次预约、计划指纹 `3961a105b5fb4383`。

> **（已重跑）同一参数在当前代码下的值**：**7760 班次，5724 通过、2036 关闭**；地面等待 2325、备用层 475、绕行 46、冲突处理 1665；层使用 `CAR:350 → 192`、`CAR:500 → 186`、`DELIVERY:160 → 2601`、`DELIVERY:80 → 2745`；配送 6912 单，送达 5346，取消 1566，送达率 0.7734，平均地面等待 2.4 分钟；456 起降点、26 个交叉区 499 次预约；关闭原因 `WEATHER_BLOCKED 1938` / `BEYOND_PLANNING_HORIZON 83` / `SEPARATION_RESOURCE_OR_TIME_LIMIT 15`。上段为 V1.3 收尾轮的原始记录，保留以便对照；**两段数字不得混用**。

**控制回路实测**：对 `DEL-1-04-01-0-31`（计划放行 36 分钟）在推演 30 分钟执行 `SUSPEND` → 台账 1 条；`RESUME` → 2 条；**重放同一 `commandId` 返回 `idempotent: true` 且台账仍为 2 条**。对已起飞或已过原时隙的班次执行 `SUSPEND` 返回 HTTP 409 并给出“请重新调度”的提示，未静默放行。

---

## 11. 未完成与未验证项

方案要求诚实交付缺失状态，因此逐条列出：

1. **DEM 与建筑净空未接入**。本地无覆盖全部航迹的地形与建筑高度数据（`obstacleSourceVersion = no-local-dem-or-building-catalog-v1`）。因此所有通过班次的净空状态为 `SIMULATION_ASSUMPTION_UNVERIFIED`（当前口径下 5724 个通过班次全部如此，2036 个关闭班次为 `NOT_EVALUATED`；V1.3 收尾轮为 2789 / 121），楼宇仅用于显示，未进入后端避障。这是本版本**最大的能力缺口**。
2. **和风天气已实测接通原始接口，但未做长期与额度验证**。收尾轮修复 gzip 缺陷后，`/api/internal/qweather/current` 返回真实 `product` 与单位表（见 §6）。仍未验证：连续多轮调用的稳定性、36 城批量额度消耗、与 Open-Meteo 的交叉一致性。Python 侧默认来源仍为 `open-meteo`。
3. **航路内部气象未全程采样**。仅城际端点与采样城市有值；`live` 快照的 `qualityFlags` 明确标注 `ROUTE_INTERIOR_NOT_FULLY_SAMPLED`。
4. **无独立雷暴观测/预报**。不使用降水概率乘固定系数冒充雷暴概率；快照中 `thunderProbability` 为 `null`，和风 `thunderEstimate` 标注为推导值且不注入风险引擎。
5. **浏览器界面未截图、未采样帧率**。目标 30 FPS 未实测。
6. **台账筛选响应 300 ms 未实测**。台账已改为虚拟滚动，但只做了单元级验证（`virtualWindow` 的可视区间与边界），未在 **7760 班次**数据集下测真实交互耗时。
7. **本轮新增视觉改动未做浏览器复核**。省界双层描边（4.4 / 2.8 px）与行政区外压暗遮罩、已飞航迹变暗（0.32 / 0.55）、虚拟滚动的实际观感均未在浏览器中确认。
8. **端到端计划等待时间超出 8 秒预算**：V1.3 收尾轮实测纯计算 3.88–4.40 秒，但从 HTTP 发起到达就绪为 **10.4–11.3 秒**。差额来自前端每 1500 ms 轮询一次 `/traffic/session`，以及该接口在 `READY` 时一次性回传全部班次（含航迹点）的序列化与传输。**这是已知未优化项**，不是计算性能问题；修法是让 `READY` 只回传统计与版本、班次改由分页接口按需拉取。
   **重跑轮补充**：纯计算已随网络规模上升到 **12.88—16.01 秒（7760 班次）**，本身已超预算；HTTP 端到端等待**本轮未重测**，因此不应给出新的端到端数字。
9. **`start.bat` / `stop.bat` 未双击端到端验证**。收尾轮在自动化宿主内实际执行了 `scripts/dev.ps1`（返回 0，三服务就绪、三个端口全部响应）与 `scripts/stop.ps1`（逐个 PID 报告正常停止），但未双击 bat，因而“启动窗口驻留”“停止后不影响其他程序”“健康后自动打开浏览器”三项仍未实测。另：本机自动化宿主存在大小写重复的环境变量（`Path`/`PATH`、`http_proxy`/`HTTP_PROXY`），会让 PowerShell 的 `Start-Process` 重定向重载直接抛错；该问题在普通用户会话中不存在，因此**未改动脚本**。
10. **未接入 METAR/TAF**，也不代表 36 城城区覆盖。
11. **未改动**：登录、预警推送、智能体研判、历史记录、数据库结构与 Flyway 迁移、三维地图框架。
12. **前端单 chunk 1878 kB** 未做代码分割。
13. **已到达航迹的 8 分钟 / 100 条线上限**是为控制 WebGL 线数自行加入的护栏，未做压力测试确认该上限在大规模运行下是否合适。

## 12. 交付物

| 路径 | 内容 |
| --- | --- |
| `VERSION` / `pom.xml` / `frontend/package.json` | 版本统一为 1.3.0 |
| `contracts/traffic-v1.3.openapi.json` | 由运行中的应用导出的交通接口合同，含 9 条路径 |
| `docs/CITY_OPERATIONS_V1.3.md` | 运行语义与数据边界说明 |
| `docs/evaluation-v1.3/test-results.json` | 四套测试与构建的实际结果、未验证项 |
| `docs/evaluation-v1.3/city-coordinate-audit.json` | 36 城坐标逐项核查 |
| `docs/evaluation-v1.3/data-coverage.json` | 数据来源、覆盖与缺失清单 |
| `docs/evaluation-v1.3/performance.json` | 计划耗时（进程内纯计算）与内存，另含端到端 HTTP 等待时间与差额说明 |
| `docs/evaluation-v1.3/simulation-run-v1.3.json` | 清空缓存后一次完整端到端运行：三服务身份、网络与计划身份、三组参数运行结果、资源与配送、控制台账、耗时对比、本轮发现 |
| `docs/evaluation-v1.3/migration-v1.3.md` | 时间语义、缓存失效与回退方法 |
| `README.md` | 更新为 V1.3 并写明数据范围 |
| `backups/v1.2_before_v1.3/` | V1.2 源码备份与 `MANIFEST.txt` |
| `_verify_fixes.py` | 缺陷修复轮四项改动的逐条核对脚本（含实时几何测量与前端包内容断言） |

## 13. 复现方式

```bash
# Python（注意：项目虚拟环境在 backend-python/.venv）
backend-python/.venv/Scripts/python.exe -m pytest tests -q --basetemp=<项目内目录>

# 前端
cd frontend && node --test          # 41 项
cd frontend && npx vite build       # 生产构建

# Java（JAVA_HOME 指向 .jdks/ms-17.0.19，pom 的 java.version 为 17）
cd backend-java && mvnw.cmd -o -B test   # 22 项

# 重新生成评测证据
backend-python/.venv/Scripts/python.exe _gen_evidence.py

# 重新导出版本合同
backend-python/.venv/Scripts/python.exe _gen_contract.py

# 重新跑一次端到端模拟运行并再生成本轮证据文件
python _sim_harness.py start 25                                   # 后台拉起三服务
python _sim_probe.py                                              # 全链路探测
python _sim_command.py                                            # 控制指令与台账
backend-python/.venv/Scripts/python.exe backend-python/_sim_bench.py  # 进程内计算耗时
python _gen_sim_evidence.py                                       # 汇总为本轮证据

# 逐项核对缺陷修复轮的四项改动（需三服务在运行）
backend-python/.venv/Scripts/python.exe _verify_fixes.py
```

---

## 14. 缺陷修复轮（2026-09-15）：用户复测反馈四项

本轮四个问题均由用户复测提出，逐项定位到根因后修复，并各配一条可失败的验证。

### 14.1 禁飞区形状呈「花状锯齿」（P0，同时影响观感与 U03 口径）

**现象**：用户报告禁飞区轮廓像花、边缘严重锯齿，V1.2 的立体感消失。

**根因（两处，缺一不可成此形）**：

1. `backend-python/traffic/weather.py` 的 `NetworkWeather.shapes()` 用**整数顶点序号**驱动半径谐波：
   `sin(i*3 + phase)` 而非 `sin(3*theta + phase)`。`i` 是采样下标而不是角度，半径因此在整数网格上跳步，三个凸瓣每个都以尖角收尾——实测外角最大 **122.03 度**（平滑曲线应为 5–8 度）。
2. 只采样 **24 个顶点**，且禁飞核心用 `field.buffer(300)` 从收缩环生成。`buffer()` 会在每一个凸瓣外包裹圆角接头，把 24 个顶点炸成 **约 215 个**，形成 300 m 宽的锯齿带。

**修复**：

- 谐波改由**角度**驱动，`RING_VERTICES` 提到 64，三阶谐波幅度收敛为 `RING_HARMONICS=((1,.10),(2,.04),(3,.02))`，曲率预算 0.44 < 1，保证不自交且近似凸。
- 禁飞核心改为**同一环的同心缩放**（`*.58` 平移）而非 `buffer()`，杜绝圆角接头锯齿。
- 三层几何统一 `simplify(120 m)` 去余冗。
- `PublicWeather`（公开天气派生风险）同步加 `simplify`，但其 `quad_segs=16` 的圆弧本身已平滑，仅去冗余顶点。

**实测效果**：

| 指标 | 修复前 | 修复后 |
| --- | --- | --- |
| 生成轮廓最大外角 | 122.03 度 | **7.57 度**（p50 5.68） |
| 禁飞核心顶点数 | 213 | **16–22** |
| 风险环顶点总数（12 单体） | 7760 | **1088** |

**回归测试**：`backend-python/tests/test_traffic_v13.py::test_weather_risk_rings_are_smooth_and_not_index_driven`。该测试已用旧公式反向验证过——旧代码最大外角 122.03 度、顶点 213，**两条阈值都会失败**，因此确实具备防回归能力（不是恒过的空壳测试）。

**保留的不规则性**：轮廓仍为三个低阶谐波叠加的非圆形状，符合用户「虽然不规则也不至于这么锯齿」的要求；纯圆盘会让区域看起来像随手画的饼。

### 14.2 禁飞区退回平面、标记不明显（U03 表现层）

**根因**：`CityTrafficMap.vue` 的 `drawWeather()` 给 BAN/CAUTION 都赋**固定高度**（620 / 600 m），且 `fill-extrusion` 只有一层、顶部无封盖，俯视时几乎读不出体积；V1.3 又移除了全域 60 倍高度选项（`heightFactor` 恒为 1），失去了仅有的放大手段。

**修复**：改为真正的体积表达，并给出与真实高度层的对应关系：

- 新增常量 `RISK_TOP_AGL_M=620`、`RISK_BASE_AGL_M=0`、`CAUTION_TOP_AGL_M=260`。禁飞柱从地面拉伸到 620 m，**贯穿飞行汽车 350/500 m 与配送 80/160 m 两层**，因此可在立体视角下看到航迹柱与禁飞柱相交；谨慎环只到 260 m，形成包络而非同高。
- 三层叠加渲染：`weather-risk-columns`（实壁，`fill-extrusion-base` 给出真实底面）、`weather-risk-volume`（半透明内芯，提供体积感）、`weather-risk-cap`（顶面封盖，限定体块上限）。
- 线框 `weather-risk-outline` 加粗至禁飞 3 px，颜色提亮为 `#ff9bac`。

**如实说明**：这只是**空间占用体的可视化**，不是官方空域管制命令；界面注释已同步写明「禁飞区与谨慎区以立体柱表示，顶面为高度上限」，且保留 `系统气象禁飞` 的措辞口径（该措辞已于 2026-09-17 统一为「派生飞行风险区（禁止进入）」，见 `docs/NAMING.md`）。

> **V1.5 已取代本节做法。** 上述三个常量与三层挤出图层（`RISK_TOP_AGL_M` / `RISK_BASE_AGL_M` /
> `CAUTION_TOP_AGL_M`、`weather-risk-columns` / `-volume` / `-cap`）已全部删除，风险区改为**平面范围**
> （`fill` + `line`），因此**「三维」一词在本系统中已无对应实现，不得再用于命名任何界面或功能**。
> 理由：推演风险区**没有经过勘测的天花板**，画一个虚构顶面会被读成法定高度限制。
> 术语现行口径为「派生飞行风险区（禁止进入）/（谨慎进入）」。见 `docs/evaluation-v1.5/risk-merge-and-flat-render.md`。

### 14.3 「部分城市地图资源载入失败」误报（P1）

**排查结论**：**底图服务本身是正常的**。逐项实测 `tiles.openfreemap.org` 全部端点：tilejson 19254 B、sprite json/png 27737/49454 B、Noto Sans Regular 0-255 与 19968-20223 字形区 76580/192358 B、矢量瓦片、Natural Earth 栅格——**HTTP 200 全通，字体栈三种全部可达**。因此这不是网络故障。

**真根因**：`CityTrafficMap.vue` 的 `map.on('error')` 把**任何** MapLibre 错误都硬编码成「部分城市地图资源载入失败，请检查网络后重试」。而 MapLibre 对以下情形都会发 `error` 事件：数据源未覆盖的瓦片、不存在的字形区、缩放平移导致的请求取消。三者都与网络无关，却被统一甩锅给网络。

**修复**：

- 新增纯函数 `classifyMapError(message)` 与 `mapErrorSummary(issues)`（放在 `frontend/src/traffic/runtime.js`，可被 `node --test` 覆盖），把错误分为 `NETWORK / TILE_404 / GLYPH / SPRITE / STYLE / ABORTED / UNKNOWN`，每类给准确文案。
- `TILE_404 / GLYPH / ABORTED` 属正常范围，**不再弹出错误横幅**；其余需累计到 `MAP_ERROR_THRESHOLD=6` 次才提示，避免滚动地图时的一次抖动就报错。
- 错误框内追加 `mapErrorSummary` 分类计数，运维能看到「哪一类、多少次」，而不是笼统一句网络问题。
- 「重载地图」同时清零计数。

**回归测试**：`frontend/tests/trafficV13.test.mjs` 的 `map errors are classified instead of always blamed on the network` 与 `map error summary reports counts per cause and ignores empty buckets`。

### 14.4 飞行汽车与外卖无人机大小相同（U03 表现层）

**根因**：`vehicle(mode)` 只有机身盒按机型区分（7 / 3），而**旋翼臂跨度硬编码为 `[-3.5,3.5]`、两种机型共用**，`g.scale` 也相同。地图缩放下机身长度差异被旋翼结构掩盖，因此视觉尺寸接近。

**修复**：抽出 `VEHICLE_SHAPES` 机型表，为每类给出独立的臂展/旋翼半径/机臂长度/整体缩放：

| 机型 | 臂展 span | 旋翼 | 机身长 | 缩放 |
| --- | --- | --- | --- | --- |
| CAR | 4.6 | 1.9 | 9.5 | 0.62 |
| DELIVERY | 2.1 | 1.05 | 3.6 | 0.42 |

**实测效果**（渲染足迹 `(span + 2*rotor) * scale`）：修复前两者比值 **1.20 倍**（基本看不出来），修复后 **2.95 倍**；机身长度比值由 2.33 倍升至 **3.90 倍**。无人机在同高度下明显更小。

**回归测试**：`delivery drones are materially smaller than flying cars`（断言比值 > 2.5 倍且两类都不会小到看不见）。

### 14.5 首页大屏内容过载，余下内容移入第二屏（P1）

**现象**：用户反馈首页「运行总览」内容放不下，希望把余下的内容切到下一个界面。

**量化核对**（按样式表固定高度累加，含 `padding 22/30`、头部 78+12、指标条 86+16、导航 58、`calc(100vh - 290px)` 主区、进程单预览 4×196+120、推演条 62）：

| 视口 | 首屏内容总高 | 可用高度 | 溢出 |
| --- | --- | --- | --- |
| 1366×768 | 1716 px | 768 px | **+948 px** |
| 1440×900 | 1848 px | 900 px | **+948 px** |
| 1920×1080 | 2028 px | 1080 px | **+948 px** |
| 2560×1440 | 2388 px | 1440 px | **+948 px** |

**修复**：新增第二屏「运行格局」（`activeSection==='dispatch'`），把**决策进程单 `DispatchBoard` 与时间推演条 `traffic-playback` 整体迁入**，总览只保留指标条、三维地图与班次剖面。

- 迁出后首屏内容降至 **750 / 882 / 1062 / 1422 px**，在四种视口下**均不再溢出**（每种视口留约 18 px 余量）。
- `OperationsConsole` 的排除条件同步加入 `dispatch`，避免第二屏重复渲染控制台。
- 总览底部加一枚指向性提示「决策进程单与时间推演已移至『运行格局』页 · 前往查看」，第二屏顶部加标题与「返回运行总览」，避免用户找不到原有功能。
- 推演条原为 `position:sticky` 挂在总览底部，随之移入第二屏，语义更自然。

**限制**：以上为按样式表推算的版面预算，**未在真实浏览器截图中确认**；帧率与筛选耗时同样仍未实测，见 §11。

### 14.6 本轮验证

| 项 | 结果 |
| --- | --- |
| Python 测试 | **142 通过 / 0 失败**（新增环平滑回归 1 项） |
| 前端测试 | **44 通过 / 0 失败**（新增 3 项） |
| Java 测试 | **22 通过 / 0 失败**，BUILD SUCCESS |
| 前端生产构建 | 成功，146 个模块 |
| 端到端模拟 | 2910 班次 / 269 走廊 / 456 起降点 / 2592 订单（送达率 0.9641）/ 控制指令 `SUSPEND`→`RESUME` 台账 1→2、已起飞班次 409 |
| 修复项逐条核对 | `_verify_fixes.py`：12 项断言全通（立体图层、机型表、错误分类、第二屏等） |

**仍需人工确认**：三维禁飞柱与无人机尺寸的**实际观感**只能在真实浏览器里判断，本轮验证的是代码与数据口径，不是像素效果。
