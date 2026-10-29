# 0.9.5（Beta） → 0.9.6（Beta） 迁移说明

适用对象：在本机继续运行、回退或复用该项目的人。

> **版本号口径（2026-09-19 起）**：版本线自 **0.9.0** 起只递增第三位 `z`，全部版本为测试版本。
> 本文件原记的旧标识 `V1.2` / `V1.3` 分别对应 **0.9.5（Beta）** / **0.9.6（Beta）**
> （新旧对照见 `changelog/CHANGELOG.md` §版本总览）。
> 为避免批量替换改坏句子，**下表的程序文件值保留当时的原始写法**，
> 同时给出当前口径下的标识；`city-traffic-1.x` 与 `traffic-plan-v1.x` 是**内部标识符**（非产品版本号），保持不变。

## 1. 版本与合同

| 项目 | 0.9.5（Beta）（旧记 V1.2） | 0.9.6（Beta）（旧记 V1.3） |
| --- | --- | --- |
| `VERSION` | `1.2.0`（当时） | `1.3.0`（当时） |
| `backend-java/pom.xml` | `1.2.0`（当时） | `1.3.0`（当时） |
| `frontend/package.json` | `1.2.0`（当时） | `1.3.0`（当时） |
| Python 交通模块 `VERSION` | city-traffic-1.2 | city-traffic-1.3 |
| `planRevision` | traffic-plan-v1.2 | traffic-plan-v1.3 |
| 交通接口合同 | `contracts/traffic-v1.2.openapi.json` | `contracts/traffic-v1.3.openapi.json` |

> 截至当前版本（**0.9.13（Beta）**），程序文件的版本值已统一为 **`0.9.13-beta`**
> 且 Maven/npm 不接受全角括号，所以文件里写 semver 形式，文档里写 `（Beta）` 形式。

`contracts/traffic-v1.2.openapi.json` 保留作为历史对照，不是当前有效合同。

## 2. 时间语义迁移（必须阅读）

旧版把 `departureMinute` 直接标成“实际放行”，未来班次也会显示该值。0.9.6（Beta） 拆分为：

| 字段 | 含义 |
| --- | --- |
| `requestedDepartureAt` / `scheduledMinute` | 申请起飞时间 |
| `plannedReleaseAt` / `departureMinute` | 本版本排程允许的时隙（未分配为空） |
| `actualReleaseAt` | 推演执行中实际签发放行的时间，未来为空 |
| `actualTakeoffAt` | 实际进入起飞阶段的时间 |
| `estimatedArrivalAt` | 按当前有效航迹计算的预计到达 |
| `actualArrivalAt` | 执行到达事件产生的时间，未发生为空 |
| `planRevision` | 班次所属排程版本，用于拒绝旧界面操作新计划 |

时间基准固定在 `SIMULATION_BASE_TIME = 2026-09-14T10:00Z`，界面统一按 `Asia/Shanghai` 显示为 `09-14 18:00:00`，并附相对推演轴 `T+00:00:00`。刷新、恢复会话和回放都不会改变 `baseTime`。

**旧数据兼容性**：任何按“`departureMinute` 就是实际发生时间”读取的旧代码，在 0.9.6（Beta） 下都会读错语义。必须改成按 `flightState(f, minute)` 判断事件是否已经发生。

## 3. 缓存失效规则

交通计划缓存键由 `identity()` 计算，输入为：

```
VERSION : FINGERPRINT : PLAN_REVISION : seed : scenario : weatherSnapshotId
```

其中 `FINGERPRINT` 是 `traffic/*.py`、机型参数文件与 `BOUNDARY_VERSION` 的 sha256。因此：

- 改动任何 `traffic/` 下的 Python 文件或机型参数 → 指纹变化 → 旧缓存自动失效。
- 改动城市目录 `data/traffic/city-centers.json` → **不会**单独改变指纹，但 0.9.6（Beta） 已把目录解析结果并入计划输出；如果手工替换了目录，请删除 `.run/traffic/` 下的缓存文件，或在首次运行时使用新的 `seed`。
- 切换 `scenario` 或 `seed` → 天然生成不同 key。
- 天气快照 ID 变化（`live` 场景下）→ 生成新计划，不会命中旧快照。
- 命中缓存前会校验 `fingerprint` 与 `planRevision` 两者都匹配，任一不符即重新计算。

删除缓存的正确方式：停止服务后删除整个 `.run/traffic/` 目录。该目录只是可重建的计算产物。

## 4. 新增配置项（全部可选）

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ALC_TRAFFIC_WEATHER_PROVIDER` | `open-meteo` | 设为 `qweather` 时优先读和风，失败则显式降级到 Open-Meteo 并加质量标记 |
| `ALC_JAVA_BASE` | `http://127.0.0.1:8085` | Python 读取 Java 内部原始天气接口的基地址 |
| `ALC_INTERNAL_TOKEN` | 空 | 与 Java 侧 `qweather.internal-token` 一致时，作为 `X-Internal-Token` 发送 |
| `ALC_QWEATHER_MAX_CITIES` | `36` | 单次快照最多请求的城市数，用于控制外部配额 |

Java 侧 `application.yml` 可选新增：

```yaml
qweather:
  internal-token: ""   # 留空则 /api/internal/qweather/** 仅允许本机回环地址调用
```

未配置令牌时，内部原始天气接口只接受本机回环调用，并带 60 秒缓存。

## 5. 回退方法

1. 停止服务：双击 `stop.bat`。
2. 展开 `backups/v1.2_before_v1.3/source-v1.2.0.zip`（**备份目录名与包名保持当时的写法，未改**），覆盖对应源码路径。
   - 清单与基线提交记录见同目录的 `MANIFEST.txt`（`baselineCommit=6bfa8250e13f26348ec4d611c649db0c1d652604`）。
   - 备份不含 `backend-java/src/main/resources/application.yml`、`*.pem`、`*.key`、`*.secret`，回退时请保留当前凭据文件。
3. 删除 `backend-python/traffic/` 下 0.9.6（Beta） 新增文件：`airspace.py`、`resources.py`、`delivery.py`、`obstacles.py`、`weather_sources.py`。
4. 删除 `.run/traffic/` 缓存与 `frontend/dist/`。
5. 重新执行 `start.bat`。

回退到更早版本请使用 `backups/v1.0_source_before_city_network/` 或 `backups/v0.12_source_before_v1.0/`。

## 6. 未迁移项

以下内容本轮未改动，仍按 0.9.5（Beta） 行为运行：

- 前端登录、预警推送、智能体研判与历史记录的既有实现。
- 数据库结构与 Flyway 迁移脚本（无新增迁移）。
- 三维地图框架（MapLibre + Three.js），未整体替换。
