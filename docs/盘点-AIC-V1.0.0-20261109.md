# 天窗智巡（AIC）· V1.0.0 全量盘点

盘点时间：2026-11-09 13:15　|　盘点口径：GitHub 仓库（HEAD `b177b9d`）+ 云端实机巡检 + 归档记忆 74 份
用途：下一轮「大范围全面更新」的基线。凡未实测的数字一律标注来源。

---

## 0. 命名口径（先纠正，后文全部按此书写）

**本项目是 AIC，不是 ALC。** 正式名称：**天窗智巡 · 低空交通协同运行管理系统**，参赛编号 **AIC-2026-41989115**，队名 **知之队**，赛道：第八届全球校园人工智能算法精英大赛 · 智慧气象。

以下标识里的 `ALC` **是历史命名失误，但已成路径/契约，不动**（改名会断迁移脚本、缓存键与文档链接）：

| 保留 `ALC` 的位置 | 值 | 不动的原因 |
|---|---|---|
| 本机工作目录 | `C:\Users\12921\Desktop\ALC` | 记忆目录也锚在这里，改不动 |
| GitHub 仓库 | `github.com/shuanzi4653/ALC` | 公开地址已对外 |
| 匿名工作区请求头 | `X-ALC-Workspace` → Cookie `alc_ws` | 前后端契约 + 线上缓存键 |
| 归档目录 | `G:\项目与竞赛归档\天窗智巡（AIC 智慧气象 · AIC-2026-41989115）\` | 已带 AIC 正名 |

其余一切（服务名、部署目录、文档、版本、材料）都用 **AIC**：云端名 `AIC-tianchuang`、单元 `AIC-tianchuang.service`、包名 `tianchuang-server.jar`、前端 `tianchuang-dashboard`。

---

## 1. 一句话结论

项目已收口在 **V1.0.0 正式版**（2026-10-28 上线，2026-10-29 17:20 最后一次构建），
**51 天内发了 62 个版本号**，代码 932 文件 / 19.5 MB / 约 10.6 万行有效代码（另 8.7 万行文档），云端 660 MB 常驻运行 12.5 天无重启。
**但本机 `Desktop\ALC` 现在是 0 字节空目录** —— 2026-11-01 已整体归档到 `G:\…天窗智巡（AIC 智慧气象 · AIC-2026-41989115）\`，G 盘当前未挂载。
下一轮开工**第一步是恢复工作副本**（见 §6）。

---

## 2. 更新统计（版本线）

### 2.1 总量

| 指标 | 数值 | 备注 |
|---|---|---|
| 发布版本号 | **62 个** | 0.9.0 → V1.0.0；`0.11.5/6/7` 只有方案文档、未发版，不计 |
| 起止 | 2026-09-09 → 2026-10-29 | 首提交 → 最后一次构建 |
| 迭代密度 | **约 1.22 版/天** | 51 天 / 62 版 |
| 问题档案 | **M1–M100**（100 条） | `changelog/ISSUES.md` 525 KB |
| 技术决策 | **ADR-1 … ADR-50**（50 条） | `changelog/DECISIONS.md` 191 KB |
| 更新日志 | 6 307 行 / 33.5 万字 | `changelog/CHANGELOG.md` 605 KB |
| Python 用例 | **204 → 514 条** | 0.9.6 的 204 起，0.11.1 登记 514；后续只增未回填总表 |
| 前端用例 | **456 / 456** | 0.11.19b 实测值 |
| 云端验收 | **PASS 37 / FAIL 0 / SKIP 0** | `bin/verify-remote.sh`，判「部署是否成立」的硬判据 |

### 2.2 版本分段

| 段 | 版本 | 数量 | 主题 |
|---|---|---|---|
| 0.9.0–0.9.13 | 工程化 → 真实云团 · 雷达 · 界面收敛 | 14 | Flyway/任务持久化 → 城市网络 36 城 53 走廊 1614 班 → 三维转平面 → 免登录雷达 |
| 0.9.14–0.9.26 | 口径纠错 · 可见性 · 算法机理 | 12 | 计划关闭误判、雷达二次投影坍缩、规划器不消费雷达几何、首屏即结论、算法机理第九项 |
| 0.9.27–0.9.35 | 红线族收尾 · 性能 · 信息密度 | 9 | 缓存指纹回收 1.4 GB、网关缺腿（雷达中继 404）、绕行守卫挂错层、四开关「定义了没人读」 |
| 0.10.1 | 换芯第一版 · **首次代位** | 1 | 标签取判据不取大模型、推理走纯 Python 树、裁决收在服务端一处 |
| 0.11.1–0.11.4 | 换芯第二版 | 4 | 标签取 METAR 实测、输出概率、TS/Brier + 三基线、五页信息架构、W 阶段 12 张工单 |
| 0.11.8–0.11.17 | 复测驱动修复 | 10 | 雾圈尺度 7–13 px、`activeCaseId is not defined`、T+2 后没飞机、三处自相矛盾 |
| 0.11.18–0.11.27 | 收敛与对外一致性 | 10 | 交付对照、展示文案去解释腔、时间语义（撤 4 处闸门 123→0 关）、建场 20.1 s→0.34 s、首屏口径同步 |
| **V1.0.0** | 正式版 | 1 | 版本号口径合并、注释归档（py −6603 / java −1173 / vue −4249 行）、软著 V1.0 同号 |

### 2.3 最近 10 个关键节点

| 日期 | 版本/事件 | 结果（可复算） |
|---|---|---|
| 10-19 | 0.11.1 换芯 | 唯一运行源 = open-meteo + METAR；标签=实测；出概率 |
| 10-21 | 0.11.9 | 首页横幅 `activeCaseId is not defined`，构建与 445 条用例全绿仍线上失效 |
| 10-23 | 0.11.14 | `mapFlights` 600 条但 `arrivalMinute` 最大 127.3，T+2 之后没飞机 |
| 10-24 | 0.11.17 | 复核推翻报告两处过期结论 |
| 10-26 | 0.11.20 | `overview` 漏传 minute，KPI 28/19 → 23/12 → 0/0 |
| 10-27 | 0.11.21–0.11.22 | 展示文案四条原则；发现材料「硬数字」会漂（2613→2402） |
| 10-28 | 0.11.25–0.11.27 + **V1.0.0** | 发版 22/22 自检、云端 37/0/0、8 页 0 异常、13 页 0 处 undefined/NaN |
| 10-29 | 代码公开 | `github.com/shuanzi4653/ALC`，HEAD `b177b9d`，10 次提交 |
| 10-29 | 作品方案 V13 + 11 张图 | 26 页、目录 38 条与 PDF 逐条对上 |
| 11-01 | **整体归档并清空本机** | 15 746 文件 / 1.0 GB，逐文件 SHA-256 15 745 一致、0 异常 |

---

## 3. 软件包内容（源码仓 = `shuanzi4653/ALC` @ `b177b9d`）

### 3.1 体量

| 目录 | 文件 | 体积 |
|---|---|---|
| docs | 132 | 6 422 KB |
| models | 4 | 3 640 KB |
| frontend | 187 | 2 276 KB |
| tools | 339 | 2 008 KB |
| changelog | 5 | 1 447 KB |
| backend-python | 98 | 1 232 KB |
| data | 10 | 1 090 KB |
| archive | 16 | 329 KB |
| backend-java | 102 | 325 KB |
| scripts | 9 | 74 KB |
| contracts | 7 | 60 KB |
| TianChuang / config / bin / notes / competition / tests | 15 | 87 KB |
| 根文件（README 68.5 KB、VERSION、4 个 bat、运行说明） | 10 | 83 KB |
| **合计** | **932** | **19.5 MB** |

### 3.2 有效代码行数

| 语言 | 文件 | 行数 |
|---|---|---|
| Python | 424 | 67 332 |
| Markdown | 116 | 86 607 |
| Java | 176 | 14 593 |
| MJS（工具/测试） | 51 | 8 621 |
| Vue | 20 | 7 236 |
| JS | 11 | 4 389 |
| SQL（Flyway） | 14 | 788 |
| PowerShell | 10 | 1 946 |
| JSON / JSONL / YAML / bat / sh / css / html | 82 | 29 000+ |

### 3.3 六大模块

**前端**（Vue 3.5 + Vite 8 + maplibre 6.9 + proj4 2.22 + three 0.186，包名 `tianchuang-dashboard` 1.0.0）
- 5 个顶层入口 / **13 个分节**：运行首页 · 运行总览 · 民航情报 · 调度台账 · 事件处置台 · 气象监测 · 算法机理 · 口径与来源 · 大模型取证 · 运行日志 · 走廊剖面 · 推演 · 反事实对照（+ 分歧台账）
- `traffic/runtime.js` 198 KB（纯算法唯一落点，`SECTION_NAMES` 是分节名的唯一来源）
- 组件：`TrafficWorkbench` / `OperationsConsole` / `CityTrafficMap` / `RegionalObservations` + traffic 子组件

**后端 Python**（FastAPI 0.141.1 + uvicorn 0.52.4 + numpy 2.5.3 + shapely 2.1.2 + pyproj 3.7.2，Python 3.13）
- `traffic/` 24 个模块：`service` `v2` `routing` `zones` `airspace` `radar_field` `cma_radar` `cma_tiles` `weather_sources` `huafeng` `operations` `delivery` `spatial` `cases` `catalog` `city_weather` `weather_control` 等
- 另有 `agent_tools.py`（大模型取证）、`decision_service.py`（SQLite 决策库，`(workspace,id)` 复合主键）

**后端 Java**（Spring Boot 3.5.6 / Java 17 / JPA + Flyway + H2 + Security）
- 主代码 74 类：`config` 16 · `service` 15 · `entity` 11 · `repository` 11 · `controller` 10 · `model` 5 · `ws` 2 · `qweather` 2 · `dto` 1
- 产物 `tianchuang-server.jar`（61 MB）

**契约**（7 份，跨层唯一真相）：`traffic-v1.1/v1.2/v1.3.openapi` · `decision-v1.openapi` · `dashboard-v1.schema` · `layer-v1.schema` · `ws-v1.schema`

**模型**（4 个，3.6 MB，运行必需）：`ml-v1` 595 KB · `ml-v2-gust` 1 171 KB · `ml-v2-vis` 622 KB · `ml-v2-vis3k` 1 252 KB
关键指标：vis3k AUC **0.947**、vis1k **0.9528**、gust **0.9358**（唯一依据 `data/training/metar/model-v2-metrics.json`）

**工具链**（339 文件）：`maintenance` 122（含 `_gate_toolchain.py` 31 项闸门）· `probes` 140（含 13 页静默异常探针）· `harness` 17 · `recon` 16 · `benches` 12 · `generators` 11 · `runners` 8 · `deploy` 1

### 3.4 运行与交付件

| 件 | 说明 |
|---|---|
| `start.bat` / `stop.bat` / `build.bat` | 一键启停；`start.bat → dev.ps1` 是入口，端口预检 + 编码归一 |
| `scripts/*.ps1` | build / dev / start / stop / backup / restore-backup / check-environment / test-local |
| `TianChuang/启动天窗智巡.bat` | 桌面快捷方式启动器（隐私窗口打开，不留口令） |
| `.run/build_manual.ps1` | **唯一正确构建入口**：`mvn clean` → vite → 写 build-info.json → package → `_verify_static_bundle.py` |
| 交付三包（11-01 拆分） | `完整代码包.zip` 907 文件 5.8 MB ／ `训练数据包.zip` 55 文件 6.1 MB ／ `高清图纸.zip` 11 张 4.4 MB |
| 命名规则 | `AIC-2026-41989115-智慧气象-天窗智巡·低空交通协同运行管理系统-XX.zip`，zip 内单一同名根目录 |

> 打包纪律：代码包**保留模型 JSON**（没有它系统跑不起来），训练数据与图纸各自独立成包；`docs/代码注释归档-V1.0.0.md`（1.5 MB）按约定只在本地。

---

## 4. 云端运行内容（2026-11-09 13:00 实机）

### 4.1 位置与入口

| 项 | 值 |
|---|---|
| 服务器 | 腾讯云轻量 `shuanzi-server` / `lhins-g86418ju` / **62.234.154.34** / Ubuntu 22.04 / 2C 3.7G |
| 部署目录 | `/opt/apps/AIC-tianchuang/`，总 **660 MB** |
| 公网入口 | `https://tianchuang.shuanzi.site/` → nginx 443 → 回环 `127.0.0.1:28081` |
| 后端 | Java `127.0.0.1:28082`（`/api` 前缀）· Python `127.0.0.1:28083`（挂根） |
| 同机邻居 | hongsight 28080 · ice-travel 28084 · wisdiet 28085–28087 · site · zhongzhuan |

### 4.2 目录构成

| 路径 | 体积 | 内容 |
|---|---|---|
| `app/` | 241 MB | `tianchuang-server.jar` 61 MB（md5 `9ba0d39…`）+ `releases/` 3 个历史 jar 181 MB |
| `backend-python/` | 144 MB | FastAPI 源码 + `.venv`（Python 3.13） |
| `backup/` | 49 MB | 每日备份 + 部署前快照 + nginx 快照 |
| `data/` | 22 MB | H2 文件库 + 案例 |
| `models/` `traffic/` `tests/` `config/` `bin/` | 4.5 MB | 模型、算法模块、夹具、`rules-v1.json`、运维脚本 |
| `.run/` | **200 MB** | `traffic/` 推演缓存 **8 个计划**、最新 204 min；**无上限，是最大增长项** |

### 4.3 服务单元（4 个，全部 enabled）

| 单元 | 状态 | 关键参数 |
|---|---|---|
| `AIC-tianchuang.service` | active running | `java -Xmx384m -Xms128m -XX:+UseSerialGC`，`MemoryMax=1024M`，`Restart=always` |
| `AIC-tianchuang-python.service` | active running | `uvicorn main:app --host 127.0.0.1 --port 28083`，`MemoryMax=768M`，`MALLOC_ARENA_MAX=2` |
| `AIC-tianchuang-backup.timer` | active waiting | 每日 03:4x 出 `files_YYYYMMDD.tar.gz` |
| `AIC-tianchuang-maintenance.timer` | active waiting | 清 logs / cache / `.run` 残留 |

> 文档写 `-Xmx512m`，实机是 **384m** —— 已下调未回填文档，下一轮顺手对齐。

### 4.4 网关（nginx）

- `listen 127.0.0.1:28081`（IPv4+IPv6 回环）· `server_name tianchuang.shuanzi.site` · `absolute_redirect off`
- `real_ip` 三段（`set_real_ip_from 127.0.0.1 / ::1` + `X-Forwarded-For`，`recursive` 保持 off）
- `gzip on` + 显式 `gzip_types … text/javascript …`（session 24.4 MB → 3.95 MB，6.2×）
- `limit_req` 挂在 `@aic-llm-throttled`（`/api/agent/ask`、`/api/traffic/explain`），**登录门已拆**
- 匿名工作区隔离：`X-ALC-Workspace` → `alc_ws` Cookie → `?ws=`；空值≠默认

### 4.5 实测健康（本机直连 HTTPS）

| 检查 | 结果 |
|---|---|
| `GET /` | 200 · 2083 B · 0.81 s |
| `GET /health` | `status=ok` · `version=1.0.0` · **uptime 1 083 961 s ≈ 12.54 天** |
| `planStore` | ok · 8 个计划 · 最新 204.6 min |
| `weather` | mode=`measured` · measured 0 帧（无人使用，不判故障） |
| `llm` | IDLE（本进程未调用 ≠ 故障） |
| `/build-info.json` | buildId `25cc9343…` · **builtAt 2026-10-29T17:20:22+08:00** · node v22.22.2 · java 17 |
| 磁盘 | 59 G 用 13 G（**23%**） |

### 4.6 备份与回退

- 每日文件备份 **8 份**（11-02 → 11-09，各 5.4–6.7 MB），滚动保留
- 部署前快照 **4 份**：`pre-0.11.3`（10-20）、`pre-deploy-20261027 / 20261028×2 / 20261029`
- Python 快照 1 份：`py-snapshot-0.11.11`
- 判代次用「VERSION + 启动版本串」，**不用 mtime**（`cp -a` 保留旧时间）

---

## 5. 已知遗留（下一轮开工清单）

| # | 项 | 现状 | 风险 |
|---|---|---|---|
| 1 | **本机无工作副本** | `Desktop\ALC` 0 字节；G 盘未挂载 | 阻断级，必须先恢复 |
| 2 | 1366×768 整站缩放 | `.hstage` `transform: scale(0.5028)`，最小字 9.5 px（渲染 ≈4.8 px） | 评委席常见分辨率，**F-10 仍开着** |
| 3 | 材料硬数字会漂 | 同构建跨天重建，A 组 2613→2402、改判 3044→3030 | 材料必须同会话录屏抄数，或改用稳定组（0 / −100% / 2848 / 8 班 320 min / 0.1%） |
| 4 | `.run/traffic` 无界 | 8 计划已 200 MB，同代次不设上限 | 长期运行膨胀；`_fingerprint()` 哈希全部字节 ⇒ 改一行注释全量重建 |
| 5 | CHANGELOG 总览表缺行 | 0.11.18–0.11.27 十版未进总览表；另漏 0.9.27 / 0.9.29 / 0.9.30 | 只数表格会少 13 个版本 |
| 6 | 文档与实机参数不一致 | `-Xmx` 512m vs 384m；`/opt/apps/README.md` 登记表版本口径不随部署更新 | 事后查账对不上 |
| 7 | 概率档可达窗口被置信门夹死 | `conf ≥ 0.65` ⇒ BLOCK 0.25 永不触发 | 要可达得改置信门，属设计变更 |
| 8 | 命名遗留 | 目录/仓库/请求头仍是 `ALC` | 不影响运行，但材料与代码两套名，交接时须先说明（见 §0） |

---

## 6. 下一轮更新的技术基线

- **已有能力**：WebGL 地图引擎（maplibre + three）· 坐标变换（proj4 两套坐标系）· 三维/平面双渲染 · 图表 · WebSocket 推送 · 角色权限模型（已降级为匿名工作区）· Flyway 版本化迁移 · Python 地理几何（shapely/pyproj）· 概率与三基线评估（TS/Brier）· 大模型取证通道（DeepSeek）· 31 项工具链闸门 + 13 页静默异常探针 + 37 项云端验收
- **硬约束**：交通一律模拟、气象须区分估算/观测/合成；`docs/NAMING.md` §7 版本口径（正式版 `x.y.z`）；注释已归档、**SQL 迁移不可改**（Flyway checksum）；`tools/` 不在版本控制内，改完必跑闸门
- **待定**：62 个 Beta 号已收口，下一轮是 `1.1.0` 还是另起线，需先改 `docs/NAMING.md` §7 再动代码

---

## 7. 恢复工作副本（三步）

1. **取代码**（G 盘在就优先用归档，与线上逐字节一致）：
   `robocopy "G:\项目与竞赛归档\天窗智巡（AIC 智慧气象 · AIC-2026-41989115）\ALC" "C:\Users\12921\Desktop\ALC" /E`
   　G 盘不可用时退到 GitHub：`git clone https://github.com/shuanzi4653/ALC.git`（HEAD `b177b9d`，932 文件 / 19.5 MB，**不含** `.run` 缓存与 6 GB 截图）
2. **还记忆**：
   `robocopy "C:\Users\12921\.workbuddy\archive\ALC-2026-11-01" "C:\Users\12921\Desktop\ALC\.workbuddy" /E`
3. **先读五份**：`G:\…\交接说明.md` → `docs/NAMING.md` §7 → `docs/V1.0.0-正式版与代码整理.md` → `changelog/CHANGELOG.md` 版本总览 → `docs/云端部署与运维说明.md`
   然后：重建 `backend-python\.venv` → `npm ci`（先删 `node_modules`，否则被 safe-delete 拦）→ `start.bat` 自检 → **构建只走 `.run\build_manual.ps1`**，不要直接 `mvnw package`。

---

## 8. 记录在案的命名更正

2026-11-09 用户确认：**项目正式名 AIC**，`Desktop\ALC` 文件夹与 GitHub 仓库名 `ALC` 均为命名失误；
因记忆目录锚在该路径，暂不改。后续材料、文档、界面、版本说明**一律写 AIC**，
只有 §0 表中四处路径/契约保留 `ALC`，并在交接文档里显式说明一次。
