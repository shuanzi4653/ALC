"""Append today's work log entry (written as a file to dodge the shell shim)."""
import os

LOG = os.path.join('.workbuddy', 'memory', '2026-09-16.md')

EXTRA = """

---

## 用户报障：进度卡 0%、超 1 分钟无数据 → 定位并修复（雨带凸包）

用户原话「浏览器收到部分报错…后端是否正确启动，进程有无报错…前端运行超1分钟未收到各飞行汽车的线路推演等数据，怀疑后端需要优化完善」。

### 逐条答复（均为实测，非推断）

1. **浏览器报错**：截图里 Rive 原生运行时、jquery 源码映射告警**不属于本项目**
   （`frontend/src` 既无 Rive 也无 jQuery，是扩展或别的页面）。MapLibre 的
   highway-shield 样式告警来自 `frontend/src/map/city-map-style.json:4918` 的
   OpenMapTiles 标准图层，非缺陷。
2. **后端是否启动**：探针时刻三个服务**都没在监听**（只有 TIME_WAIT，无 LISTENING），
   用户会话期间三者都**启动正常**：Python Application startup complete / Uvicorn 8600、
   Java Started TianchuangApplication in 14.401 seconds / Tomcat 8085、Vite 正常。
3. **进程报错**：**后端零报错**。Python stderr 干净无 traceback；Java 仅一条无关的
   HistoryRetentionService 原始类型返回告警。**142/142 次请求 200 OK**。
4. **超 1 分钟无数据**：**根因已定位并修复**（见下）。

### 教训：200 OK 不代表任何进展

142 次轮询全 200、日志零 error，而计划**从未** READY。启动/轮询型接口在任务彻底失败时
每次轮询照样 200。**存活不等于就绪**。第一件事应该是打印**状态序列**，不是翻日志找红字。

### 根因：progress 只在班次循环内发布，而循环前阶段吃掉全部预算

- 修复前：计划总计 **196.5 s**，首帧进度出现在 **82.6 s**，界面就是**钉在 0%** 的转圈。
- 逐层剖析：`weather.envelope` 占 **94.7%**（300 次 × 25.7 ms）。
- 中层按单体类型拆：21 个单体里 **20 个 RING 各 0.01 ms**，唯一那个 **BAND 要 100.6-123.3 ms**。
- 内层：雨带上轮改成 **20 个簇 × 41 顶点 = 820 顶点**（原是一条 64 顶点飘带），
  `_band_hull` 把 **820 个顶点全部**沿每个漂移偏移平移后再求凸包。

### 修复：先取轮廓凸包再平移（精确无损）

只有落在轮廓凸包上的点才可能成为平移并集的极值点 → 提前取包**无损**。
新增 `_outline_hull_coords()`，**820 顶点 → 49 顶点**，窗口 (20,40) 上 **154.6 ms → 7.0 ms**。
**四个窗口对称差面积全为 0.0 m²**，即逐位相同的包络。必须读**全部**分量：
小簇正是界定雨带刻意留出的通道边界，漏掉会让包络缩进可通行走廊。

### 修复后实测

- 冷构建：**196.5 s → 19.2 s**；**首帧 82.6 s → 2.0 s**（进度 0/12/21/31/42/53/66/77/90/100）。
- 端到端（Vite 5180 → Java 8085 → Python 8600，浏览器真实路径）：
  首帧 **3.7 s** 即 READY，7760 班次 / 5 枢纽 / 13 配送。
  Python 直连另一轮 28.2 s 是**冷进程首调**（导入 + 首次 STRtree + 投影器），口径不同不可混比。
- 回归：受影响 4 套 **63 passed**；完整 Python 套件 **210 passed**（与修复前基线一致）→ 行为中性，纯提速。

### 修掉的失实注释

`weather.py` 原注释称分箱缓存命中率 **92.3%**（13419 调用 → 1035 次计算，"11.25 s → 5.60 s"）。
实测**不成立**：调用方按**升序出发时刻**请求，窗口先被用、很久后才重复，
真实计划命中率约 **59.8%**，且缓存是**实例级**（新实例全冷）。
已改写为实测口径并写明「决定成本的是 miss 数 × 单次 miss 耗时，不是命中率」。

### 遗留

- 交互帧率 30 FPS 仍未在真实浏览器实测。
- 计划纯计算是否已回到 8 s 预算内：需按当前代码重测（本轮 HTTP 到就绪约 19 s，含 7760 班次全量回传）。
- `docs/evaluation-v1.*/` 的班次/性能快照仍待重跑。

### 本轮新增探针/脚本（均在项目根）

`_wait_ready.py`、`_probe_e2e_chain.py`、`_run_tests_band.py`、`_start_services.py`（沿用）、
`_probe_build_progress.py`（改为可从 argv 取 seed 以强制冷构建）。

### 沉淀技能

`~/.workbuddy/skills/stuck-progress-attribution/` —— 「进度卡住」归因方法论：
200 OK 不等于有进展、逐秒打印状态序列、区分「没启动」与「跑得慢」、
逐层剖析（外层带调用次数 → 中层按数据分支 → 内层单变量）、
无损裁剪用**对称差面积等于 0.0** 而非肉眼、缓存作用域与命中率依赖调用顺序、
报告必须区分冷/热并报首帧可见时间。
"""

os.makedirs(os.path.dirname(LOG), exist_ok=True)
with open(LOG, 'a', encoding='utf-8') as handle:
    handle.write(EXTRA)
print('appended', len(EXTRA), 'chars to', LOG)
