# 天窗智巡项目审查与优化方案

审查日期：2026-09-09。范围：当前工作目录中的源码、已有 JAR、配置结构、前端生产构建，以及本地隔离服务的 REST / WebSocket 联调。

## 1. 结论

项目具备 Vue 大屏、Java 规则与监测编排、Python 模拟与大模型研判、H2 存储和预警渠道的完整原型骨架，但尚不能把“页面可打开”视为“气象保障链路可靠”。优先工作应是修复数据契约、监测调度、等级规则和地图表现，再补真实空间气象数据与运行保障。

用户提出的大风、雷暴等图层失效，并非单一绘图库故障。当前代码没有独立的大风、降水、雷暴图层；四个按钮实际切换模拟剧本。与此同时，WebSocket 协议不一致、风向字段丢失、谨慎区绿色展示和同步等待 LLM 等问题叠加，形成“点击后没变化”“实时画面不刷新”的体验。

本次未修改业务源码、原配置或原 H2 数据；新增的检查脚本、隔离构建与结果位于 .audit。测试使用 18085 / 18600 和内存数据库，禁用真实大模型调用及外部消息推送。没有执行系统关闭接口。

## 2. 内容与运行状况

### 2.1 实际架构

- frontend：Vue 3、ECharts 5、Vite，九个面板构成 1920×1080 固定比例大屏。地图为中国 GeoJSON、固定示意航线和作业点。
- backend-java：Spring Boot 3.5.6 / Java 17。负责天气拉取、SFI、双轨融合、监测、持久化、REST、WebSocket 和渠道推送。
- backend-python：FastAPI；模拟 clear/wind/rain/storm，调用 DeepSeek，失败退回本地简化规则。ML 端点只是预留。
- 存储：H2，五类实体；预报和部分运行状态仅存在内存。
- 启动发布：Windows 批处理，绑定本机 JDK、IDE Maven 和 Python 虚拟环境；静态资源同时存在 dist、resources/static、target 与 JAR 中。

### 2.2 实测记录

初次检查未发现 8085、8600、5180 监听。旧 uvicorn.log 只能说明历史启动过，不能说明当前在线。

隔离启动后 Java、Python 成功运行；Java 约 13.5 秒完成启动。首个 dashboard 无 current，lastRunAt 是字符串 "null"，与首次调度缺陷一致。

| 场景 | HTTP | 本次耗时 | SFI | 等级 | 轨2 |
|---|---:|---:|---:|---|---|
| clear | 200 | 211 ms | 100 | FIT | fallback |
| wind | 200 | 37 ms | 62 | CAUTION | fallback |
| rain | 200 | 23 ms | 73 | CAUTION | fallback |
| storm | 200 | 37 ms | 23 | BAN | fallback |

这些是一次随机模拟、禁用外部 LLM 后的联调数据，不是负载测试结果，也不是天气严重程度的固定映射。

其他验证：

- WebSocket 捕获四条 dashboard 消息，全部没有 type；预警消息有 type=alert。
- 四个 dashboard 的 snapshot 均缺少 windDeg、conditionText、原始观测时间等字段。
- 非法 scenario 返回 500，随后 dashboard.scenario=invalid，但 current.scenario=storm，证明失败请求污染运行状态。
- 开发源 http://localhost:5180 的预检请求返回 403；源码跨域直连 8085，绕开已配置的 Vite 代理。
- 独立 Java 规则探针：仅降水达到项目定义的 5 mm/h 禁飞阈值，结果 sfi=65、level=CAUTION，同时 banned 检查数=1。
- 前端生产构建成功，586 个模块，主 JS 1706.57 kB，gzip 579.75 kB，出现大包告警。第一次因输出目录创建限制失败，预建隔离目录后重试通过。
- 新构建主 JS 与 frontend/dist、resources/static 中同名文件哈希一致；当前证据不支持把故障主要归因于该前端文件陈旧。
- Maven test 在指定已有本机依赖仓库后 BUILD SUCCESS，但明确输出 No tests to run。默认仓库路径曾落到 C:\.m2 并失败，说明环境可移植性仍需治理。

测试原始证据见 .audit/results.json、.audit/java.out.log、.audit/python.err.log、.audit/probe.cjs、.audit/RuleProbe.java。

边界：未执行浏览器像素级截图/拖拽回归，不能断言 Canvas 的实际截图效果；未验证真实和风账号、DeepSeek 网络调用和外部渠道送达；未做并发负载、长稳或完整依赖漏洞扫描。下面明确区分实测、源码确定缺陷与待验收事项。

## 3. 地图问题根因与修复设计

### M1：天气图层尚未实现——源码确认，P0/P1

App.vue 的四个按钮调用 /api/sim/switch；PanelMap.vue 只有航线、航点、单风向线、作业点、矩形范围及标签，没有风场网格、降水栅格、雷电点或天气图层开关。precipMmh、thunderProb 没有进入独立空间图层渲染。

处理：将“模拟剧本”与“显示图层”分为两组控件。第一组改变数据，第二组只改变可见性，支持风、降水、雷暴、风险区、航线独立开关与叠加。短期用单点观测符号和明确标注的演示覆盖区恢复可辨识体验；真实风险热力必须取得空间数据，不能把单点概率扩画成真实雷暴分布。

### M2：WebSocket 数据更新被前端丢弃——实测，P0

MonitorService.runOnce 直接广播 buildDashboard()；该 Map 没有 type。api.js 只在 msg.type==='dashboard' 时更新 store。

处理：REST 与 WS 使用同一个 Dashboard DTO；WS 统一信封 {type:'dashboard', version:1, runId, payload}，前端按 payload 更新。也可先用补 type 的兼容修复，后续一次性迁移协议。增加序号/运行 ID，拒绝过期消息，重连后重新 GET 全量快照。

注意：同页按钮成功后会用 POST 返回值更新 store，所以该缺陷主要解释定时刷新、其他客户端操作和实时同步失效，不能单独解释所有点击无变化。

### M3：风向和天气描述在后端丢失——实测与源码确认，P0

WeatherSnapshot 和 Python 有 windDeg；SfiRecordEntity 未存储该字段，buildDashboard 也未返回。地图因此执行 windDeg ?? 0，以默认北风绘制向南的风线；天气描述也变为空。

处理：保留完整标准化 WeatherSnapshot，持久化 obsTime、windDeg、conditionText、坐标及质量信息。未知风向显示“未知”，不默认 0。区分 obsTime（观测）、ingestedAt（接入）、evaluatedAt（研判），避免把入库时间显示为观测时间。

### M4：谨慎区被画成绿色——源码确定，本次接口结果可触发，P0

risky 仅检查 DANGER/BAN；CAUTION 与 FIT 共用绿色范围。rain/wind 此次均为 CAUTION，看起来与晴好类似。DANGER/BAN 又共用“风险影响区（禁入）”，无法区分。

处理：所有图元都从统一等级样式表读取四级色彩及文案；同时显示主要风险因素。矩形必须标注示意，真实边界取自区域数据。地图标题短期改为“气象与作业态势”，待真实热力实现后再使用“风险热力”。

### M5：交互状态不完整——源码确认，P0/P1

切换时提前设置 store.scenario，失败仅 console.warn；postAction 不检查 r.ok，没有超时与 loading。runOnce 等待轨2和推送，网络慢时用户持续看旧图。每轮 setOption 重设 zoom/center，可能打断用户视角。watch 未独立监听经纬度。

处理：区分 requestedScenario 与 appliedScenario；运行中禁用重复提交或采用 latest-wins 队列；成功后再确认场景，失败保留原状态并提示。补错误码、请求期限和取消机制。地图初始化与数据更新分开，保留 geo 视角，提供“回到作业区”；使用 ResizeObserver；加入坐标变更监听、稳定 series.id、图层移除后的残留清理。

### 地图目标数据契约

建议分为监测快照与空间图层两个资源：

- Dashboard：runId、regionId、configuredMode、effectiveSource、degraded、degradeReason、obsTime、updatedAt、snapshot、track1、track2、fusion、forecast。
- Layer：id、kind、source、isSimulated、validTime、expiresAt、crs、units、bbox、geometry/data、quality、status。
- 风：点位矢量或 u/v 网格；降水：带单位的网格/栅格；雷电：真实事件点及时间，或明确命名的预报概率网格；风险区：规则计算与区域边界关联的多边形。
- 雷暴概率、实际闪电与官方预警须分别表达，不能混为同一指标。
- 每个图层展示加载中、已更新、无数据、已过期、错误状态；失败不静默显示旧图。

短期保留 ECharts，避免在数据问题未修复前更换地图引擎。只有真实瓦片、连续风场和大量空间要素达到明确需求后，再做专用 GIS 渲染方案选型与性能原型。

## 4. 全链路必须同步处理的问题

| 优先级 | 问题与证据 | 优化动作 |
|---|---|---|
| P0 | @Scheduled(initialDelay=6000,timeUnit=MINUTES)，首次延迟 100 小时 | 分别用明确时长表达初始 6 秒、周期 10 分钟；增加首次成功观测的就绪判断 |
| P0 | SfiEngine 的 banned 标识只扣分，没有等级硬约束；Java 探针已复现 | 先确定业务规则是否为硬禁飞；如为硬阈值，任一命中直接设 BAN，SFI 与等级含义一致，贯穿融合和预警 |
| P0 | live 失败生成 sim，但 dashboard.mode 仍为 live，界面可能显示实时 | 分离配置模式和有效来源；生产实时缺失显示不可用/过期，模拟仅用于明确演示；禁止静默伪装实时 |
| P0 | 骤降检测在保存当前记录后查询最新记录，通常拿到自己 | 保存前取上一条，或按同区域、同来源及更早时间查询；用主键值比较；排除模拟场景切换污染真实骤降统计 |
| P0 | scenario 未校验，失败后非法状态保留；switchScenario 在锁外改共享状态 | 枚举校验返回 400；一次运行内冻结 scenario；原子提交场景和快照，失败不改变已生效场景 |
| P0 | /api/system/shutdown 未鉴权，按 8600 端口杀进程；WS 允许任意来源 | 演示绑定回环；部署版移除业务关机接口或仅管理员可用；按受管 PID 停止，鉴权并限制来源 |
| P1 | Java 等轨2最多 90 秒，Python 3 次 45 秒配置可能超过调用方期限 | 规则结果优先发布，轨2异步补全；传播 runId 和总 deadline；重试退避、熔断、缓存；拒绝旧结果回写 |
| P1 | AlertService 直接采用轨2 advice，可能与保守融合等级冲突 | 规则模板决定操作建议，模型只补充解释；对等级/建议一致性校验 |
| P1 | 多表分别保存、预报/场景/时间分开更新，没有运行级一致性 | 建 monitoring_run 及 runId 外键；结果事务提交；读同一运行快照；事务提交后异步通知 |
| P1 | Python fallback 没温度项，阈值和 Java 多处复制；非法等级 Java 默认 FIT | 统一版本化规则配置；严格输入/输出 schema；未知数据或等级标为不可判定而非适飞 |
| P1 | 和风解析大量缺省为 0 或良好能见度；雷暴概率通过代码/降水概率估算 | 校验必需字段、数值范围、单位和时间；估计字段标明方法与质量；缺失不补成安全观测 |
| P1 | 每次危险都新建预警；渠道同步发送，HTTP 200 直接算成功 | 告警去重、升级/解除/冷却状态机；事务 outbox、幂等和重试；解析渠道业务响应码 |
| P1 | SCREEN 在真正广播前就记 SENT，页面把 SENT 译为送达 | 区分生成、入队、发送、客户端确认；无客户端不能记送达；历史成功与当前健康分开 |
| P1 | 配置齐全即“已接入”，WebSocket 连上即“正常” | 展示配置、连接、最后成功、数据新鲜度和处理延迟；增加 readiness/liveness 和链路指标 |
| P1 | 前端开发请求直连 127.0.0.1:8085，预检实测 403 | REST 使用相对 /api，WS 使用同源 /ws，统一走 Vite 代理与生产反代 |
| P1 | 配置目录包含真实私钥文件；H2 console 开启；缺少权限体系 | 密钥移出项目分发物，环境变量/受控文件注入；检查分发历史再决定轮换；部署关闭 console、鉴权和日志脱敏 |
| P2 | 预报重启丢失，历史条数固定，无清理/备份设计 | 持久化完整快照与预报；时间索引、分页、保留策略、备份恢复验证；多用户部署再迁移数据库 |
| P2 | 全量 ECharts 单包约 1.7 MB，多个动效和整屏固定缩放 | 按需注册图表模块、拆包、生产压缩缓存；动态效果按可见性暂停；添加常用分辨率和低性能设备验收 |

Spring 的 timeUnit 同时作用于 initialDelay 和 fixedDelay 等参数，官方 API 可核对：https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/scheduling/annotation/Scheduled.html 。因此首次调度结论来自明确的单位语义，而非等待 100 小时实测。

## 5. 工程化与交付优化

1. 增加 Maven Wrapper；Python 固定依赖版本并提供虚拟环境初始化；Node 固定版本，构建使用 npm ci。启动前检查环境、配置、端口归属和 Python 就绪。
2. 提供 dev/demo/prod 配置分层及无凭据示例。当前“唯一配置”仍有类路径 import 与外部文件，要明确优先级、路径解析和启动覆盖规则。
3. 统一打包来源，不依赖 resources/static 手工复制；临时干净目录生成发布物，内含 buildId、commit/源码摘要、构建时间、依赖版本。只清理受管输出路径。
4. start.bat 不能仅因 JAR 存在便认为可用；构建失败立即终止，检测服务属于本项目而非端口上任意进程。
5. 结构化日志串联 runId、scenario、source、阶段耗时与错误码；限制错误内容，避免凭据和完整 webhook 入日志。
6. 前端统一 API 客户端、错误提示和状态管理；卸载关闭 WS、重连计时器，重连指数退避并补快照；多请求乱序保护。
7. SFI 图表的 markLine 当前放在 yAxis 内，应放入对应 series；修复后验收 80/60/40 阈值线。预测与观测时间统一时区，并明确预测区间。
8. 建测试和 CI，构建成功不等于业务通过；当前 Maven 没有测试、前端无 test script，必须先补关键回归用例。

## 6. 分阶段实施与成本

估算按熟悉现有栈的开发人员有效工作日，包含开发与基础验证，不含采购气象数据、账号审批或外部系统等待。阶段有交叉，不能当成承诺工期。

| 阶段 | 预计工作量 | 交付与退出条件 |
|---|---|---|
| A：稳定演示主链路 | 2–4 人日 | 修调度、WS、snapshot、场景事务/校验、开发代理、loading、四级地图色；处理硬阈值与来源误标；四剧本、双客户端同步和首次启动通过 |
| B：天气图层演示版 | 3–5 人日 | 独立图层开关、风向/强度符号、降水/雷暴示意、图例/时效/状态、视角保持和确定性模拟数据；各图层可独立验收 |
| C：可靠性与权限 | 4–7 人日 | runId、事务快照、轨2异步、告警状态机/outbox、鉴权、密钥隔离、健康指标和关键自动化测试 |
| D：真实空间气象 | 5–10+ 人日 | 先取得一份合法样例，确认覆盖、分辨率、时效、单位和接口，再完成图层适配、空间风险计算、回放和性能验证；数据未落实不启动大改造 |
| E：可维护部署 | 2–4 人日 | 可复现构建、版本信息、配置模板、安装/升级/回滚、数据库备份恢复演练、使用与运维文档 |

最有价值的顺序：A → B → C；D 依赖数据可用性并单独设门槛；E 可随 A/C 逐步完成。暂缓第三轨 ML、更多推送渠道和微服务拆分，先补齐现有主链路。

## 7. 验收矩阵

以下为建议验收门槛，未表示本次已经通过。

| 范围 | 用例 | 通过标准 |
|---|---|---|
| 首次启动 | 空数据库，Python 可用 | 应用就绪后约 6 秒触发首轮；总完成期限独立配置；页面准确显示等待与失败原因 |
| 模拟切换 | clear→wind→rain→storm→clear，使用固定 seed/clock 的 fixture | 按钮已生效态、快照、地图与预警属于同一 runId；不强求随机场景固定等级 |
| 地图图层 | 每层单独/组合开关；切换、清空、断网 | 图层确实增删，无残留，有对应图例/单位/来源/时效；无数据不等于零风险 |
| 风向 | 0/90/180/270 度、缺失风向 | 箭头按气象来向转换吹去方向，缺失时不画虚构箭头 |
| 地图视角 | 缩放拖动后再监测 | 视角保持；回中按钮有效；至少 1366×768、1920×1080 无遮挡 |
| 实时同步 | 两浏览器，一端切换；断连重连 | 另一端无需刷新更新；重连补齐快照；不出现旧消息覆盖新结果 |
| 规则边界 | 每项阈值前/等于/后；缺失、负数、NaN；温度上下界 | 与经业务确认的规则版本完全一致，禁飞标志与最终等级不冲突 |
| 骤降 | 同区域上一轮 100→65 且在 60 分钟内，融合不到危险 | 仍触发 SFI_DROP；过窗、不同区域或不同来源不错误触发 |
| 异常输入 | 非法场景、空提问、超长输入 | 400/422，已生效状态不变，无额外计费/后台任务 |
| 外部故障 | 和风超时、Python 不可用、LLM 超时/非法 JSON | 来源与降级可见；规则先反馈；后台任务有期限，不把未知标成适飞 |
| 预警 | 连续同级、升级、解除、重试；HTTP 200 业务失败 | 无重复轰炸；正确状态转换；业务失败记失败；送达有真实证据 |
| 数据一致性 | 轨2失败、落库失败、重启和同时请求 | 单个运行数据可追溯；不混合不同轮次；恢复后预报和观测关联一致 |
| 性能 | 模拟无 LLM、目标演示设备 | 建议操作至规则态势更新 P95 <1 秒；初次可用 <3 秒；拖动平均 ≥30 FPS，按真实基准修订 |
| 安全与交付 | 非管理员控制请求、发布目录扫描、安装重建 | 受限操作被拒绝；无私钥/凭据/工作库外发；全新环境可按文档启动 |

## 8. 关键源码定位

- frontend/src/App.vue：switchScenario、runNow、场景按钮。
- frontend/src/api.js：postAction、connectWs、initRealtime。
- frontend/src/components/PanelMap.vue：windLine、draw、risky、watch。
- backend-java/src/main/java/com/tianchuang/service/MonitorService.java：第 92 行调度；runOnce、switchScenario、checkAndAlert、buildDashboard。
- backend-java/src/main/java/com/tianchuang/entity/SfiRecordEntity.java：快照字段缺失。
- backend-java/src/main/java/com/tianchuang/service/SfiEngine.java、FusionService.java：规则与融合。
- backend-java/src/main/java/com/tianchuang/service/AlertService.java、PushService.java：预警与渠道状态。
- backend-java/src/main/java/com/tianchuang/controller/DashboardController.java：场景接口、关机接口。
- backend-python/track2_agent.py：同步重试、fallback、schema。
- backend-java/src/main/java/com/tianchuang/qweather/QweatherClient.java：字段默认值与雷暴估算。

本方案的首要成果应是“每次操作有反馈、每次更新可追溯、每个图层有真实含义”，再逐步提升视觉和智能化能力。
