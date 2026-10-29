"""用**加高视口**再拍一遍截图，让"折线以下"的内容也进画面（0.9.26（Beta） 第十轮）。

为什么需要它
------------
`_shot_screens.py` 用的是 2150×1250 —— 那是"大屏舞台真实的样子"，对首页与总览是对的。
但民航情报页在「改航依据 · 逐班复诵」**下面**还有两块（时间轴情报、空域与资源情报），
1250 px 高根本看不到它们。**"这一页有这两块"与"这两块真的渲染出来了"是两件事**，
而后者只有看图才知道（M24：present ≠ visible）。

第十轮正是靠这一步抓到两个真缺陷：`radarRuleBlock()` 读了一个不存在的键、
`staticAirspace` 读错了载荷 —— 两者都让页面**堂堂正正地写着"未取得"**，
而所有自动化判据全绿。

为什么不新写一套
----------------
直接**复用** `_shot_screens`：Edge 查找、静态服务 + `/api` 转发、逐分节就绪判据
（落在控制台自报的 `data-view` 上）、后端世代判定、md5 互异判据全部照旧，
这里只改两样东西 —— **视口高度**与**产物目录**。

抄一份就是两次实现：两份实现会分叉，而分叉之后"两张图不一样"既可能说明页面变了、
也可能说明量具变了（M27：量具先自证）。所以这里 import 而不是 copy。

产物落在 `artifacts/shots-tall/`（**不覆盖** `artifacts/` 里那套标准视口的图 —— 两套口径
各有用途：1250 是"用户实际看到的一屏"，3000 是"整页到底有什么"）。
`artifacts/` 在打包排除清单里，所以这不会进交付包。

跑法（**必须先有后端**，前置条件与 `_shot_screens.py` 完全相同）：

  python tools/harness/_start_services.py &          # 后台起三个服务
  backend-python/.venv/Scripts/python.exe tools/probes/_shot_screens_tall.py

退出码沿用三分（M60）：**0** 拍到 · **1** 拍出来是坏的 · **2** 无法测量。
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _shot_screens as shots  # noqa: E402

# 3000 px：够放下情报页「改航依据」以下的两块。**宽度不动** —— 舞台比例是按容器算的
# （ADR-45），改宽度会换出一组不同的尺寸，那时两张图就没法并排看了。
TALL_VIEWPORT = (2150, 3000)
OUT = shots.probe.ROOT / 'artifacts' / 'shots-tall'


def main():
    shots.VIEWPORT = TALL_VIEWPORT
    OUT.mkdir(parents=True, exist_ok=True)
    # 上一轮的图先清掉：**留着旧的会让"这次没拍到"看起来像"这次拍到了"**
    # （旧文件还在、md5 还是那一个，只有时间戳不同）。
    for old in OUT.glob('*.png'):
        os.remove(old)
    shots.SHOTS = OUT
    print('tall viewport: %dx%d  -> %s' % (TALL_VIEWPORT[0], TALL_VIEWPORT[1], OUT))
    return shots.main()


if __name__ == '__main__':
    raise SystemExit(main())
