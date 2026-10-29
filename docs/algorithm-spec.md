# 算法规格书（0.9.26（Beta））

> **用途**：`docs/paper-innovations.md` 回答「有哪些创新点、为什么算创新」；**本文回答「它在哪里、要什么、给什么、代价多少、什么算错」**。
>
> 两份文档的分工是刻意的：前者可读、可讲；后者可**跳转**、可**核对**。任何一句「我们做了 X」在本文里都必须落到 `文件::函数`，并附带一条能独立重跑的复现命令。

## 0. 四条口径纪律（硬）

1. **每个数字必须带版本与规模**。同一句「最差 44.69°」在 134 个单体上是结论，在 18 个抽样上不是 —— **引用时把规模一起写**。
2. **性能数字必须报 warm / cold**。凸包剪枝走 `@lru_cache`，首次调用与命中缓存的代价差一个量级，只报一个数等于没报。
3. **复杂度优势 ≠ 墙钟优势**。§3 的 $O(n)\to O(h)$ 是**采样量**结论；墙钟要单独量。§6 记录了一处真实反例（采样量少 19.4×，墙钟反而慢）。
4. **不把「未验证」写成「已通过」**。本文所有判据的当前状态都标注了量它的命令与其**规模**。

---

## 1. 索引：8 项创新点 → 唯一实现位置

「唯一实现位置」是收录门槛（`paper-innovations.md` 前言）：**必须能指到具体函数**，不能是"整体设计思路"。

| # | 创新点 | 唯一实现位置（`文件::函数`） | 主判据（机器可判） | 运行可达（§0.1 实测） |
| --- | --- | --- | --- | --- |
| 1 | 谐波云团轮廓生成器（含曲率预算） | `traffic/weather.py::cell_outline_params` + `::_irregular_outline`（内含采样闭包 `_sample`）+ `::_worst_exterior_turn` | 最差外角 **≤ 45°** | **否**（运行侧 `weather_sim::_texture`） |
| 2 | 同源同心风险分层构造 | `traffic/weather.py::_caution_ring` / `::core_scale` / `::_core_outline` / `::_dissolve_regions` | `ban ∩ caution` 面积 **≤ 3.5×10⁻⁷ m²**（数值零）；最差外角 ≤ 45° | **否**（运行侧 `radar_field::_erode_to_core`） |
| 3 | 避让包络的凸包精确剪枝 | `traffic/weather.py::NetworkWeather._swept_window`（`lru_cache`）/ `::_band_hull` / `::_outline_hull_coords` | 剪枝结果与全采样**对称差 = 0 m²** | **否，且运行侧无对应实现** |
| 4 | 单一运动源的架构不变量 | `traffic/weather.py::NetworkWeather.centre_at`（配套 `::radius_at` / `::is_alive` / `::drift`） | 已绘区域 ⊆ 规划包络（**时空对齐**后） | **否**（运行侧 `weather_sim::_advection` / `::_cell_state`） |
| 5 | 对流单体生命周期与分裂的运动学模型 | `traffic/weather.py::NetworkWeather.radius_at` / `::_shed_daughter` / `::is_alive` | 峰值出现在生命期 **0.42**；生前死后半径 **0** | **否**（运行侧 `weather_sim::_life_curve` / `::_cohort_phase`） |
| 6 | 证据约束的问答降级 | `traffic/operations.py::explain` | 越界 id ⇒ 整条降级 `source='rule'` | **是** |
| 7 | fail-closed 数据缺失语义 | `traffic/weather_sources.py::weather_snapshot`（单一归一化入口）/ `traffic/cma_tiles.py::frame` | 数据缺失 ⇒ **不产出几何**（而非按"无风险"放行） | **是** |
| 8 | 工具链的可验证修复方法论 | `tools/maintenance/_gate_toolchain.py`（九审计 + 两个同伴闸门的汇总） | 二次运行 `rewritten == 0` —— **⚠ 0.9.26（Beta） 实测未达成：`rewritten 70`，且 11 个文件改写后不编译**（多行 `sys.path.insert` 使行式改写器留下孤立续行），见下 | 不适用（不在运行路径上） |

> **「运行可达」列的来源**：`tools/probes/_probe_innovation_reachability.py`（**作用域级调用图**，
> 已并入 `_gate_toolchain.py` 第九项审计）。**读法**：`否` 指本行标出的**那个实现位置**
> 没有任何请求路径能走到它，**不指这个思想在系统里没有实现** ——
> 1 / 2 / 4 / 5 的运行侧落点已在上表括号内给出，完整对照见
> `docs/paper-innovations.md` **§0.1.5**。**3 是唯一一个运行侧没有对应实现的**（已验证但未接线）。
>
> **第 8 行判据的状态必须写明**：`rewritten == 0` 是**该工具自己的验收判据**，
> 而 0.9.26（Beta） 实测为 **`rewritten 70 / unchanged 103 / skipped 32 / COMPILE FAIL 11`**。
> 那 11 个文件的**改写结果**不编译（原文件本身**全部正常编译**，已逐个 `py_compile` 复核），
> 成因是 `_apply_bootstrap_fix.py` 的**行式**改写器遇到跨行的 `sys.path.insert(...)`
> 会删掉首行、留下孤立的续行 —— **与 `paper-innovations.md` §5.5.2(b) 记录的是同一族缺陷（行式改写器不认识自己处理的是不是一整条语句）**。
> 该改写器**是 fail-safe 的**（不编译就不落盘），因此**没有文件被改坏**；
> 但代价是这 11 个文件**永远不会被规范化**，于是 `rewritten == 0` 这条判据在当前树上**不可能为真**。
> **如实记为未达成，不写作"通过"。**


**模块规模**（0.9.26（Beta），2026-10-09）：`weather.py` 1855 行 / `routing.py` 202 / `spatial.py` 239 / `zones.py` 358。

---

## 2. 谐波云团轮廓生成器（创新 1）

### 2.1 形式化

生成一族平面简单闭曲线 $\{P_i\}$，同时满足：

| | 约束 | 为什么是硬约束 |
| --- | --- | --- |
| (a) | 非圆、互不相同 | 视觉上要像真实对流单体 |
| (b) | **任意相邻边外角 ≤ 45°** | 下游把轮廓当作**真实空域边界**消费；尖刺会让绕行路径凭空扭曲 |
| (c) | 时间稳定 | 同一单体的形状参数不随时间重抽，否则逐帧重抽造成形状闪烁 |
| (d) | 可随单体存储复用 | §3 要求核心区与谨慎环与母体"可辨认地同源" |

(a) 与 (b) **对抗**：要"不规则"必须加大振幅与高阶谐波；谐波能量一高，在有限顶点数下采样就会混叠成锯齿。

### 2.2 接口

```python
cell_outline_params(rng, lobes=None) -> {
    'harmonics': [(order, amplitude, phase), ...],   # order = 2..(2+count-1)，count = lobes or rng.randint(5, 8)
    'stretch':   float,                              # 各向异性拉伸比，uniform(1.0, 1.45)
    'axis':      float,                              # 拉伸轴朝向（弧度），uniform(0, π)
}
```
- `amplitude = uniform(0.55, 1.0) / order**0.9` —— **幂律衰减**，order 2 主导主不对称性，高阶只加粗糙度。
- 逐单体独立抽相位/幅值/拉伸/朝向。

```python
_irregular_outline(cx, cy, radius, cfg, harmonics=None) -> shapely.Polygon
_worst_exterior_turn(points) -> float   # 弧度；判据本身
```
- 返回 `Polygon(points).buffer(0)`，**不做 simplify**（理由见 2.6）。

### 2.3 方法（三步，缺一不可）

**第一步 · 角度驱动的谐波和**

$$r(\theta) = R \cdot \Big(1 + \frac{\rho}{N}\sum_k a_k \sin(m_k\theta + \varphi_k)\Big),\qquad
x = r(\theta)\,s\cos\theta,\; y = r(\theta)\,\tfrac{1}{s}\sin\theta$$

驱动量必须是 $\theta$ 而**不是顶点索引**。用索引驱动（$\sin(m_k i + \varphi_k)$）会在多边形上产生"尖瓣花"，实测最大外角 **122°**。

**第二步 · 曲率预算（解析下界，作为起点）**

$$\text{budget} = \Big\lceil \frac{\rho \cdot \sum_k a_k m_k \cdot \frac{s + 1/s}{2} \cdot 2\pi}{\max(N,\varepsilon)\cdot \theta_{\max}} \Big\rceil,\quad \theta_{\max}=45°$$

配合 **半步步长采样相位** $\theta_i = i\frac{2\pi}{V} + \frac{\pi}{V}$：顶点数为偶数时 `index = V/2` 恰好落在 $\theta=\pi$（拉伸后的长轴端点、曲率最高处），该点独自承担全部曲率；偏移半步步长后极值点落在两采样点之间，转角由两点分摊。

**第三步 · 生成后测量、按需加密（实测补正）**

预算是**解析上界**，把 $\sum a_k m_k$（半径的**一阶**导数）当成了 $\theta_{\max}$（**二阶**量，曲率）的代理 —— 量错了导数阶。实测该公式对越限单体给出 14—16 顶点，而实际需要 96—144，**低估 6—9 倍**，因此 `vertices` 始终由 Nyquist 项 $24\lfloor m_{\max}/2\rfloor$ 决定，预算**从未生效**。

补正写成有界循环（`weather.py::_irregular_outline` 内的 `_sample`，`sample_cap = max(OUTLINE_VERTICES, 256) = 256`，最多 6 轮）：

```
vertices ← max(24, 24·⌊m_max/2⌋, budget)          # 起点：Nyquist 与解析预算取大
points   ← sample(vertices, phase = π/vertices)   # 半步步长
while worst_turn(points) > 45° and len(points) < 256:
    vertices ← min(256, max(⌈len(points)·1.08·worst_turn/45°⌉, vertices + 24))
    points   ← sample(vertices, phase = π/vertices)
```

三个性质使这个循环可用：**精确**（判据是刚生成顶点上的真实转角，不是对转角的估计）、**确定性**（不消耗随机数，同一 seed 逐位可复现）、**终止且代价有界**（步长按 $1/V$ 衰减律一次跳到位，实测 1—3 轮收敛；`cap` 封顶，触顶的单体由 `_bench_innovations.py` **显式报告**而非静默通过）。

### 2.4 复杂度

设顶点数 $V$、谐波数 $K$：单次轮廓求值 $O(VK)$，**与半径无关**（解析式，无栅格化）。

对照的栅格路线：$O(W\cdot H)$ 栅格化 + 等值线提取 + 简化，且**曲率不可先验约束** —— 这是与"栅格 + 等值线"最本质的差别。

实测规模上限：$V \le 256$（`sample_cap`）、$K \in [5,8]$ ⇒ 单次求值 ≤ 2048 项三角和。

### 2.5 判据与实测（0.9.26（Beta），seed 42，**134 个单体**）

| 指标 | 实测值 |
| --- | --- |
| 最差外角（曲率保护**开**） | **44.69°**，**0** 个单体 > 45° |
| 最差外角（曲率保护**关**，反面对照） | **55.78°**，**4** 个单体 > 45° |
| 半径变异系数 CV | 均值 **0.1598**（0.143—0.174） |
| 面积跨度（最大/最小） | **22.78×** |
| 形状签名去重 | **134 → 134 个唯一签名**（无重复） |
| 最短边 | **43.0 m**（0 处 < 10 m，无碎边） |

### 2.6 反面案例（三条，都有实测）

| 反面做法 | 实测后果 |
| --- | --- |
| 顶点索引驱动谐波 | 尖瓣花，最大外角 **122°** |
| 等幅高频谐波 | 得到星形而非云形 |
| 共享相位 | 所有云团成为同一形状的缩放副本 |
| **只做 Nyquist**（$24\lfloor m_{\max}/2\rfloor$） | 漏掉 stretch 放大的长轴端点：WX-1-08 达 **47.85°**、WX-1-03 达 **46.88°** |
| **粗抽样自证** | 只抽 18 个「层×分钟」⇒ 结论"最差 40.66°，合格"；全时轴 5 分钟步长扫描 **480 分钟**后同一份代码暴露 **17 处**越限、最差 46.88° —— **且全部落在抽样点之间** |
| 轮廓上做 `simplify(120 m)` | 5 km 的核心被削成 19 顶点、外角 **47.5°**；6—10 km 单体上出现 **90.0°** 直角 |

> **方法论结论**：几何质量判据必须在**全时轴**上扫描。粗抽样不是"抽到差一点的样本"，而是**系统性地漏掉极值** —— 它给出的是**虚假通过**。
>
> **处置**：轮廓返回时**不做 simplify**；每个消费者按自己实际工作的尺寸施加容差（渲染方保留完整轮廓，包络方先取凸包故根本不看顶点数）。

### 2.7 复现

```bash
backend-python/.venv/Scripts/python.exe tools/benches/_bench_innovations.py --section 1
backend-python/.venv/Scripts/python.exe tools/recon/_probe_stored_outline.py      # 形状多样性与签名去重
backend-python/.venv/Scripts/python.exe tools/recon/_probe_convex_full.py         # 全时轴凸角
```

---

## 3. 同源同心风险分层构造（创新 2）

### 3.1 形式化

每个风险单体画三层 —— **核心 `ban`（禁入，≥ 45 dBZ）** / **谨慎环 `caution`（须批准，≥ 35 dBZ 且不在核内）** / **外场 `field`（监测，≥ 35 dBZ）** —— 必须同时满足：**(a) 两两不相交；(b) 无缝隙**（`field = ban ⊎ caution`）；**(c) 视觉上同源**。

### 3.2 接口

```python
NetworkWeather(seed, scenario).shapes(t)
    -> [(cell, field, ban, caution), ...]      # caution 恒等于 field - ban
```
> **口径提醒**：第二项是 **field（外场）**，不是核心。`tools/benches/_bench_innovations.py` 第 4 节曾把第二项误名为 `ban`（行为正确、命名误导），0.9.26 已改名。

### 3.3 方法

**核心洞察：三层由同一组低阶谐波生成，只有半径不同。**

$$P_{\text{core}} = \text{Outline}\big(\text{harmonics}_{\text{low}},\ r\cdot 0.58\big),\qquad P_{\text{ring}} = P_{\text{outer}} \setminus P_{\text{core}}$$

两条边**按构造同源** ⇒ 严格同心 ⇒ 差集无交叉可留薄片。把"事后修补伪影"变成"**伪影在拓扑上不可能产生**"。

**合并层必须重建，不能求并：**

$$\text{CAUTION} = \Big(\bigcup_i P_{\text{field},i} \cup \bigcup_i P_{\text{caution},i}\Big) \setminus \bigcup_i P_{\text{core},i}$$

即"先合外场，再挖掉**合并后**的核心"，两层恒不相交。

### 3.4 复杂度

逐单体为常数次布尔运算；合并层由 `_dissolve_regions(shapes)` 重建，代价随参与区域数线性增长（实测 21 单体 → 15—17 区域）。

### 3.5 判据与实测（0.9.26（Beta），seed 42，`--section 2`）

| 指标 | 实测值 |
| --- | --- |
| **关键不变量**：合并面积 == 逐单体裁剪面积之和 | 对称差 **< 1.0 m²** |
| `ban ∩ caution` | **3.494×10⁻⁷ m²**（数值零） |
| **最差外角**（同源环 vs 朴素差集） | **39.21°** vs **104.87°** |
| 包络泄漏 > 1 m² 的「层×分钟」组合 | **0 / 945** |
| 合并粒度 | 21 单体 → **15—17 区域**；多边形 63 → 45—51 |

**两处必须说清的口径**：

1. **`ban ∩ caution` 不是数值精确的 0，是 3.494×10⁻⁷ m²（≈0.35 mm²）。** 构造保证的是"两条边同源 ⇒ 差集没有交叉可留薄片"，不是"浮点运算恰好得零"。把它写成"= 0"会在有人换了几何库之后变成一句无法复核的话。
2. **本时隙的判别量是「外角」，不是「碎片计数」。** 碎片计数（面积/周长 < 1）在两侧**都是 0** —— 它在这个时隙没有区分度，不能拿来当"同源更优"的证据。真正有区分度的是外角：朴素差集在 `t=120` 的 3 个区域上出现 **104.87°** 的尖角，同源环为 **39.21°**（< 45° 限值）。

### 3.6 反面案例（三条，都有实测）

| 反面做法 | 实测后果 |
| --- | --- |
| `ring = field.buffer(+900).difference(core)`（两条光滑但**互不相关**的曲线求布尔差） | 交叉处留下尖角：`t=120` 最差外角 **104.87°**；历史上在单体 WX-3-06 上实测到 **177.4° 与 166.0°** —— 这是数值伪影，不是空域，渲染出来是穿过"实心"空域的细刺 |
| $\text{CAUTION} = \bigcup_i \text{caution}_i$（直接并各成员谨慎环） | 一个单体的核心落进另一单体的谨慎环，把"禁入"涂成"须批准"：溢出 **3.86×10⁸ m²** |
| 用**合并后**的核心去挖未合并的外场 | 见 §3.3：必须**先合外场、再挖合并后的核心**，否则两层会相交 |

### 3.7 复现

```bash
backend-python/.venv/Scripts/python.exe tools/benches/_bench_innovations.py --section 2
backend-python/.venv/Scripts/python.exe -m pytest backend-python/tests/test_weather.py -q
```

---

## 4. 避让包络的凸包精确剪枝（创新 3）

### 4.1 形式化

求"一段时间窗口内，移动且变形的风险体的**扫掠包络**"，作为规划器避让约束。约束是**单侧安全**：

$$\text{env} \supseteq \bigcup_{t\in\text{window}} \text{shape}(t)$$

偏小会放行轨迹穿带；偏大只是保守。**因此不接受任何以"偏小"为代价的近似。**

### 4.2 接口

```python
NetworkWeather.envelope(start_minute, end_minute) -> shapely.Polygon
```
- **在边界处分箱**：`_swept_window(math.floor(start/5), math.ceil(end/5))`。分箱**必须在这里做**，否则缓存键退化为原始浮点对（实测 13411 个 raw pair / 13419 次调用，逐个唯一、缓存完全失效），而分箱后的整数对会重复。
- 内部 `_swept_window` 带 `@lru_cache(maxsize=2048)`。

```python
_outline_hull_coords(geometry) -> [(x, y), ...]   # 轮廓先取凸包（820 → 49 顶点）
_band_hull(cell_index, start_bin, end_bin)        # 雨带的凸包路径
```

### 4.3 方法：两处正交的剪枝

**剪枝一（本节核心贡献）：平移量只需取漂移路径凸包的顶点。**

扫掠集合是 $\{\text{outline} + \text{drift}(t)\}$，而漂移是**纯平移**（无旋转、无缩放）。于是：

> 只有落在"漂移路径凸包"**顶点**上的那份平移，才能给结果凸包贡献极值点。

**这不是采样近似 —— 是精确的。** 证明思路：凸包由"某方向上的极值点"定义；平移 $t$ 后在某方向达极值，当且仅当 $t$ 在该方向的**支撑函数**上达极值，而支撑函数是线性的，其极值必在漂移路径凸包的顶点取到。

**剪枝二：轮廓本身先取凸包再平移**（820 → 49 顶点）。与剪枝一**正交可叠加**：剪枝一说"平移量只需取凸包顶点"，剪枝二说"轮廓也可以先取凸包"。

### 4.4 复杂度

| | 漂移偏移量个数 | 说明 |
| --- | --- | --- |
| 全枚举 | $O(n)$，$n$ = 窗口内 tick 数（实测 **97**） | 每个 tick 一次平移，且每个 tick 都要取该时刻各簇的轮廓 |
| 凸包精确剪枝 | $O(h)$，$h$ = 漂移路径凸包顶点数（实测 **5**） | 漂移偏移量 **少 19.4×** |

> **⚠ 19.4× 是「漂移偏移量个数」的结论，不是墙钟结论。** §4.7 给出实测：单次冷调用两者基本持平。

### 4.5 判据与实测（0.9.26（Beta），seed 42，`--section 3`）

| 指标 | 实测值 |
| --- | --- |
| 窗口 (0,18) (0,36) (1,14) (12,107) (56,70) 上，全枚举 vs 剪枝 | **缺失面积 0.000 m²**（5/5 个窗口） |
| 保守侧余量（剪枝超出全枚举的面积，取最差窗口） | **1.004×10¹¹ m²**（含 2200 m pad 与"跨段桥接"，见下） |
| 包络泄漏 > 1 m² 的「层×分钟」组合 | **0 / 945** |
| 生命周期峰值半径 vs 包络余量 | **1.40—1.52×**（恒 > 1） |

**第三条方向相反，必须一起报。** 包络是**单侧安全**的：它必须容纳已绘集合，多出来的面积是刻意的代价，不是缺陷。其中最大的一块是**跨段桥接** —— 把整条簇链的坐标先并起来再求凸包，会得到一个跨过链间空隙的凸体；实测桥接后的包络 **268,011 km²**，逐簇并集 **137,881 km²**，即 **48.6% 的面积不在任何云下**。它被保留是因为**运营效果实测为零**：把 7760 条已规划航迹的全部航迹点拿去命中窗口内的桥接区域，**0 个点**落入其中（`tools/probes/_probe_band_bridging.py`）；而逐簇构造实测让单次规划由 66 s 变成 92 s（**+39%**，且成因未查明）。为一个可证惰性的差异付出一个未解释的 39% 代价是错的。若将来有航迹真的穿过桥接走廊，`_probe_band_bridging.py` 会第一个报出来。

### 4.6 反面案例（四条，都有实测）

| 反面做法 | 实测后果 |
| --- | --- |
| 固定步长 stride 2 | 漏掉 **2,232,551 m²** |
| 固定步长 stride 5 | 漏掉 **191,289,917 m²** |
| **凸包剪枝（采用）** | 漏掉 **0 m²** |
| 雨带包络用"中心轨迹 buffer"（而非采样位置凸包） | 雨带宽 ~190 km；buffer 中心轨迹得 ~240 km 圆盘 ⇒ 糊死空域，计划大面积不可行 |
| 对**单个分量**做剪枝 | 雨带是 **MultiPolygon，20 个分量**（`WX-NORTHEAST-BAND`：20 分量 / 1940 顶点 / 2.32×10¹⁰ m²）—— 剪枝必须对"分量**并集**"整体做，对单分量做会漏掉链上其余部分 |
| **Minkowski 捷径**：只把漂移偏移求凸包再与轮廓凸包相加 | 漂移弧远非凸（97 个采样里 92 个严格落在自己的凸包内），返回的包络**偏小**：实测 121,638,561,897 m² vs 真值 174,724,291,628 m²，**漏掉 53,085,729,730 m²** |

> 「固定步长抽样」与「窗口吸附」两种做法已**被否决，勿再试**。

> **⚠ 对照侧的机会成本（0.9.26 修正）**：本节此前的 stride 数字（stride 2 漏 303,023 m²、stride 5 漏 21,694,389 m²）是在"对照侧只用**静态**轮廓"的旧写法下测出的。雨带改成**簇链 + 逐簇生命期**之后，那个对照会把"该窗口内早已散掉的段"也算成应被覆盖的面积，于是同时给出两个错误结论：一个**假缺口**（56..70 窗口虚报 17,950 km² 缺失）和一个**假性能结论**（剪枝看起来更慢，因为静态轮廓只有一个 48 顶点凸包）。基准脚本的对照侧已改为**逐 tick 逐簇枚举** —— 回归的证据本身也要被核对，否则一条错误的对照会把算法判成没做到。

### 4.7 性能口径（warm / cold，0.9.26（Beta），单机 Windows 10，quiet machine）

`window 0..96 min`，`seed 42`，`scenario moving`，单次取 5 轮均值：

| 路径 | 墙钟 | 口径 |
| --- | --- | --- |
| 全枚举（97 个 tick × 20 个簇） | **190.21 ms** | cold（每次重建点集） |
| 剪枝路径，缓存 **cold** | **176.35 ms** | 含 Minkowski 和 + 2200 m pad buffer |
| 剪枝路径，缓存 **warm** | **0.00 ms** | `lru_cache` 命中 —— **不可与上两行比较** |

**结论（逐字照抄，不得只引一半）**：

> 剪枝把**漂移偏移量**由 97 降到 5（**19.4×**），但在本窗口的**单次冷调用**上与全枚举**基本持平**（两次实测比值为 **1.08× / 0.95×**，落在测量噪声内）。原因是剪枝路径额外付出 Minkowski 和与 pad buffer 的代价，而全枚举只做一次凸包。
>
> **真正的收益在缓存**：一次规划会**重复**请求同一个窗口（实测约 **588 个不同窗口 / 13,419 次调用**），因此规划器付出的是"每个不同窗口一次冷调用 + 大量热命中"，命中率实测约 **59.8%**（不是早先笔记里写的 92.3% —— 那个数字经不起复测，已作废）。
>
> **所以任何引用本节的地方都必须同时给 cold 与 warm**，只报 warm 会把"缓存很快"说成"算法很快"。

**推论（写进论文时的正确措辞）**：把 19.4× 表述为**问题规模**（$O(n)\to O(h)$）的约化，**不得**表述为同等倍数的加速。复杂度收益要兑现成墙钟收益，取决于三个都与剪枝无关的条件：窗口复用率、pad buffer 的顶点数、以及 Minkowski 和的规模。

### 4.7 复现

```bash
backend-python/.venv/Scripts/python.exe tools/benches/_bench_innovations.py --section 3
backend-python/.venv/Scripts/python.exe tools/probes/_probe_band_hull_cost.py
backend-python/.venv/Scripts/python.exe tools/probes/_probe_cells.py
```

---

## 5. 单一运动源的架构不变量（创新 4）

### 5.1 问题

系统里有两个几何必须**永远一致**：

| 消费方 | 入口 | 语义 |
| --- | --- | --- |
| 地图上**画**的 | `NetworkWeather.shapes(t)` | 逐分钟精确位置 |
| 规划器**避**的 | `NetworkWeather.envelope(start, end)` | 一段时间的包络 |

两者不一致，用户看到的现象就是"**轨迹穿过图上画的风险区**"。这是本项目**反复出现的真实故障**，不是假设。

### 5.2 不变量

> **`centre_at(cell, t)` 是表达运动的唯一位置；任何需要"单体在 $t$ 时刻在哪"的代码都必须调用它，不得重写。**

**根因**（历史故障）：早期 `shapes()` 与 `swept()` **各写了一份运动算术**，随维护逐渐漂移，最终 `swept()` 漏掉了雨带（雨带只存在于 `shapes()` 的局部变量中，不在 `self.cells` 里）—— 整条最大的风险区没有参与避让包络。

**配套修法**：把雨带**升格为一等单体**（`shape == 'BAND'`，只平移不改形状），使它进入 `self.cells`，从而自动被 `envelope()` 覆盖。

**这条不变量的价值不在"少写重复代码"**，而在把一致性从"需要靠审计和测试维护"提升为"**结构上难以违反**"。

### 5.3 接口与判据

```python
centre_at(cell, t) -> (x, y)     # 唯一运动源
radius_at(cell, t) -> float       # 生命周期半径（创新 5）
is_alive(cell, t) -> bool
drift(cell, t) -> (dx, dy)        # 纯平移增量
```

| 判据 | 实测值 |
| --- | --- |
| 包络泄漏（同时覆盖渲染与规划两个消费方） | **0 / 945** |
| **时空对齐**后：5724 个有航迹班次，落入风险外缘 / 核心 | **0 班 / 0 班** |
| `centre_at(cell,120)` 两次读数一致 | **True** |
| 雨带是 `cells` 的一等成员 | **True** |

### 5.4 反面案例（时空对齐是硬要求）

拿 $t=30$ 的风险面去比对一架 $t=200$ 路过该坐标的班次 ⇒ **278 班假阳性**。

> 风险面随风漂移，**"位置对上"不等于"时间对上"**。必须按航迹点**自身的分钟**取该分钟的面。

### 5.5 复现

```bash
backend-python/.venv/Scripts/python.exe tools/benches/_bench_innovations.py --section 4
backend-python/.venv/Scripts/python.exe tools/harness/_verify_swept_safety.py
```

---

## 6. 中等分量三项（创新 5—7）

### 6.1 对流单体生命周期与分裂（时序建模）

**位置**：`traffic/weather.py::NetworkWeather.radius_at` / `::is_alive` / `::_shed_daughter`；常量 `CELL_PEAK_AGE_FRACTION = 0.42`。

```
progress = age / life
shape    = 1 - ((progress - peak)/peak)^2         if progress <= peak
         = 1 - ((progress - peak)/(1 - peak))^2   otherwise
radius   = nominal * (0.18 + 0.82 * shape)
```

选**开口向下抛物线**而非 S 曲线的两条理由：雷达统计确实如此；**末端陡降**让单体"消失"而非"渐隐拖尾"。

**分裂**：子体生于母体生命期的 30—55%（近成熟期），寿命更短（0.6—0.9×），位置沿母体**运动轴**偏移并带横向分量；两者风速略有差异，使**间隙随时间增长**而非冻结。

**实测**：峰值出现在 progress **0.40**（设定 0.42），峰值比 **0.998**，生前死后半径均为 **0**；时轴可见单体数 **1—7** 波动（非常数）；分裂对 **8 组**（跨 6 seed），其中 **6 组**间隙随时间增大（如 `WX-3-02-D1`：25.4 → 32.7 km）。

> **已知缺陷（如实记录）**：`_shed_daughter()` 返回的 dict **不含 `parent` 键**，血统信息丢失，只能靠 id 后缀 `-D1` 识别子体。已列入遗留清单。

### 6.2 证据约束的问答降级（可靠性）

**位置**：`traffic/operations.py::explain`。

LLM **不允许自由生成**：只返回 `{"evidenceIds": [...]}`，返回后校验

```python
isinstance(ids, list) and 1 <= len(ids) <= 5 and all(i in by_id for i in ids)
```

任一不满足 ⇒ 整条回答**降级**到规则路径（`source='rule'`，`errorCode` 带原因）。

**价值**：把"LLM 幻觉"这个不可控风险，转成"**输出必须落在预构造证据集内**"这个**可验证约束**。降级是**整条**而非局部修补，避免半生成半规则的不一致状态。

### 6.3 fail-closed 数据缺失语义（可靠性）

**位置**：`traffic/weather_sources.py::weather_snapshot`（唯一归一化入口）、`traffic/cma_tiles.py::frame`。

**语义**：数据缺失 ⇒ **不产出几何**，而不是按"无风险"放行；且降级**显式**，不静默。

**为什么对本系统是硬要求**：本系统输出的是**空间约束**。若数据缺失被解释为"无风险"，规划器会**主动把航班排进真实存在的风险区** —— 错误方向是**不安全**侧。这与一般 Web 系统"降级返回空列表"的直觉相反。

---

## 7. 工具链的可验证修复方法论（创新 8）

**位置**：`tools/maintenance/_gate_toolchain.py --all`（四层审计的汇总闸门）。

**背景**：`tools/` 下 138 个开发脚本在目录整理后**全部失去可运行性**（111 个带损坏特征，分 7 类）。手工修 111 个文件是 111 次引入新笔误的机会 —— 故做法是"**先建检查器，再让检查器驱动批量改写**"。

**四层审计**（每层都抓到过真实缺陷）：

| 审计 | 检查什么 | 抓到过的真实缺陷 |
| --- | --- | --- |
| `compile()` 门 | 改写后能否解析 | 2 个文件 `from __future__` 顺序被破坏 |
| AST 未绑定名 | 以 `mod.attr` 引用但从未绑定的 stdlib 名 | 用了 `io.StringIO` 无 `import io` |
| 后置重复 import | 后置 `from _repo import X` 覆盖先前的 `X = Path(X)` | 13 个文件把 `Path` 包装**还原成 str** |
| 内嵌 payload import | 内嵌 payload 字符串引用未导入的模块 | 子进程 payload 用 `sys` 未导入 |
| 根路径上溯 | 从已导入的 `ROOT` 再上溯一级 | 得到 `C:\Users\<user>` |
| **执行层**（真跑一遍） | 运行每个脚本并分类 | **20 个运行期失败（编译期全绿）** |

> **关键结论**：`compile()` 全绿而行不通 —— **静态检查的通过不等于脚本可运行**，执行层不可省略。

**三个由假阴性逼出来的设计决定**：

| # | 假阴性 | 教训 |
| --- | --- | --- |
| a | `set.intersection()` **无参调用返回自身副本** ⇒ 相减把**所有发现都抵消**，审计报"0 问题"而脚本照样崩 | **假阴性比异常更危险，因为它不报错** |
| b | 行式改写器删掉三引号字符串里的 `import sys` ⇒ 子进程 `NameError`；且**下次运行会再次静默撤销修复** | 行式改写器无法区分代码与文本，必须问 `tokenize` |
| c | 规范块重复写入 ⇒ 重复包装 | **幂等性是可测的硬指标**：验收判据 = 第二次运行 `rewritten == 0` |

**闸门当前检查项**（`--all`，2026-10-09 实测）：`unbound names` / `late re-import` / `payload imports` / `root climb` / `restore imports` / `gateway routes` / `issue counts` / `counts control` / `behavioural gate` / `innovation bench` —— 十项全绿。

---

## 8. 性能与基线口径（引用前必读）

> **另见：[`docs/evaluation-algorithm/algorithm-contrast.md`](evaluation-algorithm/algorithm-contrast.md)**
> —— 四组「朴素做法 vs 本算法」的实测对照（连续移动 / 按预计经过时刻扫掠 / 单阈值从严 /
> 单阈值从宽），全部带规模、越核口径与**量具自证**。本文讲"代价多少"，那份报告讲
> **"不做它会怎样"** —— 两句话都写下来，算法的地位才是可指认的，而不是一句自我评价。

### 8.1 引用纪律（三条，硬）

1. **每个性能数字必须写三项**：**版本** + **网络规模** + **warm/cold**。同一句"包络 176 ms"在 `0.9.18` 与 `0.9.26` 不是同一个数，在"东北三省 36 个地级行政区"与"单城"也不是同一个数，cold 与 warm 差到无法同框。
2. **不得把复杂度结论写成墙钟结论**（§4.4 / §4.7 是本文的示范，也是本文的一处反例）。
3. **量具没量成 ≠ 量出来坏了**（`M60`）。跑任何探针前先确认前置条件成立（服务已起、解释器正确）；出口必须是三类：`0 通过` / `1 量出来坏` / `2 无法测量`。本项目**唯一**正确的解释器是 `backend-python/.venv/Scripts/python.exe` —— 用托管 Python 跑闸门会得到 `ModuleNotFoundError: No module named 'fastapi'`，读起来像依赖缺失，其实是解释器选错。

### 8.2 本文出现的全部计时数字

| 量 | 值 | 口径 | 出处 |
| --- | --- | --- | --- |
| 单次轮廓求值 | ≤ 2048 项三角和 | 解析式，**与半径无关** | §2.4 |
| 全枚举包络（单次） | **190.21 ms** | 0.9.26（Beta）/ 东北三省 / window 0..96 / 20 簇 / seed 42 / cold | §4.7 |
| 剪枝包络（单次） | **176.35 ms** cold｜**0.00 ms** warm | 同上 | §4.7 |
| 逐簇构造（**被否决**） | **92 s/规划** vs 66 s（+39%，成因未明） | 同上 | §4.5 |
| 缓存命中率 | 约 **59.8%**（588 个不同窗口 / 13,419 次调用） | 同上 | §4.7 |

### 8.3 基线（第十一轮，2026-10-11 实测）

| 套件 | 结果 | 墙钟 | 备注 |
| --- | --- | --- | --- |
| Python（pytest） | **406 passed / 0 failed / 0 skipped**，RC 0（`.run/pytest-r11.out`） | **1601.55 s（26 min 41 s）** | 慢尾段集中在 `simulate` 相关用例；单次规划 12—17 s。**本轮一次全量，`0 skipped`**。**`406` 与上一轮 `398` 的差额没有完全归因**：本轮只动过 `tests/test_traffic_operations.py`（21 → 24），其余 5 条没有对应的文件改动 —— **那 5 条只是找不到解释，不是找到了解释**（见下方口径） |
| 前端（`node --test`） | **337 passed / 0 failed / 0 skipped** | **1.8 s** | 新增判据落在 `consoleSupport.test.mjs`：**三次点击的路径判据**（切片 + 逐字标题）与**情报页 6 个内容块** |
| Java（`mvnw.cmd test`） | **25 / 0 failed / 0 errors / 0 skipped**，BUILD SUCCESS | 15.7 s | **本轮改过 Java 源码**：`DecisionController` 的白名单由 `{action:note\|disposal}` 补为 `{action:note\|disposal\|dispose}`（闸门 `gateway routes` 抓到的**第四条死路由**）。套件重跑两遍：改前 25 / 12.9 s、改后 25 / 15.7 s |
| `vite build` | RC 0，**153 modules** | 2.8 s | — |
| 冒烟链路（`_smoke_flows.py`） | **6/6 PASS**（6 flow） | 29.8 s | 上限 420 s |
| 工具链闸门（`_gate_toolchain.py --all`） | **12/12 ok**（默认档 **10 项**） | — | 含 `behavioural gate` 与 `innovation bench`；**本轮它报过两次 FAIL，两次都是真信号**：`gateway routes` 抓到缺映射、`behavioural gate` 抓到"产物比源码旧"（起因是负向对照的**逐字节还原仍会更新 mtime**） |
| 算法增量对照实验（`_bench_algorithm_contrast.py`） | **五组**（四组朴素对照 + 无气象决策基线），RC 0 | 约 7 min | 报告与 JSON **同出一轮读数**；抬头带版本 / 指纹 / 快照（见 §5、§6 of `changelog/CHANGELOG.md` 第十一轮） |
| 条目计数（`_verify_issue_counts.py`） | **entries 91 / 合计 102 / 表达式 102 / 差额 11** —— ok | — | `--self-test` **PASSED**（4 + 9 + 2 全数命中）；变异字面量已改为**从文件自身取值** |
| 截图（`tools/probes/_shot_screens.py`） | **10/10 分节**（md5 互异）；`--minute 360` 再 **11/11** | — | 清单从 `runtime.js::SECTION_NAMES` **读**，不手写 |
| 版面探针（`_probe_workbench_layout.py`） | **PASS**（四个负向对照全部触发） | — | — |

> **`passed` 不可跨轮相减 —— 本轮这条口径咬了自己一次，照实记。** 上一轮基线是 **`398 passed / 0 skipped`**。
> 本轮 **`406`**，差 6+2。可归因的只有 3 条（`test_traffic_operations.py` 的 21 → 24，
> 即 `ISS-0.9.26-01` 的顺序判据）；**另外 5 条本轮没有对应的文件改动**
> （`find tests -newermt <上次读数时刻>` 只命中那一个文件）。
> 也就是说：**差额里有一部分我解释不了**。按本表口径，**"解释不了"不写成"来自新增用例"** ——
> 那正是把没有读数的东西写成有读数（**M66 / M70**）。
> 上一轮那条"`378 → 398` 的 20 里既有新用例、也有被 skip 的三条"**仍然是有效解释**，
> 本轮的 5 条**不是同一回事，只是暂时没有名字**。

> **第三轮与第四轮的旧读数，按 §6 的纪律保留原文，不随新版本改写：**
>
> | 轮次 | Python | 前端 | Java | modules |
> | --- | --- | --- | --- | --- |
> | 第十轮（2026-10-10） | **398 / 0 skipped**（1582.66 s） | 304 / 0 failed | 25 / 0 failed | 153 |
> | 第九轮（2026-10-09 夜） | 380 收集 / 378 passed（两次读数见下） | 278 | 25 | 153 |
>
> **第九轮的两次读数（不同结果、同一棵树）**：`380 collected / 378 passed / 2 failed`（1403 s）与
> `381 collected / 378 passed / 0 failed / 3 skipped`（1498 s）—— 差别来自**外部天气源可达性**，
> 详见下方 blockquote。

> **`0 skipped` 这件事本身要证明，而不能只报一个总数。** 本轮 `406 passed` 且**一处 `s` 都没有**
> —— 六行进度点 **72×5 + 46 = 406** 全满，与总数逐点吻合。它上一次被证明是在第十轮：
> 那一轮的 `398 passed / 0 skipped` 与此前第九轮的 `378 passed / 3 skipped` 相对照，
> 那三条穿越断言当时因**外部天气源不可达**走了 skip 分支。三条独立事实互证：
>
> | 事实 | 读数（第十轮，判据仍在树上） |
> | --- | --- |
> | 全量末行 | `398 passed, 2 warnings in 1582.66s (0:26:22)` —— 无 `skipped` 字段 |
> | `tests/test_zones.py` 单独复跑 | **21 passed / RC 0（28.08 s）** —— 源可达 |
> | 计划自述（同一轮） | `weatherSnapshot.available` 为真、`coverage.returnedCities` > 0、`accepted` > 0 |
>
> **「skip」不等于「通过」**这条口径**仍然有效** —— 它是源不可读时的**第三种出口**（M60）；
> 为它配的两重牙齿（负向对照用例 + 一次性注入对照）**保留在套件里**，随时可以重新被走到。
> **本轮无 `skip`，但本轮真正需要注意的是另一件事**：`406` 与 `398` 之间有 **5 条没有归因的差额**
> （见上方主表说明）—— **把"解释不了"写成"来自新增用例"，才是这一轮最该避免的那种错**
> （**M66 / M70**：没有读数的东西不得写成有读数）。

> **上一轮（0.9.26 第九轮，2026-10-09 夜）的读数，按 §6 纪律保留原文，不随新版本改写：**
>
> | 次序 | 结果 | 墙钟 | 输出 |
> | --- | --- | --- | --- |
> | 第一次 | **380 collected / 378 passed / 2 failed** | 1403 s | `.run/pytest-0926.out` |
> | 第二次 | **381 collected / 378 passed / 0 failed / 3 skipped** | 1498 s | `.run/pytest-0926b.out` |
>
> 第一次的 2 条失败与第二次的 3 条 skip 是**同一件事的两种报法**：三条断言
> （`test_plan_records_approvals_without_closing_the_network`、`test_every_recorded_crossing_carries_its_legal_basis`、
> `test_strict_airport_reading_is_available_and_measured`）的被测对象是**在飞的班次与其穿越记录**，
> 而它们跑在 `service.simulate(seed=42, scenario='live')` 上。复现该计划并读它**自己的自述**：
> `weatherSnapshot.available=false`、`provider='OPEN_METEO'`、`qualityFlags=['SOURCE_UNAVAILABLE']`、
> `errorCode='ConnectTimeout'`、`coverage.returnedCities=0` → `stats.accepted=0`、
> `closedByReason={'WEATHER_UNAVAILABLE': 7760}`。**一架都没起飞，所以不可能存在穿越记录** ——
> 失败的是"被测对象不存在"，不是代码。**本机对 `api.open-meteo.com` 的可达性是间歇的**：
> 全量套件期间超时，紧接着的 `curl` 三次都是 **HTTP 200（1.4–4.3 s）**，冒烟链路在同一天
> **36 城取数返回 200**。这解释了为什么同一棵树能先后给出"2 failed"与"3 skipped"。
> **当时发现的套件真缺陷与它的修法（`skip` 作为第三种出口 + M29 的两重牙齿）仍然在树上。**
> **仍未做的**是把这三条与外部依赖**解耦**（改用一个不依赖公网的场景，或把"必然穿越"变成夹具不变量）
> —— 那会改变断言覆盖的路径，属独立一轮的判据设计。


> **与旧基线的差异（必须一并报）**：`README.md` 里 2026-09-18 的基线是 Python **279** / 前端 **108** / Java **22** / **149 modules**。四项都已过期，**不是某一次改动造成的**：Python 279 → **406**、前端 108 → **337**、Java 22 → **25**、modules 149 → 153。引用旧数会低估覆盖面，也会把"很久没复核"读成"一直是这个规模"。
>
> **`_build_frontend.py` 的 node 路径已改为动态解析**：原先硬编码 `…/node/versions/22.22.2-3/node.exe`，托管运行时升到 `22.22.2-6` 后该路径不存在，两个步骤全部以 `FileNotFoundError: [WinError 2]` 退出 —— 这个报错读起来像"vite 缺失"，实际是"node 缺失"。现在按 `ALC_NODE` → 托管版本（新到旧）→ `PATH` 的顺序解析，并在日志里打印实际使用的 node。

### 8.4 基线（第十九轮，2026-10-17 实测）

**这一节是本文件里唯一"当前有效"的基线**；§8.3 及其下方全部 blockquote 是**第十一轮（2026-10-11）及更早的历史读数**，按 §6 纪律保留原样、不随版本改写。**引用数字前先看清它属于哪一轮。**

| 套件 | 结果 | 墙钟 | 备注 |
| --- | --- | --- | --- |
| Python（pytest） | **479 passed / 0 skipped / 0 failed**，RC 0 | **4028 s（67 min 08 s）** | 收集数 **479**（上一轮 466）。**跳过 4 → 0 不是用例变多，是数据相关的 skip 这次真的跑了**；收集数的 **+13** 才是新增，全部落在 `backend-python/tests/test_weather_sources_extra.py` |
| 前端（`node --test`） | **366 passed / 0 failed / 0 skipped**（28 个测试文件） | **4035.84 ms** | 359 → 366 的 **+7** ＝ 信息密度开关接线 **+4**、补充气象通道 **+5**、演示模式退役 **−2**。**差值是三笔可逐条点名的账，不是一句"新增用例"** |
| Java（`mvnw.cmd test`） | **50 / 0 failed / 0 errors / 0 skipped**，BUILD SUCCESS | **01:16 min** | 本轮加了**两条** `@GetMapping`（`traffic/weather/observations` 与 `traffic/weather/models`），**用例数不变** —— 网关映射由跨层审计 `_audit_gateway_routes.py` 守，不被单测覆盖 |
| `vite build` | RC 0，**156 modules** | — | 产物 `index-Bx-AP6s_.js` **2 117.78 kB** / `index-D3putjlp.css` **180.28 kB**（154 → 156 modules）。**哈希变了才是"前端源码真的动过"的旁证** |
| 冒烟链路（`_smoke_flows.py`） | **6/6 PASS**（`session-lifecycle` **18/18**） | **40.7 s** / 上限 420 s | 本轮它报过 FAIL，**是真信号**：选对象谓词读 `scheduledMinute`，而守卫读 `departureMinute`（地面等待让后者更晚，实测 23 / 33）⇒ 选中 31 分班次后在 minute 31 发 RESUME 被拒 |
| 工具链闸门（`_gate_toolchain.py --all`） | **GATE PASS** —— `AUDITS` **21 项** ＋ `--all` 另 **2 项**长跑对照 ＝ 打印 **23 行全 `ok`**，RC 0 | — | 本轮它报过一次 `counts control FAIL`：**故障在自检的变异锚点、不在检查本身**（锚点写死追加 `+1`，而分布表末项已变成 `+2`）。**本行原写「19 项 / 21 行」—— 19 是加 `rules parity` 与 `rules parity control` 之前的读数，加完就是 21；0.10.1 复查时按 `len(AUDITS)` 更正** |
| 条目计数（`_verify_issue_counts.py`） | **entries 119 / 合计 150 / 表达式 150 / 差额 31**，`--self-test` **PASSED** | — | 自检 **4 in-file + 10 restatement + 2 blind-spot** 全数命中 |
| 交付包 | **322 文件 / 7.9 MB**；zip **322 条目 / 0 目录条目 / 4.12 MB** | — | 包↔仓库**逐字节 parity 322/322、0 不同**；`_diff_pack` 对照 0.9.34：**+4 新文件、18 内容有变、0 删除**。**sha256 不写在这张表里** —— 每重打一次包它就变一次，把它抄进文档就是在制造一个几小时后即过期、却看不出过期的参照物 |

> **与 §8.3（第十一轮）的对照必须一并报**：Python 406 → **479**、前端 337 → **366**、Java 25 → **50**、modules 153 → **156**。四项都涨，但**涨的成因不同**：前端与 Python 的增量可逐笔点名（见上表"备注"列），modules 的 +3 来自 `WeatherSupplements.vue` 及其两个依赖；**Java 25 → 50 是十个轮次累积的结果，不能归给本轮** —— 本轮 Java 用例数一条未变。**引用旧数会低估覆盖面，也会把"很久没复核"读成"一直是这个规模"。**

> **本轮新增的两条外部源不在上表里**，因为它们**不进主链路的计时**：MET Norway（1995 ms）、AWC METAR（784 ms，bbox 23 站）、DWD ICON（978—1637 ms）走**按需调用的两个只读端点**，各自缓存 10 分钟。主链路每轮都抓天气、目标 ≤10 秒，把补充请求串进去等于**把外部服务抖动变成页面加载抖动**。上线前的两件待办见 `docs/云端部署与运维说明.md` §10.8。

### 8.5 基线（第二十轮，2026-10-18 实测 · `0.10.1（Beta）`）

**§8.6 起是当前有效基线**；本节及以下按 §6 纪律保留原样、不随版本改写。

| 套件 | 结果 | 墙钟 | 备注 |
| --- | --- | --- | --- |
| Python（pytest） | **497 passed / 0 skipped / 0 failed**，RC 0 | **1603.31 s（26 min 43 s）** | 收集数 **479 → 497**，**+18 全部是新文件 `backend-python/tests/test_ml_core.py`**（判据 / 特征 / 打分器 / 服务四层），**没有一条增量是"解释不了"的**。跳过 **0 → 0**：上一轮那句"数据相关的 skip 这次真的跑了"本轮不再成立，因为本来就没有 skip |
| 前端（`node --test`） | **391 passed / 0 failed / 0 skipped**（**30** 个测试文件） | 见上表—本轮未单独计时 | **366 → 391**：`track1View.test.mjs` **17** 条 + `mlEffect.test.mjs` **8** 条；`consoleSupport.test.mjs` 把 `KPIS` 与 `ENTRY_LINKS` 拆开（`model` 是 KPI 条下的入口、不是 KPI 格），**条数不变** |
| Java（`mvnw.cmd test`） | **60 / 0 failed / 0 errors / 0 skipped**，BUILD SUCCESS | 见上表 | **50 → 60**：`MlInferencePersistenceTest` **4** 条（`@DataJpaTest` + 内存 H2 + 真 Flyway + **`ddl-auto=validate`**）＋ `Track1ArbitrationTest` **6** 条（含"模型更乐观时规则否决"：BAN + FIT + conf 0.99 ⇒ BAN） |
| `vite build` | RC 0，**160 modules** | — | 产物 `index-D3aOMxG2.js` **2 135 977 B** / `index-Dh1ZCnII.css` **186 648 B**（**156 → 160**：`Track1Panel.vue` / `MlEffectBoard.vue` 及其样式）。**哈希变了才是"前端源码真的动过"的旁证** |
| 冒烟链路（`_smoke_flows.py`） | **6/6 PASS**（`session-lifecycle` **18/18**） | **81.8 s** / 上限 420 s | 本轮未改动它测的六条流，属于**回归通过**而不是新覆盖 |
| 工具链闸门（`_gate_toolchain.py`） | **GATE PASS** —— `AUDITS` **23 项**；`--all` 另 2 项长跑对照 ＝ **25 行全 `ok`** | — | **21 → 23**：新增 `version consistency` 与它的 `--self-test` 对照。**它上线第一次运行就抓到 README 标题仍停在 `0.9.35（Beta）`** —— 也就是"版本号改完了"这件事此前**没有任何判据在读** |
| 迁移（`_verify_migrations.py`） | **7 条全部应用成功**（V1–V7），`--self-test` PASSED | — | V7 新增 `ml_inference`；H2 把 `DAY` 当保留字这件事写在 V7 抬头 |
| 跨层审计（`_audit_gateway_routes.py`） | 前端 `/api` **21** / Java 映射 **37** / unmatched **0** · undecidable **0** · unverified **0** | — | 本轮新增 5 条 Java 映射（`/track1/ml`、`/track1/ml/status`、`/track1/ml/summary`、`/track1/arbitrate`、`/system/version`） |
| 条目计数（`_verify_issue_counts.py`） | **entries 119 / 合计 150 / 表达式 150 / 差额 31**，`--self-test` PASSED | — | 本轮新增 **M90 / M91 / M92 / M93** 四条方法论但**没有新增 ISS 条目**，所以条目数仍是 **119**（方法论不加条目）。**M93 是清理带出来的**：删掉 `.run/` 之后 `quota coverage` 才报出它一直在读 `config/nginx/` 之前的旧落点 —— 闸门输入住在用完即弃的目录里；现快照缺席时以 `-- skipped (nginx snapshot absent: …)` 结束，闸门只接受这一个词 |
| 交付包（`_build_handoff_pack.py` / `_make_zip.py`） | **379 文件 / 11.1 MB**；zip **379 条目 / 0 目录条目 / 4.66 MB** | — | 包↔仓库**逐字节 parity 379/379、0 不同**；`_zip_smoke` **ALL OK**（CRC＋字节级＋换 cwd）；`_diff_pack` 对照 0.9.35：**+57 新文件、19 内容有变、0 删除**。**新增 `models/` 进 `ROOT_DIRS` 与 `must_have`** —— 它是 `/track1/ml` 的运行期输入，漏了不会报错、只会让接口 `available:false`（"包少带一个文件"长得像"模型没训练"）；**`data/training/annotate-cache`（1 133 个请求缓存）明确排除**，它不是交付物。**sha256 不写在这张表里** —— 每重打一次就变一次，抄进文档等于制造一个看不出过期的参照物 |

**轨1 模型的读数**（`data/training/model-v1-metrics.json`，测试集 **170 条**，时间切分、不打乱）：

| 候选 | macroF1 | accuracy | 危险漏报（DANGER + BAN，n=99） |
| --- | --- | --- | --- |
| HistGradientBoosting | **0.9885** | 0.9882 | 0/99 |
| **RandomForest（导出选用）** | **0.9770** | **0.9765** | **2/99** |
| ExtraTrees | 0.8909 | 0.8882 | 7/99 |
| LogisticRegression | 0.4027 | 0.4882 | 30/99 |
| 规则基线（拒判计弃权、不计入分母） | 0.3933 | 0.4412 | 23/99 |

> **三句必须一起说的话**：① **macroF1 衡量的是"模型对判据的复现能力"，不是"预测天气的能力"** —— 标签来自 `config/labels-v1.json`，规则基线在同一套标签上只有 **0.3933**，说明"把判据写成阈值"与"让模型学判据"是两件事；② **最高分（HGB 0.9885）不是导出的那个** —— 它无法导出为树，`selection.note` 里写明 `bestByMetric` 与 `chosen` 的差异，**不把它藏起来**；③ **导出侧 parity：测试集 170 条、不一致 0 条**（纯 Python 树打分 vs sklearn 预测），模型 **594.7 KB / 200 棵树**。
> **判据与 DeepSeek 的一致性 κ = 0.7946**（`label-agreement.json`）—— DeepSeek 是**第二标注员**，不是标签源：它 1 133 条里只给 27 条 FIT（2.4%），是**系统性一档偏移**，不是噪声。

### 8.6 基线（第二十一轮，2026-10-19 实测 · `0.11.1（Beta）`）

**这一节是当前有效基线**；§8.5 起是历史读数，按 §6 纪律保留原样、不随版本改写。

| 套件 | 结果 | 墙钟 | 备注 |
| --- | --- | --- | --- |
| Python（pytest） | **513 passed / 1 skipped / 0 failed**，RC 0，收集 **514** | **2495.52 s（41 min 35 s）** | 收集 **497 → 514**，**+17 全部是新文件 `backend-python/tests/test_v2_probability.py`**（融合裁决全网格 / 期望损失与「取消是兜底」/ 频次表无样本不插值 / 模型卡契约 / 台账往返）。**跳过 0 → 1 已逐条归因**：唯一那条是 `tests/test_traffic_network.py:128`（`live snapshot produced no drawable tier in this environment`），**不是新增用例**、也不是回归 —— 它是环境相关守卫，**能在两次运行之间来回翻**，所以上一版写「0 skipped」与本版写「1 skipped」两句都是真的 |
| 前端（`node --test`） | **400 passed / 0 failed / 0 skipped**（**31** 个测试文件） | 见上表 | **391 → 400**：**+9** 全部来自新增 `navGroups.test.mjs`（五组结构 / 子页名不写第二份 / 归组双向对账 / 三层反查 / 阈值只一处 / 缺值印「—」/ `hourLabel(null)` 返空串 / 置信度门限 / 组件内不得自写 0.8 与 0.5）。另两条既有判据按 **M95** 同轮改口径（`mlEffect.test.mjs`、`homeStage.test.mjs`），**条数不变** |
| Java（`mvnw.cmd test`） | **60 / 0 failed / 0 errors / 0 skipped**，BUILD SUCCESS | **31.1 s** | **用例数一条未变**：本轮 Java 侧只加了 `/traffic/v2/*` 三条网关映射。**刻意不加** `ml_inference` v2 留痕表 —— 裁决留痕落 Python 侧 `decisions/<workspace>.jsonl`，Java 再写一份就是两个写入口两个口径（M24 的同一形态） |
| `vite build` | RC 0，**171 modules** | — | 产物 `index-CYARziSc.js` **2 177 791 B** / `index-CKLFG6eA.css` **206 592 B**（**160 → 171**：`SituationBrief` / `CorridorPanel` / `ModelCardPanel` / `CounterfactualPanel` / `DivergencePanel` / `CommandPalette` 及样式） |
| 冒烟链路（`_smoke_flows.py`） | **6/6 PASS**（`session-lifecycle` **18/18**） | **38.4 s** / 上限 420 s | 本轮未改动它测的六条流 → 属**回归通过**，不是新覆盖。⚠️ 必须用 `backend-python/.venv/Scripts/python.exe` 跑；用托管解释器会得到 `ModuleNotFoundError: fastapi` —— **那个报错长得像依赖缺失，实际是解释器选错** |
| 工具链闸门（`_gate_toolchain.py`） | **GATE PASS** —— `AUDITS` **25 项**；`--all` 另 2 项长跑对照 ＝ **27 行全 `ok`** | — | **23 → 25**：新增 `copy leaks` 与它的 `--self-test` 对照。**它上线第一次运行就抓到 README 自己**：`restates 工具链闸门审计项数 as 23, measured 25` |
| 迁移（`_verify_migrations.py`） | **7 条全部应用成功**（V1–V7），`--self-test` PASSED | — | 本轮未新增迁移 |
| 跨层审计（`_audit_gateway_routes.py`） | 前端 `/api` **28** / Java 映射 **40** / unmatched **0** · undecidable **0** · unverified **0** | — | **21 → 28、37 → 40**：v2 的六个只读端点 + `POST decision`，以及它们在 Java 网关上的三条映射 |
| 条目计数（`_verify_issue_counts.py`） | **entries 119 / 合计 150 / 表达式 150 / 差额 31**，M 上界 **99**，`--self-test` PASSED | — | 新增 **M96 / M97 / M98 / M99** 四条方法论，**没有新增 ISS 条目**，所以 `entries` 仍是 **119**。另：0.10.1 那一行历史表里的 `AUDITS` **23 项** 已去掉粗体 —— 判据要求「当前基线」是**唯一**一处重述，历史段保留数字但不与它竞争同一个正则 |
| 截图覆盖（`_shot_screens.py`） | **14/14** 分节各一张，**md5 全互异** | — | **10 → 14**：`profile` / `card` / `counterfactual` / `ledger` 四页，就绪判据带**内容锚点**（`.corr-detail h2` / `.mc-table tbody tr` / `.cf-head` / `.dg-hd`），不是「元素存在」 |
| 交付包（`_build_handoff_pack.py` / `_make_zip.py`） | 见 `README.md` 当轮小节 | — | METAR 原料（`raw/` / `series.csv` / `om-*.csv`，合计 **42 MB**）不进包；运行期必需的三个模型 + `model-v2-metrics.json` + `dataset.json` 进 `must_have` |

**轨2 模型的读数**（`data/training/metar/model-v2-metrics.json`，测试集 **26 193** 行，时间切分 train ≤2023 / val 2024 / test ≥2025、不打乱）：

| 任务 | 正例率 | AUC | 工作点 τ | **TS** | POD | FAR | Brier | BSS | 0.5 处 TS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `vis3k` 能见度 <3000 m | 6.33%（1 657） | 0.9470 | **0.30** | **0.4936** | 0.6741 | 0.3517 | 0.0298 | 0.5053 | 0.4896 |
| `gust` 阵风 >10 m/s | 3.50%（917） | 0.9358 | **0.21** | **0.2846** | 0.4460 | 0.5597 | 0.0254 | 0.2508 | 0.1806 |
| `vis` 能见度 <1000 m | 0.77%（202） | 0.9528 | **0.23** | **0.2568** | 0.4653 | 0.6357 | 0.0060 | 0.2179 | 0.2131 |

三条基线（同一测试集、同一标签，TS）：

| 任务 | 持续性 | Open-Meteo 逐时值 | 单要素阈值规则 | 模型 |
| --- | --- | --- | --- | --- |
| `vis3k` | 0.4855 | 0.0967 | 0.0337 | **0.4936** |
| `gust` | 0.1861 | 0.1804 | 0.1861 | **0.2846** |
| `vis` | **0.2683** | 0.0311 | 0.1972 | 0.2568 |

样本量 **train 130 939 / val 26 274 / test 26 193**；跨阈事件的**提前量中位数**：`vis` 120 min（n=10）、`vis3k` 60 min（n=62）、`gust` 60 min（n=56）。可靠性曲线 **10 箱**、失败样本 **各 20 例**均已落盘。

> **这一组数字有三句话必须一起说**：
> ① **`vis` 那一格是输的**（0.2568 < 持续性 0.2683）。它是三个任务里正例最稀的一个（202/26 193 = 0.77%），
> 也是唯一一个「按现状报就会输给一句『下一小时跟这一小时一样』」的格子。**只报赢的两格是最容易被一句话拆穿的那种报告。**
> ② **`thresholdRule` 在 `vis3k` 上只有 0.0337 不是笑话**：那条规则判的是「当下 <800 m」，而任务是「未来 1–3 h 内 <3000 m」——
> **基线弱，说明的是基线与任务错配，不是说明模型强**。把它当对手打赢了没有意义，判据里因此把「赢基线」写成描述而不是结论。
> ③ **Open-Meteo 基线是近似基线**：取 `historical-forecast-api` 的逐时值、**不带起报时刻**，不是同一起报时次的业务预报。
> `baselineNote` 已随载荷发布，模型卡页也写了这一句。

> **两条读数纪律（本轮各踩一次）**：
> ① **「哈希变了」这条旁证，只有在哈希被重测过之后才成立。** 本版第一次记录的产物是
> `index-DE6vDSEG.js` / `206 588 B`，那是**最后一次文案改动之前**的构建；重跑后实测为
> `index-CYARziSc.js` / **2 177 791 B**、`index-CKLFG6eA.css` / **206 592 B**。两次都"跑过构建"，
> 但只有后一次与仓库当前状态对应。**引用前重跑，不是客套话。**
> ② **墙钟不可跨版本直接比**：本轮 pytest 与 Java、前端套件**有重叠**，2495.52 s 与 §8.5 的 1603.31 s
> 不构成"变慢了 55%"的证据。要比较先保证同一台机、同一并发度、无重叠。
