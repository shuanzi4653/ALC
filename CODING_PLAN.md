# 天窗智巡：具体编码实施计划

编制日期：2026-09-09  
依据：项目根目录 `OPTIMIZATION_PLAN.md`，以及本次对 Java 编排/规则/预警、Python 接口、Vue 数据接入/地图、构建清单的源码核对。  
状态：待实施。本文只规划编码与验收，不代表修复、运行测试、外部接口验证已经完成。优化方案中的历史实测结果作为设计输入，不作为本次复测结果。

## 1. 目标、范围与实施顺序

首个交付目标：启动后自动产生首轮有效结果；切换模拟剧本有明确反馈；两个客户端同步；天气字段完整；四级风险表现一致；实时故障不会被模拟数据伪装。

第二个交付目标：风、降水、雷暴概率、风险区、航线可以独立显示；每层明确标识来源、时间、单位和数据状态。

第三个交付目标：规则先返回、模型异步补充；运行与预警可追溯；失败可恢复；具备权限、可靠打包与运维能力。

实施顺序：准备 G → 稳定链路 A → 演示图层 B → 可靠性 C → 发布完善 E。真实空间数据 D 在样例、许可和指标明确后独立推进；E 的构建基础从 G 开始。

- 保留 Vue 3、Java 17 / Spring Boot、FastAPI、ECharts、H2，不在本轮拆微服务或开发第三轨 ML。
- 先修数据和状态，再扩展渲染；真实空间图层不由单点天气推演冒充。
- 所有新增路径均为建议目标路径；表格中的“修改”指已经存在的文件。下文 `J/` 代表 `backend-java/src/main/java/com/tianchuang/`，`F/` 代表 `frontend/src/`，`P/` 代表 `backend-python/`，其他路径相对项目根目录。
- 当前共享 store 实际定义于 `F/api.js`，不存在独立 `store.js`；重构时需一起迁移九个面板的导入，不能直接假设已经有独立状态模块。

## 2. 编码前需要冻结的设计

这些是建议实现口径。可先实现接口、测试和配置结构，业务规则未确认时不将演示参数宣称为生产标准。

| 编号 | 决策 | 建议实现 | 影响与完成门槛 |
|---|---|---|---|
| DEC-01 | `banned` 是否强制禁飞 | 明确配置 `hardBanEnabled`；演示按硬约束实现并标记规则版本；生产启用前确认阈值和比较符 | A03 的规则验收与生产发布门槛；不阻塞协议和地图编码 |
| DEC-02 | 分数与等级关系 | 保存原始 `rawSfi`；硬约束命中时对外 `sfi=min(rawSfi,39)`、`level=BAN`，附 `hardBanReasons`；融合等级单独展示 | 39 是按项目 80/60/40 分段提出的产品约定，需与业务共同确认；不得悄悄改写原始扣分明细 |
| DEC-03 | 实时失败 | prod 不切模拟；保留历史快照但标 `STALE/UNAVAILABLE`，不生成新鲜观测；demo 如允许模拟降级必须显式配置 | A02，顶部、地图、预警共用来源状态 |
| DEC-04 | 手动请求并发 | 第一版每区域 single-flight；运行中再次请求返回 409 和当前运行信息，不静默返回旧结果当成功 | A02/A04；暂不实现 latest-wins 队列，降低场景错配风险 |
| DEC-05 | 暂无有效观测 | `assessmentStatus=UNDETERMINED`，`level=null`，灰色“不可判定” | 不是第五种可排序飞行等级，不能进入现有枚举 ordinal 运算 |
| DEC-06 | 权限边界 | demo 绑定回环；prod 使用同源会话登录、VIEWER/OPERATOR/ADMIN 三类权限 | A06 先关闭危险入口；C04 完成正式权限 |
| DEC-07 | 真实空间数据 | 提供合法样例、覆盖范围、更新频率、分辨率、坐标系、许可与调用额度 | D00 未通过时仅交付演示图层，不承诺真实雷暴热力 |

建议将确认后的决策写入 `docs/architecture-decisions.md`，记录确认人、日期和 `ruleVersion`。代码不使用文档中的自然语言替代结构化配置。

## 3. 统一数据契约

### 3.1 Dashboard 与消息排序

新增 `contracts/dashboard-v1.schema.json`、`contracts/ws-v1.schema.json` 和成功/失败/空数据 fixture。REST 返回 Dashboard DTO；WebSocket 的 `payload` 返回同一 DTO，不再返回 JPA 实体或临时拼接 Map。

建议骨架（下列值仅为协议示例）：

```json
{
  "version": 1,
  "regionId": "demo-region",
  "runId": "48ce76f4-02ae-4c21-8d5d-9a3842b9ce17",
  "runSequence": 101,
  "revision": 1,
  "status": "RULE_READY",
  "configuredMode": "sim",
  "effectiveSource": "sim",
  "degraded": false,
  "degradeReason": null,
  "appliedScenario": "wind",
  "obsTime": "2026-09-09T02:00:00Z",
  "ingestedAt": "2026-09-09T02:00:00.100Z",
  "evaluatedAt": "2026-09-09T02:00:00.180Z",
  "updatedAt": "2026-09-09T02:00:00.200Z",
  "dataStatus": "FRESH",
  "snapshot": {},
  "track1": {},
  "track2": {"status": "PENDING", "source": null, "level": null},
  "fusion": {},
  "forecast": [],
  "sfiHistory": [],
  "tracksHistory": [],
  "alerts": [],
  "lastAttempt": {"runId": null, "status": null, "errorCode": null}
}
```

空 `{}` 只为展示结构；schema 中必须补齐类型、必填字段与可空约束。快照至少包含坐标、天气描述、温度、湿度、风速、阵风、风向、降水、能见度、气压、云量、雷暴概率，以及逐字段质量信息。

WebSocket 信封：

```json
{
  "type": "dashboard",
  "version": 1,
  "runId": "48ce76f4-02ae-4c21-8d5d-9a3842b9ce17",
  "payload": {"runSequence": 101, "revision": 2}
}
```

`payload` 在真实消息中为完整 Dashboard。预警采用 `{type:"alert",version:1,eventId,runId,payload}`；不能继续混用顶层 `alert` 与 `payload`。

排序与空值约束：

1. `runId` 是关联标识，UUID 不用于大小排序；`runSequence` 在数据库中按区域单调分配，重启后不归零；同轮轨2补充令 `revision` 增加。
2. 前端仅应用同区域且 `(runSequence,revision)` 更新的结果；POST、GET、WS 全部走同一个 `applyDashboard()`，旧 HTTP 返回也不能覆盖新 WS。
3. 重连先获取全量；订阅期间收到的消息按同一序号规则合并。新浏览器首次加载允许接收当前版本，重复版本只更新独立连接状态。
4. 冷启动 `runId=null`、`snapshot=null`、`status=WAITING`；失败尝试通过 `lastAttempt` 暴露，不篡改最后成功运行的归属和观测时间。
5. 时间保存带时区的 ISO-8601/UTC，前端按 Asia/Shanghai 展示；不再输出字符串 `"null"`。未知值使用 JSON null，不能补零或默认安全值。
6. 观测新鲜度由观测时间和数据源 TTL 决定；模型补全只能更新 `updatedAt`，不能刷新 `obsTime` 或把旧天气变成新天气。

### 3.2 接口清单与兼容迁移

| 接口 | A 阶段 | C 阶段目标 | 错误约束 |
|---|---|---|---|
| `GET /api/dashboard` | DTO v1，全量快照 | 同一已提交运行及其最新 revision | 空数据 200 + WAITING；服务不可用按统一错误响应 |
| `POST /api/sim/switch?scenario=wind` | 保留现有 query 参数；200 返回已提交规则快照 | 不改变调用形状；轨2 PENDING 后通过 WS 补全 | 非法值 400；prod live 模式拒绝模拟切换；忙 409 |
| `POST /api/monitor/run-now` | 成功返回本轮 Dashboard | 规则落库后返回，不等待轨2/渠道 | 忙 409；上游不可用 503；超时 504 |
| `GET /api/layers?regionId=...&runId=...` | B 新增；返回指定运行的图层集合 | D 接真实数据适配器 | 不存在 404；不静默返回另一轮图层 |
| `POST /api/agent/ask` | 保留现有功能 | 限长、鉴权、限流及超时 | 空/过长 400；Python schema 不通过 422；限流 429 |
| `/ws/dashboard` | 同源 WS v1 | 会话鉴权、预警 ACK | 来源或会话非法拒绝握手 |
| `GET /api/config/status` | 配置与实际来源分开 | 配置、健康、新鲜度分别返回 | 不暴露凭据及完整私有地址 |

错误体固定 `{code,message,requestId,runId,retryable}`。message 可直接用于界面，内部异常只在脱敏日志记录。网络断开不等于服务端任务已取消；前端恢复后查询快照确认结果。

迁移采用一次前后端同版本发布：新增 `F/dashboardAdapter.js`，把 v1 DTO 转换为旧面板短期仍使用的 `current/tracks/forecastSfi` 视图；A 阶段完成所有入口切换。该适配层只在前端存在，C 结束前逐步移除，避免数据库和协议维护两套真值。

### 3.3 图层契约

新增 `contracts/layer-v1.schema.json`。每层包含 `id,kind,regionId,runId,source,isSimulated,validTime,expiresAt,crs,units,bbox,geometry,data,quality,status,errorCode`。

| kind | B 阶段表现 | D 阶段数据 | 单位/语义 |
|---|---|---|---|
| WIND | 作业点风向箭头及风速标签 | 观测矢量或 u/v 网格 | m/s，风向为气象来向 |
| PRECIPITATION | 单点数值 + 标“演示”的覆盖面 | 带时效的降水栅格/网格 | mm/h，不混淆累计降水 |
| THUNDER_PROBABILITY | 概率符号/演示覆盖面 | 合法预报概率网格 | 存储 0–1，显示 % |
| LIGHTNING | B 默认不提供 | 事件坐标及发生时间 | 实际事件，独立于概率 |
| RISK_AREA | 明示“示意”的多边形 | 区域边界关联规则输出 | 等级 + ruleVersion + 依据 |
| ROUTE | 明示“示意航线” | 后续可接任务航线 | GeoJSON，坐标顺序 lon/lat |

统一 WGS84 / EPSG:4326。`bbox=[minLon,minLat,maxLon,maxLat]`。`geometry` 与 `data` 按 kind 约束；无数据不得伪造空风险区域。后端状态为 READY/NO_DATA/EXPIRED/ERROR，前端加载时另外维护 LOADING。图层版本与 dashboard 不匹配时不覆盖当前层。

## 4. G 阶段：基础准备与测试入口

### G01：建立可重复的隔离验证环境（0.5–1 人日）

**修改/新增**：`backend-java/pom.xml`、`frontend/package.json`；新增 `backend-java/src/test/resources/application-test.yml`、`P/requirements-dev.txt`、`frontend/vitest.config.js`、`frontend/playwright.config.js`、`tests/fixtures/`、`scripts/test-local.ps1`。

编码步骤：

1. 检查项目及父目录适用的 `AGENTS.md`；记录当前源码摘要和构建入口。只在受管输出目录构建。
2. Java 使用内存 H2、随机或隔离端口；Python/和风/渠道使用 stub，不读取真实密钥配置，不调用关机接口。
3. 利用已有 `spring-boot-starter-test` 建立首个规则测试和 Controller 测试；新增 Vitest、Vue Test Utils、Playwright、pytest 的开发依赖及锁定流程。
4. 建立固定 clock、固定 seed、标准观测和四个剧本 fixture；Python 已有 seed 参数，补固定时间注入，避免重复实现随机入口。
5. 保存原始规则边界与 DTO fixture，先编写复现缺陷的用例，再在后续任务中修复；合并到交付分支时所有启用测试必须通过。

**验收**：三端均能运行至少一个实际断言；测试命令遇到零测试或用例失败返回非零；不以 “No tests to run” 作为通过证据。

### G02：规则与契约冻结（0.5 人日）

新增第 3 节 schema、`docs/architecture-decisions.md`、`tests/fixtures/rule-cases.json`。逐字段记录类型、单位、必填、可空、时间口径和前后端映射。根据 DEC-01/02 记录规则临时演示约定和生产确认状态。

**验收**：空数据、正常数据、故障数据、轨2 PENDING/失败数据均有 fixture；每个示例可以通过对应 schema 校验。

## 5. A 阶段：稳定主链路

### A01：运行标识、完整快照与最小事务（1–1.5 人日；依赖 G02）

**修改**：`J/model/WeatherSnapshot.java`、`J/entity/SfiRecordEntity.java`、`J/entity/TrackResultEntity.java`、对应 Repository、`J/service/MonitorService.java`。  
**新增**：`J/dto/DashboardDto.java`、`J/dto/WsEnvelope.java`、`J/dto/ErrorResponse.java`、`J/entity/MonitoringRunEntity.java`、`J/repository/MonitoringRunRepo.java`、`J/service/RunCommitService.java`、数据库迁移目录。

1. 创建 `monitoring_run`，至少包含 runId、区域、序号、revision、场景、配置模式、实际来源、规则版本、状态、各阶段时间和错误码。
2. 快照增加 windDeg、conditionText、原始时间、坐标和质量字段；缺失可能性存在的数值改为包装类型/显式缺失模型，并更新所有构造位置，包括预报到 WeatherSnapshot 的转换。
3. `RunCommitService` 作为独立 Spring Bean 提供事务方法，避免同类自调用使事务不生效；提交 run + snapshot + track1 + forecast + appliedScenario。网络调用不放在该事务内。
4. 用 runId 查询完整快照，禁止从不同表各取“最新一条”再拼接；历史列表可以包含多轮，但每项带归属。
5. A 阶段即持久化排序标识和关联预报，C 阶段在此基础上扩展异步更新，不再推倒重建。
6. 提取 DashboardAssembler，HTTP 和 WS 使用注入的同一 ObjectMapper/DTO 规则。

**测试/验收**：往返序列化保留所有字段；旧记录缺字段显示未知；中途落库异常整个成功快照事务回滚；重启后 runSequence 不倒退；不混合两轮结果。

### A02：调度、场景原子性与真实来源（1–1.5 人日；依赖 A01）

**修改**：`J/service/MonitorService.java`、`J/config/MonitorProperties.java`、`J/controller/DashboardController.java`、应用配置。  
**新增**：`J/model/Scenario.java`、`J/model/RunContext.java`、`J/controller/ApiExceptionHandler.java`。

1. 将配置拆为 `monitor.initial-delay-ms=6000` 与 `monitor.fixed-delay-ms=600000`，调度注解统一毫秒，删除 MINUTES 混用。旧 interval-minutes 在过渡读取层换算，并在同时配置时让新键优先。
2. 入口先校验场景、模式和参数，再分配 RunContext；RunContext 冻结区域、场景、来源策略、ruleVersion、deadline，运行过程中不读取可变 currentScenario。
3. 同一区域通过原子占用控制 single-flight，finally 释放；定时触发忙时跳过并记指标，手动触发忙时返回 409。废除“节流后返回旧成功结果”的歧义。
4. 只有成功提交后才更新 appliedScenario；无效请求不分配任务，不修改全局变量。运行失败独立记录 lastAttempt，不污染成功快照。
5. prod live 拉取失败返回可解释失败，保留历史快照并标过期/不可用；demo 的显式模拟降级记录 effectiveSource=sim 和 degraded=true。
6. 冷启动给出 WAITING；首轮失败保留原因；readiness 不把“有历史数据”当作“当前观测就绪”。

**测试/验收**：应用启动调度配置触发间隔正确；非法场景 400 且状态不变；两个并发场景只执行一个；Python/和风失败后可再执行下一轮；无任何失败路径显示伪造实时数据。

### A03：规则硬约束、未知值与骤降（1–1.5 人日；依赖 G02、A01）

**修改**：`J/service/SfiEngine.java`、`J/model/FlightLevel.java`、`J/service/FusionService.java`、`J/service/MonitorService.java`、`J/repository/SfiRecordRepo.java`、`J/service/AlertService.java`。  
**新增**：`J/service/ObservationValidator.java`、`J/config/RuleProperties.java`、`config/rules-v1.json`。

1. 在规则计算前校验缺失、有限数、数值范围和单位；湿度/雷暴概率限定 0–1，风速/降水/能见度不接受负值；温度可为负，不能套用非负校验。
2. 使用配置加载阈值、比较符、扣分、等级边界和 ruleVersion；保留原始检查明细、rawSfi、硬约束原因。
3. 按 DEC-01/02 实现硬约束，FusionService 明确不可把硬 BAN 降级；轨2非法等级表示不可用，不能默认 FIT。
4. “数据未知”输出 UNDETERMINED；如果已知要素已命中硬禁飞，可仍输出 BAN 并标数据不完整，具体优先级写入测试。
5. 骤降在保存当前记录前按同区域、同有效来源、同规则版本查询上一条；模拟额外限定同 scenario，避免剧本切换产生伪骤降。
6. 比较严格早于当前的观测，时间差要求 `0 < delta <= 60分钟`；下降 `>=30` 触发；用主键值比较或查询条件排除自己。
7. 操作建议由等级/骤降规则模板确定，模型只作补充说明；骤降文案改为“至少 30 分”，与 >= 比较一致。界面统一显示综合等级，轨1分数及硬约束来源独立标注。

**测试/验收**：覆盖每项阈值前/等于/后、温度上下界、NaN/无穷/缺失；单项降水硬阈值不会出现最终 CAUTION；100→65 同源同区域窗口内触发 SFI_DROP，过窗/倒序/跨来源/跨场景不触发。

### A04：前端 API、WebSocket 与操作状态（1–1.5 人日；依赖 A01/A02）

**修改**：`F/api.js`、`F/App.vue`、`frontend/vite.config.js`、各面板导入。  
**新增**：`F/store.js`、`F/dashboardAdapter.js`、`F/composables/useRealtime.js`、`F/components/RequestStatus.vue`。

1. API 只访问相对 `/api`；WS 使用当前页面 host、对应 ws/wss 和 `/ws/dashboard`，复用现有 Vite 代理。
2. 封装 `requestJson`：检查 HTTP 状态、处理非 JSON 错误、AbortController 超时、映射统一错误；按钮有 loading/错误/重试状态。
3. store 分离 requestedScenario、appliedScenario、pendingAction、connectionState；按钮成功后才改变已生效态；失败保持上一轮并显示原因。
4. REST/POST/WS 均经 `applyDashboard` 排序；信封校验版本、type、payload；拒绝未知版本并给出重新加载提示。
5. WS 指数退避并带抖动，建议 1/2/4/8/16/30 秒上限；open 后补快照；dispose 时关闭连接和重连/弹窗计时器，主动关闭不触发重连。
6. 配置浏览器超时大于规则链路服务端 deadline；A 临时阶段必须配置轨2关闭或严格限时，不能让长模型调用继续卡按钮。

**测试/验收**：503、超时、HTML 错误页可展示；双客户端同步；重连补齐；旧 POST 覆盖新 WS 的回归测试通过；反复挂载卸载不增加连接数或重连定时器。

### A05：地图与面板纠错（0.5–1 人日；依赖 A03/A04）

**修改**：`F/components/PanelMap.vue`、`PanelWeather.vue`、`PanelTop.vue`、`PanelTracks.vue`、`PanelSfi.vue`、`F/utils.js`、`F/App.vue`。

1. 扩展已有 LEVEL_COLORS/LEVEL_LABELS 为共享 LEVEL_STYLES，所有边框、填充、点、标签都引用该表；CAUTION 不再绿色，DANGER 不标“禁入”。
2. 地图标题改“气象与作业态势”；矩形明确“示意范围”；无有效等级用灰色不可判定，陈旧数据覆盖时效提示。
3. windDeg 缺失不画方向箭头；0 是有效北风，不能用真假值判断；静风单独表示。坐标同样用有效数判断，0 经度/纬度不得触发默认值。
4. 风来向转换吹去方向 `(deg+180)%360`，完成四个正交风向视觉核验。
5. PanelSfi 将 markLine 移到实际 SFI series，显示 80/60/40；预测时间与观测时间统一显示时区，预测与历史采用可辨识样式。
6. 顶部将“配置完整”“连接正常”“数据新鲜”分开展示；天气时间显示 obsTime。

**验收**：四个等级截图颜色、标签一致；未知值无虚构数值；阈值线存在；所有面板来自同轮数据。

### A06：关闭危险控制入口（0.5 人日；可与 A01 独立实施）

**修改**：`J/controller/DashboardController.java`、`J/ws/WebSocketConfig.java`、`J/config/WebConfig.java`、配置模板、`start.bat`、`stop.bat`。

移除业务 HTTP 关机接口及 killPort 逻辑；停止系统交给本地受管启动脚本。demo 只监听回环；WS/CORS 使用显式来源列表。prod 关闭 H2 console；生产包排除真实密钥、日志和工作数据库。停止脚本必须验证记录 PID 的进程启动时间、命令行和项目目录匹配，禁止仅按端口杀进程。

**验收**：HTTP 关机入口不可用；非法 Origin 拒绝；受管停止逻辑用替身进程测试，不影响同端口历史记录对应的其他进程。

**A 退出门槛**：G 用例及 A 回归通过；固定 fixture 四剧本完整循环；两客户端同步；首轮调度正常；无来源误标、场景错配、硬约束被融合覆盖。A 的演示交付允许明确关闭 LLM，不能据此宣称 C 的异步能力完成。

## 6. B 阶段：独立天气图层演示版

### B01：图层资源与确定性生成（1–1.5 人日；依赖 A01、G02）

**新增**：`J/dto/LayerDto.java`、`J/controller/LayerController.java`、`J/service/LayerService.java`、`P/layers.py`、图层 fixtures；修改 `P/simulator.py`、`P/main.py`。

1. 生成图层时传入本轮快照和 RunContext，不重新随机生成一份天气；固定 seed 和 clock 时输出稳定。
2. 图层资源按 regionId/runId 关联，返回有效时间和 expiresAt；模拟覆盖面强制 isSimulated=true，并在质量说明中注明几何为演示。
3. 单点降水/雷暴概率标记为点位观测或预测，面仅为演示符号，不使用“实际覆盖范围”文案。
4. 构建无数据、过期、错误 fixture；保留 READY 且合法零值的情况，用于区分“无降水”和“无数据”。

**验收**：相同 fixture 输出一致；每层通过 schema；错 runId 不返回当前层冒充；真实雷电层无数据时不造点。

### B02：图层控件、图例与状态（1–1.5 人日；依赖 B01/A04）

**新增**：`F/components/MapLayerControls.vue`、`MapLayerLegend.vue`、`F/composables/useMapLayers.js`、`F/map/layerRenderers.js`；修改 `F/App.vue`、`PanelMap.vue`。

1. 模拟剧本控件与图层显隐分为两组。图层状态使用独立 enabledLayers，不写回 scenario，也不触发监测或 LLM。
2. 风、降水、雷暴概率、风险区、航线独立开关；加载/空/过期/失败状态分别展示；图例同步当前可见层。
3. 每个渲染器输入 LayerDto，输出稳定 series.id；关闭图层时明确移除对应系列，保留底图和其他图层。
4. 图层获取取消旧请求并做 runId 比对；请求失败可保留历史层，但必须降透明度并标陈旧，不能无提示续用。
5. 单位、来源、演示标记和时间由 DTO 驱动；概率层与将来的 LIGHTNING 层采用不同名称和符号。

**验收**：逐层开关和全组合关键用例中图元确实增删；切换显隐不出现 `/sim/switch` 或 `/track2` 请求；图例无重复、数据无残留。

### B03：地图视角、尺寸与性能（0.5–1 人日；依赖 B02）

拆分 `initMap()`、`updateLayers()`、`resetView()`；geo 初始视角只设置一次，刷新仅更新 series。监听 georoam 保存视角；回中按钮显式复位。坐标、区域变化单独监听并更新作业点，是否回中由用户动作决定。ResizeObserver 观察容器；卸载时 disconnect/dispose。统一稳定 series.id 并验证 replaceMerge 或显式清空策略不会重置视角。

**验收**：拖拽缩放后自动刷新与轨2补全都不跳回；回中有效；1366×768、1920×1080 无控件遮挡；10 次切换无系列数量增长。按目标设备记录拖动 FPS，建议平均不低于 30。

**B 退出门槛**：每层有独立测试和截图；风向四向、未知、零风均正确；断网/清空/过期表现清晰；演示信息在截图中也能辨识。

## 7. C 阶段：异步研判、可靠预警与权限

### C01：规则先发布、轨2异步补全（1.5–2 人日；依赖 A01–A04）

**修改**：`J/service/MonitorService.java`、`PythonClient.java`、`FusionService.java`、`P/main.py`、`P/track2_agent.py`。  
**新增**：`J/service/Track2JobService.java`、`J/config/AsyncConfig.java`、`J/entity/Track2JobEntity.java` 及 Repository、`P/schemas.py`。

1. 主流程变为：采集 → 校验 → 规则 → 短事务提交 RULE_READY 和轨2任务 → 返回/广播 → 后台研判 → 条件事务更新 revision → 广播。
2. 任务持久化后由有界 worker 领取，避免提交后 JVM 崩溃导致任务永远遗失；设置并发上限、队列上限和拒绝状态，不使用无限制线程。
3. Java/Python 传递 runId、ruleVersion、绝对 deadline；每次重试使用剩余预算，预算不足直接退出。建议演示初值：规则总期限 3 秒，轨2总期限 20 秒，至多 1 次重试，最终按实测修订。
4. HTTP 超时、退避和队列等待都计入总期限；Python 在重试前检查预算，不能 Java 已超时后仍继续 3 次 45 秒调用。
5. 回写验证任务归属与期望 revision；旧轮结果可存入该轮历史，但不得更新当前运行指针或触发当前场景预警；不能只依赖前端过滤。
6. 超时/非法响应置 TIMEOUT/INVALID/UNAVAILABLE，保留规则结果；恢复启动时到期任务标终态，未到期可按幂等键恢复。
7. 模型结果 schema 限制等级、置信度、因子数组、建议长度和输出大小；不把模型建议当规则操作指令。
8. 缓存键包括标准快照摘要、forecast、regionId、taskType、ruleVersion、模型/提示词版本；TTL 不超过天气有效期，返回内容仍绑定调用轮次。熔断按连续失败开启，半开仅允许少量探测。

**验收**：人为延迟模型 30 秒仍能先看到规则结果；旧任务不会覆盖新场景；队列满可解释降级；进程重启、重复执行、超时后晚返回均不会重复提交或漏掉终态。

### C02：Java/Python 规则一致与气象校验（1–1.5 人日；依赖 A03）

**修改**：`J/qweather/QweatherClient.java`、`P/track2_agent.py`、`P/main.py`、`J/service/PythonClient.java`；新增 `P/rules.py`。

Java/Python 加载同一 `config/rules-v1.json`，两端实现相同配置 schema 和比较符语义，共享 golden cases。Python fallback 补温度等项目，明确 source=fallback，不伪装模型结果；版本不同拒绝融合。气象必需字段缺失返回校验错误，可选字段 null；对估算雷暴概率保留 method/quality，不能标为实际闪电。预报和观测分别校验 validTime、单位、合理范围和 TTL。

**验收**：共享样本两端等级、硬约束和扣分一致；缺失不能得到默认 FIT；无效单位/过期天气不会进入正常新鲜态势；所有构造点不再填入虚构风向、湿度或良好能见度。

### C03：预警状态机、outbox 与送达语义（1.5–2.5 人日；依赖 C01/A03）

**修改**：`J/service/AlertService.java`、`PushService.java`、预警/推送实体及 Repository、`J/ws/DashboardWebSocketHandler.java`、`F/components/PanelAlerts.vue`、`PanelPush.vue`。  
**新增**：`J/entity/AlertStateEntity.java`、`OutboxEventEntity.java`、`J/service/OutboxDispatcher.java` 及对应 Repository。

1. 状态键按 regionId + source + triggerType + ruleVersion 分区，模拟再加 scenario；状态为 INACTIVE/ACTIVE/RESOLVED，记录等级、最近时间、冷却截止和 episodeId。
2. 首次命中创建；同级延续只刷新 lastSeen；升级立即发；解除按可配置连续恢复轮数确认；恢复阈值/冷却值写配置及测试。无数据不可当作恢复，也不可自动解除。
3. 预警变化与 outbox 在同一事务保存；唯一键 `episodeId + transitionVersion + channel` 防重复入队；LLM 同轮补全不重复轰炸。
4. worker 按领取租约/状态条件更新取任务，重试退避、有上限和 DEAD 状态；网络操作在事务外，成功后写业务响应。
5. 各 webhook adapter 同时判断 HTTP 与渠道业务码，未知响应不能算成功；目标记录 channel/脱敏 targetId，不截取含 token 的 URL 当脱敏。
6. 推送状态区分 QUEUED、SENDING、SENT、ACKED、FAILED、SKIPPED；SENT 只表示发送/渠道受理，界面不译为“用户已收到”。无第三方回执的渠道不生成 ACKED。
7. SCREEN 实际广播成功才能 SENT；无人在线保持待发送或按 TTL 到期；客户端渲染预警后发送 `{type:"alert_ack",eventId}`。ACK 关联已发送会话并去重，仅代表该客户端已确认显示，不代表所有人阅读。
8. 外部渠道若无幂等支持，明确采用至少一次投递，崩溃窗口可能重复；不能承诺外部 exactly-once。前端按 eventId 去重。

**验收**：同级连续 10 轮不轰炸；升级/解除有唯一事件；HTTP 200 业务失败为 FAILED；无人在线不显示送达；崩溃重启 outbox 可恢复，重复 ACK 不重复计数。

### C04：权限、配置和健康指标（1–1.5 人日；依赖 A06）

**新增**：`J/config/SecurityConfig.java`、`J/controller/HealthController.java`、`F/components/LoginPanel.vue`、dev/demo/prod 无凭据配置模板；修改 `pom.xml`、WS 握手、`PanelTop.vue` 和问答接口。

1. 使用 Spring Security 实现会话登录；VIEWER 读大屏，OPERATOR 触发监测/允许的模拟操作，ADMIN 管理受限配置。Cookie 设置 HttpOnly，prod HTTPS 下 Secure；变更请求校验 CSRF，WS 同时校验会话和 Origin。
2. Python 仅供 Java 内部访问，绑定回环或内网受限地址；对跨主机部署配置服务间认证。限制问答长度、请求速率、并发和费用相关超时。
3. 明确环境变量 > 显式外部配置 > profile 默认值；Java/Python 共用解析约定，日志只记录配置来源路径和非敏感状态，不打印配置正文。
4. 私钥由受控文件路径注入；发布产物扫描不得含私钥/凭据。历史泄露调查和必要轮换作为运维任务记录，不在普通测试中使用真实凭据。
5. liveness 只检查进程；readiness 区分数据库/首轮有效观测和可选轨2/渠道降级。输出 configured、lastSuccessAt、freshness、latency、errorCode，不用单一绿色状态灯覆盖全部链路。
6. 结构化日志记录 requestId/runId/regionId/source/stage/duration/errorCode；指标包含规则耗时、轨2超时、队列深度、outbox 失败、WS 连接数、观测年龄。runId 不作为指标标签，避免高基数。

**验收**：未登录读受保护资源 401、越权写 403、非法 WS 拒绝；正确角色可执行；live 数据陈旧而 WS 正常时顶部仍提示数据异常；日志/包扫描无敏感字段。

**C 退出门槛**：LLM 和渠道均不阻塞规则响应；乱序/重启/事务失败有测试；权限矩阵、告警状态转换、状态文案全部通过。

## 8. 数据库迁移与回退方案

建议引入 Flyway 管理增量迁移，迁移工具版本在实际编码时按当前 Spring Boot/H2 依赖验证后锁定。不能靠 `ddl-auto=update` 隐式修改生产数据。

| 迁移批次 | 表/字段 | 策略 |
|---|---|---|
| V1 基线 | 现有五类表 | 从实际 schema 导出并审核；已有库只在备份副本验证后显式 baseline；新库从 V1 创建 |
| V2 运行快照 | monitoring_run、snapshot 完整字段、runId 外键、forecast_json | A01 实施；旧表先增加可空字段，legacy 标记；新写入必须关联 runId |
| V3 异步研判 | track2_job、状态/revision/期望版本 | C01 实施；runId + jobKind 唯一，支持领取及恢复 |
| V4 可靠预警 | alert_state、outbox_event、ACK/状态字段 | C03 实施；增加幂等唯一键及 dueAt/status 索引 |
| V5 历史治理 | 历史查询索引、保留策略配置 | E 实施；按区域、来源、观测时间查询，清理遵守外键顺序 |

具体约束：

1. `sfi_record.run_id` 对新数据唯一；track result 按 runId/revision 或一个可更新聚合保存，编码前选定一种，推荐每次 revision 留历史；forecast 与 runId 绑定。
2. 原始 snapshot/forecast JSON 与索引列并存时，规定 JSON 为完整观测证据、索引列为查询投影，必须同事务生成。
3. 老数据无法准确关联轨1/轨2时不按“时间差不多”强行归轮；保留 legacy 历史展示，当前页使用迁移后的第一轮有效快照。
4. 旧记录缺风向/观测时间不可回填 0 或当前时间；旧 ts 只有明确部署时区后才转换，否则保留原值并标质量未知。
5. 每批在副本上执行“旧库升级、空库创建、重复启动”，对行数、外键、唯一约束和历史读取进行验证。
6. 上线前备份并验证可恢复；失败回退旧程序及匹配数据库备份。若新增数据已产生，先导出保存再回退；不让旧程序直接读取不兼容新结构。

## 9. D 阶段：真实空间数据（独立准入）

### D00：样例与适配可行性（1–2 人日，不含采购等待）

新增 `docs/spatial-data-contract.md`，记录数据提供方、许可、区域、分辨率、频率、延迟、单位、坐标系、缺失值、单次尺寸、额度与缓存许可。至少保存一份可用于测试的脱敏/许可样例及 expected metadata。

**门槛**：样例能合法读取并覆盖目标作业区；否则停止 D 的接入编码，B 保持演示标识。只提供单点 API 不等于拥有空间网格。

### D01：适配、空间风险、缓存与回放（4–8+ 人日；依赖 D00/B/C02）

新增 `J/spatial/SpatialWeatherProvider.java`、具体 provider adapter、`SpatialRiskService.java`，以及空间样例测试。

1. 适配器统一 LayerDto，进行坐标/单位/缺失值转换；真实数据不继承模拟矩形生成逻辑。
2. 真实风矢量/降水栅格/闪电事件分别接入，概率网格明确时间区间；按来源+区域+有效时间缓存，缓存失效仍保留原有效时间。
3. 仅在各必要要素的空间覆盖与时间对齐可证明时输出完整 SFI 风险多边形；仅有降水时输出“降水单要素风险”，不能补齐其他要素成完整适飞区。
4. 风险多边形关联输入数据版本、ruleVersion、边界版本，支持按观测时刻回放；缺数据区域保留掩膜/未知。
5. 记录要素数量、载荷大小、渲染耗时和 FPS；先做目标数据量基准，再决定是否需要专用 GIS 引擎。选型迁移作为额外任务估算，不混入已承诺工期。

**验收**：位置/单位/时效与样例一致；同一历史输入可重放相同结果；断源与过期可辨；性能达到目标设备基准，来源与许可可追溯。

## 10. E 阶段：构建、部署、存储维护与性能

### E01：可复现构建与受管启动（1–1.5 人日；G 可开始，C 后发布）

**修改**：`build.bat`、`start.bat`、`stop.bat`、`backend-java/pom.xml`、`P/requirements.txt`、`frontend/package.json`、`README.md`。  
**新增**：Maven Wrapper、Python 锁定依赖、Node 版本约束、`scripts/build.ps1`、`scripts/start.ps1`、`scripts/stop.ps1`、`config/*.example.yml`、`docs/deployment.md`。

1. 不依赖本机 IDE Maven/JDK 绝对路径；启动前验证 Java/Node/Python、配置和端口归属；依赖精确版本在实际环境验证后锁定，不在本计划猜测最新版本。
2. `npm ci → 前端构建 → Maven 静态资源生成目录 → JAR` 串成唯一发布入口；不手工复制到源码 `resources/static`；临时 staging 目录受管。
3. 任一步失败立即非零退出；不能因旧 JAR 存在继续启动。生成 buildId、源码摘要或 commit、构建时间、依赖清单和 checksum。
4. Python readiness 成功后启动 Java；HTTP 健康返回 serviceId/buildId 验证端口上的服务身份。后台进程隐藏窗口并记录 PID、启动时间、项目路径。
5. 清理/停止只作用受管路径/进程；发布目录包含程序、示例配置、运行说明，不含 `.audit`、私钥、node_modules、旧工作库和日志。

**验收**：干净目录按文档安装运行；故意构建失败不启动旧包；无关进程占端口时明确退出；buildId 前后端一致；可按备份恢复流程回退。

### E02：历史分页、保留、备份恢复（0.5–1 人日；依赖第 8 节迁移）

新增历史分页接口，支持 regionId、source、时间窗、cursor/pageSize 上限；索引匹配查询。按配置清理超期历史与终态任务，未发送 outbox 不随历史误删。实现停机一致性备份或经验证的数据库备份方式，不直接复制正在写入的 H2 文件当可靠备份。恢复到隔离目录并核对最近运行、预报、预警关联；多用户数据库迁移另立任务。

### E03：前端包体、动画与 CI（0.5–1 人日；依赖 B03）

新增 `F/echarts.js` 按需注册地图、lines、effectScatter、custom、折线及实际使用组件，统一面板导入；保持地图 GeoJSON 只注册一次。必要时拆 chunk；不靠提高 chunkSizeWarningLimit 掩盖包体。页面不可见暂停可控动画/轮询，恢复后补快照。CI 依次执行契约、Java/Python/前端测试、端到端、生产构建与发布目录扫描；CI 平台按实际仓库托管环境确定。

**验收**：九个面板功能无回归，记录优化前后 gzip 和首屏指标；阈值以目标设备实测设定，不承诺固定压缩比例。

## 11. 自动化测试与验收清单

### 11.1 计划新增的关键测试

| 测试位置（建议） | 覆盖行为 | 对应任务 |
|---|---|---|
| `backend-java/src/test/java/com/tianchuang/service/SfiEngineTest.java` | 所有边界、缺失、硬约束、rawSfi 与有效 SFI | A03 |
| 同目录 `FusionServiceTest.java` | BAN 不降级、轨2未知、置信度非法 | A03/C02 |
| 同目录 `MonitorServiceTest.java` | 固定上下文、single-flight、失败场景不提交、来源降级 | A02 |
| 同目录 `RunCommitIntegrationTest.java` | 事务回滚、同轮组装、revision、重启排序 | A01/C01 |
| 同目录 `SfiDropTest.java` | 100→65、60 分钟边界、来源/区域/场景隔离 | A03 |
| 同目录 `Track2JobTest.java` | 超时、重试预算、晚返回、恢复、队列满 | C01 |
| 同目录 `AlertLifecycleTest.java` / `OutboxTest.java` | 同级/升级/解除/崩溃窗口/幂等/业务码 | C03 |
| `backend-java/src/test/java/com/tianchuang/controller/ApiSecurityTest.java` | 400/401/403/409、输入限制、WS 来源 | A02/C04 |
| `backend-python/tests/test_rules.py` | 跨语言 golden cases、温度项与规则版本 | C02 |
| `backend-python/tests/test_track2.py` | 非法 JSON、deadline、fallback 的来源标识 | C01 |
| `backend-python/tests/test_simulator.py` | seed+clock 稳定、图层与快照同轮 | G01/B01 |
| `frontend/src/__tests__/realtime.test.js` | GET/POST/WS 乱序、重连、卸载清理 | A04 |
| `frontend/src/__tests__/mapLayers.test.js` | 图层显隐、状态/图例、runId 拒收 | B02 |
| `frontend/e2e/dashboard.spec.js` | 双客户端、剧本循环、故障反馈与重新加载 | A/B |
| `frontend/e2e/map.spec.js` | 风向、四级颜色、缩放保持、两种分辨率截图 | A05/B03 |

### 11.2 命令入口（相关脚本和依赖建成后执行）

以下命令当前不保证可运行，是 G/E 阶段需要落实的开发接口；应在各目录独立执行，日志输出到受管测试目录。

```powershell
# backend-java 目录；测试默认使用隔离配置，禁外部服务
.\mvnw.cmd test
.\mvnw.cmd verify

# backend-python 目录；使用项目锁定依赖的虚拟环境
.\.venv\Scripts\python.exe -m pytest tests -q

# frontend 目录
npm ci
npm run test:unit -- --run
npm run test:e2e
npm run build

# 项目根目录；聚合入口负责独立端口、stub 和测试数据生命周期
.\scripts\test-local.ps1
```

`test-local.ps1` 负责准备依赖、启动 stub 与被测服务、等待就绪、执行测试、回收自己启动的进程；端口冲突选择空闲测试端口或明确失败，禁止结束占用者。

### 11.3 交付必须保存的证据

- 每个版本记录实际测试数量、失败数、构建结果和环境版本；截图不能替代协议/事务断言。
- 四剧本使用固定数据，断言相应规则结果；不要求随机 wind/rain 永远对应某个等级。
- 双浏览器 A 切换、B 自动更新，以及断网重连录像或自动化记录。
- 地图每层独立/叠加/关闭、四向风、无数据、过期、两分辨率截图。
- 故障注入：和风超时、Python 不可用、LLM 慢/非法 JSON、数据库写失败、渠道业务失败。
- 建议性能门槛：目标设备固定模拟无 LLM 条件下，至少 100 次串行有效操作统计“点击到规则态势显示”的 P95，目标 <1 秒；服务已就绪时页面首次可用 <3 秒；地图拖动平均 ≥30 FPS。冷启动 Java 耗时单列，不混入前端首屏指标。
- 生产准入额外要求：业务规则确认、真实来源质量验证、权限验证和备份恢复成功。D 未交付时在界面和交付说明持续标明演示图层。

## 12. 提交拆分、依赖与工作量

每个提交组均包含对应测试和文档更新；schema/数据库变更必须先落地，前端不能先引用未提供的新字段。下表人日是熟悉现有技术栈的有效工作量，不是承诺日历工期。

| 提交组 | 范围 | 前置 | 评审重点 |
|---|---|---|---|
| PR-01 | G01/G02 测试与契约 | 无 | 隔离性、fixture、决策可追溯 |
| PR-02 | A06 危险入口收口 | 无 | 不再按端口杀进程、来源限制 |
| PR-03 | A01 运行/快照/迁移 | PR-01 | 同轮一致、可空字段、迁移回退 |
| PR-04 | A02/A03 调度、场景、规则 | PR-03 | 并发、失败不污染、硬约束 |
| PR-05 | A04/A05 前端协议与表现 | PR-03/04 | 乱序、代理、四级和未知态 |
| PR-06 | B01–B03 演示图层 | PR-05 | 独立性、真实性标识、视角 |
| PR-07 | C01/C02 异步与一致规则 | PR-04/05 | deadline、旧轮写回、恢复 |
| PR-08 | C03 可靠预警 | PR-07 | 状态转换、事务 outbox、送达语义 |
| PR-09 | C04 权限与健康 | PR-02/05 | 角色边界、会话、数据新鲜度 |
| PR-10 | E01–E03 发布与维护 | G 开始准备，C/B 完成后收口 | 可复现包、受管进程、备份恢复 |
| PR-11+ | D00/D01 真实空间数据 | 数据准入 + B/C02 | 样例依据、空间真实性、性能 |

| 阶段 | 任务合计估算 | 可评审交付 |
|---|---:|---|
| G | 1–1.5 人日 | 测试入口、schema、规则决策 |
| A | 5–7.5 人日 | 稳定演示主链路与最小持久化一致性 |
| B | 2.5–4 人日 | 独立天气图层演示版 |
| C | 5–7.5 人日 | 异步、预警、权限与运行保障 |
| E | 2–3.5 人日 | 可安装、可升级、可回退交付包 |
| D | 5–10+ 人日 | 真实空间适配与验证，不含数据等待/地图引擎迁移 |

G+A+B+C+E 合计约 **15.5–24 人日**；加 D 约 **20.5–34+ 人日**。相比原优化方案，A 增加最小运行实体、数据库迁移和自动化测试，以避免 C 再次重写数据链路。单人顺序执行按有效投入折算；多人协作只能在接口冻结后并行，不直接按人数除工期。业务确认、数据采购、真实渠道联调等待单列。

建议第一个开发周期按以下次序推进：

1. 完成 G01/G02，创建隔离测试和契约 fixture；同时实现 A06。
2. 完成 A01，验证新旧数据库与同轮快照。
3. 完成 A02/A03，先让后端规则、场景、来源行为正确。
4. 完成 A04/A05，跑双客户端与地图回归，形成 A 可演示版本。
5. A 门槛通过后进入 B；C 的任务持久化和 deadline 设计可先评审，但不绕过 A 的验收。

## 13. 每个任务的完成定义

- [ ] 涉及文件、契约和配置同步修改，旧字段/旧入口有明确迁移处理。
- [ ] 正常、失败、空数据、并发/乱序等相关行为有测试，实际通过且有测试数量。
- [ ] 数据来源、有效时间、运行归属和规则版本可追溯。
- [ ] 日志/错误/界面文案能区分等待、失败、降级、过期，不将未知标为适飞。
- [ ] schema 或数据库变更已在隔离副本验证升级与恢复。
- [ ] 相关 UI 完成目标分辨率的真实浏览器核验。
- [ ] 构建成功且发布物来源明确；配置样例与部署说明更新。
- [ ] 未完成的业务确认、真实数据或外部联调明确列出，不写成“已通过”。

本文的下一步是按 PR-01 开始实现；本次文档交付本身不执行这些业务源码变更、数据库迁移或外部推送。
