"""实测雷达源（CMA 公开瓦片）可达性探针 —— 只读，不写任何产物。

回答一个问题：**「雷达回波不可用」是数据真的没了，还是我们自己的代码读错了。**

三种出口（与项目既有约定一致）：
  0  源可用，且能解出时次 —— 打印时次、滞后分钟、回波占比
  1  源可用，但 12 个回退时次全部 404（可能是接口换代/路径变更）
  2  根本无法测量（网络不可达 / 依赖缺失）—— **这不是「源坏了」**

刻意不走 `traffic.service.radar_regions()`：那是被测对象。这里直接问
`cma_tiles.frame()` 与原始 HTTP，判据独立于被测对象。
"""
import datetime as dt
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend-python'))

from traffic import cma_tiles  # noqa: E402

RC_OK = 0
RC_SOURCE_DOWN = 1
RC_CANNOT_MEASURE = 2


def _try_raw(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'ALC-radar-probe/1.0'})
    try:
        with cma_tiles._OPENER.open(request, timeout=20) as response:
            body = response.read()
            return f'HTTP {response.status}, {len(body)} B'
    except urllib.error.HTTPError as exc:
        return f'HTTP {exc.code}'
    except Exception as exc:  # noqa: BLE001
        return f'{type(exc).__name__}: {exc}'


def main():
    now = dt.datetime.now(dt.timezone.utc)
    nominal = cma_tiles.latest_slot(now)
    print(f'now(UTC)      = {now.isoformat()}')
    print(f'nominal slot  = {nominal.isoformat()}')
    print(f'tile base     = {cma_tiles.TILE_BASE}')
    print(f'grid          = {cma_tiles.DEFAULT_GRID}')
    print('')

    # 1) 裸 HTTP —— 对「最新时次」与「最早回退时次」各打一次，看清是 404 还是网络层
    for label, slot in (
        ('newest nominal', nominal),
        ('oldest lookback', nominal - dt.timedelta(
            minutes=cma_tiles.CADENCE_MINUTES * (cma_tiles.MAX_LOOKBACK_STEPS - 1))),
    ):
        url = cma_tiles.tile_url(slot, 3, 6, 3)
        print(f'raw GET [{label}] {url}')
        print(f'          -> {_try_raw(url)}')
    print('')

    # 2) 走模块自身路径（含回退与缓存语义），但 force 掉缓存
    try:
        result = cma_tiles.frame(force=True)
    except Exception as exc:  # noqa: BLE001
        print(f'frame() raised {type(exc).__name__}: {exc}')
        print('RESULT: 2 无法测量（模块自身抛错，先查环境）')
        return RC_CANNOT_MEASURE

    print(f'frame.available = {result.get("available")}')
    print(f'frame.error     = {result.get("error")}')
    print(f'frame.slot      = {result.get("slot")}')
    print(f'slotAgeMinutes  = {result.get("slotAgeMinutes")}')
    print(f'lookbackUsed    = {result.get("lookbackStepsUsed")}')
    stats = result.get('stats') or {}
    if stats:
        print(f'stats           = {stats}')
    print('')

    if result.get('available'):
        print('RESULT: 0 源可用 —— 「不可用」不是数据源的问题，去查下游读法')
        return RC_OK

    error = str(result.get('error') or '')
    if 'HTTP' in error or '不可用' in error:
        print('RESULT: 1 源本身在拒绝（12 个时次全失败）—— 接口可能已换代')
        return RC_SOURCE_DOWN
    print('RESULT: 2 无法测量 —— 网络层失败，不能据此说源坏了')
    return RC_CANNOT_MEASURE


if __name__ == '__main__':
    sys.exit(main())
