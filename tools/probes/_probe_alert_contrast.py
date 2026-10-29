"""预警中心卡片配色对比度核验。

用户 2026-10-01 报告：「预警中心看不清楚那些黑色的字」。根因是
`.operational-alert` 强制了深色背景（#152b3c!important）但没有给出 `color`，
卡片的 <p> 于是继承了浏览器默认的黑色正文。

这个探针不"看"渲染结果，它算 WCAG 对比度：任意一对前景/背景如果
比值 < 4.5，就是不可读的。它同时充当**负向对照** —— 把修复前的配色喂进去，
必须判 FAIL；否则这个探针就没有牙齿（M29）。

跑法：
  python tools/probes/_probe_alert_contrast.py
"""
import sys

BG_CARD = (0x15, 0x2B, 0x3C)      # .operational-alert 背景
BG_LEGEND_DELAY = (0x24, 0x1F, 0x10)
BG_LEGEND_DETOUR = (0x10, 0x25, 0x30)
BG_LEGEND_CLOSED = (0x3A, 0x27, 0x12)

# 修复后的实际取值（与 OperationsConsole.vue 的 scoped 样式逐字对应）。
# 注意：0.9.27 把「停止放行」的砖红/玫红统一进了暖橙重色族 —— 前景 #f6aab7
# 已成历史，现值是 #ffd9a8；图例 .tag.closed 的底也从 #28141a 挪到 #3a2712。
# 这份表**必须**与组件同步，否则探针会拿一套早已不存在的配色自证达标
# （「参照物过期」型假通过）。
CURRENT = {
    'card 正文 <p>':        ((0xA9, 0xC6, 0xD8), BG_CARD),
    'card 标题 <h3>':       ((0xE2, 0xF1, 0xFA), BG_CARD),
    'card 落款 <small>':    ((0x7F, 0xA3, 0xB8), BG_CARD),
    'card 标签 时隙重排':   ((0xF1, 0xC7, 0x7F), (0x3D, 0x33, 0x20)),
    'card 标签 停止放行':   ((0xFF, 0xD9, 0xA8), (0x4A, 0x2A, 0x12)),
    '图例 时隙重排':        ((0xF1, 0xC7, 0x7F), BG_LEGEND_DELAY),
    '图例 改航绕飞':        ((0x8F, 0xD8, 0xEA), BG_LEGEND_DETOUR),
    '图例 停止放行':        ((0xFF, 0xD9, 0xA8), BG_LEGEND_CLOSED),
}

# 修复前的配色：<p> 无 color 规则 = 继承浏览器默认黑 (#000000)
LEGACY = {
    'card 正文 <p>（继承默认黑）': ((0x00, 0x00, 0x00), BG_CARD),
}

# 深色正文里"看着像浅色其实不够"的中间值，用来证明 4.5:1 阈值真的在起作用
# （0.9.27 起 style.css 里那个 .alert-item 浅色样本已随旧仪表盘删除，
#  这里改为纯构造的临界值，不再依赖任何现存的旧样式）
EDGE = {
    '临界样本 #6d899d（应判 FAIL）': ((0x6D, 0x89, 0x9D), BG_CARD),
}

AA_NORMAL = 4.5


def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = (_lin(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg, bg):
    l1, l2 = luminance(fg), luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def report(title, samples):
    print(f'\n== {title} ==')
    worst = 99.0
    for name, (fg, bg) in samples.items():
        ratio = contrast(fg, bg)
        worst = min(worst, ratio)
        print(f'  {name:<28} {ratio:5.2f}:1  {"PASS" if ratio >= AA_NORMAL else "FAIL"}')
    return worst


def main():
    print('WCAG AA 正文阈值 = 4.5:1')
    worst_current = report('修复后（应对全部 PASS）', CURRENT)
    worst_legacy = report('修复前（应有 FAIL —— 负向对照）', LEGACY)
    worst_edge = report('临界样本（应判 FAIL —— 阈值有效性对照）', EDGE)

    ok = True
    if worst_current < AA_NORMAL:
        print(f'\n[FAIL] 修复后仍有配色不达 {AA_NORMAL}:1（最低 {worst_current:.2f}）')
        ok = False
    else:
        print(f'\n[PASS] 修复后全部达标，最低 {worst_current:.2f}:1')

    if worst_legacy >= AA_NORMAL:
        print('[FAIL] 负向对照没有牙齿：修复前的黑色正文竟然被判达标')
        ok = False
    else:
        print(f'[PASS] 负向对照有效：修复前正文仅 {worst_legacy:.2f}:1，确为不可读')

    if worst_edge >= AA_NORMAL:
        print('[FAIL] 阈值对照失败：临界样本被误判达标')
        ok = False
    else:
        print(f'[PASS] 阈值对照有效：临界样本 {worst_edge:.2f}:1 被判 FAIL')

    print('\nALERT CONTRAST ' + ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
