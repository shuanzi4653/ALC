import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
import {dirname,resolve} from 'node:path'

// 两条回归护栏，对着 V1.0.1 实测出来、**看起来都不像 bug** 的两个形态：
//
// ① 全国视图的右下「气象实况」整段被一张空卡片压住。DOM、尺寸、文字全部正常，
//    所以量什么都对；真凶是 `OperationsConsole` 在 `national` 视图下仍被渲染，
//    空壳仍有 `min-height:480px` + 不透明底，排在后面前面正好盖住溢出区。
//    这条一旦回退，页面只是"右下角变空白"，不会让任何既有断言变红 —— 只能靠这里钉住。
//
// ② 首页的整站缩放。1366 下真实 scale 是 0.648（容器 1166×700），把 9.5px 压成 6.16px。
//    断点的存在形式是「容器窄于 1500 就不套 scale、改 compact 排版」，
//    这行判断若被删掉或阈值被改大，首页会静默退回 6px 小字。

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')

function read(relative) {
  return readFileSync(resolve(root, relative), 'utf8')
}

test('national view does not mount the operations console shell', () => {
  const source = read('src/components/TrafficWorkbench.vue')
  const mount = source.match(/<OperationsConsole[^>]*v-if="([^"]+)"/)
  assert.ok(mount, '找不到 <OperationsConsole> 的 v-if，护栏失效')
  const condition = mount[1]
  // 排除列表里必须点名 national：`!['home','overview','schedule'].includes(activeSection)` 会渲染空壳。
  assert.match(condition, /\[\s*'home'[^\]]*'national'[^\]]*\]|\[\s*'national'/,
    `OperationsConsole 的 v-if 必须把 national 排除掉，实际是：${condition}`)
  assert.match(condition, /includes\(activeSection\)/,
    'v-if 仍然要按 activeSection 判断，不能退化成恒真/恒假')
})

test('home stage drops the whole-page scale on narrow containers', () => {
  const source = read('src/components/traffic/HomeStage.vue')
  // 阈值：容器 <1500 走 compact。写死成常量，避免被随手改大而让 1366 又落回缩放。
  const threshold = source.match(/COMPACT_MAX_W\s*=\s*(\d+)/)
  assert.ok(threshold, '找不到 COMPACT_MAX_W，1366 断点会静默消失')
  assert.equal(Number(threshold[1]), 1500)
  // compact 时不能带内联 transform，否则 scale(0) 或 scale(旧值) 仍会生效。
  assert.match(source, /:style="\[?compact\?null:/,
    'compact 时必须不输出内联 width/height/transform')
  // 字号地板按当前缩放反算：缺了这个变量，1920 下 12px 会被 0.937 压成 11.2px。
  assert.match(source, /--alc-stage-scale/,
    'hstage 必须把 --alc-stage-scale 传给 CSS，否则 1920 下字号地板算不出来')
  assert.match(source, /compact\.value\s*=\s*w\s*>\s*0\s*&&\s*w\s*<\s*COMPACT_MAX_W/,
    'compact 的判据必须是容器宽度，不是 window.innerWidth')
})

test('the four 1366 pages keep a 12px floor breakpoint', () => {
  const pages = [
    ['src/components/traffic/CorridorPanel.vue', /@media \(max-width:1440px\)/],
    ['src/components/traffic/CounterfactualPanel.vue', /@media \(max-width:1440px\)/],
    ['src/components/TrafficWorkbench.vue', /@media \(max-width:1440px\)/],
  ]
  for (const [file, pattern] of pages) {
    assert.match(read(file), pattern, `${file} 缺少 1440 断点，10–11.5px 的辅助文字会掉回 12px 以下`)
  }
  // 首页不靠媒体查询，靠 compact 类里的字号地板。
  assert.match(read('src/components/traffic/HomeStage.vue'), /\.hstage\.compact/,
    '首页 compact 断点缺失')
})

// 机场净空的审批口径（用户 2026-11-10 拍板）：能小绕就小绕，绕不掉的一律自动审批，
// 不进人工队列。这条口径只活在文案里 —— 回退后页面不会算错任何数字，只会把
// "已自动放行" 重新说成 "须经批准"，所以只能靠源码断言钉住。
test('airport clearance crossings are described as auto-approved', () => {
  const detail = read('src/components/TrafficWorkbench.vue')
  assert.match(detail, /机场净空按自动审批放行/,
    '班次详情必须说明机场净空是自动审批放行')
  assert.doesNotMatch(detail, /须经空中交通管理机构批准/,
    '旧的"须经空中交通管理机构批准"文案会让读者以为机场净空还在排队')

  const map = read('src/components/CityTrafficMap.vue')
  assert.match(map, /机场净空（自动审批放行/,
    '地图越界监视条里的口径没跟上')

  const runtime = read('src/traffic/runtime.js')
  assert.match(runtime, /APPROVAL_REQUIRED\]:'已进入机场净空（自动审批）'/,
    'zoneIntrusionLabels 的 APPROVAL_REQUIRED 仍是"须批准管制空域"')
})
