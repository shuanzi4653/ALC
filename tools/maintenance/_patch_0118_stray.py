"""0.11.8 修复：`</script>` 之后的三块雾区函数搬回模块内 + weather 的 case 参数改用唯一来源。

两个 bug 都是**同一类**：写的时候以为"插进去了"，而没有任何东西核对插入位置。
- `_patch_b_frontend_fog.py` 把 `FOG_RING_KM / fogRing / fogFeatureCollection /
  paintFogCircles` 追加到了 `</script>` **之后** —— 它们不在模块里，于是
  `rebuild()` 里的 `paintFogCircles()` 每次重画都抛 ReferenceError，
  连带 `map.triggerRepaint()` 都不执行。构建与 430 条测试全绿。
- `TrafficWorkbench` 的 weather URL 手写了 `${activeCaseId?...}`，而这个变量
  只存在于 `OperationsConsole.vue`。**实时首页（无 case）每次都抛错**，
  于是气象层整块加载失败、横幅写"本帧已作废"，看起来像后端坏了。
  而 `traffic/caseMode.js` 早有 `caseQuery()` 这一唯一来源。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fix_city_map():
    path = ROOT / 'frontend/src/components/CityTrafficMap.vue'
    source = path.read_text(encoding='utf-8')

    close = source.index('</script>')
    head, after = source[:close], source[close + len('</script>'):]

    template_at = after.index('<template>')
    stray, rest = after[:template_at], after[template_at:]

    if 'paintFogCircles' not in stray:
        print('CityTrafficMap：没有越界块，跳过')
        return

    # 只搬"雾区影响圈"那一整段；若越界内容里还有别的东西，宁可停下来
    assert stray.lstrip().startswith('// ---- 雾区影响圈'), \
        '越界块里除了雾区函数还有别的内容，需要人工看：' + stray[:120]

    rebuilt = head + stray + '</script>\n' + rest
    path.write_text(rebuilt, encoding='utf-8')
    print('CityTrafficMap：%d 行雾区函数已搬进 <script setup>' % stray.count('\n'))


def fix_weather_case():
    path = ROOT / 'frontend/src/components/TrafficWorkbench.vue'
    source = path.read_text(encoding='utf-8')

    old = ("${activeCaseId?`&case=${encodeURIComponent(activeCaseId)}`:''}")
    assert old in source, 'activeCaseId 锚点不存在（可能已经修过）'
    source = source.replace(old, '${caseQuery()}', 1)

    old_import = "import {isCaseMode} from '../traffic/caseMode.js'"
    assert old_import in source, 'caseMode import 锚点'
    source = source.replace(
        old_import,
        "import {isCaseMode, caseQuery} from '../traffic/caseMode.js'", 1)
    path.write_text(source, encoding='utf-8')
    print('TrafficWorkbench：weather 的 case 参数改用 caseQuery()')

    # 预检那条也带上 case：案例模式下**不该去中继实时瓦片**（那是拿今天的回波
    # 冒充 2025-01-05）。带 case 之后后端会直接回 available=false + relay 缺席。
    old_pre = ("const value=await requestJson(`/api/traffic/weather?seed=${seed.value}"
               "&scenario=${scenario.value}&minute=${minute.value}`)")
    if old_pre in source:
        source = source.replace(
            old_pre,
            "const value=await requestJson(`/api/traffic/weather?seed=${seed.value}"
            "&scenario=${scenario.value}&minute=${minute.value}${caseQuery()}`)", 1)
        path.write_text(source, encoding='utf-8')
        print('TrafficWorkbench：预检也带 case（案例下不中继实时瓦片）')


def scan_stray_blocks():
    """顺手查全仓：任何 .vue 的 `</script>` 与 `<template>` 之间还有代码，就是同类事故。"""
    bad = []
    for f in (ROOT / 'frontend/src').rglob('*.vue'):
        text = f.read_text(encoding='utf-8')
        if '</script>' not in text or '<template>' not in text:
            continue
        close = text.index('</script>')
        tpl = text.index('<template>')
        if tpl <= close:
            continue
        between = text[close + len('</script>'):tpl]
        stripped = '\n'.join(
            line for line in between.split('\n')
            if line.strip() and not line.strip().startswith('//') and not line.strip().startswith('*'))
        if stripped.strip():
            bad.append((f.name, stripped.split('\n')[0][:70]))
    return bad


fix_city_map()
fix_weather_case()
strays = scan_stray_blocks()
if strays:
    print('⚠️  仍有越界块：')
    for name, first in strays:
        print('   %-28s %s' % (name, first))
else:
    print('全仓 .vue 的 </script> 之后无残留代码')
