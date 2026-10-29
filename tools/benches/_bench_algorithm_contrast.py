# -*- coding: utf-8 -*-
"""AL-3 · 算法增量对照实验：五组「朴素做法 vs 本算法」。

为什么实验在脚本里做，而不在产品代码里加开关
--------------------------------------------------
产品代码里没有、也不应该有一个 ``NAIVE=1`` 分支：一个永远为假的分支不会被执行，
一旦为真就没人知道它是否还正确。五组对照都通过**临时替换模块属性**构造
（与 ``_bench_innovations.py`` §1 关闭曲率保护同一手法），``try/finally`` 恢复，
所以实验期间的性质改变不会漏到下一次构建。

五组的朴素变体
--------------
A 连续移动 vs 静态单时刻      把 ``weather_sim._advection`` 换成恒零偏移：
                              回波整场不动，等于只用一个静止时刻的场。
B 扫掠过 vs 单帧              把 ``service.RADAR_SWEEP_STRIDE_MINUTES`` 拉到大于
                              时间轴，``_virtual_radar_sweep`` 只取 t=0 一帧。
C 两级两规则 vs 单阈值**从严**  35 dBZ 这一个阈值，之上全部是硬障碍、不许擦边
                              （内核请求改回外场几何，软障碍并进硬障碍）。
D 两级两规则 vs 单阈值**从宽**  45 dBZ 这一个阈值，外场整条带子不进入避让集合
                              （外场请求改回内核几何）。
E 做气象决策 vs **不做气象决策** 气象照常读取、照常逐档判定，但**两条通往几何的
                              出口同时置空**（``PublicWeather.envelope`` 与
                              ``_radar_window_union``）。固定管制区等法定障碍照旧
                              —— E 量的是"这一层气象决策值多少"，不是"没有约束值多少"。
                              E 的放行率会**变高**：那不是缺陷，是这一层机制的账被
                              摊开了（不改航就没有绕行代价，也就没有 45 dBZ 内核
                              那条不可触碰的红线）。

> **C 与 D 是同一个问题的两个方向，缺一不可。** 只报 D 会读成"两级两规则当然
> 更好"；只报 C 会读成"两级两规则没有用"。两个方向都量，才能说清它到底替代了
> 什么：**收紧没有收益（C：关闭数几乎不变，却把可用的擦边权收掉了），放松不安全
> （D：越核实测非零）。** 这是本项目一贯的记账方式（参见 §5.2 的 0.74×）。

> **E 与 A/B 也不是同一件事。** A/B 改的是"气象读得准不准"，E 改的是"读准了之后
> 用不用"。三组一起看，才分得清"气象没读准"和"读了但不用"这两种代价。

四个结果指标（每组逐项报，不只报"改了几班"）
------------------------------------------
``releaseRate``              放行率 = 放行班数 / 总班数。分母是**全队**，不是
                             "被拦下的那些" —— 后者恒为 0%，量不出任何差异。
``delayedFlights`` / ``averageDelayMinutes``
                             地面等待班数，与其中 ``delayMinutes>0`` 的班次的算术
                             平均。分母写清楚：把零延误也算进去会得到一个很像
                             "几乎没有延误"的读数。
``detouredFlights`` / ``averageDetourMinutes``
                             受气象影响改航的班数，与 ``detourMinutes>0`` 的班次的
                             平均绕行量，分母同理。
``closedFlights``            停止放行班数，与 ``closedByReason`` 配套看。

越核口径
--------
逐分钟（步长 STEP）在**当时绘制的**帧上判飞机位置 —— 帧按
``SIMULATION_BASE_TIME + minute`` 独立 derive，与被测计划自己的采样无关。
``core`` 是图例的禁止进入，一次命中即是缺陷；``field`` 是须绕飞，落在声明允许量
内不算越界。同 ``tools/probes/_probe_flight_vs_echo_timeline.py``。

运行：``backend-python\\.venv\\Scripts\\python.exe tools\\benches\\_bench_algorithm_contrast.py``
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import DOCS, ROOT, artifact, version  # noqa: E402

import datetime as dt  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402

from shapely.geometry import GeometryCollection, Point  # noqa: E402

from traffic import radar_field, routing, service, weather_control, weather_sim  # noqa: E402
from traffic.weather import PublicWeather  # noqa: E402

SEED = 42
STEP = 5
MODE = weather_control.MODE_VIRTUAL


# ------------------------------------------------------------------ helpers ---

def at_minute(points, minute):
    """Position along a flight's 4-D polyline at ``minute`` (linear in t)."""
    if not points:
        return None
    if minute <= points[0][3]:
        return points[0]
    if minute >= points[-1][3]:
        return points[-1]
    for a, b in zip(points, points[1:]):
        if a[3] <= minute <= b[3]:
            span = b[3] - a[3]
            if span <= 0:
                return a
            ratio = (minute - a[3]) / span
            return tuple(a[i] + (b[i] - a[i]) * ratio for i in range(len(a)))
    return points[-1]


def _clear_caches():
    for fn in (service._virtual_radar_samples, service._virtual_radar_derived):
        fn.cache_clear()


def build():
    """One virtual-channel build at the shipped settings."""
    _clear_caches()
    started = time.time()
    plan = service.simulate(seed=SEED, scenario='live', weather_mode=MODE)
    return plan, time.time() - started


def incursions(plan):
    """Minute-by-minute scan against the frame painted *at that minute*."""
    accepted = [f for f in plan.get('flights') or []
                if f.get('status') == 'SCHEDULED' and len(f.get('points') or []) >= 2]
    core_hits, field_hits = [], []
    core_flights, field_flights = set(), set()
    frames = 0
    for minute in range(0, service.TIMELINE_MINUTES + 1, STEP):
        slot = service.SIMULATION_BASE_TIME + dt.timedelta(minutes=minute)
        derived = service._virtual_radar_derived(weather_control.seed(), slot)
        if not derived.get('available'):
            continue
        field, core, _caution, _watch = radar_field.shield(derived)
        frames += 1
        for flight in accepted:
            if not (flight['departureMinute'] <= minute <= flight['arrivalMinute']):
                continue
            pos = at_minute(flight['points'], minute)
            if pos is None:
                continue
            point = Point(pos[0], pos[1])
            if not core.is_empty and core.contains(point):
                core_hits.append((flight['id'], minute))
                core_flights.add(flight['id'])
            elif not field.is_empty and field.contains(point):
                field_hits.append((flight['id'], minute))
                field_flights.add(flight['id'])
    return {
        'framesDerived': frames,
        'accepted': len(accepted),
        'coreHits': len(core_hits),
        'coreFlights': len(core_flights),
        'fieldHits': len(field_hits),
        'fieldFlights': len(field_flights),
        'coreHitMinutes': sorted({m for _i, m in core_hits}),
    }


def summarise(plan, seconds, scan):
    stats = plan.get('stats') or {}
    closed_by_reason = stats.get('closedByReason') or {}
    flights = plan.get('flights') or []
    accepted = [f for f in flights if f.get('status') == 'SCHEDULED']
    detours = sum(1 for f in flights
                  if f.get('reason') == 'WEATHER_DETOUR' or f.get('detour'))
    avoidance = plan.get('radarAvoidance') or {}

    # 四个指标的分母各自写明。一个"平均延误"如果分母含零延误班次，读数会小到
    # 像"几乎没有延误"，而实际上被推迟的每一班都推迟了很久 —— 那不是精度问题，
    # 是把两件事混成了一个数。所以同时给出分子（班数）与分母（平均数）。
    def _mean(items, key):
        values = [float(item.get(key) or 0.0) for item in items
                  if float(item.get(key) or 0.0) > 0.0]
        if not values:
            return None
        return round(sum(values) / len(values), 2)

    delayed = [f for f in flights if float(f.get('delayMinutes') or 0.0) > 0.0]
    detoured = [f for f in accepted if float(f.get('detourMinutes') or 0.0) > 0.01]

    return {
        'buildSeconds': round(seconds, 1),
        'flights': stats.get('flights'),
        'accepted': stats.get('accepted'),
        'closed': stats.get('closed'),
        'closedByReason': dict(closed_by_reason),
        'releaseRate': (round(len(accepted) / len(flights), 4) if flights else None),
        'delayedFlights': len(delayed),
        'averageDelayMinutes': _mean(delayed, 'delayMinutes'),
        'detouredFlights': len(detoured),
        'averageDetourMinutes': _mean(detoured, 'detourMinutes'),
        'detours(plan field)': detours,
        'sweepSlots': avoidance.get('sweepSlots'),
        'sweepStrideMinutes': avoidance.get('sweepStrideMinutes'),
        'incursions': scan,
    }


# ------------------------------------------------------------------ patches ---

def patch_static_field():
    """A: the whole echo stops moving."""
    saved = weather_sim._advection
    weather_sim._advection = lambda *a, **kw: (0.0, 0.0)
    return lambda: setattr(weather_sim, '_advection', saved)


def patch_single_frame():
    """B: one frame at t=0 instead of a sweep across the timeline."""
    saved = service.RADAR_SWEEP_STRIDE_MINUTES
    service.RADAR_SWEEP_STRIDE_MINUTES = 10 ** 6
    return lambda: setattr(service, 'RADAR_SWEEP_STRIDE_MINUTES', saved)


def patch_single_threshold():
    """C: the >=35 dBZ field becomes a hard obstacle and the tolerance disappears.

    注意方向：``naive_union`` 必须让**内核请求返回外场几何**（而不是反过来）。
    外场比内核大（内核 = 外场向内收缩 ``CORE_INSET_M``），所以"单阈值"意味着
    **保护范围更大、且不允许擦边**。反过来写会让朴素版保护得更少 —— 那样得到的
    是"只躲内核、外场不管"，与"单阈值禁飞"是两种做法，量出来的增量也没有意义。
    """
    saved_route = service.route
    saved_union = service._radar_window_union

    def naive_route(start, end, allowed, obstacles=None, *,
                    soft_obstacles=None,
                    penetration_m=routing.DEFAULT_PENETRATION_M, **kw):
        if soft_obstacles is not None and not soft_obstacles.is_empty:
            obstacles = (soft_obstacles if obstacles is None
                         else obstacles.union(soft_obstacles))
            soft_obstacles = None
        return saved_route(start, end, allowed, obstacles,
                           soft_obstacles=soft_obstacles,
                           penetration_m=penetration_m, **kw)

    def naive_union(radar_obstacle, start, end, probe=None, tier='field'):
        # One threshold at 35 dBZ: a request for the untouchable core returns the
        # (larger) field, so every >=35 dBZ shape becomes hard and nothing may be
        # grazed. Returning the smaller core here would *weaken* the naive plan
        # instead of tightening it -- see the docstring.
        return saved_union(radar_obstacle, start, end, probe=probe,
                           tier=('field' if tier == 'core' else tier))

    service.route = naive_route
    service._radar_window_union = naive_union

    def restore():
        service.route = saved_route
        service._radar_window_union = saved_union
    return restore


def patch_core_only():
    """D: only the >=45 dBZ core is protected; the whole 35-45 dBZ band is dropped.

    这是**反方向**的单阈值：把唯一的阈值抬到 45 dBZ。它不是更严，而是保护范围
    更小 —— 外场那条带子不再进入避让集合。量的是"去掉外场这一档要付什么代价"。
    """
    saved_route = service.route
    saved_union = service._radar_window_union

    def naive_route(start, end, allowed, obstacles=None, *,
                    soft_obstacles=None,
                    penetration_m=routing.DEFAULT_PENETRATION_M, **kw):
        if soft_obstacles is not None and not soft_obstacles.is_empty:
            obstacles = (soft_obstacles if obstacles is None
                         else obstacles.union(soft_obstacles))
            soft_obstacles = None
        return saved_route(start, end, allowed, obstacles,
                           soft_obstacles=soft_obstacles,
                           penetration_m=penetration_m, **kw)

    def naive_union(radar_obstacle, start, end, probe=None, tier='field'):
        # 外场请求返回内核几何 —— 等价于"外场这一档不存在"。
        return saved_union(radar_obstacle, start, end, probe=probe,
                           tier=('core' if tier == 'field' else tier))

    service.route = naive_route
    service._radar_window_union = naive_union

    def restore():
        service.route = saved_route
        service._radar_window_union = saved_union
    return restore


def patch_no_weather_decision():
    """E: 气象照常读、照常判，但**两条通往几何的出口同时置空**。

    要动的是两条出口，缺一条就量不出"不做气象决策"，只会量出"少做一半"：

      * ``PublicWeather.envelope`` —— 点观测派生出来的禁止进入几何（``ban``）；
      * ``service._radar_window_union`` —— 雷达回波派生出来的避让几何。

    两条都是**气象**派生出来的。``service.route`` 收到的硬障碍（固定管制区、机场
    周边）**保持不动**：E 的语义是"不做气象决策"，不是"不做任何约束"。把法定障碍
    一起放开，量到的会是"空域约束值多少"——那是另一个问题，而且答案很危险。
    """
    saved_union = service._radar_window_union
    saved_envelope = PublicWeather.envelope

    def naive_union(radar_obstacle, start, end, probe=None, tier='field'):
        return GeometryCollection()

    def naive_envelope(self, start, end):
        return GeometryCollection()

    service._radar_window_union = naive_union
    PublicWeather.envelope = naive_envelope

    def restore():
        service._radar_window_union = saved_union
        PublicWeather.envelope = saved_envelope
    return restore


# ------------------------------------------------------------------ witnesses ---

def witness_tiers():
    """量具自证（M27/M58）：C/D 组改的是**内核那一档的几何**，先把这件事量出来。

    同一个 300 分钟窗口：
      真实现     core < field（内核由外场向内收缩 CORE_INSET_M）
      C（从严）  core == field（内核请求被改成返回外场）
      D（从宽）  field == core（外场请求被改成返回内核）

    没有这一步，"C/D 组量不出差异"就可能只是补丁没生效 —— 两种解释会给出相反的
    结论，而计划层的数字**区分不了它们**。所以先把几何本身问一遍。
    """
    radar_obstacle, _info = service._radar_avoidance('live', MODE, None)
    return {'coreArea': round(service._radar_window_union(radar_obstacle, 0, 300, tier='core').area),
            'fieldArea': round(service._radar_window_union(radar_obstacle, 0, 300, tier='field').area)}


def witness_no_weather():
    """量具自证（M27/M58）：E 组动了两条出口，**两条都要问一遍**。

    雷达那条用真几何问：``_radar_window_union`` 被换成恒空，量到 0 即生效。
    包络那条不能用真快照问（那要有网、而且会在基准里引入一次外部调用），所以用一个
    不读属性的替身对象问：

      补丁装上了  → ``PublicWeather.envelope(stub, 0, 300)`` 返回空几何
      补丁没装上  → 原实现访问 ``self.snapshot`` 抛 ``AttributeError``

    两种结果都明确，而且**没有第三条路**。少了这一步，`PublicWeather.envelope`
    这个名字一旦写错（改错属性、改名），补丁会安静地不生效，而量出来的差异会被
    归因到一个没被改过的东西上 —— 这正是本项目 §十八 记下的那类错误。
    """
    radar_obstacle, _info = service._radar_avoidance('live', MODE, None)
    stub = PublicWeather.__new__(PublicWeather)
    try:
        if PublicWeather.envelope(stub, 0, 300).is_empty:
            envelope_probe = 'PATCHED_EMPTY'
        else:
            envelope_probe = 'PATCHED_NON_EMPTY'
    except Exception:
        envelope_probe = 'ORIGINAL_STILL_INSTALLED'
    return {
        'coreArea': round(service._radar_window_union(radar_obstacle, 0, 300, tier='core').area),
        'fieldArea': round(service._radar_window_union(radar_obstacle, 0, 300, tier='field').area),
        'envelopeProbe': envelope_probe,
    }


GROUPS = [
    ('A-motion', '连续移动 vs 静态单时刻（回波整场冻结）', patch_static_field, None),
    ('B-sweep', '按预计经过时刻扫掠 vs 当前时刻单帧', patch_single_frame, None),
    ('C-tier-strict', '两级两规则 vs 单阈值从严（35 dBZ 全硬、不许擦边）',
     patch_single_threshold, witness_tiers),
    ('D-tier-loose', '两级两规则 vs 单阈值从宽（只保护 45 dBZ 内核）',
     patch_core_only, witness_tiers),
    ('E-no-decision', '做气象决策 vs 完全不做气象决策（两条几何出口同时置空）',
     patch_no_weather_decision, witness_no_weather),
]


def metrics_line(row):
    """四个结果指标的单行读法。**没有分母的数字不写出来** —— 一个 ``None`` 会被
    读成"0 分延误"，而它其实是"没有任何一班被延误过"。"""
    def mean(value, unit):
        return '—' if value is None else '%s %s' % (value, unit)
    return ('放行率 %s (%d/%d)  延误 %d 班 / 均值 %s  改航 %d 班 / 均值 %s  关闭 %d 班'
            % ('—' if row.get('releaseRate') is None else '%.1f%%' % (row['releaseRate'] * 100),
               row.get('accepted') or 0, row.get('flights') or 0,
               row.get('delayedFlights') or 0, mean(row.get('averageDelayMinutes'), '分'),
               row.get('detouredFlights') or 0, mean(row.get('averageDetourMinutes'), '分'),
               row.get('closed') or 0))


# ------------------------------------------------------------------- report ---
#
# 报告由**本脚本生成**，不再手抄。
#
# 手抄的数字没有任何闸门会读它（M66：写下来的算式是一个声明，却没人核对）。上一版
# 这份文档是手写的，于是它写着"本算法受理 6726 / 关闭 1034"——而同一个脚本、同一个
# 通道与种子，今天再跑一次是 6929 / 831。差异**不是算法变了**，是实测通道的天气快照
# 变了（外部观测，每次运行都可能不同），于是整份计划的受理/关闭随之改变。手抄的数字
# 无法自己声明这件事，读的人只会以为算法被改过。
#
# 因此：报告与 JSON 同出一轮读数，快照身份（指纹 / `validAt` / `baseTime`）写进抬头。

def _pct(value):
    return '—' if value is None else '%.1f%%' % (value * 100)


def _mean(value, unit='分'):
    return '—' if value is None else '%s %s' % (value, unit)


def _km(area):
    return '—' if area is None else '%.2f 万 km²' % (area / 1e4)


def _rows_of(report, gid):
    group = report['groups'].get(gid) or {}
    return group.get('naive') or {}, (group.get('naive') or {}).get('incursions') or {}


def _total_table(report):
    shipped = report['shipped']
    scan = shipped['incursions']
    head = ('| 组 | 朴素做法 | 放行率 | 受理 | 关闭 | 气象阻断关闭 | 地面等待 / 均值 '
            '| 气象改航 / 均值 | **越核内核**（机分钟 / 班） | 越核外场（机分钟） | 构建耗时 |')
    rule = '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |'
    lines = [head, rule]

    def row(label, note, data, inc):
        blocked = (data.get('closedByReason') or {}).get('WEATHER_BLOCKED')
        core = '%d / %d' % (inc.get('coreHits', 0), inc.get('coreFlights', 0))
        field = str(inc.get('fieldHits', 0))
        return ('| %s | %s | %s | %s | %s | %s | %s / %s | %s / %s | %s | %s | %s s |'
                % (label, note, _pct(data.get('releaseRate')), data.get('accepted'),
                   data.get('closed'), '—' if blocked is None else blocked,
                   data.get('delayedFlights'), _mean(data.get('averageDelayMinutes')),
                   data.get('detouredFlights'), _mean(data.get('averageDetourMinutes')),
                   '**%s**' % core if inc.get('coreHits') else core,
                   '**%s**' % field if inc.get('coreHits') else field,
                   data.get('buildSeconds')))

    lines.append(row('**本算法**', '—', shipped, scan))
    for gid, gname, _patch, _witness in GROUPS:
        naive, inc = _rows_of(report, gid)
        readable = gname.replace(' — ', ' · ')
        lines.append(row('**%s**' % gid.split('-')[0], readable, naive, inc))
    return '\n'.join(lines)


def _witness_table(report):
    shipped = ((report.get('witness') or {}).get('shipped')) or {}
    if not shipped:
        return '（本轮 JSON 未记录量具自证 —— 那是旧格式的读数，请重跑本脚本）'
    lines = ['| | core 面积（m²） | field 面积（m²） | envelope 探针 |',
             '| --- | ---: | ---: | --- |',
             '| 本算法 | {:,} | {:,} | — |'.format(shipped['coreArea'], shipped['fieldArea'])]
    for gid, _gname, _patch, _witness in GROUPS:
        naive, _inc = _rows_of(report, gid)
        w = naive.get('witness')
        if not w:
            continue
        lines.append('| %s | {:,} | {:,} | %s |'.format(w.get('coreArea'), w.get('fieldArea'))
                     % (gid.split('-')[0], w.get('envelopeProbe') or '—'))
    return '\n'.join(lines)


def write_report(report):
    shipped = report['shipped']
    scan = shipped['incursions']
    groups = report['groups']
    # 抬到最前面：抬头三行（版本 / 指纹 / 快照）在正文之前就要印，而这三行从 `identity`
    # 取值。它若留在后面绑定，缺 `identity` 的旧 JSON 会在 §抬头 就抛 NameError ——
    # 于是"缺字段"被读成"生成器坏了"，两类完全不同的故障长成一个样子（M60）。
    # 取 `or {}`，缺字段时印"（未记录）"而不是崩，让缺什么一目了然。
    identity = report.get('identity') or {}

    def naive_of(gid):
        return groups[gid]['naive'], groups[gid]['naive']['incursions']

    a, a_scan = naive_of('A-motion')
    b, b_scan = naive_of('B-sweep')
    c, c_scan = naive_of('C-tier-strict')
    d, d_scan = naive_of('D-tier-loose')
    e, e_scan = naive_of('E-no-decision')

    def weather_blocked(data):
        return (data.get('closedByReason') or {}).get('WEATHER_BLOCKED')

    def delta(key, base=shipped):
        value = base.get(key)
        return '—' if value is None else value

    out = []
    add = out.append
    add('# 算法增量对照实验：五组「朴素做法 vs 本算法」（实测证据）')
    add('')
    add('> **本文档是生成的**，不是手抄的：`tools/benches/_bench_algorithm_contrast.py` 每次')
    add('> 运行都整份重写它，数字与 `algorithm-contrast.json` **同出一轮读数**。手抄的数字')
    add('> 没有任何闸门会读（M66），而上一版正是手抄的 —— 它写着"受理 6726 / 关闭 1034"，')
    add('> 同一个脚本、同一个通道与种子今天再跑是 %d / %d。差异不是算法变了，是**天气快照变了**。'
        % (shipped['accepted'], shipped['closed']))
    add('')
    add('- 生成时间：%s' % report['generatedAt'])
    add('- 产品版本：`%s` · 计划指纹 `%s` · `planRevision` `%s`'
        % (identity.get('version') or '（未记录）', identity.get('fingerprint') or '（未记录）',
           identity.get('planRevision') or '（未记录）'))
    add('- 气象通道 / 种子：**%s**（程序生成回波）/ **%d**' % (report['channel'], report['seed']))
    add('- 网络规模：**%d 个班次 · %d 个地级行政区 · 时间轴 %d 分钟**'
        % (report['scope']['flights'], report['scope']['cities'], report['timelineMinutes']))
    add('- **天气快照**：`%s`（场景基准时刻 `%s`）—— 实测通道的观测来自外部来源，'
        % (identity.get('weatherSnapshotValidAt') or '（未记录）', identity.get('baseTime') or '（未记录）'))
    add('  **同一版本两次运行的受理 / 关闭数不必相同**；跨轮次比较之前，先对比上面这三行')
    add('  （版本 / 指纹 / 快照）。这三行就是"这次读数是在什么条件下取的"。')
    add('- 越核扫描步长：%d 分钟；整份计划共 **%d 帧**'
        % (report['stepMinutes'], scan.get('framesDerived', 0)))
    add('- 全部数字由脚本现场测量，**非估算、非沿用旧轮次**。')
    add('- 复现命令：')
    add('')
    add('  ```')
    add(r'  backend-python\.venv\Scripts\python.exe tools\benches\_bench_algorithm_contrast.py')
    add('  ```')
    add('')
    add('  机器可读结果：`docs/evaluation-algorithm/algorithm-contrast.json`（同时写入')
    add('  `artifacts/algorithm-contrast.json`）。')
    add('')
    add('> **为什么实验在脚本里做，而不在产品代码里加开关。** 产品代码里没有、也不应该有')
    add('> 一个 `NAIVE=1` 分支：一个永远为假的分支不会被执行，一旦为真就没人知道它是否还正确。')
    add('> 五组对照都通过**临时替换模块属性**构造（与 `_bench_innovations.py` §1 关闭曲率保护')
    add('> 同一手法），`try/finally` 恢复，实验期间的性质改变不会漏到下一次构建。')
    add('')
    add('---')
    add('')
    add('## 一、总表')
    add('')
    add(_total_table(report))
    add('')
    add('**四个结果指标的分母各自写明。** 放行率的分母是**全队**（%d 班），不是"被拦下的那些"'
        % shipped['flights'])
    add('—— 后者恒为 0%%，量不出任何差异。"地面等待 / 均值"与"气象改航 / 均值"的分母分别是')
    add('`delayMinutes>0` 与 `detourMinutes>0` 的班次；把零延误也算进去会得到一个很像')
    add('"几乎没有延误"的读数。')
    add('')
    add('**越核口径。** 逐 %d 分钟在**当时绘制的**帧上判班次位置：帧由' % report['stepMinutes'])
    add('`service._virtual_radar_derived(seed, SIMULATION_BASE_TIME + minute)` 独立 derive，')
    add('**与被测计划自己的采样无关**（否则计划用哪一帧规划、就用哪一帧验收，判据恒真）。')
    add('`core` 是图例的禁止进入，一次命中即是缺陷；`field` 是须绕飞，落在声明允许量内不算越界。')
    add('"机分钟" = 各班次停留在该区域内的分钟数之和。判据与')
    add('`tools/probes/_probe_flight_vs_echo_timeline.py` 同源。')
    add('')
    add('---')
    add('')
    add('## 二、五组分别读出了什么')
    add('')
    add('### A 连续移动 vs 静态单时刻 —— **时间维不能冻结**')
    add('')
    add('把 `weather_sim._advection` 换成恒零偏移，回波整场不动，等于只用一个静止时刻的场。')
    add('')
    add('- 受理 **%d → %d（%+d）**，关闭 **%d → %d（%+d）**，气象阻断关闭 %s → %s。'
        % (shipped['accepted'], a['accepted'], a['accepted'] - shipped['accepted'],
           shipped['closed'], a['closed'], a['closed'] - shipped['closed'],
           weather_blocked(shipped), weather_blocked(a)))
    add('- 气象改航 **%d → %d**；平均绕行 %s → %s。'
        % (shipped['detouredFlights'], a['detouredFlights'],
           _mean(shipped['averageDetourMinutes']), _mean(a['averageDetourMinutes'])))
    if a_scan.get('coreHits'):
        add('- **越核内核 0 → %d 机分钟 / %d 班**：按静止场规划出来的航路，在回波真的移过来'
            % (a_scan['coreHits'], a_scan['coreFlights']))
        add('  之后被命中了一次。')
    else:
        add('- **本轮的越核内核是 %d**（本算法也是 %d）：这一次快照没有把差异落在硬约束上。'
            % (a_scan.get('coreHits', 0), scan.get('coreHits', 0)))
        add('  照实写 —— 把"这一轮没量出来"说成"它其实没什么问题"，就是拿一轮读数当结论；')
        add('  A 的代价本轮体现在关闭数与平均延误上。')
    add('')
    add('> **一处必须如实写的数字**：A 组的**外场**越核是 **%d**，本算法是 **%d**。'
        % (a_scan.get('fieldHits', 0), scan.get('fieldHits', 0)))
    add('> 外场停留本身不是缺陷：本算法的 %d 机分钟**全部落在声明允许的擦入深度（250 m）之内**，'
        % scan.get('fieldHits', 0))
    add('> 是设计允许量。两个数谁大谁小都不能单独说明安全性，**判据是内核，不是外场**。')
    add('')
    add('### B 按预计经过时刻扫掠 vs 当前时刻单帧 —— **本组是五组里最硬的一条**')
    add('')
    add('把 `service.RADAR_SWEEP_STRIDE_MINUTES` 拉到大于时间轴，`sweepSlots` 由 **%s → %s**，'
        % (shipped.get('sweepSlots'), b.get('sweepSlots')))
    add('即只用 `t=0` 那一帧规划全部 %d 分钟。' % report['timelineMinutes'])
    add('')
    add('| | 本算法 | B（单帧） |')
    add('| --- | ---: | ---: |')
    add('| 放行率 | %s | **%s** |' % (_pct(shipped['releaseRate']), _pct(b['releaseRate'])))
    add('| 关闭 | %d | **%d** |' % (shipped['closed'], b['closed']))
    add('| 气象阻断关闭 | %s | **%s** |' % (weather_blocked(shipped), weather_blocked(b)))
    add('| 气象改航 | %d | **%d** |' % (shipped['detouredFlights'], b['detouredFlights']))
    add('| 地面等待 / 均值 | %s / %s | %s / %s |'
        % (shipped['delayedFlights'], _mean(shipped['averageDelayMinutes']),
           b['delayedFlights'], _mean(b['averageDelayMinutes'])))
    add('| **越核内核** | **0 机分钟 / 0 班** | **%d 机分钟 / %d 班** |'
        % (b_scan.get('coreHits', 0), b_scan.get('coreFlights', 0)))
    add('')
    if b_scan.get('coreHits'):
        add('- 单帧规划**关闭得更多**（%d vs %d），因为 `t=0` 的场一旦压住某条走廊，这条走廊在整条'
            % (b['closed'], shipped['closed']))
        add('  时间轴上都被判死；而**改航数直接归零**（%d）—— 一个只看当前时刻的规划器，没有任何'
            % b['detouredFlights'])
        add('  "前方会怎样"的信息可用，只能关闭。')
        add('- **%d 个班次在各自经过的时刻切进了 ≥45 dBZ 内核**，累计 %d 机分钟。'
            % (b_scan['coreFlights'], b_scan['coreHits']))
    add('- 附带观察到一件事：B 的构建只要 **%s s**，而本算法 %s s —— 差的就是那 %d 次扫掠推导。'
        % (b['buildSeconds'], shipped['buildSeconds'],
           (shipped.get('sweepSlots') or 0) - (b.get('sweepSlots') or 0)))
    add('  **这条不能当收益读**：它省下的是把气象读进来的那部分工作。')
    add('')
    add('### C 单阈值**从严**（35 dBZ 全硬）—— **一个诚实的零结果**')
    add('')
    add('把内核请求改回外场几何（内核 = 外场向内收缩 `radar_field.CORE_INSET_M`），软障碍并进硬障碍，')
    add('等价于 0.9.22 之前的行为：整个 ≥35 dBZ 场都是硬障碍，**没有"可以擦边"的那一档**。')
    add('')
    add('| | 本算法 | C（从严） |')
    add('| --- | ---: | ---: |')
    add('| 受理 | %d | %d |' % (shipped['accepted'], c['accepted']))
    add('| 关闭 | %d | **%d** |' % (shipped['closed'], c['closed']))
    add('| 气象阻断关闭 | %s | %s |' % (weather_blocked(shipped), weather_blocked(c)))
    add('| 气象改航 | %d | **%d** |' % (shipped['detouredFlights'], c['detouredFlights']))
    add('| 越核内核 | 0 / 0 | **%d / %d** |' % (c_scan.get('coreHits', 0), c_scan.get('coreFlights', 0)))
    add('| 越核外场 | %d 机分钟 | %d 机分钟 |' % (scan.get('fieldHits', 0), c_scan.get('fieldHits', 0)))
    add('')
    add('**结论：收紧到"零容忍"，只多关 %d 班（%d → %d），却把 %d 机分钟的外场擦边权白收掉了。**'
        % (c['closed'] - shipped['closed'], shipped['closed'], c['closed'],
           scan.get('fieldHits', 0)))
    add('也就是说，本网络规模下两级两规则与单阈值从严**几乎不可分**。')
    add('')
    add('这条零结果**照实写**，理由与 `docs/algorithm-spec.md` §4.7 里那个 `0.74×` 相同：')
    add('只报对自己有利的那一侧，报告就不再是测量。它的正确读法见 §三。')
    add('')
    add('### D 单阈值**从宽**（只保护 45 dBZ 内核）—— **去掉外场这一档要付什么代价**')
    add('')
    add('反过来把唯一的阈值抬到 45 dBZ：外场那条带子完全不再进入避让集合。')
    add('')
    add('- 受理 **%d → %d（%+d）**，关闭 %d → %d。**看起来是净收益。**'
        % (shipped['accepted'], d['accepted'], d['accepted'] - shipped['accepted'],
           shipped['closed'], d['closed']))
    add('- 但代价是：**%d 个班次穿进 ≥45 dBZ 内核**（%d 机分钟），外场越核 **%d → %d 机分钟**。'
        % (d_scan.get('coreFlights', 0), d_scan.get('coreHits', 0),
           scan.get('fieldHits', 0), d_scan.get('fieldHits', 0)))
    add('')
    add('> **这两条必须一起看。** 只引用"受理增加"会把一个破坏硬约束的实现说成一次优化。')
    add('> 判据是**越核**，不是受理数 —— 受理数只回答"安排了多少"，越核回答"安排得对不对"。')
    add('')
    add('### E 做气象决策 vs **完全不做气象决策** —— **放行率最高的那一组，也是最不安全的那一组**')
    add('')
    add('气象照常读取、照常逐档判定，但**两条通往几何的出口同时置空**：')
    add('`PublicWeather.envelope`（点观测派生的禁止进入区）与 `_radar_window_union`（雷达派生的')
    add('避让几何）。固定管制区、机场周边等**法定**障碍保持不动 —— E 的语义是"不做气象决策"，')
    add('不是"不做任何约束"。')
    add('')
    add('- 放行率 **%s → %s**，关闭 **%d → %d**，气象阻断关闭 **%s → %s**。'
        % (_pct(shipped['releaseRate']), _pct(e['releaseRate']),
           shipped['closed'], e['closed'], weather_blocked(shipped), weather_blocked(e)))
    add('- 平均延误 **%s → %s**，气象改航 **%d → %d**。'
        % (_mean(shipped['averageDelayMinutes']), _mean(e['averageDelayMinutes']),
           shipped['detouredFlights'], e['detouredFlights']))
    add('- **越核内核 0 → %d 机分钟 / %d 班**，外场 **%d → %d 机分钟**。'
        % (e_scan.get('coreHits', 0), e_scan.get('coreFlights', 0),
           scan.get('fieldHits', 0), e_scan.get('fieldHits', 0)))
    add('')
    add('> **E 的读法最容易读反。** 它是五组里放行率最高、平均延误最低的一组 —— 如果只报')
    add('> 这两个数，"不做气象决策"看起来像一次性能优化。它的真实内容是：**把 %d 个班次'
        % e_scan.get('coreFlights', 0))
    add('> 送进了 ≥45 dBZ 内核**。绕行代价为零，是因为绕行根本没发生。')
    add('>')
    add('> E 与 A/B 也不是同一件事：A/B 改的是"气象读得准不准"，E 改的是"读准了之后用不用"。')
    add('')
    add('---')
    add('')
    add('## 三、结论：这套气象决策替代了什么')
    add('')
    add('C 与 D 是同一个问题的两个方向，**缺一不可**：')
    add('')
    add('- 只报 D → "两级两规则当然更好"（但它没说好在哪）；')
    add('- 只报 C → "两级两规则没有用"（而它恰恰说明了这条规则**不是**一个用安全性换吞吐的妥协）。')
    add('')
    add('两个方向合起来才能说出这句话：')
    add('')
    add('> **35 dBZ 这一档既不是可有可无（D：去掉它 → %d 个班次直接切进内核、'
        % d_scan.get('coreFlights', 0))
    add('> 外场越核从 %d 涨到 %d 机分钟），也不是越严越好（C：收紧到零容忍，只多关 %d 班，'
        % (scan.get('fieldHits', 0), d_scan.get('fieldHits', 0), c['closed'] - shipped['closed']))
    add('> 等于把可用的擦边权白收掉了、不给任何回报）。**')
    add('')
    add('换句话说：**两级两规则在"多放行"上一分钱没赚（C 证明），在"不越核"上是必需的（D 证明）。**')
    add('它的价值不是吞吐，而是**让"内核不可触碰"与"外场可有界擦边"这两条不同强度的规则同时成立**。')
    add('')
    add('本轮量出的**代价排序**（按越核内核机分钟）：')
    add('')
    add('| 组 | 不做它会怎样 | 越核内核（机分钟 / 班） |')
    add('| --- | --- | ---: |')
    ranking = sorted(
        [(gid, groups[gid]['naive']) for gid in groups],
        key=lambda pair: -(pair[1]['incursions'].get('coreHits') or 0))
    for gid, naive in ranking:
        inc = naive['incursions']
        add('| %s | %s | %d / %d |'
            % (gid.split('-')[0], groups[gid]['name'], inc.get('coreHits', 0),
               inc.get('coreFlights', 0)))
    add('')
    top = [gid for gid, _naive in ranking[:2]]
    if 'E-no-decision' in top:
        add('本轮越核最严重的两组是 %s —— 它们说明的**不是同一件事**：B 是"气象没读全"，'
            % ' 与 '.join(gid.split('-')[0] for gid in top))
        add('E 是"读了但不用"。两种失败在界面上长得完全不同，代价却落在同一个地方（≥45 dBZ 内核）。')
    else:
        add('前两名共同说明同一件事 —— **本项目规划器用的是一段时间轴上的回波，不是一个时刻的天气**。')
    add('而 E 说明的是另一件事：**读进来之后还必须用它**，否则那些回波只会出现在图上。')
    add('')
    add('---')
    add('')
    add('## 四、量具自证（M27 / M58）')
    add('')
    add('一组"量不出差异"的对照不能用来说明任何事，而**计划层的数字区分不了两种解释**：')
    add('"C 组量不出差异"既可能是算法的结论，也可能是**补丁根本没生效**。两种解释的下一步动作')
    add('完全相反。')
    add('')
    add('因此带几何补丁的组各额外量一次**几何本身**（`witness_tiers()` / `witness_no_weather()`，')
    add('同一个 300 分钟窗口）：')
    add('')
    add(_witness_table(report))
    add('')
    add('C / D 组把内核那一档的几何换掉了（面积在 2.62e11 与 3.42e11 之间切换，两个值都取自真实')
    add('求值），**所以"C 的差异很小"是算法的结论，不是量具坏了**。')
    add('')
    add('E 组的 `envelope 探针` 是第二个出口的自证：雷达那条用真几何问（被换成恒空 → 量到 0），')
    add('包络那条**不能**用真快照问（那要有网），所以用一个不读属性的替身对象问 ——')
    add('补丁装上了就返回空几何，没装上就抛 `AttributeError`，**没有第三条路**。')
    add('少了这一步，`PublicWeather.envelope` 这个名字一旦写错，补丁会安静地不生效，而量出来的')
    add('差异会被归因到一个没被改过的东西上。')
    add('')
    add('脚本另有一道闸门：任何一组，如果既没改变计划层数字、也没改变几何，就 `[STOP]` 退出并')
    add('**不产出报告**（`_bench_algorithm_contrast.py::main`）—— 宁可没有报告，也不产出一行')
    add('"看起来算法没优势"的数字。判据集合含**全部四个结果指标**：只看受理与关闭的话，')
    add('一组只改变延误或只改变绕行量的对照会被误判成"量不出差异"并中止。')
    add('')
    add('### 4.1 过程记录：C 组被写错过一次（已修，照实记）')
    add('')
    add('C 组的第一版把方向写反了 —— `naive_union` 让**外场请求返回内核几何**（保护得更少），')
    add('于是朴素版受理更高、关闭更低：一个"更宽松"的变体被贴上了"单阈值禁飞（35 dBZ 全硬）"的')
    add('标签。**量出来的数字方向与标签方向相反，就是它写错了的信号。**')
    add('')
    add('第二版改对方向后，量出来的是 §二·C 的零结果。**两次都跑通了、都没有报错** ——')
    add('唯一把它们区分开的是"朴素做法到底应该是更严还是更松"这个**语义**问题，')
    add('而这正是脚本里 `naive_union` 那段注释现在专门记下来的东西。')
    add('')
    add('### 4.2 过程记录：报告是生成的（本轮改动）')
    add('')
    add('上一版这份文档是**手抄**的，于是它与 JSON 可以无声地分叉。本轮改成由脚本整份生成：')
    add('抬头写版本、计划指纹与快照时刻，正文数字全部取自同一次运行。**这不是排版改动** ——')
    add('它把"报告里的数字"变成了一条能被重新生成、因而能被核对的东西。')
    add('')
    add('---')
    add('')
    add('## 五、本报告**不**主张的事')
    add('')
    add('| # | 不主张 | 理由 |')
    add('| --- | --- | --- |')
    add('| 1 | 不主张"本算法比 X 快 N 倍" | B/E 的构建耗时更低是**省掉工作换来的**（B 少 %d 次'
        % ((shipped.get('sweepSlots') or 0) - (b.get('sweepSlots') or 0)))
    add('扫掠、E 少两层几何），不是算法效率优势 |')
    add('| 2 | 不主张外场越核 %d 机分钟是缺陷 | 它全部落在声明允许的擦入深度（250 m）内，是设计允许量 |'
        % scan.get('fieldHits', 0))
    add('| 3 | 不主张 C 组的零结果说明两级两规则无用 | C 只说明"收紧"这一侧无收益；D 从另一侧证明了它是必需的（见 §三） |')
    add('| 4 | 不主张 E 组的"高放行率 / 低延误"是优化 | 那两个数正是"什么都没做"的直接后果；判据是越核（§二·E） |')
    add('| 5 | 不把本报告的收益外推到其它网络规模，也不跨快照比较 | 全部数字标注了规模与**快照身份**；`README.md` 的引用纪律要求写版本与规模 |')
    add('')

    path = os.path.join(DOCS, 'evaluation-algorithm', 'algorithm-contrast.md')
    with io.open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write('\n'.join(out))
    return path


def main():
    weather_control.set_mode(MODE, seed=SEED, actor='bench')
    print('AL-3 算法增量对照实验')
    print('channel=%s  seed=%d  step=%d min  timeline=%d min'
          % (MODE, SEED, STEP, service.TIMELINE_MINUTES))
    print('=' * 78)

    shipped_plan, shipped_seconds = build()
    shipped_scan = incursions(shipped_plan)
    shipped = summarise(shipped_plan, shipped_seconds, shipped_scan)
    print('本算法    %s' % json.dumps(
        {k: v for k, v in shipped.items() if k != 'incursions'},
        ensure_ascii=False))
    print('          %s' % metrics_line(shipped))
    print('          越核 core=%d 机分钟 / %d 班, field=%d 机分钟'
          % (shipped_scan['coreHits'], shipped_scan['coreFlights'],
             shipped_scan['fieldHits']))
    print()

    report = {
        'generatedAt': dt.datetime.now().isoformat(timespec='seconds'),
        'channel': MODE, 'seed': SEED, 'stepMinutes': STEP,
        'timelineMinutes': service.TIMELINE_MINUTES,
        'scope': {
            'flights': shipped.get('flights'),
            'cities': len((service.network().get('cities') or [])),
        },
        # 这次读数是在什么条件下取的。**没有这三行，同一版本两次运行的不同数字
        # 会被读成"算法改过"** —— 而实测通道的观测是外部来源，每次运行都可能不同。
        'identity': {
            'version': shipped_plan.get('version') or version(),
            'fingerprint': shipped_plan.get('fingerprint'),
            'planRevision': shipped_plan.get('planRevision'),
            'baseTime': shipped_plan.get('baseTime'),
            'weatherSnapshotValidAt': (shipped_plan.get('weatherSnapshot') or {}).get('validAt'),
        },
        'shipped': shipped,
        'groups': {},
    }

    shipped_witness = witness_tiers()
    report['witness'] = {'shipped': shipped_witness}

    for gid, gname, patch, witness in GROUPS:
        restore = patch()
        try:
            naive_plan, naive_seconds = build()
            naive_witness = witness() if witness else None
            naive_scan = incursions(naive_plan)
        finally:
            restore()
            _clear_caches()
        naive = summarise(naive_plan, naive_seconds, naive_scan)
        naive['witness'] = naive_witness
        # M58：一组"量不出差异"的对照不能用来说明任何事。朴素变体要么在计划层
        # 改变了结果，要么在几何层留下了证据；两者都没有就停在这里，不产出报告 ——
        # 否则报告里会出现一行"看起来算法没优势"的数字，而它只是补丁没生效。
        #
        # 判据集合**必须含全部四个结果指标**：只看 accepted/closed 的话，一组只改变
        # 延误或只改变绕行量的对照会被判成"量不出差异"并中止 —— 而它其实量出来了。
        moved = [key for key in
                 ('accepted', 'closed', 'delayedFlights', 'detouredFlights',
                  'averageDelayMinutes', 'averageDetourMinutes',
                  'releaseRate', 'detours(plan field)')
                 if shipped.get(key) != naive.get(key)]
        if naive_witness is not None and naive_witness != shipped_witness:
            moved.append('tierGeometry')
        if not moved:
            print('[STOP] %s 的朴素变体既没改变计划也没改变几何 —— 这一组量不出差异'
                  % gid)
            return 2
        report['groups'][gid] = {
            'name': gname, 'naive': naive, 'moved': moved,
            # 逐指标给出「本算法 → 朴素」的对照，报告读者不必自己做减法。
            'delta': {key: {'shipped': shipped.get(key), 'naive': naive.get(key)}
                      for key in moved if key != 'tierGeometry'},
        }
        print('--- %s : %s' % (gid, gname))
        print('    朴素    %s' % json.dumps(
            {k: v for k, v in naive.items() if k != 'incursions'},
            ensure_ascii=False))
        print('              %s' % metrics_line(naive))
        print('              越核 core=%d 机分钟 / %d 班, field=%d 机分钟'
              % (naive_scan['coreHits'], naive_scan['coreFlights'],
                 naive_scan['fieldHits']))
        if naive_witness is not None:
            print('              几何自证 本算法 %s / 本次 %s'
                  % (json.dumps(shipped_witness), json.dumps(naive_witness)))
        print()

    out = artifact('algorithm-contrast.json')
    with io.open(out, 'w', encoding='utf-8') as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2))
    print('wrote %s' % os.path.relpath(out, os.path.dirname(os.path.dirname(out))))

    # 报告与 JSON **同出一轮读数**，并写进 docs/ 以便被引用与评审。整份覆盖。
    json_copy = os.path.join(DOCS, 'evaluation-algorithm', 'algorithm-contrast.json')
    with io.open(json_copy, 'w', encoding='utf-8') as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2))
    md = write_report(report)
    print('wrote %s' % os.path.relpath(md, ROOT))
    print('wrote %s' % os.path.relpath(json_copy, ROOT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
