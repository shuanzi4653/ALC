# 0.9.3（Beta） 本地源码运行与恢复

入口：`start.bat` → `scripts/dev.ps1`；界面：http://127.0.0.1:5180。只执行 Maven compile、dependency:build-classpath 和 Vite 源码预览，不执行package或发布构建；此外会**同步或清除** `backend-java/target/classes/static`（见下节）。

启动器先执行PowerShell编码与语法预检。含中文的 `.ps1` 必须保存为UTF-8 BOM，以兼容系统自带的Windows PowerShell 5.1；不要只用PowerShell 7验证。详情见 `STARTUP_FIX_2026-09-13.md`。

**`start.bat` 自身还有一条同类要求**：必须 **GBK + CRLF + 无 BOM + 不含 `chcp`**。cmd 按**字节偏移**
增量读批处理，中途 `chcp` 或混合行尾都会让偏移失同步。0.9.16 实测 `start.bat` 同时犯了这两条
（含 `chcp 65001`，且 17 个 CRLF 混着 22 个孤立 LF），已统一修正；改完要手工复验，因为
`scripts/check-powershell.ps1` **只检查 `.ps1`**，不覆盖 `.bat`。

## 静态包新鲜度（0.9.16 起）

`dev.ps1` 在启动服务之前处理 `backend-java/target/classes/static`：

| `frontend/dist/index.html` | 动作 | 结果 |
| --- | --- | --- |
| 存在 | 整目录同步过去 | 8085 提供的是**当前**前端，与 5180 同源 |
| 不存在 | **删除**该静态包 | 8085 对 `/` 返回 404，而不是回答一份旧界面 |

原因是 Spring Boot 把该目录当作 `classpath:/static` 提供。**留一份过期包在那里，等于给
"改了却看不到"留一个永远查不出来的出口**：2026-09-12 的包一直躺到 2026-09-24，期间任何前端
修复都到不了 8085。旧包已备份到 `backups/v0.9.16_before_static_bundle_removal/`。

**多版本 JDK 共存时**：启动器（`start.ps1::Resolve-JavaExe`）按
`JAVA_HOME` → `~/.jdks/*`（名含 17 或 21，倒序）→ `Program Files` 两处 → `PATH`
**逐个探测并自动回退**，所以 `JAVA_HOME` 指向 JDK 26 也能正常启动。
`check-env.bat` 复现同一条候选顺序，输出三种互斥结论：
经 `JAVA_HOME` 命中 = PASS / 经回退命中 = **WARN（exit 0）** / 整机无 17|21 才 = FAIL。
不要把这三种情况合并成「行/不行」。

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

**但底图不再依赖网络**：断网时前端自动切到随程序内置的离线低精度底图
（`frontend/src/assets/northeast-offline.json`，45 KB，约 1 km 简化），并在界面上明确标注。
在线瓦片恢复后自动切回完整底图。详见面板行为见根 `README.md` §离线底图。

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

**气象通道可在界面上运行时不重启切换**：「运行总览」地图上方与「气象监测」页顶部各有
`实测气象` / `虚拟气象` 两个并列按钮，当前态高亮。虚拟态下整条控件转橙色并常驻警示条，
地图图例同步改为「模拟雷达回波」。切换后立即作废在途请求并重新取数。

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

> 直接跑 pytest 时 `traffic` 包可能不在 `sys.path` 上（报
> `ModuleNotFoundError: No module named 'traffic'`）。稳妥做法是走
> `python tools/runners/_run_pytest.py`，它会切到 `backend-python` 并设好 `--basetemp`。
> **`--basetemp` 必须用 `C:/…` 风格且落在项目内**，否则默认落到 `%TEMP%` 会报 WinError 5。

benchmark先冻结输入与哈希，再写480条结果；重跑更新 `docs/evaluation-v1/` 实验文件。固定输入与引擎可重现路线，耗时受机器负载影响。

决策与解释保存在 `.run/decisions.sqlite3`；原监测保留H2。迁移时先停服务，再单独保存数据库。源码备份在 `backups/v0.12_source_before_v1.0`，不含密钥和依赖。本轮不修改、删除用户原有数据库或旧包。

## 运行时目录

| 目录 | 内容 | 可否删除 |
|---|---|---|
| `.run/traffic/` | 推演结果缓存，键为交通算法源码 SHA256 指纹 | **可整个删除**，下次推演自动重建；旧代次会自动回收 |
| `.run/*.log` | 三服务运行日志 | 可删 |
| `.run/processes.json` | 启停校验用的进程记录 | 可删（删后 `stop.bat` 只报告占用，不杀进程） |
| `.run/environment-check.json` | `check-env.bat` 的自检报告 | 可删 |

`_prune_stale_store()` 在每次构建后清理缓存：只读文件头部 8 KB 取指纹，**不解析正文**；
指纹不等于当前值的整份删除。**只认指纹**，目录里的其他文件不会被误删。
