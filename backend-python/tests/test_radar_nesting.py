# -*- coding: utf-8 -*-
"""回波分级必须**嵌套**（V1.0.4）。

现场问题：三档回波画出来像"等高线地图"——红、黄、绿三片并排相邻，谁也不包谁。
根因不在配色，在几何：旧实现"每格只归一个档"，三档天生互斥；
真实雷达的每一格是反射率数值，按阈值取档才会层层相套（红核一定在黄里）。

这条用例盯的是 ``bands_from_cells``：同样是那几个栅格，只要把 STRONG 的格子
换成一个环、中间放 CONVECTIVE，就应该得到"红在黄里、黄在绿里"的面积关系。
任何把它改回互斥分档的实现都会在这里掉。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from weather import radar_public  # noqa: E402

G = radar_public.GRID_DEG


def _area(ring):
    s = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def _sum_area(rings):
    return sum(_area(r) for r in rings)


def _bbox(rings):
    xs, ys = [], []
    for ring in rings:
        for lon, lat in ring:
            xs.append(lon)
            ys.append(lat)
    return min(xs), min(ys), max(xs), max(ys)


def _cell(i, j, sub=0.0):
    """第 (i,j) 格的中心坐标；sub 用来把同一格挪开一点，避免闭运算把它们并成一片。"""
    return (i * G + sub, j * G + sub)


def test_three_bands_nest_by_area():
    """强回波一定落在中强里，中强一定落在弱回波里。"""
    weak, mid, strong = [], [], []
    # 一片 7×7 的弱回波
    for i in range(0, 7):
        for j in range(0, 7):
            weak.append(_cell(i, j))
    # 中间 5×5 是中强
    for i in range(1, 6):
        for j in range(1, 6):
            mid.append(_cell(i, j))
    # 正中心 3×3 是强回波
    for i in range(2, 5):
        for j in range(2, 5):
            strong.append(_cell(i, j))

    bands, cells = radar_public.bands_from_cells(
        {'WEAK': weak, 'CONVECTIVE': mid, 'STRONG': strong})

    assert cells == 49, '有效栅格数必须去重，不能把三档相加'
    a_weak = _sum_area(bands['WEAK'])
    a_mid = _sum_area(bands['CONVECTIVE'])
    a_strong = _sum_area(bands['STRONG'])
    assert a_weak > a_mid > a_strong > 0, (
        f'三档没有嵌套：弱 {a_weak:.3f} / 中 {a_mid:.3f} / 强 {a_strong:.3f}')

    # 强回波的外接框必须在中强里，中强必须在弱里 —— 面积对了但位置偏了也是错的
    wx0, wy0, wx1, wy1 = _bbox(bands['WEAK'])
    mx0, my0, mx1, my1 = _bbox(bands['CONVECTIVE'])
    sx0, sy0, sx1, sy1 = _bbox(bands['STRONG'])
    assert wx0 <= mx0 and wy0 <= my0 and mx1 <= wx1 and my1 <= wy1, '中强跑出了弱回波范围'
    assert mx0 <= sx0 and my0 <= sy0 and sx1 <= mx1 and sy1 <= my1, '强回波跑出了中强范围'


def test_a_lone_weak_cell_only_shows_up_in_the_weakest_band():
    """孤立小雨团：只该出现在弱回波里。以前"每格归一个档"，它会单独成一片红或黄。

    三个格子是下限：`_rings_of` 有 0.004 平方度（≈6×6 km）的面积地板，
    两格只有 0.0032，会被当成碎点丢掉 —— 这是既有的"最小 3 格"口径。
    """
    bands, _cells = radar_public.bands_from_cells(
        {'WEAK': [_cell(0, 0), _cell(1, 0), _cell(1, 1)], 'CONVECTIVE': [], 'STRONG': []})
    assert bands['WEAK'], '三格的弱回波应该成环'
    assert not bands['CONVECTIVE'] and not bands['STRONG'], '弱回波不许跑到中强/强档'


def test_band_rank_is_the_single_source_of_thresholds():
    """三档阈值只能有一处定义；前端按 WEAK→CONVECTIVE→STRONG 叠色依赖这个顺序。"""
    assert list(radar_public.BAND_RANK) == ['WEAK', 'CONVECTIVE', 'STRONG']
    assert radar_public.BAND_RANK['WEAK'] < radar_public.BAND_RANK['CONVECTIVE']
    assert radar_public.BAND_RANK['CONVECTIVE'] < radar_public.BAND_RANK['STRONG']
