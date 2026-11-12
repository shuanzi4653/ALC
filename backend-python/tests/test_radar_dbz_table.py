# -*- coding: utf-8 -*-
"""雷达反算与色阶的护栏。

这三条守的是本次修复里最容易复发的东西：
  1. 阈值只有一份（`weather/dbz.py`），且与 `cma_tiles` 是**同一个对象**；
  2. 色阶断点必须包含 15 / 35 / 45（判据落在色块边界上，而不是色块中间）；
  3. 反查必须是官方色表的逐色精确映射，且不许把删掉的拟合函数复活。
"""
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic import cma_tiles  # noqa: E402
from weather import dbz, radar_public  # noqa: E402


def test_thresholds_come_from_one_reading():
    """`cma_tiles` 的常量必须是 `weather/dbz.py` 里那几个对象的**再导出**。

    用 `is` 而不是 `==`：`==` 抓不到"又抄了一遍同样的数字"这种写法 ——
    而本次的问题正是抄了一遍（32/41）。这条一变红，说明有人重新打了数字。
    """
    assert cma_tiles.CONVECTIVE_DBZ is dbz.CONVECTIVE_DBZ
    assert cma_tiles.ECHO_FLOOR_DBZ is dbz.ECHO_FLOOR_DBZ
    assert cma_tiles.STRONG_DBZ is dbz.STRONG_DBZ
    assert cma_tiles.SEVERE_DBZ is dbz.SEVERE_DBZ
    assert (dbz.ECHO_FLOOR_DBZ, dbz.CONVECTIVE_DBZ, dbz.STRONG_DBZ) == (15.0, 35.0, 45.0)


def test_radar_public_reads_the_band_floors():
    """`radar_public` 不许再出现自己的门限：cells 三档一律用 `dbz.BAND_FLOOR`。"""
    assert radar_public.BAND_EDGES is dbz.BAND_EDGES
    source = io.open(radar_public.__file__, encoding='utf-8').read()
    # 只扫"比较式"，不扫裸数字：色表里本来就有 32.0 / 41.0 这些 dBZ 取值，
    # 按子串判会误伤（这也是原来那个 `'32.' not in src` 写法不可用的原因）。
    for literal in (r'>=\s*32\.0', r'>=\s*41\.0'):
        assert not re.search(literal, source), f'radar_public 里还有硬编码门限 {literal}'


def test_fitted_helpers_stay_deleted():
    """手调拟合那三个函数已删，且没有调用点复活。

    `_band_of` 是死代码但更危险：它有 docstring、有类型注解，谁把它接回去，
    32/41 就会以"新写的代码"身份复活，而且看起来是正经函数。
    """
    for name in ('_pixel_dbz', '_band_of', '_tile_range'):
        assert not hasattr(radar_public, name), f'{name} 又回来了'


def test_scale_breaks_contain_the_decision_thresholds():
    """色阶断点必须包含 15 / 35 / 45 —— 否则"这条边就是阈值"画不出来。"""
    breaks = [float(t) for t, _rgba in radar_public.NEXRAD_LUT]
    for value in (dbz.ECHO_FLOOR_DBZ, dbz.CONVECTIVE_DBZ, dbz.STRONG_DBZ):
        assert value in breaks, f'色阶断点缺 {value}'


def test_scale_lists_only_reachable_bands():
    """图例 12 条：条数由可达档位推出，10 与 65 两档不可达，不该出现。"""
    scale = radar_public.nexrad_scale()
    assert [row['dbz'] for row in scale] == [15.0, 20.0, 25.0, 30.0, 35.0, 38.0,
                                             42.0, 45.0, 50.0, 55.0, 60.0, 70.0]
    assert scale[-1]['until'] is None
    assert scale[-2]['until'] == 70.0
    # 每条区间里至少有一个可达代表值，否则就是"图上永不出现的一格"
    for index, row in enumerate(scale):
        ceiling = row['until'] if row['until'] is not None else float('inf')
        assert any(row['dbz'] <= v < ceiling for v in radar_public.REACHABLE_DBZ)
    # 10 / 65 结构性不可达
    values = [row['dbz'] for row in scale]
    assert 10.0 not in values and 65.0 not in values


def test_reverse_lookup_is_exact_for_every_official_colour():
    """官方色表 51 个颜色逐色回读，必须原值返回（±0.01）。"""
    import numpy as np
    from PIL import Image

    colours = list(radar_public.COLOUR_TO_DBZ)
    pixels = np.zeros((len(colours), 1, 4), dtype=np.uint8)
    for index, (r, g, b) in enumerate(colours):
        pixels[index, 0] = [r, g, b, 255]
    out = radar_public._tile_dbz_array(Image.fromarray(pixels, 'RGBA'))
    for index, colour in enumerate(colours):
        expected = radar_public.COLOUR_TO_DBZ[colour]
        assert abs(float(out[index, 0]) - expected) < 0.01, f'{colour} -> {out[index, 0]}'


def test_reverse_lookup_rejects_non_echo_colours():
    """云边米色晕 / 溢出纯绿 / 低 alpha 一律不算回波。

    拟合版把米色晕判成 STRONG（真实帧里 99.4% 的"强回波"就是它），
    这里用官方表证明它们都低于 15 dBZ 或根本不在回波色表里。
    """
    import numpy as np
    from PIL import Image

    samples = [(206, 192, 135, 150),   # 云边米色晕（真实 10 dBZ）
               (222, 208, 151, 190),   # 云边米色晕（真实 14 dBZ）
               (0, 255, 0, 255),       # 75 dBZ 以上的溢出标记色
               (136, 221, 238, 10)]    # 正常回波色但 alpha 低于底噪
    arr = np.array([[list(s) for s in samples]], dtype=np.uint8)
    out = radar_public._tile_dbz_array(Image.fromarray(arr, 'RGBA'))
    assert out.ravel().tolist() == [0.0, 0.0, 0.0, 0.0]


def test_image_encoder_does_not_upscale_by_default():
    """默认不放大：升采样是纯插值零信息，原来白付 49% 字节还被 4096 截断成 1.498。"""
    import numpy as np

    field = np.zeros((40, 60), dtype=np.float32)
    field[5:20, 5:30] = 30.0
    uri, size = radar_public._encode_nexrad_png(field)
    assert uri.startswith('data:image/png;base64,')
    assert size == [60, 40]


def test_image_encoder_skips_below_floor():
    import numpy as np

    assert radar_public._encode_nexrad_png(np.zeros((10, 10), dtype=np.float32)) == (None, None)


def test_png_palette_is_index_aligned():
    """调色板：索引 0 透明作背景，14 个档位占 1–14，768 字节不溢出。"""
    import base64
    import struct

    import numpy as np
    from PIL import Image

    field = np.zeros((8, 8), dtype=np.float32)
    field[2:6, 2:6] = 60.0
    uri, _size = radar_public._encode_nexrad_png(field)
    raw = base64.b64decode(uri.split(',', 1)[1])
    assert b'PLTE' in raw and b'tRNS' in raw
    image = Image.open(io.BytesIO(raw))
    palette = image.getpalette()
    assert len(palette) == 768
    assert palette[0:3] == [0, 0, 0]
    # 索引 1 对应 NEXRAD_LUT 第一档（10 dBZ 浅青）
    assert tuple(palette[3:6]) == radar_public.NEXRAD_LUT[0][1][:3]
    assert struct.calcsize('B') == 1

def test_fetch_deadline_uses_one_clock():
    """止损判据必须与它比较的时钟同源。

    这里守的是一次真实事故：`started = time.time()`（epoch）却拿 `time.monotonic()`
    去比，两者差三个数量级，判据恒为 False —— 45 s 全局止损等于没写。
    """
    source = io.open(radar_public.__file__, encoding='utf-8').read()
    assert 'started_mono = time.monotonic()' in source
    assert 'deadline = started_mono + FETCH_DEADLINE_SECONDS' in source
    assert 'deadline = started + FETCH_DEADLINE_SECONDS' not in source


def test_mask_cache_keeps_only_success():
    """掩膜缓存只存成功结果：缓存住 None 等于"一次读不到，整进程都不裁国界"。"""
    bounds = radar_public._tile_bounds(radar_public.TILE_ZOOM, radar_public.BBOX)
    radar_public._MASK_CACHE.clear()
    first = radar_public._china_raster_mask(radar_public.TILE_ZOOM, *bounds)
    second = radar_public._china_raster_mask(radar_public.TILE_ZOOM, *bounds)
    assert first is not None
    assert second is first, '第二次应命中缓存（同一对象），否则每帧白算 8.5 M 像素'


def test_reverse_lookup_report_is_shipped():
    """反查失配统计必须随载荷下发：它是色表漂移的唯一观测点。"""
    report = radar_public._reverse_lookup_report()
    for key in ('hitPixels', 'missPixels', 'resolvedFromNearest', 'missRatio', 'degraded'):
        assert key in report
    assert report['degraded'] is False


def test_mask_status_reports_both_clipping_paths():
    """国界裁剪两条链都要能被看见（矢量环 / 贴图栅格）。"""
    from traffic import nation

    status = nation.mask_status()
    assert status['vectorClipped'] is True
    assert status['maskError'] is None
