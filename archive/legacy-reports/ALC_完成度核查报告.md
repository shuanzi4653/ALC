# 天窗智巡 0.9.0（Beta） 更新完成度核查报告

> **版本标识对照（2026-09-19 起）**：本文件的编号按新口径对应 **0.9.0（Beta）**；正文保留当时原措辞，未逐字回改。

核查日期：2026-09-10
核查对象：`C:\Users\12921\Desktop\ALC`（GPT-6 完成的更新）
对照文档：`CODING_PLAN.md`（具体编码实施计划）、`OPTIMIZATION_PLAN.md`（项目审查与优化方案）
核查方式：源码逐项比对 + 三端构建/测试实际执行 + 隔离服务 REST 联调实测

---

## 一、总体结论

**完成度约 55%~60%，集中在 A 阶段主链路 + B01 后端图层 + C01/C03 部分 + E01 脚本层。**

三个阶段的骨架已经立起来了：运行标识与完整快照、场景原子性与 400/409 校验、硬禁飞约束、图层资源接口、预警状态机与 outbox、受管启动脚本都已落地且**在全新数据库下实测跑通**。

但存在一个**阻断级问题**：**数据库迁移没有做**。当前仓库自带的 `data/tianchuang.mv.db`（旧库）下启动后 `/api/dashboard` 与 `/api/health/ready` 直接 500，应用实际不可用。这正好命中了优化方案第 8 节「不能靠 `ddl-auto=update` 隐式修改生产数据」的预警。

---

## 二、阻断级问题（必须先修）

### P0-1：旧数据库与新实体不匹配，核心接口 500

**实测证据（使用仓库自带 data/tianchuang.mv.db 启动）：**

```
DDL 失败：alter table if exists alert add column transition_version integer not null
         → NULL not allowed for column "TRANSITION_VERSION"
查询失败：Column "SRE1_0.CLOUD_COVER" not found
         → /api/dashboard = 500
         → /api/health/ready = 500
```

**根因**：本次为 `WeatherSnapshot` / `SfiRecordEntity` / `AlertEntity` 新增了 `cloud_cover`、`condition_text`、`pressure_hpa`、`wind_deg`、`transition_version` 等字段，但只依赖 Hibernate `ddl-auto=update` 隐式加列：
- 给已有数据的表加 `NOT NULL` 无默认值列 → 立即失败
- `alert` 表 DDL 失败后，后续表的结构变更未能完整执行 → `sfi_record` 新列缺失
- 查询语句引用了不存在的列 → 接口 500

**对照计划**：第 8 节「数据库迁移与回退方案」明确要求引入 Flyway（V1 基线 / V2 运行快照 / V3 异步 / V4 预警 / V5 历史治理），并要求每批在副本上验证「旧库升级、空库创建、重复启动」。**该部分完全未实施。**

**建议**：
1. 引入 Flyway，先把现有 schema 导出为 V1 baseline，再用 V2 增量脚本以「可空列 + 回填」方式补字段；
2. 或（演示阶段的务实做法）提供 `scripts/reset-db.ps1` 重置演示库，并在 README 说明「升级 0.9 需重建数据库」；
3. **在修复前不要用旧库启动**，否则每次启动都会触发失败的 DDL 尝试。

### P0-2：注意事项 — 核查过程对旧库的影响

本次核查为定位问题，用旧库启动过一次服务，Hibernate 对该库执行了 DDL 尝试（`alert` 表加列失败，部分表可能已有结构变更）。建议：
- **先备份 `data/` 目录**再决定是迁移还是重建；
- 若演示数据可丢弃，直接删除 `data/tianchuang.mv.db` 用新库启动即可（已实测新库下全部接口正常）。

---

## 三、逐任务完成度对照

### G 阶段（基础准备）

| 任务 | 状态 | 已完成 | 未完成 |
|---|---|---|---|
| G01 隔离验证环境 | 部分 | Java 测试 3 类 10 例全通过；Python 测试 2 文件 5 例全通过；`requirements-dev.txt` | `contracts/`、`tests/fixtures/`、`scripts/test-local.ps1`、前端 vitest/playwright 配置**全部缺失**；前端零测试 |
| G02 规则与契约冻结 | **未完成** | — | `contracts/dashboard-v1.schema.json`、`ws-v1.schema.json`、`layer-v1.schema.json`、`docs/architecture-decisions.md`、`tests/fixtures/rule-cases.json` 均不存在 |

### A 阶段（稳定主链路）

| 任务 | 状态 | 已完成 | 未完成 |
|---|---|---|---|
| A01 运行标识/完整快照/事务 | **基本完成** | `MonitoringRunEntity`+Repo、`RunCommitService`、runId/runSequence/revision、snapshot 15 字段（windDeg/conditionText/cloudCover/pressureHpa）、obsTime 带时区 | `DashboardDto`/`WsEnvelope`/`ErrorResponse` 独立 DTO 类（仍用 Map 拼装）；无 `DashboardAssembler` |
| A02 调度/场景原子性/真实来源 | **完成** | 毫秒双配置（6000/600000）、`Scenario` 枚举校验→400、`runLock.tryLock` single-flight→409、appliedScenario 成功后才更新、configuredMode/effectiveSource/degraded 分离、live 拒绝切换 | `RunContext` 独立类（用局部变量替代，可接受） |
| A03 硬约束/未知值/骤降 | 部分 | `hardBanEnabled`+`hardBan`（sfi=min(raw,39)、level=BAN）、rawSfi、`ObservationValidator`、骤降按 区域+来源+规则版本+场景+TsBefore 查询 | **阈值未配置化**（`config/rules-v1.json` 不存在，80/60/40 与各项扣分仍硬编码在 `SfiEngine`）；`RuleProperties` 只有 version+hardBanEnabled；`UNDETERMINED` 状态未确认 |
| A04 前端 API/WS/操作状态 | **基本完成** | 相对 `/api`、AbortController 超时、统一错误码+retryable、store 分离 requested/applied/pending/connectionState、WS 信封校验（version+type+payload）、指数退避 1→30s、旧消息拒收 | `useRealtime.js`、`RequestStatus.vue`、`store.js` 拆分为独立 store（逻辑已内联实现）；前端测试 |
| A05 地图与面板纠错 | 部分 | `markLine` 已移入 SFI series（80/60/40 生效）、PanelTop 分离「配置/连接/新鲜度」、`resetView`+「回到作业区」、图层状态与图例标签 | **`LEVEL_STYLES` 统一等级样式表未做**（`utils.js` 仍是 LEVEL_COLORS + LEVEL_LABELS 两张表）；地图标题未改「气象与作业态势」；DANGER/BAN 文案细分待确认 |
| A06 关闭危险入口 | **基本完成** | HTTP shutdown 接口与 `killPort` 已移除、WS `setAllowedOriginPatterns` 限定回环、start/stop 脚本校验端口不杀进程 | H2 console 未在生产关闭；真实私钥仍在 `config/qweather/` 分发目录内 |

### B 阶段（独立天气图层演示版）

| 任务 | 状态 | 已完成 | 未完成 |
|---|---|---|---|
| B01 图层资源与确定性生成 | 部分 | `LayerDto`/`LayerController`/`LayerService`；实测 5 类图层（WIND/PRECIPITATION/THUNDER_PROBABILITY/RISK_AREA/LIGHTNING），带 `isSimulated=true`、`quality.spatialMeaning=DEMO_SYMBOL`、LIGHTNING 正确返回 `NO_DATA` | `P/layers.py`（Python 侧确定性生成、固定 seed/clock）；图层 fixtures；`LayerController` 的 runId 失配行为待复测 |
| B02 图层控件/图例/状态 | 部分 | `useMapLayers.js`（runId 竞态丢弃、generation 保护、onScopeDispose 清理）、PanelMap 内嵌图层复选框 + 图层状态文案 | `MapLayerControls.vue`、`MapLayerLegend.vue`、`map/layerRenderers.js`（独立渲染器 + 稳定 series.id）**均缺失** |
| B03 地图视角/尺寸/性能 | 部分 | `resetView` 回中按钮 | `initMap/updateLayers/resetView` 拆分、`georoam` 视角保存、`ResizeObserver`、性能基准（FPS） |

### C 阶段（异步研判、可靠预警、权限）

| 任务 | 状态 | 已完成 | 未完成 |
|---|---|---|---|
| C01 规则先发布/轨2异步 | 部分 | `AsyncConfig`（track2Executor，core1/max2/AbortPolicy）、`track2Executor.execute` 异步补全、RULE_READY/COMPLETE 状态、**实测 revision=2 证明异步补全生效** | **`Track2JobEntity`+Repo（任务持久化）缺失** → JVM 崩溃任务丢失；deadline 预算传递与重试；缓存/熔断；`P/schemas.py` |
| C02 Java/Python 规则一致 | 部分 | `QweatherClient` 有改动（需细验字段校验） | `P/rules.py`、共享 `rules-v1.json`、跨语言 golden cases、Python fallback 温度项、单位/过期校验 |
| C03 预警状态机/outbox/送达 | 部分 | `AlertStateEntity`+Repo+`AlertStateService`（INACTIVE/ACTIVE/RESOLVED、episodeId、RESOLVE 决策）、AlertService 接入、`PushService` outbox（`existsByEventKey` 幂等 + 入队 + 异步投递 + 业务码校验）、SCREEN 在线才记 SENT、`AlertStateServiceTest` 3 例通过 | `OutboxDispatcher` 独立类（功能内联在 PushService）；各渠道 adapter 业务码完整实现；`alert_ack` 协议；冷却/解除轮数配置化 |
| C04 权限/配置/健康指标 | 部分 | `HealthController`（`/api/health/live`、`/ready`） | **`SecurityConfig` 未做**（未引入 Spring Security，无登录/VIEWER/OPERATOR/ADMIN）；`LoginPanel.vue`；结构化日志与指标；dev/demo/prod 配置分层 |

### D 阶段（真实空间数据）

| 任务 | 状态 | 说明 |
|---|---|---|
| D00 / D01 | **未开始** | `docs/spatial-data-contract.md`、`J/spatial/` 包均不存在。**符合预期**——计划明确要求数据准入通过后才启动 |

### E 阶段（构建、部署、维护）

| 任务 | 状态 | 已完成 | 未完成 |
|---|---|---|---|
| E01 可复现构建/受管启动 | **基本完成** | `scripts/build.ps1`（用 `target/generated-resources/static`，不手工复制）、`start.ps1`（校验 venv/JAR/端口占用不杀进程 + `Wait-Json` 就绪 + `.run` 目录 + 非零退出）、`stop.ps1`、`config/application.example.yml`、三个 .bat 薄封装 | **Maven Wrapper 缺失**（`mvnw` 不存在，build.ps1 仍回退 IDE Maven 绝对路径）；`docs/deployment.md`；buildId/checksum/源码摘要；发布目录扫描（私钥排除） |
| E02 历史分页/保留/备份 | **未完成** | — | 历史分页接口、保留策略、备份恢复脚本均无 |
| E03 前端包体/动画/CI | **未完成** | — | 无 `F/echarts.js` 按需注册（实测单包 **1.71 MB**，gzip 581 kB 告警）；无 CI |

---

## 四、本次实测记录（可复现）

### 构建与测试

| 项目 | 命令 | 结果 |
|---|---|---|
| Java 编译 | `mvn -DskipTests compile` | ✅ 通过 |
| Java 测试 | `mvn test` | ✅ **10/10 通过**（AlertStateService 3 + FusionService 2 + SfiEngine 5） |
| Python 测试 | `.venv\Scripts\python.exe -m pytest tests -q` | ✅ **5/5 通过**（需先 `pip install pytest`，venv 未预装） |
| 前端构建 | `npm run build` | ✅ 通过，主包 1710.98 kB / gzip 581.18 kB（触发大包告警） |

### 隔离服务联调（全新数据库，未污染原库）

| 用例 | 结果 |
|---|---|
| `GET /api/health/live` | ✅ 200 |
| `GET /api/health/ready` | ✅ 200 |
| `GET /api/dashboard` | ✅ 200：version=1、runSequence=1、**revision=2**、status=COMPLETE、dataStatus=FRESH、configuredMode=sim、effectiveSource=sim、degraded=false、appliedScenario=clear |
| snapshot 字段完整性 | ✅ 15 字段全含（含 **windDeg=221**、**conditionText=晴**、cloudCover=0.27、pressureHpa） |
| `POST /api/sim/switch?scenario=wind` | ✅ 200，applied=wind、SFI 62 CAUTION、runSequence=2 |
| `POST /api/sim/switch?scenario=invalid` | ✅ **400**（旧版为 500，修复生效） |
| `GET /api/layers?...` | ✅ 5 层：WIND/PRECIPITATION/THUNDER_PROBABILITY/RISK_AREA = READY，LIGHTNING = NO_DATA，isSimulated=true |
| **旧数据库下启动** | ❌ dashboard=500、ready=500（见 P0-1） |
| 并发 409 | ⚠️ 未复现（`runLock.tryLock` 逻辑存在，因单轮规则先发布耗时极短，两次并发请求均 200 完成；建议后续用延迟注入复测） |

### 优化方案中已确认修复的原始缺陷

| 原始问题 | 状态 |
|---|---|
| M2 WebSocket 消息无 type 被前端丢弃 | ✅ 已修（v1 信封 + version 校验） |
| M3 windDeg/conditionText 丢失 | ✅ 已修（实测 snapshot 含 windDeg=221、conditionText=晴） |
| 首次调度 100 小时（timeUnit 误用） | ✅ 已修（`initialDelayString=6000` + `fixedDelayString=600000`） |
| banned 只扣分、不硬禁飞 | ✅ 已修（hardBan → level=BAN，sfi=min(raw,39)） |
| 非法 scenario 返回 500 且污染状态 | ✅ 已修（400 + 场景原子性） |
| 骤降查询拿到自己 | ✅ 已修（TsBefore + 来源/规则版本/场景隔离） |
| shutdown 未鉴权按端口杀进程 | ✅ 已移除接口 |
| 开发请求直连 8085 跨域 403 | ✅ 已修（相对 /api + Vite 代理） |
| PanelSfi markLine 放错层级 | ✅ 已修（移入 series） |

---

## 五、建议的下一步优先级

**P0（阻断，先做）**
1. 数据库迁移方案落地（Flyway baseline + 增量，或重置脚本 + 文档说明）；
2. 备份现有 `data/`，确认升级路径。

**P1（影响交付质量）**
3. G02 契约文件（三份 schema + architecture-decisions.md）；
4. 规则阈值配置化（`config/rules-v1.json`，Java/Python 共读）；
5. C01 任务持久化（`Track2JobEntity` + Repo，防崩溃丢任务）；
6. C04 引入 Spring Security（登录 + 三角色）。

**P2（体验与工程化）**
7. B02 独立图层控件 `MapLayerControls.vue` / `MapLayerLegend.vue` / `layerRenderers.js`；
8. `LEVEL_STYLES` 统一等级样式表 + 地图标题改名；
9. E03 按需注册 ECharts（当前单包 1.71 MB）；
10. 前端测试（Vitest + Playwright）与 `scripts/test-local.ps1` 聚合入口；
11. Maven Wrapper + 私钥移出分发目录。

---

## 六、计划文档中未覆盖但值得记录的事项

1. **Python 环境缺 pytest**：`requirements-dev.txt` 写了依赖，但 `.venv` 未安装，测试无法开箱运行。建议在 `scripts/build.ps1` 或初始化脚本中加 `pip install -r requirements-dev.txt`。
2. **未提交的工作量**：git 仅有 2 个初始提交，所有 0.9 改动都处于未提交状态。建议按计划的 PR-01~PR-11 拆分提交，便于回溯与回退。
3. **`_stop_test` 等临时文件**：核查过程产生的临时数据库与测试文件已清理，原 `data/tianchuang.mv.db` 保留未删。
