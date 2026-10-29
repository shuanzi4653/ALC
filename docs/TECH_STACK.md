# 天窗智巡 · 技术栈总览

**系统正式名**：天窗智巡 · 低空交通协同运行管理系统
**当前版本**：0.9.25（Beta）（程序文件写作 `0.9.25-beta`，口径见 `docs/NAMING.md` §7）
**整理日期**：2026-10-07
**来源**：`VERSION` / `backend-java/pom.xml` / `backend-python/requirements-lock.txt` / `frontend/package.json` / `config/application.yml` / `README.md`

> 图标：`★` = 本系统业务主线或关键实现；版本号未标 `^` 者为精确锁定。

## 1. 总体架构

三进程本地运行，全部只绑定回环地址；浏览器**不直连** Python，统一经 Java 网关转发。

| 层 | 技术 | 端口 | 职责 |
|---|---|---:|---|
| 前端 | Vue 3 + Vite | **5180** | 运行中心单页界面（唯一对外入口） |
| 网关 / 主服务 | Java · Spring Boot | **8085** | REST + WebSocket、白名单转发 Python、气象编排、持久化 |
| 算法 / 智能服务 | Python · FastAPI | **8600** | 交通推演、雷达几何、气象快照（仅 Java 内部调用） |

调用链：`浏览器 :5180 → Java :8085 → Python :8600`

## 2. 前端

`frontend/package.json`（锁于 `package-lock.json`），构建器 Vite 8.3.0，Vue SFC 由 `@vitejs/plugin-vue` 编译。

| 包 | 版本 | 用途 |
|---|---|---|
| `vue` | ^3.5.12 | 界面框架 |
| `maplibre-gl` | 6.9.0 | 二维矢量地图（底图 `tiles.openfreemap.org`，含离线降级底图） |
| `three` | 0.186.0 | 飞行器推演可视化（WebGL 2） |
| `proj4` | 2.22.0 | 前端坐标投影 |
| `vite` | ^8.3.0（dev） | 构建与热更新 |
| `@vitejs/plugin-vue` | ^6.0.8（dev） | Vue 单文件组件编译 |

纯算法层单独放在 `frontend/src/traffic/runtime.js` 并显式导出，可直接用 `node --test` 测试，不依赖浏览器。

## 3. Java 后端

`backend-java/pom.xml`：Spring Boot 3.5.6 · Java 17 · 构建走仓库自带 Maven Wrapper（`mvnw.cmd`，无需单独装 Maven）。

| 依赖 | 用途 |
|---|---|
| `spring-boot-starter-web` | REST 接口与静态资源托管 |
| `spring-boot-starter-websocket` | 实时推送（推演 / 监控通道） |
| `spring-boot-starter-data-jpa` | 持久层 |
| `spring-boot-starter-validation` | 请求参数校验 |
| `spring-boot-starter-security` | 权限（本机演示默认关闭，`prod` 开启后按 VIEWER/OPERATOR/ADMIN 控制） |
| `spring-boot-starter-mail` | 邮件推送（默认关闭） |
| `com.h2database:h2` | 内嵌数据库（runtime） |
| `org.flywaydb:flyway-core` | ★ 数据库迁移，替代 `ddl-auto=update` 的隐式改表 |
| `spring-boot-starter-test` | 测试 |

包结构（`com.tianchuang`）：`config` / `controller` / `dto` / `entity` / `model` / `qweather` / `repository` / `service` / `ws`。

## 4. Python 后端

`backend-python/requirements-lock.txt`（精确锁定；`requirements-dev.txt` 在其上追加 `pytest`）。

| 包 | 版本 | 用途 |
|---|---|---|
| `fastapi` | 0.141.1 | Web 框架 |
| `uvicorn` | 0.52.4 | ASGI 服务器 |
| `starlette` | 1.6.0 | ASGI 基础（FastAPI 依赖） |
| `pydantic` | 2.13.5 | 数据模型 / 校验 |
| `httpx` | 0.28.1 | 外部源异步请求 |
| `numpy` | 2.5.3 | 数值计算（**决定 Python 下限 3.12**） |
| `shapely` | 2.1.2 | ★ 几何运算（编译扩展，需 64 位） |
| `pyproj` | 3.7.2 | ★ 坐标投影（编译扩展） |
| `PyYAML` | 6.0.3 | 配置读取 |
| `pytest` | 9.1.1 | 测试 |

核心模块（`backend-python/traffic/`）：`weather_control.py`（实测/虚拟气象源控制器）、`weather_sim.py`（模拟对流回波生成器）、`cma_tiles.py`（CMA 实测雷达瓦片读取）、`radar_field.py`（反射率 → 风险几何，阈值 15/35/45/60 dBZ）、`service.py`（推演服务，缓存按代码指纹自动清理）。

## 5. 数据与存储

| 项 | 内容 |
|---|---|
| 数据库 | H2 文件库 `jdbc:h2:file:./data/tianchuang;MODE=MySQL`（MySQL 语法兼容模式） |
| 表结构 | 由 Flyway 管理（`classpath:db/migration`），`ddl-auto: none` |
| 数据迁移 | Flyway，`baseline-on-migrate: true` 接管旧库 |
| 推演缓存 | `.run/traffic/`，键 = 交通算法源码 SHA256 指纹，按代次自动清理 |

## 6. 外部数据源

系统设计原则：**气象为唯一运行源，不合成**；实测源失败如实报不可用。

| 主机 | 用途 | 是否需凭据 | 缺失时 |
|---|---|---|---|
| `api.open-meteo.com` | 公开气象（模型估算） | 否 | 气象模块报不可用；亦为和风失败后的兜底源 |
| `image.data.cma.cn` | 中国气象数据网雷达瓦片 | 否 | 雷达图层不可用 |
| 和风天气（`config/application.yml::qweather.api-host`） | ★ Java 首选气象源（JWT 认证） | 是（已配置） | 降级 open-meteo 并标 `degraded` |
| `tiles.openfreemap.org` | 城市矢量底图（瓦片/字体/sprite） | 否 | 自动切内置离线省界底图并标注 |
| `api.deepseek.com` | 智能研判（AI 解释调度结果） | 是（Key 可选） | 未配 Key / 失败降级为本地规则基线 |

> 和风主机名由控制台分配、写在配置里，**不是代码或文档常量**；换主机无需改脚本。

## 7. 构建与运行工具链

| 工具 | 实测版本 | 说明 |
|---|---|---|
| JDK | Microsoft OpenJDK **17.0.19** LTS | 须含 `javac`（源码模式先编译） |
| Python | CPython **3.13.14** | 最低 **3.12**（由 `numpy==2.5.3` 元数据决定），虚拟环境固定 `backend-python/.venv` |
| Node.js | **22.22.2** | 最低 `^20.19.0 \|\| >=22.12.0`（取自 Vite 的 `engines.node`），仅前端构建/开发服务器需要 |
| Maven | 仓库自带 `mvnw.cmd` | 无需单独安装，首次联网下载 |
| 操作/脚本 | Windows 10/11 + Windows PowerShell 5.1 | 一键启停为 PowerShell，故实际只支持 Windows |

`.bat` 文件统一 **GBK + CRLF + 无 BOM + 不含 `chcp`**；含中文的 `.ps1` 须存为 **UTF-8 BOM**。

## 8. 运行入口与端口

| 入口 | 说明 |
|---|---|
| `start.bat` | 编译 Java 并启动三服务，就绪后自动开浏览器（源码模式，实际走 `scripts/dev.ps1`） |
| `stop.bat` | 按项目目录 / PID / 启动时间校验停止三进程 |
| `build.bat` | 构建入口（生成 release JAR，当前交付未执行） |
| `check-env.bat` | ★ 环境自检（只读，不启服务），覆盖 OS/CPU/内存/磁盘/Python/Node/Java/可启动性/端口/配置/外网 十一类 |

| 端口 | 服务 | 绑定 |
|---:|---|---|
| 5180 | 前端（Vite 运行中心入口） | 127.0.0.1 |
| 8600 | Python（FastAPI，仅 Java 内部调用） | 127.0.0.1 |
| 8085 | Java（Spring Boot REST + WebSocket） | 127.0.0.1 |

## 9. 硬件要求

| 项目 | 最低 | 推荐 |
|---|---|---|
| CPU | 4 核 | 8 核及以上（几何/推演为单线程密集，主频优先于核数） |
| 内存 | 8 GB | 16 GB 及以上（三服务实测工作集约 483 MB，加地图渲染约 1 GB；8 GB 机器须限制 JVM 堆） |
| 可用磁盘 | 8 GB | 15 GB 及以上 |
| GPU / 显示器 / 网络 | 无需独显 / 1366×768 / 需联网 | — / 1920×1080 及以上 / 宽带 |

## 10. 测试与质量基线

| 套件 | 命令 | 基线（2026-09-18 实测，0.9.19 后未复核） |
|---|---|---|
| Python | `backend-python/.venv/Scripts/python.exe -m pytest tests -q --basetemp=…` | 279 passed |
| 前端 | `node --test frontend/tests/<file>.test.mjs` | 108 passed / 0 fail |
| Java | `cd backend-java && mvnw.cmd -o -B test` | 22 |
| 构建 | `cd frontend && npx vite build` | 149 modules |

三道闸门（改动 `tools/` 后必跑；`tools/` 不在版本控制内）：`tools/maintenance/_gate_toolchain.py --all`、`tools/maintenance/_smoke_flows.py`、`tools/maintenance/_bench_innovations.py`。
