# 天窗智巡 · 低空经济飞行气象保障系统（初代 V0.1）

大屏可视化 + 双轨风险推演 + 预警推送的低空飞行气象保障原型系统。

技术栈：Spring Boot 3.5.6 (JDK17) + FastAPI (Python 3.13) + H2 文件数据库 + Vue 3 / ECharts 5 大屏。

## 一、目录结构

```
tianchuang/
├── start.bat                    一键启动（Python 服务 + Spring Boot + 浏览器）
├── config/
│   ├── application.yml          Java 与 Python 共享配置（唯一配置文件）
│   └── qweather/                和风天气 Ed25519 私钥/公钥（JWT 认证用）
├── backend-java/                Spring Boot 主服务（端口 8085）
│   └── src/main/java/com/tianchuang/
│       ├── qweather/            QweatherJwtService（JWT 签发）/ QweatherClient（数据拉取）
│       ├── service/             SfiEngine（轨1规则）/ PythonClient / MonitorService（编排）
│       │                        FusionService（双轨融合）/ AlertService / PushService
│       ├── controller/          DashboardController（REST API）
│       ├── ws/                  WebSocket 实时推送（/ws/dashboard）
│       ├── entity/ repository/  H2 持久层（5 张表）
│       └── model/               WeatherSnapshot / FlightLevel / ForecastHour
├── backend-python/              FastAPI 智能服务（端口 8600）
│   ├── main.py                  /health /sim/generate /track2 /agent/ask
│   ├── simulator.py             四剧本本地数据生成器（晴好/大风/强降水/雷暴）
│   └── track2_agent.py          DeepSeek 轨2 研判（失败自动降级规则研判）
└── frontend/                    Vue 3 大屏（npm run build 产出 dist/，由 Java 托管）
```

## 二、快速启动

1. 双击 `start.bat`（首次运行会自动打包后端 JAR 并等待服务就绪，随后自动打开浏览器）。
   - 脚本会分别打开两个服务窗口：Python 智能服务（8600）与 Spring Boot 主服务（8085）。
   - 主服务以工程根为工作目录运行，自动加载 `config/application.yml` 共享配置。
2. 浏览器自动打开 `http://127.0.0.1:8085`，即大屏页面。
3. 关闭两个命令行窗口即停止服务。

> 也可在 IDEA 中运行 `TianchuangApplication`，但需注意：
> Working directory 必须设为工程根 `tianchuang/`（否则 `config/application.yml`、私钥与 H2 相对路径都解析不到），
> 且 Python 服务需先行启动。

大屏交互：
- 中栏可切换模拟剧本（晴好/大风/强降水/雷暴），并支持"立即监测"手动触发一轮。
- 右栏"智能体问答"可直接向 DeepSeek 智能体提问（如：当前适合巡检吗？）。

## 三、配置说明（均在 `config/application.yml`）

### 1. 和风天气（JWT 认证，非 API Key 方式）

| 配置项 | 说明 |
|---|---|
| `qweather.api-host` | 专属 API Host（控制台-设置中查看） |
| `qweather.kid` | JWT 凭据 ID |
| `qweather.iss` | 开发者 ID（用户 ID） |
| `qweather.sub` | 项目 ID |

私钥文件位于 `config/qweather/qweather_private_key.pem`（对应公钥需已在和风控制台上传并绑定凭据）。
JWT 由 `QweatherJwtService` 使用 JDK 原生 Ed25519 签发，15 分钟有效，自动缓存复用。

### 2. DeepSeek（轨2 智能体）

`deepseek.api-key` / `deepseek.model`。留空或填错时轨2自动降级为本地规则研判（`source=rule`），系统不中断。

### 3. 数据源模式（sim / live）

- `monitor.mode: sim` —— 本地模拟数据生成器（四剧本），用于演示与联调。
- `monitor.mode: live` —— 接入和风真实 API（实时天气 + 逐小时预报）。
  live 失败会自动降级为 sim，保证大屏不中断。
- `monitor.interval-minutes` —— 监测轮询间隔（分钟）。

### 4. 预警推送渠道

钉钉/飞书/企业微信填对应群机器人 Webhook；邮件填 SMTP 信息并 `enabled: true`。
未配置渠道会记录 SKIPPED 日志，不影响其他渠道。

## 四、核心流程（每轮监测）

```
数据获取(sim生成器/和风live，失败自动降级)
  → 轨1：SfiEngine 六要素规则研判 → SFI 0-100 + 四级窗口(适飞≥80/谨慎60-79/危险40-59/禁飞<40)
  → 轨2：DeepSeek 五元组 JSON 研判(risk_level/confidence/key_factors/advice/alert_text)
  → FusionService 双轨融合(一致采用/加权融合/安全优先)
  → 落库(H2) → 骤变检测(60分钟内降30分)与等级触发预警
  → 多渠道推送(大屏弹窗/Webhook/邮件) → WebSocket 广播大屏
```

## 五、REST API 一览（端口 8085）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/dashboard | 大屏全量快照 |
| POST | /api/monitor/run-now | 立即执行一轮监测 |
| POST | /api/sim/switch?scenario= | 切换模拟剧本（clear/wind/rain/storm） |
| GET | /api/config/status | 配置状态（和风就绪情况） |
| POST | /api/agent/ask | 智能体问答（body: {question}） |
| GET | /api/push/logs | 最近 50 条推送日志 |
| GET | /h2-console | H2 控制台（JDBC URL: jdbc:h2:file:./data/tianchuang，用户 sa，密码空） |

## 六、前端开发说明

- 开发热更新：`cd frontend && npm run dev`（端口 5180，已代理 /api 与 /ws 到 8085）。
- 生产构建：`npm run build` 产出 `frontend/dist/`，由 Spring Boot 静态托管，直接访问 8085。
- 地图数据：`src/assets/china.json`（DataV GeoJSON，含九段线）。

## 七、后续演进建议

- Python 侧 `/track1/ml` 预留端点：接入历史数据训练的 ML 风险模型，形成第三轨。
- 接入分钟级降水、天气预警等和风扩展 API。
- 预警推送增加短信/语音渠道；多作业区并发监测。
