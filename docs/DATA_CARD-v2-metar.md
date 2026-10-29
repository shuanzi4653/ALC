# 数据卡 v2 —— 短临气象概率模型（`ml-v2`）

> 0.11.1（Beta）新增。与 [`DATA_CARD-v1.md`](DATA_CARD-v1.md) **并行、不替代**：
> v1 描述的是轨1 的"情景 → 判据档位"数据集（标签来自 `config/labels-v1.json`），
> v2 描述的是"METAR 实测 → 未来 1–3 h 是否发生"数据集（标签来自**观测本身**）。
> 两张卡的标签来源不同，**指标不可并列比较**。

---

## 1. 一句话定位

**用三个机场 7 年的逐时实测报文，训练一个"未来 1–3 小时会不会出现低能见度 / 强阵风"的概率模型。**
标签是观测，特征是观测，评分用气象圈那四个（AUC / TS / POD / FAR / Brier），并且必须对着三条基线看。

## 2. 来源与时间窗

| 项 | 值 |
|---|---|
| 数据源 | Iowa State University · [ASOS archive](https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py) |
| 报文类型 | `report_type=3`（逐时 METAR） |
| 站点 | `ZYTX` 沈阳桃仙 / `ZYCC` 长春龙嘉 / `ZYHB` 哈尔滨太平 |
| 时间窗 | 2019-01-01 ～ 2025-12-31 |
| 行数 | **183 493** 行（每行 = 一站一小时） |
| 特征行数 | **183 406**（首个 3 小时窗口因回看特征不足被丢弃） |
| 落盘 | `data/training/metar/series.csv` + `dataset.json`（含 `sha256`） |
| 复现 | `python tools/ml/build_metar_dataset.py`（外网；全量约 4.5 min） |

运行时的近实时观测**不用这个源**：`/traffic/v2/*` 的观测走 Aviation Weather Center 的
`metar` 接口（`backend-python/weather/metar_history.py`，近 9 小时、10 分钟缓存）。
两者站点相同、字段口径相同（单位换算写在同一处），**不是同一份报文**，因此
"训练集里某一小时的值"与"线上同一小时的值"允许有分钟级差异。

## 3. 字段与单位（**这张表是防静默错配的唯一依据**）

接口返回的是**英制**，全部换算进 SI。换算写错一位不会报错，只会让阈值判断整体偏移。

| 原始字段 | 含义 | 单位 | 换算 | 去向 |
|---|---|---|---|---|
| `vsby` | 能见度 | 法定英里 | **×1609.344** m | `visM` |
| `sknt` | 持续风 | 节 | **×0.514444** m/s | `windMs` |
| `gust` | 阵风 | 节 | ×0.514444 | `gustMs`（见 §5.1） |
| `drct` | 风向 | 度 | 分解为 `wdirSin` / `wdirCos` | 两列 |
| `tmpf` | 气温 | 华氏 | `(F-32)×5/9` | `tempC` |
| `dwpf` | 露点 | 华氏 | 同上 | `dewC`（并派生 `dewSpread`） |
| `skyl1` | 云底高 | 英尺 | **×0.3048** m | `cloudBaseM`（见 §5.2） |
| `skyc1` | 云量 | 代码 | — | 晴空判定用 |
| `alti` | 修正海压 | 英寸汞柱 | **×33.8639** hPa | `qnhHpa` |
| `mslp` | 海平面气压 | — | **不可用**：`report_type=3` 下整列不返回（实测 0/8 736） | — |

派生特征（窗口 `t-3 h` ～ `t`）：`visMin3h` / `visMin6h` / `gustMax3h` / `windChange3h` /
`qnhTendency3h` / `visChange3h` / `tempTendency3h` / `spreadTendency3h`；
时间编码 `hourSin` / `hourCos` / `month`；站点编码 `stationCode`；
缺失指示 `miss_vis` / `miss_gust` / `miss_cloud` / `miss_temp`。共 **26 维**。

## 4. 标签与切分

窗口 `t+1 h` ～ `t+3 h`，命中任一小时即为正例：

| 任务 | 定义 | 正例率（全量） |
|---|---|---|
| `vis` | 能见度 < **1 000 m** | 0.71% |
| `vis3k` | 能见度 < **3 000 m** | 6.33% |
| `gust` | 阵风 > **10 m/s** | 2.12% |

切分**按时间**、区间不相交：train ≤ 2023-12-31 / val 2024 / test ≥ 2025-01-01。
不用随机切分：相邻小时高度相关，随机切分会让"前一天"出现在训练集、"后一天"出现在测试集，
指标会虚高（这是气象/时序任务最常见的一处自欺）。

## 5. 已知局限（引用这批数据时必须一并说明）

### 5.1 阵风的"缺失"不是缺测，是"没有阵风"

METAR 只在出现阵风时报 `G`。实测 **gust 缺失 97.43%**（只有 4 712 小时报了阵风）。
语义上这意味着"这一小时没有阵风"，故**用持续风回填**，并在数据的每一行留痕
`gustSource ∈ {OBSERVED, FALLBACK_WIND}`（OBSERVED 4 712 / FALLBACK 178 781）。

> **代价必须说清**：`gust > 10 m/s` 这个任务因此**大半建立在"持续风回填"之上**，
> 它更接近"风很大"而不是"出现了阵风"。`gust` 的 TS（0.2846）也是三者里最不稳定的一格。

### 5.2 云底高的"缺失"同样有两种含义

`skyl1` 大量为 `M`，且常与 `skyc1 ∈ {CLR, SKC, NSC, NCD, CAVOK, M}` 同时出现 ——
与"晴空"同义。故给 5 000 m 哨兵并记 `cloudSource ∈ {OBSERVED, CLEAR_SENTINEL, MISSING}`
（OBSERVED 55 801 / CLEAR_SENTINEL 127 691 / MISSING 0）。
哨兵值不是观测值：云底判据（<300 m）在哨兵上永远不成立，这与"没报云底"在业务上是一致的，
但**读数据时必须知道这 127 691 行不是量出来的**。

### 5.3 只有三个站

三站都在机场，彼此相距 200–500 km。任何"走廊概率"都是这三点的**插值**
（1/d²，最近 3 站），最近站距 >250 km 时 `confidence='LOW'`、只给"建议人工复核"。
**不要把它读成"整片区域的实测"。**

### 5.4 事件定义是本项目的选择，不是气象标准

`<1000 m` / `<3000 m` / `>10 m/s` 是本项目按运行含义定的阈值（与 `config/rules-v1.json`
的地图几何阈值、SFI 规则阈值**允许不同**，三者是不同用途）。换成气象行业的
LIFR/IFR 分级会得到另一组数字，两组不可混用。

### 5.5 3–6 h 那一段不是本模型

`MODEL_EXTENSION` 段由 Open-Meteo 逐时值按**历史频率表**映射成概率
（`model-v2-metrics.json::omProbability`）。它是频率映射，不是模型推理；图上已分色，
脚注已写明。频率表里**没有样本的区间返回 `None`，不插值** —— 插出来的数最像真的，
但它不是观测到的频率。

## 6. 指标（test 集，工作点阈值）

| 任务 | AUC | 工作点 | TS | POD | FAR | Brier | 对持续性基线 |
|---|---|---|---|---|---|---|---|
| `vis3k` | 0.947 | 0.30 | 0.4936 | 0.6741 | 0.3517 | 0.0298 | **赢**（0.4855） |
| `vis` | 0.9528 | 0.23 | 0.2568 | 0.4653 | 0.6357 | 0.006 | **输**（0.2683） |
| `gust` | 0.9358 | 0.21 | 0.2846 | 0.4460 | 0.5597 | 0.0254 | **赢**（0.1861） |

> 工作点阈值是**在验证集（2024）上按 TS 最大化**选的，不是 0.5 ——
> isotonic 校准之后概率很少越过 0.5。`atThreshold05` 那一组也随载荷发布，便于对照。

## 7. 复现步骤

```bash
# 1) 拉三站 7 年逐时 METAR（需外网，约 4.5 min）
python tools/ml/build_metar_dataset.py
# 2) 拉 Open-Meteo 同期逐时值（作基线 + 3–6 h 频率表，约 2 min）
python tools/ml/build_om_history.py
# 3) 训练 + 导出 + 基线 + 失败样本（sklearn 在 D 盘 Anaconda，运行期不装）
D:/Anaconda3/python.exe tools/ml/train_nowcast.py
#   → models/ml-v2-{vis,vis3k,gust}.json + data/training/metar/model-v2-metrics.json
```

第 3 步的产物里 `exportParity` 必须满足 `maxAbsDiff <= 1e-6`；
不满足说明纯 Python 树与 sklearn 走样，那种偏差会被误读成"模型不稳定"。
