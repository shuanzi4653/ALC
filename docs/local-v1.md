# V1.0 本地源码运行与恢复

入口：`start.bat` → `scripts/dev.ps1`；界面：http://127.0.0.1:5180。只执行 Maven compile、dependency:build-classpath 和 Vite 源码预览，不执行package或发布构建。

启动器先执行PowerShell编码与语法预检。含中文的 `.ps1` 必须保存为UTF-8 BOM，以兼容系统自带的Windows PowerShell 5.1；不要只用PowerShell 7验证。详情见 `STARTUP_FIX_2026-09-13.md`。

## 环境与启动

Windows、JDK17、Python3.13、Node.js。具体版本依赖见 `backend-python/requirements-lock.txt`、`frontend/package-lock.json`、`backend-java/pom.xml`。

新环境先安装依赖：

```powershell
cd backend-python
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
cd ../frontend
npm ci
cd ..
.\scripts\dev.ps1
```

首次安装需要网络；本机已有依赖可离线运行模拟与规则问答。完整离线依赖分发尚未制作，不能称为全新机器离线安装。

已编译当前源码可加 `-SkipCompile`。修改Java后重新编译；修改Python后重启；Vue由Vite热更新。

## 停止与排障

运行 `stop.bat`。脚本读取 `.run/processes.json`，校验项目路径、PID、启动时间。PID复用则拒绝停止；记录不存在则只报告占用，不按端口批量杀进程。

| 入口 | 用途 |
|---|---|
| http://127.0.0.1:5180 | 更新版页面 |
| http://127.0.0.1:8085/api/health/live | Java存活 |
| http://127.0.0.1:8600/health | Python存活 |
| http://127.0.0.1:8085/api/system/version | 前后端版本 |

日志：`.run/*-dev.out.log`、`.run/*-dev.err.log`。观测未就绪与进程不存活分开处理。

源码启动器禁用邮件和三种Webhook外部推送，历史记录仍可查看。DeepSeek从本地忽略配置或环境变量读取；真实调用可能产生接口用量，测试套件使用Mock。

## 验证

```powershell
cd backend-python
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe experiments/benchmark.py
.\.venv\Scripts\python.exe experiments/sensitivity.py
cd ../frontend
npm test
cd ../backend-java
.\mvnw.cmd test
```

benchmark先冻结输入与哈希，再写480条结果；重跑更新 `docs/evaluation-v1/` 实验文件。固定输入与引擎可重现路线，耗时受机器负载影响。

决策与解释保存在 `.run/decisions.sqlite3`；原监测保留H2。迁移时先停服务，再单独保存数据库。源码备份在 `backups/v0.12_source_before_v1.0`，不含密钥和依赖。本轮不修改、删除用户原有数据库或旧包。
