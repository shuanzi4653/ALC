# 架构决策记录（ADR）

本文件记录天窗智巡已冻结的实现口径。每条决策包含：结论、实现位置、完成门槛、确认状态。
**未经业务确认的演示参数不得对外宣称为生产标准。**

规则版本字段：`ruleVersion`，当前值 `v1`，来源 `config/rules-v1.json`。

---

## DEC-01 硬禁飞语义

- **决策**：任一要素命中禁飞阈值时，直接判定 `BAN`，不再只做扣分。
- **实现**：`SfiEngine.evaluate()` → `hardBan = rules.hardBanEnabled() && 任一 Check.banned`；开关与阈值来自 `config/rules-v1.json`（`hardBanEnabled`）。
- **完成门槛**：单项降水达到 5 mm/h 时最终等级必须为 `BAN`，不得出现 `CAUTION`。
- **状态**：已实现（`SfiEngineTest` 覆盖）；**生产启用前需业务确认阈值与比较符**。

## DEC-02 分数与等级关系

- **决策**：保留原始扣分明细分 `rawSfi`；硬约束命中时对外 `sfi = min(rawSfi, 39)`、`level = BAN`，并附硬约束来源。
- **实现**：`SfiResult(sfi, rawSfi, level, hardBan, ruleVersion, checks)`；`hardBanSfiCap` 来自配置（默认 39）。
- **说明**：39 是按项目 80/60/40 分段提出的产品约定，不得悄悄改写原始扣分明细。
- **状态**：已实现；分段值与 cap 待业务确认。

## DEC-03 实时数据失败处理

- **决策**：prod 下 live 拉取失败**不**自动切换为模拟数据；保留历史快照但标记 `STALE` / `UNAVAILABLE`，不生成新鲜观测。demo 允许显式降级，且必须记录 `effectiveSource=sim` 与 `degraded=true`。
- **实现**：`MonitorService` 的 `configuredMode` / `effectiveSource` / `degraded` / `degradeReason` 分离；`allowSimFallback` 配置开关（`MonitorProperties`）。
- **状态**：已实现（字段与状态齐备）。**待补**：前端对 `STALE` 的显式陈旧提示（当前已展示 `dataStatus` 文案）。

## DEC-04 手动请求并发策略

- **决策**：第一版采用每区域 single-flight；运行中再次请求返回 `409 RUN_IN_PROGRESS`，**不静默返回旧结果当成功**。
- **实现**：`MonitorService.execute()` 使用 `runLock.tryLock()`；`ApiExceptionHandler` 将 `RunBusyException` 映射为 409 + `retryable=true`。定时触发忙时跳过并记日志。
- **状态**：已实现。实测因单轮规则发布耗时极短，未稳定复现 409；建议后续用延迟注入复测。

## DEC-05 无有效观测的表达

- **决策**：无有效观测时 `assessmentStatus=UNDETERMINED`、`level=null`，界面显示灰色「不可判定」。**该状态不是第五种可排序飞行等级**，不得参与现有枚举 ordinal 运算。
- **实现**：当前以 `dataStatus`（`NO_DATA` / `UNKNOWN` / `STALE`）与 `status=WAITING` 表达，`FlightLevel` 保持四级不变。
- **状态**：部分实现。**待补**：`assessmentStatus` 独立字段与前端灰色态；本轮未引入新枚举值以避免风险。

## DEC-06 权限边界

- **决策**：demo 绑定回环地址；prod 使用同源会话登录与 `VIEWER` / `OPERATOR` / `ADMIN` 三级权限。
- **实现**：`server.address=127.0.0.1`、WS `setAllowedOriginPatterns` 限定本机来源、HTTP 关机接口已移除。
- **状态**：回环与危险入口收口已完成；**Spring Security 会话与角色尚未实现**（见 C04 待办）。

## DEC-07 真实空间数据准入

- **决策**：必须提供合法样例、覆盖范围、更新频率、分辨率、坐标系、许可与调用额度后，才启动真实空间图层接入；否则仅交付演示图层且界面持续标注「模拟/示意」。
- **实现**：`LayerDto.isSimulated` + `quality.spatialMeaning=DEMO_SYMBOL`；`LayerService` 全部图层标 `isSimulated=true`。
- **状态**：准入条件未满足，D 阶段未启动（符合预期）。

---

## DEC-08 底图降级必须显式标注（离线底图）

- **决策**：城市底图依赖远端 `tiles.openfreemap.org`。断网时**不白屏**，自动切到随程序内置的
  离线低精度底图；但该降级**必须在界面上可辨识**（橙色徽标 + 常驻提示条 + 「重试在线底图」按钮），
  且通道状态对外可读。
- **实现**：`frontend/src/traffic/runtime.js` 的三态通道
  （`pending` / `online` / `offline`）+ `frontend/src/components/CityTrafficMap.vue` 的
  `offline-basemap-*` 图层与提示条；数据为
  `frontend/src/assets/northeast-offline.json`（由 `china.json` 以 0.01° 容差派生）。
- **判据**：
  1. **三态而非布尔** —— 首块瓦片返回前是 `pending`，因为「在线」与「离线」当时都只是未证实的断言；
  2. **降级需连续 6 次**可取不到瓦片的错误；`GLYPH` / `SPRITE` / `ABORTED` **不计入**；
  3. **计数双向** —— 一次成功即清零并升回在线；
  4. **降级是可用性降级，不是故障**，不触发红色错误横幅。
- **完成门槛**：离线态必须能一眼看出与在线态不同；且离线几何须经独立校验
  （`_verify_offline_basemap.py`：面积比、外接框漂移、环闭合性、顶点数四判据）。
- **状态**：已实现（14 条单测 + SSR 三态差分渲染检查 + 四判据形状校验，全绿）。

## DEC-09 降级与合成一律显式标注（跨模块通则）

- **决策**：凡系统在缺失外部输入时**仍然给出画面或结论**的路径，必须在**界面**与**数据结构**
  两处同时标注来源性质。合成/降级数据不得以实测口径流通。
- **实现**：
  - 虚拟气象 → `provider='SYNTHETIC_RADAR'`、`synthetic:true`、`source='SYNTHETIC_RADAR_CREF'`；
    前端橙底按钮 + 警示条 + 图例改「模拟回波」。
  - 离线底图 → 见 DEC-08。
- **为什么不能省**：`radar_field.derive()` 会在**自己的**输出里硬编码
  `provider:'CMA_DATA_NET'`。上游不打标记，合成帧会被下游读成**国家组网实测**，
  而前端文案写的正是「实测雷达」。
- **推论**：`measured` 模式下实测源失败必须**如实返回失败**（`available:false`），
  **绝不**用合成帧顶替。这是设计决定，不是缺陷。
- **状态**：已实现（单测锁定措辞与来源字段）。

---

## 附：图层语义对照

| kind | 当前（演示） | 真实数据要求 | 单位 |
|---|---|---|---|
| WIND | 作业点风向箭头 + 风速标签 | 观测矢量或 u/v 网格 | m/s（气象来向） |
| PRECIPITATION | 单点数值 + 标「演示」覆盖面 | 带时效降水栅格 | mm/h（非累计） |
| THUNDER_PROBABILITY | 概率符号 / 演示覆盖面 | 合法预报概率网格 | 存 0–1，显示 % |
| LIGHTNING | **不提供**（返回 NO_DATA） | 实际事件坐标与时间 | 事件 |
| RISK_AREA | 明示「示意」多边形 | 区域边界 + 规则输出 | 等级 + ruleVersion |
| ROUTE | 明示「示意航线」 | 任务航线 GeoJSON | lon/lat |

雷暴**概率**、实际**闪电**与官方预警必须分别表达，不得混为同一指标。

---

## 确认记录

| 决策 | 确认人 | 日期 | 备注 |
|---|---|---|---|
| DEC-01 ~ DEC-07 | 待业务确认 | — | 当前为演示口径，已在代码与界面标注 |
| DEC-08 ~ DEC-09 | 已实现（工程口径） | 2026-09-18 | 降级/合成的标注方式为工程硬判据，由单测锁定 |
