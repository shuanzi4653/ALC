# 天窗智巡 · 部署与运维说明

面向部署与运维人员。开发调试见根目录 `README.md`。

---

## 1. 组件与端口

| 组件 | 端口 | 说明 |
|---|---:|---|
| 前端（Vue3 + Vite，运行中心入口） | 5180 | 地图与调度界面；绑定 `127.0.0.1` |
| Spring Boot 主服务（Java 17） | 8085 | 大屏页面、REST、WebSocket；绑定 `127.0.0.1` |
| Python 智能服务（FastAPI） | 8600 | 模拟数据生成、轨2 研判；仅供 Java 内部调用 |
| H2 数据库 | — | 文件库 `data/tianchuang.mv.db`，由 Flyway 管理结构 |

三个端口**全部只绑定回环地址**，不对外暴露。

## 2. 环境要求

- JDK 17（`JAVA_HOME` 指向它；仓库自带 Maven Wrapper，无需预装 Maven）
  - **本机装有多版本 JDK 时**：启动器按 `JAVA_HOME` → `~/.jdks/*`（名含 17/21，倒序）→
    `Program Files` 两处 → `PATH` **逐个探测并自动回退**，`JAVA_HOME` 指向 26 也能启动。
    自检程序 `check-env.bat` **复现同一条候选顺序**，因此不会把「能启动」误判为 FAIL。
- Node.js 18+（前端构建与预览）
- Python 3.13，虚拟环境位于 `backend-python/.venv`
- 网络：底图与气象需要出网；**断网时底图自动降级为内置离线低精度底图并明确标注**，服务本身始终可用

首次准备 Python 环境：

```powershell
cd backend-python
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # 仅测试需要
```

## 3. 构建

```powershell
# 一键构建：前端构建 → target/generated-resources → JAR（不手工复制到源码 static）
.\scripts\build.ps1

# 跳过测试
.\scripts\build.ps1 -SkipTests
```

产物：`backend-java/target/tianchuang-server-0.12.0.jar`

构建要点：
- 前端产物写入 `backend-java/target/generated-resources/static`（`pom.xml` 已声明该资源目录）
- 任一步失败立即非零退出，不会用旧 JAR 继续启动

## 4. 启动与停止

```powershell
.\scripts\start.ps1            # 启动（校验环境/端口占用/等待就绪）
.\scripts\start.ps1 -OpenBrowser
.\scripts\stop.ps1             # 停止（只结束本脚本记录的受管进程）
```

Windows 下也可直接双击 `start.bat` / `stop.bat`。

> **`start.bat` 走的是源码模式，不是这里的 JAR 模式**：它调用 `scripts/dev.ps1`，前端由
> Vite 在 5180 实时提供，**不生成也不使用 JAR**。本节其余内容针对打包模式。
> 根目录的四个 `.bat`（`start` / `stop` / `build` / `check-env`）都必须保存为
> **GBK + CRLF + 无 BOM + 不含 `chcp`**（0.9.16 修正了前三个：原先各含 1 处
> `chcp 65001`，`start.bat` 另有混合行尾；修复前原文件在
> `backups/v0.9.16_bat_encoding_fix_before/`），改完须手工复验——
> `scripts/check-powershell.ps1` 只检查 `.ps1`。

启动脚本的行为约定：
- 启动前校验 Python venv、JAR 是否存在，**端口被占用时直接退出，不会停止占用端口的其他进程**
- 启动后轮询 `/api/health/live`，就绪后再开浏览器
- 进程 PID、启动时间、项目路径记录在 `.run/` 下

## 5. 配置

配置来源优先级：**环境变量 > 外部 `config/application.yml` > classpath 默认值**。

| 配置项 | 默认 | 说明 |
|---|---|---|
| `monitor.mode` | `sim` | `sim` 演示 / `live` 和风实时 |
| `monitor.initial-delay-ms` | `6000` | 启动后首轮延迟（毫秒） |
| `monitor.fixed-delay-ms` | `600000` | 轮询间隔（毫秒） |
| `rules.config-file` | `./config/rules-v1.json` | 规则阈值配置；缺失时用 classpath 副本 |
| `history.retention-days` | `30` | 历史保留天数 |
| `history.max-page-size` | `100` | 历史分页单页上限 |
| `security.enabled` | `false` | 置 `true` 启用登录与角色控制 |
| `push.*-webhook` | 空 | 渠道未配置时该渠道记为 SKIPPED |
| `qweather.*` | 已填 | 和风 JWT 凭据；**私钥文件不要随发布物外发** |

示例配置见 `config/application.example.yml`。

## 6. 数据库迁移与回退

结构变更由 **Flyway** 管理（`backend-java/src/main/resources/db/migration/`），
`spring.jpa.hibernate.ddl-auto=none`，禁止隐式改表。

| 版本 | 内容 | 适用 |
|---|---|---|
| V1 | 基线全表（`CREATE TABLE IF NOT EXISTS`） | 新库建表；旧库自动跳过 |
| V2 | 0.9.0（Beta） 新增列（`ADD COLUMN IF NOT EXISTS` + DEFAULT） | 旧库原地升级 |
| V3 | `track2_job` 任务表 | 异步研判持久化 |
| V4 | 预警轮次状态与 Outbox 租约字段 | 去重恢复与卡死投递回收 |

已有旧库首次启动会自动 baseline 后执行增量，历史数据保留。

**回退流程**：
1. 停止服务
2. 备份当前 `data/` 目录
3. 还原备份的 `data/tianchuang.mv.db`
4. 回退到匹配版本的 JAR 后启动

## 7. 备份与恢复

```powershell
.\scripts\backup.ps1                    # 默认输出到 backup/<时间戳>/
.\scripts\backup.ps1 -OutputDir D:\bak
.\scripts\restore-backup.ps1 -BackupFile D:\bak\tianchuang.mv.db -Force
```

- 当前脚本只允许离线备份：先停止服务，再复制 `data/tianchuang.mv.db`。
- 备份完成后脚本以只读方式打开副本执行查询，并输出文件大小和 SHA-256。
- 恢复脚本会先创建恢复前回滚副本，再替换数据库文件。

恢复后启动服务，核对最近运行、预报与预警关联。

## 8. 健康检查与可观测性

| 端点 | 用途 |
|---|---|
| `GET /api/health/live` | 进程存活（liveness） |
| `GET /api/health/ready` | 就绪（数据库可用 + 首轮有效观测） |
| `GET /api/config/status` | 配置与实际来源（不含凭据） |
| `GET /api/history/runs` | 运行历史分页 |

界面上的状态灯分别表达：**配置完整性**、**连接状态**、**数据新鲜度**，三者不可互相替代。

## 9. 安全建议（部署前必做）

1. **私钥隔离**：`config/qweather/*.pem` 属敏感文件，不要放入对外分发的发布包；生产建议用受控路径或环境变量注入，并核查分发历史决定是否轮换
2. **开启权限**：受控环境设 `security.enabled=true` 并配置 VIEWER / OPERATOR / ADMIN 账号（bcrypt 存储）
3. **保持回环绑定**：`server.address=127.0.0.1`；如需跨主机访问，请置于反向代理之后并启用 HTTPS
4. **关闭 H2 控制台**：`spring.h2.console.enabled=false`（默认已关闭）
5. **日志脱敏**：不要在日志中输出完整 webhook URL 与凭据

## 10. 发布物检查清单

- [ ] `scripts/build.ps1` 全新环境构建通过
- [ ] `scripts/test-local.ps1` 三端测试全绿
- [ ] 发布目录不含 `data/`、`backup/`、`.audit/`、`node_modules/`、`.pem` 私钥、日志
- [ ] 发布目录**不含 `.run/`**（运行时缓存与进程记录，会自动重建）
- [ ] 版本与构建时间可追溯
- [ ] 按本文件第 6、7 节完成一次升级与备份恢复演练
- [ ] 确认发布包内含 `frontend/src/assets/northeast-offline.json`（离线底图，45 KB；缺失则断网只能白屏）

## 11. 运行时缓存与磁盘

`.run/traffic/` 存推演结果，键是**交通算法源码的 SHA256 指纹**。改任何一个
`traffic/*.py` 都会让整代缓存失效。`service.py::_prune_stale_store()` 在每次构建完成后
只读每个缓存文件的**头部 8 KB** 取指纹，指纹不等于当前值的整份删除，`.tmp` 残留一并清理。
**保留判据只认指纹**：放在该目录里的其他文件不会被误删。

- 该目录**可以随时整个删除**，下次推演自动重建。
- 上线前若从旧版本升级，首次启动会自动回收历史残留（实测某次升级回收约 **1.4 GB**）。
