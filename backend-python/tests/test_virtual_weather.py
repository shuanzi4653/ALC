# -*- coding: utf-8 -*-
"""虚拟气象（演示包）的判据 —— 2026-11-12 补。

用户第 8 条原话：「虚拟气象主要针对的是雷达回波和雾，判据当中只有雷达回波数据和雾
产生了变动，气温等数据依旧真实，所以气象实况是不变的，这个逻辑需要强化一下。」

这句话拆成四条可测的约束，正是下面的用例：

1. **回波与雾必须真的变**（不是只换个标签）。上一版虚拟通道的雾完全没动，
   于是"开了虚拟气象和实测差不多" —— 那是最坏的情况：演示开关看起来坏了。
2. **只替换这两样**。`weatherMode.replaced` 必须恰好是 `['radar', 'fog']`，
   气温、风等要素一个都不许改；同一城市两种模式下的 tempC 必须逐值相等。
3. **三档回波要有结构**（WEAK ⊃ CONVECTIVE ⊃ STRONG），片数与实测同量级。
   以前每档各画一个同心椭圆，三档面积差不多，画出来是靶心不是回波。
4. **口径自洽**：页头「低能见度城市」、雾区城数、`traffic.lowVisCities`
   必须是同一个数。只改其中一处，屏幕上就会出现"雾区盖了 104 城、页头写 11 城"。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from traffic import nation  # noqa: E402

MINUTE = 60


def _payload(virtual: bool):
    return nation.payload('nation', minute=MINUTE, virtual=virtual)


def test_virtual_radar_is_a_structured_field_not_three_targets():
    """三档都有片，且总量与实测同量级（≥40 片）。"""
    radar = _payload(True)['radar']
    counts = radar['counts']
    assert radar['virtual'] is True
    for band in ('WEAK', 'CONVECTIVE', 'STRONG'):
        assert counts[band] > 0, f'{band} 一片都没有：虚拟回波退化成空'
    total = sum(counts.values())
    assert total >= 40, f'虚拟回波只有 {total} 片，画出来还是一团而不是回波群'
    # stats 必须与实测同构，否则"口径与来源"页在读虚拟帧时会拿到 None
    assert radar['stats']['totalRings'] == total


def test_virtual_fog_actually_changes():
    """雾必须跟着变 —— 上一版虚拟通道雾区与实测一模一样，于是"差距不大"。"""
    real = _payload(False)['fog']
    virt = _payload(True)['fog']
    assert virt.get('virtual') is True
    assert virt['counts']['cities'] > real['counts']['cities'] * 3, (
        f"虚拟雾覆盖 {virt['counts']['cities']} 城、实测 {real['counts']['cities']} 城："
        '差距太小，演示开关等于没开'
    )
    assert sum(len(v) for v in virt['bands'].values()) > sum(len(v) for v in real['bands'].values())


def test_low_visibility_count_is_the_same_number_everywhere():
    """页头、雾区、traffic 三处必须是同一个数（自洽性）。"""
    for virtual in (False, True):
        body = _payload(virtual)
        fog_cities = body['fog']['counts']['cities']
        assert body['summary']['lowVisCities'] == fog_cities, (
            f"virtual={virtual}：摘要写 {body['summary']['lowVisCities']} 城、"
            f'雾区是 {fog_cities} 城'
        )
        assert body['traffic']['lowVisCities'] == fog_cities, (
            f"virtual={virtual}：traffic 写 {body['traffic']['lowVisCities']} 城、"
            f'雾区是 {fog_cities} 城'
        )
        # 地图红圈（node.weather.low）也要跟着同一个数，否则图上没有一处红圈
        hot = sum(1 for node in body['nodes']
                  if (node.get('weather') or {}).get('low'))
        assert hot == fog_cities, f'virtual={virtual}：红圈节点 {hot} 个、雾区 {fog_cities} 城'


def test_virtual_only_replaces_radar_and_fog():
    """声明的替换面必须恰好是回波 + 雾；气温与风必须逐值不变。"""
    body_v = _payload(True)
    mode = body_v['weatherMode']
    assert mode['virtual'] is True
    assert mode['replaced'] == ['radar', 'fog'], f"替换面写成 {mode['replaced']}"
    for key in ('tempC', 'windMps'):
        assert key in mode['untouched'], f'{key} 不在"未改动"清单里'

    real = {row['city']: row for row in _payload(False)['intel']}
    virt = {row['city']: row for row in body_v['intel']}
    shared = [name for name in real if name in virt]
    assert shared, '两种模式的机场城市对不上，无法比较'
    for name in shared:
        assert virt[name].get('tempC') == real[name].get('tempC'), f'{name} 的气温被改了'
        assert virt[name].get('windMps') == real[name].get('windMps'), f'{name} 的风速被改了'


def test_virtual_visibility_is_marked_so_it_is_not_read_as_observed():
    """虚拟雾里那些城市的能见度必须带标记，否则会被当成实况抄进材料。"""
    body = _payload(True)
    marked = [row for row in body['intel'] if row.get('virtualVis')]
    assert marked, '虚拟模式下没有任何一行被标记为虚拟能见度'
    for row in marked:
        assert row['visM'] is not None
