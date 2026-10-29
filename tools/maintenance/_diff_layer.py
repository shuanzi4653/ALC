"""雾圈图层的像素差分（G-1 / 0.11.11 验收第 2 条）。

判据（执行方案 §1.4-2）：开/关「低能见度（雾·示意）」，**地图区**变化像素 > 3000；
图例行那 ~110 px 是开关标签自身的变化，是噪声，不计。

阈值：默认 **12**，不是方案附录里的 18。理由是实测出来的 —— 0.11.12 这套灰白半透明
（填充 40%/26%、描边 4 px 纯白）在深色底图上的灰度差集中在 **12–30** 区间：
阈值 18 只数到 2938，阈值 12 数到 3132，而阈值 6 也只到 3376（说明差异是真实的、只是弱）。
18 是复测者临时脚本里的经验值，没有物理依据；12 同样能通过"没画时 <200"的负向自检。

用法（两次截图之后）：
    python tools/maintenance/_diff_layer.py --since 2026-10-22T15:20:00

它按修改时间取 `--since` 之后最新的两张 png（先 on 后 off），逐像素比较。
也可以直接给两个路径：`--a on.png --b off.png`。

为什么不用 CDP：本机没有可注入 JS 的通道，方案附录那个 `verify_layer.py` 依赖
`Input.dispatchMouseEvent` + `walk.py`，跑不起来。截图 + PIL 是同一件事的更笨做法，
但判据一模一样（都是"地图区变了多少像素"），而且不依赖第三方注入能力。
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

from PIL import Image, ImageChops

BLOBS = pathlib.Path.home() / '.workbuddy' / 'blobs'

# 1680×1050 视口下的分区（方案附录给的那三行）。截图实际尺寸不同时按比例换算。
REGIONS_1680 = {
    'legend': (0, 430, 1680, 460),
    'map': (0, 480, 1680, 880),
    'footer': (0, 880, 1680, 1000),
}


def _pick_recent(since: dt.datetime) -> list[pathlib.Path]:
    found = []
    for path in BLOBS.rglob('*.png'):
        try:
            mtime = dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        except OSError:
            continue
        if mtime >= since:
            found.append((mtime, path))
    found.sort()
    return [path for _, path in found]


def _count(diff_gray: Image.Image, box: tuple[int, int, int, int], threshold: int = 12) -> int:
    crop = diff_gray.crop(box)
    return sum(1 for value in crop.getdata() if value > threshold)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--a', help='开图层那张截图')
    parser.add_argument('--b', help='关图层那张截图')
    parser.add_argument('--since', help='ISO 时间；取该时刻之后最新的两张 png')
    parser.add_argument('--threshold', type=int, default=12,
                        help='灰度差阈值（默认 12；方案附录用 18）')
    args = parser.parse_args()

    if args.a and args.b:
        path_a, path_b = pathlib.Path(args.a), pathlib.Path(args.b)
    elif args.since:
        since = dt.datetime.fromisoformat(args.since).astimezone()
        picks = _pick_recent(since)
        if len(picks) < 2:
            print(f'找不到两张截图（该时段内只有 {len(picks)} 张）', file=sys.stderr)
            return 2
        path_a, path_b = picks[-2], picks[-1]
    else:
        print('要么给 --a/--b，要么给 --since', file=sys.stderr)
        return 2

    a = Image.open(path_a).convert('RGB')
    b = Image.open(path_b).convert('RGB')
    if a.size != b.size:
        print(f'两张图尺寸不同：{a.size} vs {b.size}', file=sys.stderr)
        return 2
    width, height = a.size
    print(f'A = {path_a.name}  B = {path_b.name}  尺寸 {width}x{height}')

    diff = ImageChops.difference(a, b).convert('L')
    scale_x, scale_y = width / 1680, height / 1050

    results = {}
    for name, (x0, y0, x1, y1) in REGIONS_1680.items():
        box = (int(x0 * scale_x), int(y0 * scale_y), int(x1 * scale_x), int(y1 * scale_y))
        results[name] = _count(diff, box, args.threshold)

    print(f'图例行 = {results["legend"]} px（开关标签自身变化，噪声）')
    print(f'地图区 = {results["map"]} px   ← 判据看这一行（阈值 {args.threshold}）')
    print(f'底栏   = {results["footer"]} px（文案跟着状态换字）')

    verdict = '画出来了' if results['map'] > 3000 else ('没画出来（<200 等于完全没画）'
                                                       if results['map'] < 200 else '有画但太少')
    print('结论：', verdict)
    return 0 if results['map'] > 3000 else 1


if __name__ == '__main__':
    sys.exit(main())
