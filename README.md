# 天窗智巡 · 低空交通协同运行管理系统 V1.0.0

覆盖 36 个地级行政区的本地运行系统：城际飞行汽车走廊、城区外卖无人机配送走廊、按已声明高度层与时隙协同的连续四维调度、以及按推演时间轴连续呈现的运行总览与放行队列。跨省仅连接沈阳—长春—哈尔滨。真实城市矢量地图、飞行器、公开天气驱动的风险场与 AI 研判已整合到统一操作界面。

**版本**：`V1.0.0`（正式版，2026-10-28）。程序文件（`VERSION` / `pom.xml` / `package.json` / `package-lock.json` 两处）写合法 semver **`1.0.0`** —— Maven 与 npm 不接受 `V` 前缀与全角括号。此前 `0.9.0` … `0.11.27` 为 Beta 线，已于 `0.11.27` 收口；版本口径与递增规则见 [`docs/NAMING.md`](docs/NAMING.md) **§7**。

**完整开发史料见 [`changelog/`](changelog/README.md)**：版本演进史、问题档案、技术决策记录、证据索引。
引用前先读 [`changelog/README.md`](changelog/README.md) 的引用纪律。

## 材料数字的核查入口

作品方案与应用成效中的每一项数值，都能在本仓库找到唯一来源。按表对应即可复算。

| 材料中的数字 | 仓库中的依据 |
|---|---|
| 训练样本 26 193 条；正样本 1 657 / 202 / 917 | [`data/training/metar/dataset.json`](data/training/metar/dataset.json) |
| TS 0.4936、BSS 0.5053、AUC 0.9470 / 0.9528 / 0.9358；三条基线对照 | [`data/training/metar/model-v2-metrics.json`](data/training/metar/model-v2-metrics.json) |
| 三个目标模型本体（含校准参数） | [`models/`](models) 下 `ml-v2-vis.json`、`ml-v2-vis3k.json`、`ml-v2-gust.json` |
| 逐 5 km 插值、σ 合成、判据分档、班次处置 | [`backend-python/traffic/v2.py`](backend-python/traffic/v2.py) |
| 判据阈值（能见度 3000 / 1000 m、阵风 10 / 13 m/s 等） | [`config/rules-v1.json`](config/rules-v1.json) |
| 走廊与城市台账（36 城、53 + 216 条走廊） | [`backend-python/data/traffic/`](backend-python/data/traffic) |
| 筛选与消融的复现命令 | `changelog/CHANGELOG.md` §复现方式 |

原始 METAR 序列（`data/training/metar/*.csv`，42 MB）未入库，因其为公开归档的可再下载副本；指标、标签与数据集清单已全部入库，上游数字可由此独立复算。

## 竞赛定位与主题关联

本项目参加 **第八届全球校园人工智能算法精英大赛 · 算法主题赛（智慧气象）**，作品名 **天窗智巡——东北低空气象决策**。
气象是本系统的**业务主线**而非装饰图层：决策链的上游是气象，结论的下游是「放不放行」。

**一句话对接主题**：把「未来某时刻航线上有没有危险天气」变成可计算、可复现、可被否决的放行结论。

| 主题要求（附件1 [A] 二、） | 本项目的落实 | 可核对的落点 |
|---|---|---|
| 合理使用气象数据与 AI，并说明具体作用 | 气象为唯一运行源（公开模型估算 + 实测雷达），AI 只做受控工具调用与证据检索，不越过禁飞/谨慎区域改写路线 | `weather_sources.py`、`radar_field.py`、`docs/evaluation-v1/ai-50-real.json` |
| 数据与案例真实、来源可溯 | 公开源全部免凭据；实测源失败**如实报不可用**，不合成、不编造；三省站点台账保留真站号与原始链接 | `real_weather.py`、`backend-python/data/stations/` |
| 标注创新层级并与主流方案比较 | 创新集中在**组合与可验证行为**（连续移动天气 + 未来风险扫掠 + 出发时间比较 + 证据绑定），并附朴素对照 | `docs/paper-innovations.md`、`artifacts/_innovations_bench.json` |
| 原型须有可行性测试报告 | 固定评测集、环境清单、原始结果与失败案例全部留存 | `docs/evaluation-v1/`、`docs/evaluation-v1.6/` |
| 问题—数据—方法—实现—验证—价值闭环 | 六段闭环逐项对应；无实飞的部分明确说明并提供离线验证替代 | `competition/CONTENT_V1.md` |
| 材料匿名 | 全部作品材料不得出现学校、指导教师、联系方式 | 见下方「匿名与凭据」 |

**主题贴合点，逐条对应到功能**：

1. **气象驱动，而非气象展示** —— 雷达 dBZ 网格直接生成风险区几何（阈值 15/35/45/60 dBZ），再驱动航线绕行与关闭判定；气象图层不是可选装饰。
2. **未来时刻的航线上是否有危险天气** —— 按**预计经过时刻**逐点检查风险，而不是按当前时刻的重叠；这是「预报」语义，也是与常规叠加式风险图的核心差别。
3. **气象不确定时的诚实边界** —— 实测源不可用即如实报不可用；虚拟气象仅用于演示且**处处显式标注**（`SYNTHETIC_RADAR`、橙色警示条、图例改写「模拟雷达」），不得与实测叠加或冒充实测。
4. **气象与调度的联合决策** —— 同一任务给出左右绕行与延后出发两类可比方案，并给出各自代价；绕行超过限定时间时不给放行路线。

**边界声明（不得越界表述）**：本系统为**可运行原型**，用于算法与交互验证。气象为**模型估算 + 公开实测雷达**，**不是专业气象预报产品**；交通班次与配送订单**仍为模拟生成**；大屏运行建议**不等同于法定空域许可**，合成/虚拟数据**不等同于官方预报**。

## 匿名与凭据

参赛材料必须匿名，且不得携带任何凭据。本仓库为此提供两项可复跑的核验：

- **披露扫描**：`tools/harness/_audit_disclosure.py` —— 遍历待打包树，按类别报告凭据/身份信息；只打印**形状与位置**，不打印值本身，因此输出可直接粘进报告。
  实测 **506 个文件 · BLOCK 0 条 · WARN 141 条**（其中 5 个被 gitignore 覆盖，已降级标注）。
  余下 WARN 全部可逐条解释：**112** 条长十六进制串（评测结果的 SHA-256、城市站点源文件校验和）、**24** 条含用户名的绝对路径（脚本里的解释器路径）、**2** 条 PEM 私钥头（Java 代码中用于**剥离**头部、`.pem` 配置文件本身已 gitignore）、**2** 条已忽略的密钥文件字段。结论：**未发现会实际泄露凭据或身份信息的阻断项**。
- **自测**：`backend-python/tests/test_audit_disclosure.py` —— **38 项**，同时约束「漏报」与「误报」两个方向，防止规则被悄悄放宽或收紧。近期据实测误报收紧了两类：**哈希体内的连续数字**（NOAA 源文件的 `rawSha256` 里含形如手机号的数字串）与**带标签的数字标识**（`referencePoint: OpenStreetMap node/…`）。

## 0.9.14（Beta） 相对 0.9.13（Beta） 的变化

1. **「计划关闭」口径纠错（真 bug）**：关闭原因分类表里混进了一个 `CLEAR` —— 它是**机队普查的计数项**，不是关闭原因。于是出现了"气象图层没有任何影响区、却报气象冲突与计划关闭"。实测 `clear`/`live` 两种天气下均为 `closed=123`、`closedByWeather=0`，关闭原因只有**超出推演时段 88** 与**资源或耗时不足 35**（两项之和恰为 123）。界面文案因此改为「**无气象原因** · 超出推演时段 88 · 资源或耗时不足 35」。**没有为了让天气好看而隐藏任何关闭计数。**
2. **顶部成排**：眉标、主标题、「运行数据模拟」徽标、副标题改为**同一排**布局，并清理两条失配的媒体查询规则。
3. **双通道强制互斥**：实测气象与模拟气象**不可能同时可见**；被抑制的图层会**点名说明为什么消失**（不静默不画）。13 项前端单测锁定该不变量。
4. **分段式雨带沿走廊主轴**：雨带不再按经纬度包围盒摆放，改为沿**航线走廊主轴**定向（双方位角平均 → 108.8°）、以**城市网络质心**为参考点。同批 40 个随机种子实测：中位穿越航线条数 **7 → 12**，穿越不足 8 条的种子 **24/40 → 8/40**。
5. **风向箭头覆盖三省全域**：由"只在城市位置取点"改为全域规则网格。实测 **27 个矢量**、跨域覆盖率 **94%/99%**、**0 个零矢量**、**27/27 全部经插值得出**、最远边界偏移 291 km。
6. **竞赛主题对齐**：见上文「竞赛定位与主题关联」与「匿名与凭据」两节。
7. **顺带修好的构建脚本**：`_build_frontend.py` 的测试发现走到了 `backups/`（三份无 `node_modules` 的归档前端副本，`import 'vue'` 报错），且 `vite` 从仓库根而非 `frontend/` 解析 —— 两者合起来让一次**全绿的构建看起来是坏的**（`156 tests / 148 pass / 8 fail`，8 个失败全在归档件里）。已改为 cwd 一律 `frontend/`、显式列举测试文件并排除 `backups`/`archive`，另加**发现数量下限断言**。修好后：前端 **121 passed**、`vite build` **149 modules**。

## 0.9.13（Beta） 相对 0.9.12（Beta） 的变化

1. **虚拟气象切换修复**：Java 网关此前未转发 `/api/traffic/weather/mode`（两段路径落不进单段白名单），按钮点了只闪一下「切换中」就没反应。已补 GET/POST 显式映射，并新增**网关路由一致性静态审计**防复发。
2. **地图回到纯地图**：原先压在地图画布上的状态条、雷达图例卡、视角按钮三块浮层全部移到画布**下方**的信息条；图例默认折叠、可展开。地图上只保留**标注位置**的两类标记。
3. **顶部导航复用空白**：气象通道开关与地图状态移入「运行总览 / 调度台账」右侧原本闲置的位置。
4. **地图专注真实生效**：该控件此前只是个装饰（class 加了、没人消费），现补上真实布局规则。

## 0.9.9（Beta） 相对 0.9.8（Beta） 的变化

1. **地图界面收敛**：删除地图版权标注（截图里"背后那段文字"）；上方图例由 8 项合并为 5 项并重排网格。
2. **取消双轨命名**：不再出现「派生飞行风险区」「官方固定禁入」等把内部分层泄漏到界面的名称，直接标 **风险区**（橙红）与 **官方管制区域**。配色分工固定：**冷色 = 官方固定管制区域，暖色 = 本系统气象派生风险区**。
3. **云团不规则化**：风险单体轮廓改为**按角度驱动**的多频谐波叠加（逐单体独立随机种子），半径变异系数由 0.000 → **0.194**，单体大小差异达 **3.0 倍**。
4. **动态演变**：单体按**生命周期抛物线**变大变小，支持晚生、分裂与合并，贴合对流单体 45–60 分钟寿命的实际规律。
5. **真实雷达接入**：新增免登录的中国气象数据网雷达瓦片通道（`backend-python/traffic/cma_tiles.py`），256×256 大端 int16、值 ×0.1 = dBZ、6 分钟一帧。实测帧龄 3.0 分钟、回波占比 1.89%、最强 51.5 dBZ。**dBZ 网格已驱动风险区几何**（阈值 15 / 35 / 45 / 60 dBZ，见 `radar_field.py`）。
6. **几何质量收敛**：修掉四类尖角成因（低阶轮廓粗糙度过大、误用单位半径、负缓冲、`difference` 薄片），凸角由 54 个 → **0 个**，最短边由 1.0 m → **211.8 m**。

## 0.9.8（Beta） 相对 0.9.7（Beta） 的变化

1. **时间语义**：申请起飞、计划放行、实际放行、预计到达分开记录；未来班次不再提前显示"实际时间"；统一北京时间显示并保留相对推演轴。
2. **城市中心**：36 城使用带来源的坐标目录，删除城际端点统一 2.69 公里偏移；中心枢纽与起降点显式区分，不再静默吸附越界坐标。
3. **高度合同**：新增机型参数文件与已声明高度层；冲突以**高度层、时隙或地面等待**解决，不再逐点叠加高度。
4. **资源日历**：起降点与交叉区按时隙预约，排队占用可追溯。
5. **气象来源**：支持 Open-Meteo 公开接口与和风天气（经 Java 内部原始接口）两种来源，统一快照与降级标注。**合成天气已于 0.9.9（Beta） 之后全部退役，现仅使用真实数据集**；无法取得真实值的量（如雷暴概率）显式记为缺失，不编造。
6. **调度台账**：放行队列与班组班次台账支持分组、筛选、虚拟滚动与地图双向联动。
7. **配送业务**：固定短线升级为订单运行，包含商家/收货节点、无人机载具状态与电量余量估算。
8. **航迹与边界显示**：已飞过的航迹段落变暗保留、未飞段落高亮，拖动时间轴不再整条消失；三省外轮廓与内部省界分级加粗（4.4 / 2.8 px），行政区外区域压暗。
9. **风险区平面化**：风险区改为**平面范围**（填充 + 轮廓），不再使用立体柱。理由是推演风险区**没有经过勘测的天花板**，给一个虚构顶部的柱体会被读成法定高度限制。
10. **风险区合并**：不再逐个画单体，改为按**场区连通分量**合并后呈现（实测 21 个单体 → 34–36 个区域）。仅改呈现——避让包络仍逐单体计算，因此「已画区域」永远是「被避让区域」的子集。
11. **进入固定禁入区标红**：计划航迹落入固定**禁入**区的载具转为红色并弹出告警条；进入**须批准**管制空域只计数上报、不染色（实测 41.1% 的班次正常穿越机场净空区，全部染红等于让「红」失去含义）。无告警时界面常驻「本视图内 0 架位于禁入区」的监视态，使检查结果可见。
12. **机型尺寸区分**：飞行汽车与外卖无人机使用各自独立的臂展与缩放，配送无人机在同等高度下明显更小。
13. **首页分屏**：运行总览只保留指标、空间视图与班次剖面；放行队列与时间推演迁至同一页下屏（调度区域），首屏在常见分辨率下不再溢出。

**数据范围必须如实阅读**：交通班次、配送订单与起降点均为**模拟生成**；公开天气为**模型估算**，不是测站实况；本地**没有覆盖全部航迹的 DEM 与建筑高度数据**，因此净空状态显示为"条件未验证"，而不是"已通过真实地形净空检查"。仍缺少的数据与限制逐条列在 [`changelog/`](changelog/README.md) 的遗留清单中。

## 电脑与环境要求

本节是**在一台新电脑上把本项目跑起来**所需的全部条件。版本号是**本机实测通过的版本**；内存与磁盘数字是**三服务同时运行时的实测值**（测量环境：24 核 / 32 GB RAM / Windows 11 / PowerShell 5.1），不是估计值。

### 硬件要求

| 项目 | 最低 | 推荐 | 实测依据 |
|---|---|---|---|
| CPU | 4 核 | 8 核及以上 | 三服务同时常驻。几何计算与大规模班次推演是**单线程密集**的，主频比核心数更重要 |
| 内存 | **8 GB** | 16 GB 及以上 | 三服务实测工作集合计约 **483 MB**（Python 34.5 + Java 416.8 + Node 31.9），加浏览器地图渲染实测 **514 MB**（15 个 Edge 进程），合计约 **1 GB**。但见下方 JVM 说明——**8 GB 机器上必须限制 Java 堆**，否则单是 JVM 就会预留 2 GB |
| 可用磁盘 | 8 GB | 15 GB 及以上 | 依赖 373 MB（`frontend/node_modules` 173 + `backend-python/.venv` 137 + `backend-java/target` 63）；`.run/` 推演缓存单文件最大 **21.7 MB**。缓存**会按代码指纹自动清理**（见下方说明），稳态占用远小于旧版，且可随时整个删除、会自动重建 |
| GPU | 不需要独显 | — | 推演视图走浏览器 WebGL，集显可运行 |
| 显示器 | 1366×768 | 1920×1080 及以上 | 首页与调度区域为分屏布局，低于 1600×900 时下屏需要滚动 |
| 网络 | 需要（联网） | 宽带 | 在线底图需要 `tiles.openfreemap.org`。**断网不再导致地图空白**：会自动切到随程序内置的离线低精度底图并明确标注（见下方「离线底图」）。服务本身与后端接口始终可用 |

#### JVM 堆内存必须注意（8 GB 机器上的关键配置）

**本项目没有为 Java 服务配置 `-Xmx`**，因此 JVM 会按**物理内存的 1/4** 自动设定最大堆。实测本机（32 GB）的 JVM 参数为：

```
-XX:InitialHeapSize=528482304   (-Xms ≈ 504 MB)
-XX:MaxHeapSize=8438939648      (-Xmx ≈ 8.0 GB，即物理内存的 1/4)
```

当前实际只用了约 **147 MB** 堆（G1 已提交 612 MB）。

- **在 16 GB 及以上机器**：无需任何配置，自动值足够。
- **在 8 GB 机器上**：JVM 会把最大堆设为约 **2 GB**。实际用量远低于此，但预留会挤压 Python 几何计算与浏览器渲染，**建议显式限制**：

```powershell
# 启动 Java 前设置，例如限制到 1 GB
$env:JAVA_TOOL_OPTIONS = "-Xmx1024m"
.\start.bat
```

**已实测验证**：设置后 JVM 报告 `Picked up JAVA_TOOL_OPTIONS: -Xmx1024m`，`MaxHeapSize` 由
8.0 GB 降为 1 GB。该环境变量对 `start.bat` 与 `scripts/dev.ps1` 都生效（两者都以
`Start-Process` 启动 `java.exe`，会继承当前环境）。

**内存紧张时优先限制这里，而不是怀疑系统本身跑不动。** 8 GB 机器在未限制堆的情况下同时跑三服务 + 浏览器地图，可能出现卡顿或交换，这不是代码缺陷。

#### `.run/` 推演缓存会按代码指纹自动清理

推演结果缓存在 `.run/traffic/`，键是**交通算法源码的指纹**——
`backend-python/traffic/service.py::_fingerprint()` 对 `traffic/*.py` 全部字节、班次台账、
机型档案、固定管制区和边界版本一起做 SHA256。

这带来一个必须知道的后果：**改动任何一个交通算法文件，整个缓存代次同时失效**。
早期版本只清理**内存里**的 `JOBS` 字典（最多 4 条），**磁盘上的旧代次从未被回收**，
于是每改一次代码就整批作废一次，而作废的文件永久留在盘上（实测曾累积到
**73 个文件 / 1.46 GB，其中 48 个属于 21 个已死指纹代次**，约 0.9 GB 是纯垃圾）。

现在 `_prune_stale_store()` 在**每次构建完成后**扫一遍缓存目录：只读每个文件的
**头部 8 KB** 取出内嵌指纹（**绝不解析 20 MB 的正文**），指纹不等于当前值的整份删除，
`.tmp` 残留一并清掉，真正的缓存（当前指纹代次）一个不动。**磁盘占用因此与「改过几次代码」脱钩。**

- 缓存目录**可以随时整个删除**，下次推演会自动重建，不影响任何功能。
- 清理**只认指纹**。若在该目录放了别的东西（如 `README.txt`），不会被误删。
- 实测：删除 1.4 GB 冗余缓存后，其余功能与全部测试不受影响。

> **底图口径**：`frontend/src/map/city-map-style.json` 的瓦片、sprite、字体全部指向 `tiles.openfreemap.org`，**市政道路、立体建筑与地名注记只有这一个来源，无法离线替代**。断网时不会白屏——前端会自动切到随程序内置的省界级离线底图并明确标注，但它**不能**用来判断航路方位（详见[离线底图](#离线底图断网也能看出方位)）。

### 软件环境

| 依赖 | 实测版本 | 最低要求 | 备注 |
|---|---|---|---|
| 操作系统 | Windows 10 / 11（64 位） | Windows 10 及以上 | **一键启停脚本是 PowerShell，因此实际只支持 Windows**。核心服务本身跨平台，但 `start.bat` / `dev.ps1` 依赖 PowerShell 5.1 |
| JDK | **Microsoft OpenJDK 17.0.19 LTS** | JDK 17 或 21，**须含 `javac`** | 启动器**不要求 `JAVA_HOME` 指向 17/21**。源码模式的 `scripts/dev.ps1` 按 `JAVA_HOME → ~/.jdks/ms-17.0.19 → ~/.jdks/*` 逐个试，取第一个版本为 17/21 **且带 `javac`** 的 JDK（要先编译）；发布包模式的 `scripts/start.ps1` 另按 `JAVA_HOME → ~/.jdks/* → C:\Program Files 常见路径 → PATH` 找，**不要求 `javac`**。因此 `JAVA_HOME` 指向 JDK 26、但本机另装了 17 时**两条路径都能启动**；只有整机找不到 17/21 才会报「需要 JDK17 或21」 |
| Python | **CPython 3.13.14** | **3.12 及以上** | 虚拟环境固定在 `backend-python/.venv`，启动器硬编码该路径；shapely / pyproj 是编译扩展，**必须是 64 位 Python**。**下限是 3.12 而不是 3.11**：`requirements-lock.txt` 锁定 `numpy==2.5.3`，其 PyPI 元数据声明 `requires_python >=3.12`（`pyproj==3.7.2` 另需 `>=3.11`）；因为锁定的是精确版本，pip **不会**回退到旧 numpy，在 3.11 上会直接报 `No matching distribution found for numpy==2.5.3` |
| Node.js | **22.22.2**（系统另装 24.14.1 亦可用） | **`^20.19.0 \|\| >=22.12.0`** | 下限直接取自 `frontend/node_modules/vite/package.json` 的 `engines.node`（Vite 8.3.0）。**Node 18 / 20.0–20.18 / 21 都不满足**；仅前端构建与开发服务器需要 |
| Maven | **不需要单独安装** | — | 仓库自带 `backend-java/mvnw.cmd`（Maven Wrapper），首次使用需联网下载 Maven 与依赖 |
| 浏览器 | Chrome / Edge 最新版 | 支持 WebGL 2 的现代浏览器 | 地图与推演视图需要 WebGL 2 |

**PowerShell 版本注意**：启动脚本用系统自带的 **Windows PowerShell 5.1** 运行。含中文的 `.ps1` 文件**必须保存为 UTF-8 BOM**，否则在 5.1 下会乱码或语法报错——只用 PowerShell 7 验证过是不够的。

### Python 依赖（精确版本）

`backend-python/requirements-lock.txt` 锁定的完整清单（运行 + 测试）：

```
fastapi==0.141.1          uvicorn==0.52.4           httpx==0.28.1
shapely==2.1.2            pyproj==3.7.2             PyYAML==6.0.3
pydantic==2.13.5          starlette==1.6.0          anyio==4.15.1
numpy==2.5.3              pytest==9.1.1             pluggy==1.6.0
```

其中**只有 shapely 与 pyproj 是必装的编译扩展**（几何运算与坐标投影）；`requirements-dev.txt` 在其上追加 `pytest`，仅跑测试需要。

### 前端依赖（精确版本）

`frontend/package.json`（锁定于 `package-lock.json`）：

| 包 | 版本 | 用途 |
|---|---|---|
| `vue` | ^3.5.12 | 界面框架 |
| `maplibre-gl` | **6.9.0**（精确锁定） | 二维矢量地图 |
| `three` | **0.186.0**（精确锁定） | 飞行器推演 |
| `proj4` | **2.22.0**（精确锁定） | 前端坐标投影 |
| `vite` | ^8.3.0（dev） | 构建与热更新 |
| `@vitejs/plugin-vue` | ^6.0.8（dev） | Vue 单文件组件编译 |

### 新机器首次安装

```powershell
# 1) Python 虚拟环境（必须建在 backend-python/.venv，启动器硬编码此路径）
cd backend-python
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt

# 2) 前端依赖
cd ../frontend
npm ci

# 3) 回到根目录，一键启动
cd ..
.\start.bat
```

**首次安装必须联网**（pip 与 npm 都要拉包）。依赖装好后，日常运行**不需要再联网下载依赖**，但**城市底图仍需联网**。

### 环境自检（推荐先跑这一步）

**双击 `check-env.bat`** 即可检查本机是否满足上述要求，无需安装任何额外工具：

```
check-env.bat                 完整自检（含出网探测）
check-env.bat --no-network    跳过出网探测（离线/计量网络环境）
check-env.bat --quiet         只输出结论与报告文件，供脚本调用
check-env.bat --json-only     等价于 --quiet --no-network（最快的纯报告模式）
check-env.bat --help          显示全部选项
```

选项**可以组合**（如 `check-env.bat --quiet --no-network`），顺序不限。

> `check-env.bat` 本身按 **GBK + CRLF + 无 BOM + 不含 `chcp`** 保存——这是 cmd 下
> 同时保证「零报错 / 中文正常 / `@echo off` 生效」的唯一组合。**用编辑器改它会
> 被静默存成 UTF-8**，改完请复跑一次自检确认中文没有变成报错行。
>
> **同一要求适用于根目录的全部四个 `.bat`。** 0.9.16 实测其中**三个**犯了这个错：
>
> | 文件 | `chcp` | 行尾（修复前） | 行尾（修复后） |
> | --- | --- | --- | --- |
> | `start.bat` | 1 处 | **17 CRLF + 22 孤立 LF** | 38 CRLF / 0 孤立 LF |
> | `stop.bat` | 1 处 | 18 CRLF + 1 孤立 LF | 18 CRLF / 0 孤立 LF |
> | `build.bat` | 1 处 | 19 CRLF / 0 孤立 LF | 18 CRLF / 0 孤立 LF |
>
> 症状是一串看着像"文件有乱码"的 `'xx' is not recognized`。三者均已统一为
> **GBK + CRLF + 无 BOM + 无 `chcp`**；修复前的原文件备份在
> `backups/v0.9.16_bat_encoding_fix_before/`。`check-env.bat` 本来就合规 —— 注意它正文里
> 那句"contains NO chcp"是**注释**，用字节搜索查 `chcp` 会把它误判成有。
> **`.bat` 没有自动检查**（`scripts/check-powershell.ps1` 只查 `.ps1` 的 BOM 与语法），
> 改完必须手工复验编码与行尾。

自检覆盖 **操作系统 / 处理器 / 内存 / 磁盘 / Python / Node.js / Java / 可启动性 / 端口 / 配置 / 外网** 十一类，
逐项给出 `[通过] / [注意] / [失败] / [信息]` 四档结论：

- **[失败]** = 不满足硬性要求，系统无法启动或会出错，退出码 `1`；
- **[注意]** = 可以运行，但低于推荐配置，**不影响退出码**（全部按失败处理会让报告失去意义）；
- **[信息]** = 中性事实（如端口占用、启动器实际选用的路径），不计入结论；
- **[可启动性]** = 把上面各节合成交付时会问的那一个问题：**接手方双击哪一个 `.bat` 能真的起界面**。它按两条互不替代的路径分别给结论——**源码模式**（`start.bat` → `dev.ps1`，要 `.venv` + `node_modules` + 含 `javac` 的 JDK 17/21 + `mvnw.cmd`）与**发布包模式**（`scripts/start.ps1`，要 `build.bat` 产出的、与 `VERSION` 同名的 jar）。缺件只报 `[注意]`：那是**产物**没准备好，不是机器不达标；
- 结论与要求明细同源于本章节，两者不会各自漂移。

**「外网」一节的主机清单是问配置要的，不是写死的。** 和风主机名由和风控制台分配、写在
`config/application.yml` 的 `qweather.api-host`；自检按该配置探测，换主机时无需改脚本。
配置里没有它时，自检如实报告「未配置」而不是去探一个可能早已作废的域名。

**Java 一项与实际启动逻辑逐条同源。** 实际入口是 `start.bat → scripts/dev.ps1`（源码模式），
它的候选顺序是 `JAVA_HOME → ~/.jdks/ms-17.0.19 → ~/.jdks/*`，并且**要求该 JDK 含 `javac`**
（源码模式要先编译）。自检照抄的是这一个顺序与要求，而不是另外一套：

| 情形 | 结论 |
|---|---|
| 由 `JAVA_HOME` 命中含 `javac` 的 17/21 | `[通过]`，与启动器一致 |
| 由**回退路径**命中（如 `JAVA_HOME` 指向 JDK 26 或其他版本） | `[注意]` —— 系统**能启动**，只是建议统一 `JAVA_HOME`；退出码仍为 `0` |
| 候选里没有可用的 17/21 | `[失败]`，退出码 `1`，并**列出实际试过的每一个候选** |

> 早前版本只探 `java -version`，而启动器读的是 JDK 自带的 `release` 文件
> （`java -version` 把版本写到 stderr，部分环境取不到）。两者不同源会产生**假失败**：
> 自检报「起不了」，而双击 `start.bat` 其实起得来。现在两侧用同一个读取顺序。
> 判据见 `.workbuddy/memory/notes/2026-09-19-selfcheck-parity.md`。

`[信息] 发布包模式选用` 单独列出 `scripts/start.ps1`（读 jar 的那条路径）会选中的 `java.exe`，便于核对。

**Python 与 Node.js 的版本下限也是硬判据，且下限取自有出处的元数据，不是估的。**

| 解释器 | 下限 | 下限的来源 | 结论档位 |
|---|---|---|---|
| Python | `3.12` | `requirements-lock.txt` 里 `numpy==2.5.3` 的 `requires_python`（PyPI 元数据） | 低于下限：**虚拟环境与「系统解释器」都报 `[失败]`**；系统解释器另分一档——若现有 `.venv` 本身可用，则降为 `[注意]`（能跑、但重建虚拟环境会失败） |
| Node.js | `^20.19.0 \|\| >=22.12.0` | `frontend/node_modules/vite/package.json` 的 `engines.node` | 不满足即 `[失败]`（前端构建不过＝界面起不来） |

> 这两项此前偏松：Python 侧把 `3.11` 当成合格（实际上锁定的 numpy 装不上），
> 系统解释器**只报 `[信息]`**——于是一台 Python 3.10.11 的机器拿到了「仅缺 `.venv`」的报告，
> 按提示去 `python -m venv .venv` 必然撞墙；Node 侧用 `-ge 20` 判，会**放行 Node 20.0–20.18 与 21**，
> 而那三档 Vite 都不接受。两处都已改成与所声明要求一致的比较。
> 判据见 `.workbuddy/memory/notes/2026-10-07-handover-minimum-versions.md`。

完整报告写入仓库根目录下 `.run` 目录里的 `environment-check.json`（该目录已被 `.gitignore`
忽略，属于**首次运行自检后才生成**的运行时产物，全新克隆的仓库里不存在），在仓库根目录下
可直接打开该文件并附在问题反馈里。报告带**项目版本**（读 `VERSION`）与生成时间——交付出了
问题时，第一句话总是「那是哪一版」。自检**只读**：不启动服务、不安装依赖、不改动任何现有文件。

### 端口占用

| 端口 | 服务 | 绑定 |
|---:|---|---|
| 5180 | 前端（Vite，运行中心入口） | 127.0.0.1 |
| 8600 | Python 服务（FastAPI，仅供 Java 内部调用） | 127.0.0.1 |
| 8085 | Java 服务（Spring Boot REST + WebSocket） | 127.0.0.1 |

三个端口**全部只绑定回环地址**，不对外暴露。启动器会预先探测端口占用，**被占用时直接退出，不会去杀占用端口的其他进程**。

### 外网依赖一览

系统会对以下主机发起出网请求。「缺失时」一列说的是**功能完整度**，不是「不联网就起不来」——断网时服务照常启动，底图会自动降级为内置离线底图（见[离线底图](#离线底图断网也能看出方位)），气象与雷达则如实显示不可用。

| 主机 | 用途 | 缺失时 |
|---|---|---|
| `tiles.openfreemap.org` | 城市矢量底图（瓦片、字体、sprite） | 自动改用内置省界级离线底图并标注；只影响底图观感 |
| `api.open-meteo.com` | 公开气象数据（模型估算） | 气象模块如实报不可用；它同时是**和风失败后的兜底源** |
| `image.data.cma.cn` | 中国气象数据网公开雷达瓦片（免凭据） | 雷达图层不可用，其余功能不受影响 |
| 和风天气 —— `config/application.yml` 的 `qweather.api-host`（当前为 `m82vhh82ma.re.qweatherapi.com`） | **Java 侧首选气象源**（JWT 认证，凭据已配置） | 自动降级到 `api.open-meteo.com`，并把本轮标记为 `degraded` |
| `api.deepseek.com` | 智能研判（AI 解释调度结果） | 配置了 Key 才出网；失败则轨2 降级为本地规则基线 |

> **和风主机名不是常量**：它由和风控制台分配、写在 `config/application.yml` 里。本文档与
> `check-env.bat` 自检都以该配置为准，换主机时不必改代码或改本文档的常量。

**没有真实凭据也能跑**：公开气象、雷达、底图三项都是免凭据的；和风凭据已在
`config/application.yml` 配好，未配置时会直接走公开气象源；智能研判在未配置 Key 时降级，
不影响其余功能。密钥统一放在被忽略的 `config/application.yml`，**不要提交到版本控制或放进参赛材料**。

### 数据范围（必须如实阅读，勿当性能承诺）

- **交通班次、配送订单、起降点均为模拟生成**；气象为**模型估算**，不是测站实况；雷达为公开实况瓦片。
- 本地**没有覆盖全部航迹的 DEM 与建筑高度数据**，因此净空状态显示为「条件未验证」而非「已通过真实地形净空检查」。
- 性能数字（30 FPS / 台账 300 ms）随机器与网络规模变化，**引用时必须同时写明机器配置与网络规模**。

## 运行更新版

1. 双击 `start.bat`：编译 Java 源码并启动 Python、Java、Vite。三个服务就绪后会自动用系统默认浏览器打开运行中心。
2. 启动窗口会持续驻留并监控服务，不要关闭；运行地址是 **http://127.0.0.1:5180**。8085 是 Java API，8600 是 Python 内部服务。
3. 双击 `stop.bat`：按项目目录、PID和启动时间校验，停止本项目三个进程。启动窗口会显示停止完成，并等待按键后关闭。

源码入口不依赖旧 JAR。`scripts/start.ps1` 是历史发布包启动器，本轮不用；`build.bat` 留作未来构建入口，本轮未执行。

**前端包的新鲜度由启动器负责**（0.9.16 起）：`scripts/dev.ps1` 启动三个服务之前会检查
`frontend/dist` —— **存在就同步**到 `backend-java/target/classes/static`，**不存在就删掉**
那份静态包。原因是 Spring Boot 把该目录当作 `classpath:/static` 提供，于是 **8085 端口可能
悄悄回答一份几天前的前端**：2026-09-12 的包一直躺到 2026-09-24，期间任何前端修复都到不了 8085
（旧包已备份到 `backups/v0.9.16_before_static_bundle_removal/`，4 个文件 / 1.33 MB）。
**日常请以 5180 为准**；若直接开 8085，现在拿到的也是与 5180 同源的当前产物。

前置环境为 JDK17、Node.js、Python3.13。本机依赖已安装；新机器见 [本地运行说明](docs/local-v1.md) 与上文[电脑与环境要求](#电脑与环境要求)。服务只监听本机，源码启动默认关闭外部推送。

## 使用

- 运行总览：选择36城之一，加载城市道路与立体建筑；可旋转、跟随航班和进入地图专注视图。运行区域侧栏可折叠。地图画布保持干净——状态、视角按钮、图层图例都在画布下方的信息条上，不遮挡航线。
- 放行队列与推演：运行总览下屏承载放行队列（含班组班次台账）与时间推演播放条；支持分组、筛选与地图双向联动。
- 调度台账：按待放行、运行中、受限/异常、已完成分组；搜索班次、筛选状态、城市、类型与关闭原因，完整台账使用虚拟滚动连续浏览。
- 预警中心：合并同一走廊与原因的事件，直接定位相关班次。
- 气象监测：明确区分公开来源天气与不可用降级，风险区标注为「风险区（禁止进入 / 谨慎进入）」。
- 智能研判：结合当前网络、班次、气象和人工操作证据解释调度结果。
- 操作记录：本地保存人工操作；按时间回看，支持导出当前完整记录。

城市底图**在线时优先使用联网矢量底图；断网自动降级为内置离线低精度底图并明确标注**（见[离线底图](#离线底图断网也能看出方位)）。班次、订单、起降点为模拟数据；公开天气为模型估算；部分地区建筑覆盖不完整，楼宇与地形尚未用于实机避障。完整数据范围和限制见 [`changelog/README.md`](changelog/README.md)。

### 气象数据源切换（实测 / 虚拟）

雷达通道可在**实测**与**虚拟**两种数据源之间**运行时切换，无需重启**。

**雷达回波与航线绕行的关系（0.9.17 起）**：**35 dBZ 以上回波**（对流 35–45、强回波 ≥45）
已并入航线避让几何 —— 地图上画为"禁止进入"的强回波核，计划真的会绕行或标注气象关闭；
**层状降水（15–35 dBZ）只展示、不避让**（可飞越的雨）。plan 结果携带
`radarAvoidance`（模式 / 观测时次 / 面积），说明是哪一时次的观测驱动了本轮绕行。

**虚拟模式的回波会随推演时间移动（0.9.18 起）**：推演播放条拖到第几分钟，回波就是
`基准时刻 + 该分钟` 那一帧 —— 生成器是平流模型（实测质心 8 小时漂移约 99 km），
云团会像真实风暴场一样平移、生消。计划的避让按**各班次自己的飞行窗口**取当刻回波，
所以同一片云在不同时段对不同的航班分别生效。**实测模式刻意不移动**：外推单时刻观测
等于伪造预报，实测回波保持观测时刻原位，由徽标报告其时效。

**两种来源不要混看**：地图上的**圆形风险区**派生自公开天气**点观测** —— 阵风、能见度或
降水**达标的城市**，以城市位置为中心（severe 另有 8 km 禁飞核，且全部进入避让）。
它与雷达回波是**两个独立图层、两个独立来源**：回波再淡，大风达标的城市照样出现红色内核；
回波强而无点观测超标，也只画雷达层。圆心在城里是点观测的固有约束（按城市取点），不是缺陷。

**界面上怎么切（推荐）**：在「运行总览」顶部**分区导航栏的右侧**（`运行总览 / 调度台账 / …`
之后、城市下拉框之前）有一组 **气象通道** 按钮——`实测气象` / `虚拟气象` 两个并列按钮，
当前态高亮并标「当前」，点另一个即切换。同一个控件也出现在「气象监测」页顶部。
虚拟态下整条控件左侧出现橙色描边、按钮转为橙底，按钮上带 ▲ 标记；
完整警示文案（「本帧为程序生成的模拟对流回波，不是观测数据」）在地图下方
「图层说明」抽屉里，地图图例与雷达图层名称同步从「实测雷达回波」改为「模拟雷达回波」。
切换后地图会**立即重新取数**，不会停留在上一模式的回波上。

> **切换结果一定可见**：成功显示「已切换到…」/「模式未变化」，失败显示
> 「切换失败：<原因>」。此前失败路径在两个布局下都可能**看不见**（紧凑态隐藏了结果行），
> 症状就是"闪了一下切换中就没有然后了"。

| 接口 | 方法 | 说明 |
|---|---|---|
| `/traffic/weather/mode` | GET | 查询当前模式、切换人、切换时间与各分支已服务帧数 |
| `/traffic/weather/mode` | POST | 切换模式，体 `{"mode":"virtual","seed":42,"actor":"...","reason":"..."}` |

> **加新接口时必读**：浏览器**不直连** Python 服务。它连 Java 网关（8085），
> 由 `DecisionController` 把**白名单内**的路径转发到 Python（8600）。
> 因此"Python 端点写好了、前端也调用了"并**不代表**能用 —— **中间那条转发**也得加，
> 否则请求会落到 Spring 默认错误响应，前端只拿到一句泛化错误。
> `weather/mode` 就踩过这个坑：它是**两段路径**，而网关的 `{resource}` 只吃一段。
> 现在有静态审计守着：`python tools/maintenance/_audit_gateway_routes.py`
> （闸门中名为 `gateway routes`），任何前端 `/api/*` 调用找不到映射即 FAIL。

命令行等价写法（无需开界面）：

```bash
curl -X POST http://127.0.0.1:8600/traffic/weather/mode \
  -H "Content-Type: application/json" -d "{\"mode\":\"virtual\",\"seed\":42}"
```

- `measured`（**默认**）：读取 CMA 组网组合反射率实测瓦片。**实测源失败时如实报告 `available:false`，绝不用虚拟帧顶替。**
- `virtual`：由 `backend-python/traffic/weather_sim.py` 生成模拟对流回波——离散对流单体 + 尾随层状降水盾 + 生命史
  （生成→成熟→消散）+ 平均风平移，强度分档沿用实测同一条阈值（15/35/45/60 dBZ），
  输出与实测帧**逐字段同构**，因此下游几何代码无需任何分支。同一 `seed` + 同一时次可**逐字节复现**。

**虚拟帧一定带标记**：`provenance.provider = 'SYNTHETIC_RADAR'`、`synthetic: true`、
`source = 'SYNTHETIC_RADAR_CREF'`，前端图例同步切换为「模拟回波」措辞（`radarIsVirtual()`）。
这是刻意的：一个生成出来的回波若被读成观测结果，雷达通道就失去了它唯一的意义。
注意 `radar_field.derive()` 会在**自己的**输出里固定写 `provider: 'CMA_DATA_NET'`，
所以标记必须在上游 `weather_control.radar_frame()` 打——下游不会替你补。
虚拟模式只影响气象/雷达通道，**交通数据全程为模拟生成，不受该开关影响**。

### 离线底图（断网也能看出方位）

城市底图依赖 `tiles.openfreemap.org`。断网时**不会白屏**：前端会自动切到**随程序内置的离线低精度底图**，并明确标注当前处于降级状态。

底图通道是**三态**的，不是一个布尔开关：

| 通道 | 界面提示 | 含义 |
|---|---|---|
| `底图载入中` | 「正在载入城市地图」 | **冷启动的诚实取值**：第一块瓦片还没回来之前，「在线」和「离线」都只是没被证实的断言 |
| `在线底图` | 「全域城市地图已载入 / 已加载 N 栋立体建筑」 | 矢量瓦片确实到达 |
| `离线底图` | 橙色徽标 + 警示条 + 「重试在线底图」按钮 | 远端瓦片连续失败，已切到内置边界 |

> 这些提示显示在**地图下方的信息条**里，不再压在地图上。地图画布上只保留两类
> 必须贴着目标画的东西：选中载具的标签、固定禁入区告警——它们标的是地图上的
> **具体位置**，挪走就失去意义。视角按钮（立体视角 / 俯视 / 跟随航班）与
> RADAR 图例也都在同一条信息条上，图例默认收起、点「图层说明」展开。

**怎么做出来的**：`frontend/src/assets/northeast-offline.json`（**45 KB**）是由已入库的
`frontend/src/assets/china.json`（DataV GeoJSON，582 KB / 35 个要素）**派生的三省子集**，
用 Douglas-Peucker 以 **0.01°（约 1 km）** 容差抽稀：

| 省 | 顶点数（源 → 离线） | 保留率 | 文件字节 |
|---|---|---|---|
| 辽宁省 | 764 → 631 | 83% | 11 942 |
| 吉林省 | 866 → 735 | 85% | 13 816 |
| 黑龙江省 | 1335 → 1032 | 77% | 19 414 |

重新生成与校验：

```bash
# 重新生成（读 china.json，写 northeast-offline.json）
./backend-python/.venv/Scripts/python.exe tools/generators/_gen_offline_basemap.py

# 校验——必须证明它「形状对」，而不只是「文件小」
./backend-python/.venv/Scripts/python.exe tools/maintenance/_verify_offline_basemap.py
```

校验器不信任文件大小，而是独立判四项：**鞋带公式面积比**（0.90–1.05）、**外接框质心漂移**、
**环闭合性**、**顶点数**（≥20 且严格少于源）。当前实测 **面积比 100.0% / 100.0% / 100.0%、
外接框漂移 0.0000°** → `OK`。

**为什么必须显式标注**：离线底图只保留了省界轮廓，**没有城市道路、没有立体建筑、没有地名注记**
（地名靠静态 DOM 标签，不走远端 glyph 字体）。如果它被当成完整底图读，运行人员会据一条
1 km 精度的省界去判断航路方位。所以降级态一律带橙色标记，并在恢复后自动切回。

**恢复是自动的**：只要矢量瓦片重新到达（`reportMap()` 检测到 `openmaptiles` 源已载入），
通道立即升回 `在线底图`、失败计数清零、离线图层隐藏。失败计数是**双向**的——
连续失败累计到阈值才降级，一次成功即清零。

**降级阈值与误报**：需要**连续 6 次**「确实取不到瓦片」的错误才降级（`BASEMAP_OFFLINE_AFTER_FAILURES`）。
字体（GLYPH）、精灵图（SPRITE）、主动取消（ABORTED）三类错误**不计入**——它们不代表底图不可达。
降级是**可用性降级，不是故障**，因此不会触发红色错误横幅（那条横幅仍只由「样式加载失败」等真故障触发）。

## 目录结构

```
ALC/
├── start.bat / stop.bat / build.bat    一键启停
├── check-env.bat                       ★ 运行环境自检（只读，不启动服务）
├── README.md                           本文件
├── changelog/                          ★ 开发史料（论文素材）
│   ├── README.md                       总索引与引用纪律
│   ├── CHANGELOG.md                    版本演进史（0.9.0（Beta） → 0.9.33（Beta））
│   ├── ISSUES.md                       问题档案（119 条，含 M1–M100 方法论）
│   ├── DECISIONS.md                    技术决策记录（50 条 ADR + 35 条跨决策方法论）
│   └── evidence/INDEX.md               证据文件索引与引用规范
├── docs/                               技术文档与评测证据
│   ├── evaluation-v1 … v1.5/           各阶段实测证据
│   ├── weather-decision.md             气象基线决策书（已签字）
│   └── architecture-decisions.md        早期架构决策
├── contracts/                          接口合同（由 app.openapi() 实际导出）
├── backend-python/                     Python 服务（FastAPI，8600）
│   ├── traffic/                        交通模拟核心
│   │   ├── weather_control.py          气象源控制器（实测 / 虚拟，运行时可切）
│   │   ├── weather_sim.py              模拟对流回波生成器（与实测帧同构）
│   │   ├── cma_tiles.py                CMA 实测雷达瓦片读取
│   │   ├── radar_field.py              反射率 → 风险几何（15/35/45/60 dBZ）
│   │   └── service.py                  推演服务（含缓存按代码指纹自动清理）
│   └── data/traffic/                   交通数据
├── backend-java/                       Java 服务（Spring Boot，8085）
├── frontend/                           前端（Vue3 + Vite，5180）
│   ├── src/assets/china.json           全国省界（DataV GeoJSON，离线底图的源）
│   ├── src/assets/northeast-offline.json  ★ 内置离线低精度底图（45 KB，1 km 简化）
│   ├── src/traffic/runtime.js          纯算法层（node --test 直接可测）
│   └── src/components/traffic/         交通可视化组件（含 WeatherSourceSwitch.vue 气象通道开关）
├── scripts/                            启停与运维脚本
│   └── check-environment.ps1           环境自检实现（check-env.bat 调用）
├── tools/                              ★ 开发工具（按用途分类，文件名不变）
│   ├── probes/       (89)              单问题测量探针
│   ├── generators/   (11)              证据/合同/资产生成器
│   ├── harness/      (15)              三服务联调与验证
│   ├── benches/      (11)              成本与预算测量
│   ├── runners/      (7)               测试/构建运行器
│   ├── recon/        (16)              外部数据侦察
│   ├── shared/       (2)               跨工具共用（含 _retired.py 退役声明）
│   ├── maintenance/  (27)              仓库维护（闸门、文档链接校验、离线底图校验）
│   └── _repo.py                        路径与产物名唯一来源（artifact(name)）
├── archive/                            历史文档
│   ├── plans/                          历代更新计划
│   ├── completions/                    历代完成报告
│   └── legacy-reports/                 早期报告
├── artifacts/                          生成的测量产物（JSON/PNG，可再生）
├── backups/                            旧版源码备份
└── competition/                        参赛文稿与演示脚本
```

## 交付索引

- **[开发史料库](changelog/README.md)** —— 论文与答辩的首选入口
  - [版本演进史](changelog/CHANGELOG.md)｜[问题档案](changelog/ISSUES.md)｜[技术决策记录](changelog/DECISIONS.md)｜[证据索引](changelog/evidence/INDEX.md)
- [固定管制空域证据](docs/evaluation-v1.4/fixed-airspace.md)：69 站点与两种净空口径的真实代价
- [风险区合并与平面渲染证据](docs/evaluation-v1.5/risk-merge-and-flat-render.md)：合并粒度、平面渲染、被否决的卫星变体
- [0.9.9（Beta） 云团与雷达证据](docs/evaluation-v1.6/cloud-shape-and-radar.md)：云团不规则度、生命周期曲线、几何收敛、真实雷达通道
- [气象基线决策书](docs/weather-decision.md)：Himawari-9 红外 / CMA 雷达 / 星图云三方案对比（**已签字，2026-09-18**）
- [雷达数据通道](docs/radar-channels.md)｜[红外云图追踪](docs/ir-cloud-track.md)
- [系统命名规范](docs/NAMING.md)：正式系统名、六个一级模块、风险与空域术语的分层口径
- [**算法规格书**](docs/algorithm-spec.md)：8 项创新点的 `文件::函数` 索引、输入/输出、复杂度、判据与反面案例、性能口径
- [论文创新点](docs/paper-innovations.md)：创新点的**可读叙述**（做法、依据、配图建议）
- [**算法增量对照报告**](docs/evaluation-algorithm/algorithm-contrast.md)：四组「朴素做法 vs 本算法」实测对照 —— 连续移动 / 按预计经过时刻扫掠 / 单阈值从严 / 单阈值从宽，每组带规模、越核口径与量具自证
- [模型与数据设计](docs/model-and-data-v1.md)｜[部署说明](docs/deployment.md)｜[本地运行说明](docs/local-v1.md)
- [0.9.6（Beta） 评测证据](docs/evaluation-v1.3/)｜[旧版评测原始结果](docs/evaluation-v1/)
- [参赛内容文稿与演示脚本](competition/CONTENT_V1.md)
- 历史计划与完成报告见 [`archive/`](archive/)；旧版源码备份见 `backups/`（均不包含密钥和依赖）
- 废弃文件清理时逐项签字的清单见 [`docs/CLEANUP_CHECKLIST.md`](docs/CLEANUP_CHECKLIST.md)

全部自动化测试不需要真实密钥。配置密钥保留在忽略文件 `config/application.yml`，不要添加到版本控制或参赛材料。

## 测试与复现

```bash
# Python（虚拟环境在 backend-python/.venv；--basetemp 必须用 Windows 风格路径且落在项目内）
backend-python/.venv/Scripts/python.exe -m pytest tests -q --basetemp="C:/Users/<user>/Desktop/ALC/artifacts/_ptmp"

# 前端测试 + 构建（Windows 下 node --test 需显式传文件路径，不要传目录）
node --test frontend/tests/<file>.test.mjs
cd frontend && npx vite build

# Java（必须在 backend-java 目录内执行 mvnw.cmd，JAVA_HOME 指向 .jdks/ms-17.0.19）
cd backend-java && mvnw.cmd -o -B test

# 三道闸门（改动 tools/ 后必跑；tools/ 不在版本控制内，改坏了没有 git 兜底）
./backend-python/.venv/Scripts/python.exe tools/maintenance/_gate_toolchain.py --all
./backend-python/.venv/Scripts/python.exe tools/maintenance/_smoke_flows.py

# 资产校验：离线底图形状 + 文档链接
./backend-python/.venv/Scripts/python.exe tools/maintenance/_verify_offline_basemap.py
./backend-python/.venv/Scripts/python.exe tools/maintenance/_verify_doc_links.py

# 离线底图三态渲染检查（可选，走 SSR，不启动浏览器）
node frontend/tests/render-offline-basemap.mjs
```

以下为 **2026-10-19 实测** 的基线（**`0.11.1（Beta）`**，第二十一轮 · 换芯第二版）；本表只随逐项实测更新，引用前请重跑 —— 本轮数字与口径见 [`docs/algorithm-spec.md`](docs/algorithm-spec.md) **§8.6**（§8.5 是第二十轮、§8.4 是第十九轮、§8.3 及以下是第十一轮及更早的历史读数，保留不改写）。**本节按轮次分段**，最新的在上面：

| 套件 | 结果 | 墙钟 |
| --- | --- | --- |
| Python（pytest） | **513 passed / 1 skipped / 0 failed**（RC 0；收集 **514**；2 条第三方弃用告警） | 2495.52 s（41 min 35 s） |
| 前端（`node --test`） | **400 passed / 0 failed / 0 skipped**（**31** 个测试文件） | 见 §8.6 |
| Java（`mvnw.cmd test`） | **60 / 0 failed / 0 errors / 0 skipped**（BUILD SUCCESS） | 31.1 s |
| `vite build` | RC 0，**171 modules**（`index-CYARziSc.js` 2 177 791 B / `index-CKLFG6eA.css` 206 592 B） | — |
| 冒烟链路（`_smoke_flows.py`） | **6/6 PASS**（`session-lifecycle` **18/18**，RC 0） | 38.4 s / 上限 420 s |
| 工具链闸门（`_gate_toolchain.py`） | **GATE PASS** —— `AUDITS` **31 项**（0.11.8 新增 `js unbound names` 与对照两条；0.11.13 新增 `vue prop refs` 与对照两条）＝ 打印 **31 行全 `ok`**；`--all` 另加 2 项长跑对照 ＝ **33 行全 `ok`** | — |
| 条目计数（`_verify_issue_counts.py`） | **entries 119 / 合计 150 / 表达式 150 / 差额 31**，M 上界 **99**，`--self-test` **PASSED** | — |
| 迁移（`_verify_migrations.py`） | **7 条全部应用成功**（V7 = `ml_inference`），`--self-test` **PASSED** | — |
| 跨层审计（`_audit_gateway_routes.py`） | 前端 `/api` 调用 **28** / Java 映射 **40** / **unmatched 0 · undecidable 0 · unverified 0** | — |
| 截图覆盖（`_shot_screens.py`） | **14/14 分节各一张、md5 全互异** | — |
| 云上复核（服务器上跑 `verify-remote.sh` ＋ `verify-static-remote.sh`） | **PASS 37 / FAIL 0 / SKIP 0**（RC=0，结论：全过）＋ 静态 **RC=0 / `static checks passed`** ＋ 本机侧公网 `200 / 0.261 s`；线上 `VERSION = 0.11.1-beta`、`/api/system/version` 的 Java 与 Python **同为 0.11.1-beta**、`build-info.json` 的 `buildId` 是当次构建（不是缓存）、公网 28081 **rc=28** | 部署前快照 `files_20261019-1205.tar.gz` 2.4 MB；顺序 = **备份 → 部署 → 验收** |
| 交付包（`_build_handoff_pack.py` / `_make_zip.py`） | **398 文件 / 14.3 MB**；zip **398 条目 / 0 目录条目 / 5.90 MB**；包↔仓库**逐字节 398/398 一致、0 不同** | 正向自检 **16 项启动输入**（含三个 v2 模型 + `model-v2-metrics.json` + `dataset.json`）、负向自检 **17 项排除目标**（含 METAR 原料五项）。⚠️ 上一版包不在本机 ⇒ **本轮未做增量对照**，不编造「+N 新文件」 |

> **`0.11.1（Beta）`（2026-10-19）本节读数与上一版的对照**：Python **497 → 514 收集**
> （**+17 全部是新文件 `backend-python/tests/test_v2_probability.py`**，可逐条点名）；
> **跳过 0 → 1 的成因已逐条归因**（不写"来自新增用例"）：唯一那条是
> `tests/test_traffic_network.py:128` —— `live snapshot produced no drawable tier in this environment`。
> 它**不是新增用例**（该文件本轮未改），而是**环境相关**的守卫：实时快照里当下没有可绘制的分带时，
> 用例自己说"这台机器此刻量不出来"，而不是拿一个空集合去断言。**这条能来回翻** ——
> 上一版写"0 skipped"是真的，本轮写"1 skipped"也是真的，两句都不构成回归。
> 前端 **391 → 400**（**+9** = `navGroups.test.mjs`；另两条既有判据按 **M95** 同轮改口径、条数不变）；
> Java **60 → 60**（本轮 Java 只加了 `/traffic/v2/*` 三条网关映射，**用例数一条未变**）；
> `vite build` **160 → 171 modules**，**产物哈希已变**。
>
> **闸门项数 23 → 25 的由来**：本轮把穿帮文案扫描落成 `_scan_copy_leaks.py` 并接进闸门，
> 连同它的 `--self-test` 对照共**两条**。**它上线第一次运行就抓到 README 自己**
> —— `restates 工具链闸门审计项数 as 23, measured 25`：也就是"我把扫描器写了但没接闸门"
> 与"接进去了"这两件事，此前在文档里长得一模一样。**两个数都对，差额必须能点名。**
>
> **渲染文案的闸门谓词有一个坑值得单独记**：`"0 命中" in out` 会被 `10 命中` 满足
> （`"1" + "0 命中"`），也就是**命中越多越算过**。现在只认整句 `PASS 穿帮文案扫描：0 命中`。

以下为 **2026-10-18 实测** 的基线（**`0.10.1（Beta）`**，第二十轮 · 换芯第一版，**历史读数**）；本表只随逐项实测更新，引用前请重跑 —— 本轮数字与口径见 [`docs/algorithm-spec.md`](docs/algorithm-spec.md) **§8.5**（§8.4 是第十九轮、§8.3 及以下是第十一轮及更早的历史读数，保留不改写）。**本节按轮次分段**，最新的在上面：

| 套件 | 结果 | 墙钟 |
| --- | --- | --- |
| Python（pytest） | **497 passed / 0 skipped / 0 failed**（RC 0；收集 **497**；2 条第三方弃用告警） | 1603.31 s（26 min 43 s） |
| 前端（`node --test`） | **391 passed / 0 failed / 0 skipped**（**30** 个测试文件） | 见 §8.5 |
| Java（`mvnw.cmd test`） | **60 / 0 failed / 0 errors / 0 skipped**（BUILD SUCCESS） | 见 §8.5 |
| `vite build` | RC 0，**160 modules**（`index-D3aOMxG2.js` 2 135.98 kB / `index-Dh1ZCnII.css` 186.65 kB） | — |
| 冒烟链路（`_smoke_flows.py`） | **6/6 PASS**（`session-lifecycle` **18/18**，RC 0；两次独立运行均 PASS：66.3 s / 81.8 s） | 66.3 s / 上限 420 s |
| 工具链闸门（`_gate_toolchain.py`） | **GATE PASS** —— `AUDITS` 23 项（本轮新增 `version consistency` 与它的对照两条）＝ 打印 **23 行全 `ok`**；`--all` 另加 2 项长跑对照 ＝ **25 行全 `ok`** | — |
| 条目计数（`_verify_issue_counts.py`） | **entries 119 / 合计 150 / 表达式 150 / 差额 31**，`--self-test` **PASSED** | — |
| 迁移（`_verify_migrations.py`） | **7 条全部应用成功**（V7 = `ml_inference`），`--self-test` **PASSED** | — |
| 跨层审计（`_audit_gateway_routes.py`） | 前端 `/api` 调用 **21** / Java 映射 **37** / **unmatched 0 · undecidable 0 · unverified 0** | — |
| 云上复核（服务器上跑 `verify-remote.sh` ＋ `verify-static-remote.sh`） | **PASS 37 / FAIL 0 / SKIP 0**（RC=0，结论：全过）＋ 静态 **RC=0 / `static checks passed`** ＋ 本机侧公网 `200 / 0.467 s`；线上 `VERSION = 0.10.1-beta`、Flyway 已到 **v7**。⚠️ 旧记法里的 `_verify-live-deploy.sh` 是一次性脚本，**仓库里已无此物**，别再照抄 | — |
| 截图覆盖（`_shot_screens.py`） | **本轮未跑**（本轮未改分节清单；上次读数见 A 段） | — |
| 版面探针（`_probe_workbench_layout.py`） | **本轮未跑**（本轮未改版面；上次读数见 A 段） | — |

> **`0.10.1（Beta）`（2026-10-18）本节读数与上一版的对照**：Python **479 → 497 收集**
> （**+18 全部是新文件 `backend-python/tests/test_ml_core.py`**，可逐条点名，不含"解释不了"的增量；
> **跳过 0 → 0**，即上一轮那句"数据相关的 skip 这轮真的跑了"这次**没有重复出现**）；
> 前端 **366 → 391**（**+25** = `track1View.test.mjs` **17** 条 + `mlEffect.test.mjs` **8** 条；
> 另 `consoleSupport.test.mjs` 拆出 `ENTRY_LINKS` 后**条数不变**）；
> Java **50 → 60**（**+10** = `MlInferencePersistenceTest` **4** 条 + `Track1ArbitrationTest` **6** 条）；
> `vite build` **156 → 160 modules**（新增 `Track1Panel.vue` / `MlEffectBoard.vue` 及其样式），**产物哈希已变**。
>
> **闸门项数 21 → 23 的由来**：本轮新增 `_check_version_consistency.py` 与它的 `--self-test` 对照 **两条**，
> 而上一版是 **21 项** —— 两个数都对，**差额必须能点名**，否则"闸门变多"与"我记错了"长得一样。
> （第一版我把 21＋2 写成了 **22**，是闸门自己报 `restates 工具链闸门审计项数 as 21, measured 23` 才纠正过来 ——
> 这条判据只用了一分钟就证明了自己有用。）
>
> **交付包与清理**：包 **379 文件 / 11.1 MB**，zip **379 条目 / 0 目录条目 / 4.66 MB**，
> 包↔仓库逐字节 **379/379 一致**；对照 0.9.35 为 **+57 新文件 / 19 内容有变 / 0 删除**。
> 本轮把 `models/` 补进打包清单（它是 `/track1/ml` 的**运行期输入**，漏了只会让接口
> `available:false` —— "包少带一个文件"长得像"模型没训练"），并把 `data/training/annotate-cache`
> （**1 133 个请求缓存**）明确排除。**`.run/`（228 MB）已备份 44 个脚本到
> `backups/scratch-2026-10-18/run-scripts.zip`（CRC 全量核算 OK）后整目录删除**，
> 另删掉根目录一个 **0 字节**的 `60`（历史上 heredoc 写坏的同类残渣）。

以下为 **2026-10-17 实测** 的基线（**`0.9.35（Beta）`**，第十九轮，**历史读数**）；本表只随逐项实测更新，引用前请重跑 —— 那一轮的数字与口径见 [`docs/algorithm-spec.md`](docs/algorithm-spec.md) **§8.4**。**本节按轮次分段**，最新的在上面；A 段（2026-10-11，第十一轮）与它下面的笔记是**历史读数**，保留不改写：

> **`0.9.33（Beta）`（2026-10-15）本轮 Python 与前端都改了，四套件全部重跑**：
> Python **455 通过 → 466 通过**（总计 **476** = 466 + 9 跳过 + 1 xfail，RC 0，**2150 s**）、
> 前端 **354 → 356**（+2：`homeStage` 1 条 + `radarRelay` 静态契约 1 条）、
> Java **47**（未变；本轮一行 Java 源码未动，只改了 `pom.xml` 的版本串）、
> `vite build` **154 modules**（未变，但产物哈希**变了**：`index-BDyO2MK0.js` 2 114 306 B
> 对照 0.9.32 的 `index-D-u68t6t.js` —— **哈希变了才是"前端源码真的动过"的旁证**）。
> **Python 那 +11 通过里只有 +7 可归因**（3 条虚拟扫掠判据 + 4 条中继/会话键判据），
> 其余 **+4 通过 / +6 跳过 / +1 xfail 本轮未逐条归因** —— 按本表口径，
> **"解释不了"不写成"来自新增用例"**。
>
> **`0.9.33（Beta）` 本轮顺带修掉一条工具链坑**：PowerShell 5.1 在 `$ErrorActionPreference='Stop'` 下
> 把**原生进程的 stderr** 当成终止错误，于是 `.run/build-noinstall.ps1` 在 vite **已成功**之后中止，
> 留下没有 JAR 的半成品，而屏幕上唯一像错误的那行只是 vite 的 chunk 体积提示。
> **⇒ 判"构建成功"看 JAR 在不在、`sha256` 是多少，不看脚本有没有报错。**
> 已修在产生它的地方（`.run/build-noinstall.ps1` 与 `scripts/build.ps1` 两处），并记入
> [`changelog/ISSUES.md`](changelog/ISSUES.md) **ISS-0.9.33-04**。

| 套件 | 结果 | 墙钟 |
| --- | --- | --- |
| Python（pytest） | **479 passed / 0 skipped / 0 failed**（RC 0；收集 **479**） | 4028 s（67 min 08 s） |
| 前端（`node --test`） | **366 passed / 0 failed / 0 skipped**（28 个测试文件） | 4035.84 ms |
| Java（`mvnw.cmd test`） | **50 / 0 failed / 0 errors / 0 skipped**（BUILD SUCCESS） | 01:16 min |
| `vite build` | RC 0，**156 modules**（`index-Bx-AP6s_.js` 2 117.78 kB / `index-D3putjlp.css` 180.28 kB） | — |
| 冒烟链路（`_smoke_flows.py`） | **6/6 PASS**（`session-lifecycle` **18/18**） | 40.7 s / 上限 420 s |
| 工具链闸门（`_gate_toolchain.py --all`） | **GATE PASS** —— 审计 **21 项**（当轮读数；`AUDITS` 的具体项数以执行闸门模块时 `len(AUDITS)` 为准，**本行刻意不写成机器可读的复述式**，唯一锚点在上表）＋ `--all` 另 **2 项**长跑对照 ＝ 打印 **23 行全 `ok`** | — |
| 条目计数（`_verify_issue_counts.py`） | **entries 119 / 合计 150 / 表达式 150 / 差额 31**，`--self-test` **PASSED** | — |
| 云上复核（`_verify-live-deploy.sh`） | **PASS 15 / FAIL 0 / WARN 1 / SKIP 0**（WARN = 已知的 `degraded:true`） | — |
| 截图覆盖（`_shot_screens.py`） | **本轮未重跑**（本轮未改分节清单；上次读数见 A 段：10/10 分节 ＋ `--minute 360` 11/11） | — |
| 版面探针（`_probe_workbench_layout.py`） | **本轮未重跑**（本轮未改版面；上次读数见 A 段：PASS，四个负向对照全部触发） | — |

> **`0.9.35（Beta）`（2026-10-17）本节读数与上一版的对照**：Python **466 → 479 收集**
> （差 **+13** 全部是新文件 `backend-python/tests/test_weather_sources_extra.py`；**跳过 4 → 0** ——
> 那些 `pytest.skip` 是**数据相关**的（`test_traffic_network.py` 在"实时源不可用"时跳），
> 本轮实时源可用，故没有跳过；**这不是"用例变多"，是同一批用例这次真的跑了**）；
> 前端 **359 → 366**（**+7** = 信息密度接线 4 条 + 补充气象通道 5 条 − 演示模式退役 2 条）；
> Java **50 → 50**（新增两条 `@GetMapping` **不改用例数**，由跨层审计 `gateway routes` 守）；
> `vite build` **154 → 156 modules**（新增 `WeatherSupplements.vue` 及其样式），**产物哈希已变**。
> 另记一条**判据自身的坑**：`session-lifecycle` 曾报 14/15，根因在**冒烟流程自己** ——
> 它按 `scheduledMinute` 选驱动班次、而守卫读 `departureMinute`
> （见 [`changelog/ISSUES.md`](changelog/ISSUES.md) **ISS-0.9.35-03**）。修后 **18/18**。

### 历史读数（append-only，保留不改写）

> 以下笔记与表格是 **0.9.27 / 0.9.28** 两轮的原始记录（以及再往前的 2026-10-11 读数）。
> **它们不是当前读数** —— 当前读数见上面的 `0.9.35（Beta）` 表。里面的每一条都带着
> **当时的口径与理由**，而那些理由比数字更值得留，故连表一并保留。**引用前先确认你要的是哪一轮。**

> **`0.9.27（Beta）`（2026-10-12）本轮只改前端与文档**：前端 **337 → 346**
> （+9：`EVENT_COLORS` 族与两条延迟上限契约用例；`344` 是本轮改动前的当日读数），
> `vite build` **153 modules** RC 0。**Python 与 Java 本轮一行未动，未重跑**，
> 故下表它们两行仍是 2026-10-11 的读数，**不是本轮结论**。
>
> **`0.9.27（Beta）`（2026-10-12）第十五轮追加**：用户选定**彻底清理**（删掉全部
> **15** 个不可达文件 ＋ **4** 个只覆盖它们的测试）与**状态色全部统一**之后，前端基线
> **346 → 321**（**−25**，随模块退役而退休；`node --test` 实测 **321 passed / 0 failed**）。
> 同一轮另有：全局 `style.css` 由 **58 个类选择器收敛到 0**（产物 CSS **177.65 kB**）、
> 移除死依赖 `echarts`（lock **93 → 90** 条目、0 新增）。**下表前端一行仍是 2026-10-11
> 的 337** —— 该表只在**逐项全量重跑**时更新，本轮的 321 与它是**两次不同的测量**，
> 不合并成一个数。
>
> **`0.9.28（Beta）`（2026-10-13/14）本轮四套件全部重跑，下表数字即本轮读数**：
> Python **406 → 422**（**421 通过 / 1 跳过 / 0 失败**，RC 0，**1912.23 s = 31 min 52 s**；
> **+16 全部可归因** —— 新增的低能见度两档通道用例 `test_traffic_fog_layer.py`）；
> 前端 **321 → 336**（**+15**：9 条低能见度图层 + 6 条构建进度条）；Java **25**（未变）；
> `vite build` **153 modules**（未变）。
>
> **一条必须记下来的过程坑**：同日更早的一次全量报了 **406**，看着像"新用例没生效"。
> 真相是新测试文件落盘于**那次套件启动之后**，而 pytest **在会话开始时收集** ——
> 那 16 条根本没进那次运行。⇒ **跑全量前先 `--collect-only` 数一遍**，
> 因为"套件跑绿了"与"新用例跑过了"是两句不同的话。

| 套件 | 结果 | 墙钟 |
| --- | --- | --- |
| Python（pytest） | **406 passed / 0 failed / 0 skipped**（RC 0；**一处 `s` 都没有**，六行进度点 72×5 + 46 = 406 与总数逐点吻合） | 1601.55 s（26 min 41 s） |
| 前端（`node --test`） | **337 passed / 0 failed / 0 skipped** | 1.8 s |
| Java（`mvnw.cmd test`） | **25 / 0 failed / 0 errors / 0 skipped**（BUILD SUCCESS；**本轮改过 Java 源码**，套件重跑两遍） | 15.7 s |
| `vite build` | RC 0，**153 modules** | 2.8 s |
| 冒烟链路（`_smoke_flows.py`） | **6/6 PASS**（6 个流程） | 29.8 s / 上限 420 s |
| 工具链闸门（`_gate_toolchain.py --all`） | **12/12 ok**（默认档 **10 项**） | — |
| 条目计数（`_verify_issue_counts.py`） | **entries 92 / 合计 104 / 表达式 104 / 差额 12**，`--self-test` **PASSED** | — |
| 截图覆盖（`_shot_screens.py`） | **10/10 分节**（md5 互异）＋ `--minute 360` 再 **11/11** | — |
| 版面探针（`_probe_workbench_layout.py`） | **PASS**（四个负向对照全部触发） | — |

> **`passed` 不能跨轮相减 —— 这一轮它咬了自己一次，照实写。** 上一轮是 `398 passed / 0 skipped`，
> 这一轮 **`406`**。可归因的只有 **3 条**（`backend-python/tests/test_traffic_operations.py` 由 21 条补到 24 条），
> **另外 5 条本轮没有对应的文件改动**。按本表口径，**"解释不了"不写成"来自新增用例"** ——
> 那正是把没有读数的东西写成有读数。**「skip」不等于「通过」**这条口径仍然有效，本轮只是没有触发。
>
> 前端 304 → **337**：新增判据落在 `frontend/tests/consoleSupport.test.mjs` ——
> **「三次点击到达原始依据」的端到端路径判据**（按分节切片 + 断言提示里「」引的标题在落点页**逐字存在**）
> 与**情报页承诺的 6 个内容块**。**这条路径判据连续红了五次，五次全是判据自己的错**（判据的 bug 会以
> "产品缺陷"的形式被修掉）—— 详见 [`changelog/CHANGELOG.md`](changelog/CHANGELOG.md) 第十一轮 §3 与 `ISSUES.md` **M68**。
>
> **闸门本轮报过两次 FAIL，两次都是真信号**：`gateway routes` 抓到一键处置缺一条 Java 映射
> （`/api/traffic/operations/dispose`，**两端各自都"对"、缺的是中间那一腿**）；
> `behavioural gate` 抓到"前端产物比源码旧" —— 起因是负向对照脚本的**逐字节还原仍会更新 mtime**
> （**"内容没变"不等于"时间没变"**）。两处都修在产生它们的地方。
>
> **闸门默认档 10 项 / `--all` 12 项**：第九项「创新可达性」探针与第十项「闸门报告路径」自检在默认档，
> `--all` 额外跑 `behavioural gate` 与 `innovation bench` 两项**长跑对照**。


（此前 **2026-09-18** 的基线为 Python 279 / 前端 108 / Java 22 / 149 modules —— 已过期，差距不是一次改动造成的，详见 `docs/algorithm-spec.md` §8.3。）

重新生成证据与接口合同的命令见 [`changelog/CHANGELOG.md`](changelog/CHANGELOG.md) §复现方式。
