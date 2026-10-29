"""0.11.8：雾区圈的纯算法搬进 `runtime.js`（项目约定：纯算法只有这一个家）。

为什么必须搬：
1. **它原来一条判据都没有** —— 而 `paintFogCircles` 那一轮"写了没接"（函数被写到
   `</script>` 之后）之所以没人发现，就是因为这段几何没有任何测试能红。
2. `runtime.js` 是唯一能被 `node --test` 直接 import 的地方；`.vue` 里的函数
   只能靠"读源码字符串"这种间接判据。
3. 原来的半径常量注释说"要同步 rules-v1.json"，但没有任何东西核对它 ——
   搬出来之后可以由测试读 `config/rules-v1.json` 比对，把散文换成判据。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VUE = ROOT / 'frontend/src/components/CityTrafficMap.vue'
RUNTIME = ROOT / 'frontend/src/traffic/runtime.js'

vue = VUE.read_text(encoding='utf-8')

start = vue.index('// ---- 雾区影响圈')
end = vue.index('function paintFogCircles()')
block = vue[start:end].rstrip() + '\n'

# 去掉 `</script>` 留下的空行残留
vue = vue[:start] + vue[end:]
VUE.write_text(vue, encoding='utf-8')
print('CityTrafficMap：雾区几何 %d 行已移出' % block.count('\n'))

exported = (block
            .replace('const FOG_RING_KM = { BAN: 6, CAUTION: 12 }',
                     'export const FOG_RING_KM = Object.freeze({ BAN: 6, CAUTION: 12 })')
            .replace('\nfunction fogRing(', '\nexport function fogRing(')
            .replace('\nfunction fogFeatureCollection(', '\nexport function fogFeatureCollection('))

runtime = RUNTIME.read_text(encoding='utf-8')
runtime = runtime.rstrip() + """

// ============================================================================
// 雾区影响圈（0.11.7 / B；0.11.8 从 CityTrafficMap.vue 搬到这里）
// ============================================================================
//
// 为什么在 runtime.js：这是**纯几何**，而纯几何必须能跑测试。它原来住在一个 .vue
// 里，于是"函数被写到 `</script>` 之后"这种事只能靠人眼发现（判据 0 条）。
//
// 半径不是"看着差不多"，是**判据阈值的派生量**：
//   rules-v1.json 的 banValue 1000 m  -> 6 km 深灰（BAN）
//                    warnValue 5000 m -> 12 km 浅灰（CAUTION）
// 这个映射不写在 rules 里（rules 是气象阈值，不是画图半径），所以由
// `frontend/tests/fogRings.test.mjs` 反向核对：配置里的阈值一改、档位名字变了，
// 测试必须红 —— 否则这两个常量会在无人察觉时变成"过期副本"。
""" + exported
RUNTIME.write_text(runtime, encoding='utf-8')
print('runtime.js：已导出 FOG_RING_KM / fogRing / fogFeatureCollection')

# 接上导入
old_import = "import { altitudeText,atTime,flightState"
assert old_import in vue, 'runtime 导入锚点'
vue = VUE.read_text(encoding='utf-8')
vue = vue.replace(old_import,
                  "import { FOG_RING_KM,fogRing,fogFeatureCollection,altitudeText,atTime,flightState", 1)
VUE.write_text(vue, encoding='utf-8')
print('CityTrafficMap：已从 runtime.js 导入三件套')

# 自检：`</script>` 之后必须干净，且三件套只剩定义在 runtime
build = VUE.read_text(encoding='utf-8')
close = build.index('</script>')
tpl = build.index('<template>')
between = [line for line in build[close + len('</script>'):tpl].split('\n') if line.strip()]
assert not between, '越界块又出现了：' + between[0][:80]
assert 'function fogRing(' not in build, '.vue 里还有 fogRing 的定义'
print('自检通过：.vue 无雾区几何、无越界块')
