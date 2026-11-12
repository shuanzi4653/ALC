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

test('airport clearance crossings are described as auto-approved', () => {
  // V1.0.5：原断言的落点（TrafficWorkbench 里的班次详情）随东北总览一起下线，
  // 全国层的净空口径改由「气象监测 → 机场情报」这一行承担。
  const intel = read('src/components/traffic/NationBriefing.vue')
  assert.match(intel, /净空（规则化生成，非官方公布）/,
    '机场情报必须说明净空是规则化生成、非官方公布')
  assert.match(read('src/components/traffic/NationMap.vue'), /机场净空限制区（规则化生成，非官方公布）/,
    '地图上的禁飞区说明没跟上')
  const detail = read('src/components/TrafficWorkbench.vue')
  assert.doesNotMatch(detail, /须经空中交通管理机构批准/,
    '旧的"须经空中交通管理机构批准"文案会让读者以为机场净空还在排队')

  const map = read('src/components/CityTrafficMap.vue')
  assert.match(map, /机场净空（自动审批放行/,
    '地图越界监视条里的口径没跟上')

  const runtime = read('src/traffic/runtime.js')
  assert.match(runtime, /APPROVAL_REQUIRED\]:'已进入机场净空（自动审批）'/,
    'zoneIntrusionLabels 的 APPROVAL_REQUIRED 仍是"须批准管制空域"')
})
