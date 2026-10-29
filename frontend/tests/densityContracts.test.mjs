// 信息密度三档（P2-4）的**接线**判据 —— 2026-10-17 补加。
//
// 为什么这条测试必须存在
// ----------------------
// `DENSITY_POLICY` 定义了 6 个开关，而在 2026-10-17 之前只有 2 个
// （`engineering` / `glossary`）真的被界面消费 —— 另外四个（`raw` / `audit` /
// `ledger` / `replay`）写在常量里、**没有任何一处读它的返回值**。
// 后果：切「演示 / 值班员 / 指挥」时屏幕上什么都没发生，而当时 359 条测试全绿。
//
// 这不是"少写了一个功能"，而是**判据问错了问题**：既有测试只问
// 「`densityPolicy('duty')` 返回什么」（纯函数契约），从来不问
// 「有没有人用它的返回值」。前者可以全绿而后者完全落空。
//
// 它属于哪一族
// ------------
// 与 MEMORY 里「有 API ≠ 能用」同族（开关要给可点控件、可切换口径必须进缓存键），
// 也与 ㉓「前端没有未绑定名闸门」相邻：那个闸门管「用了没定义的名」，
// 这条管它的镜像 —— **「定义了没人读的字段」**。
//
// 三条判据 + 一条负向自检：
//   1. 每个开关至少有一个 `:open="…policy.<键>"` 消费点；
//   2. 档位只能改**默认开合**，不许挂 `v-if` / `v-show`（否则三档变成三份产品，M25）；
//   3. 三档的策略两两不同（否则"换了三个名字"，而第 1、2 条照样全绿）；
//   4. 检测器咬得住 —— 只喂一个消费点时，必须报出其余未消费的开关。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { densityPolicy, DENSITY_TIERS } from '../src/traffic/runtime.js'

const here = dirname(fileURLToPath(import.meta.url))
const components = join(here, '..', 'src', 'components')

/** 模板求值 `node --test` 够不着（构建也不跑模板求值），所以「存在」只能从源码读。 */
async function sources() {
  return Promise.all(
    ['OperationsConsole.vue', 'TrafficWorkbench.vue'].map(async name => ({
      name,
      text: await readFile(join(components, name), 'utf8'),
    })),
  )
}

/** 收集所有 `:open="…policy.<键>"` 形式的消费点。 */
function consumedKeys(rows) {
  const out = new Set()
  for (const { text } of rows) {
    for (const match of text.matchAll(/:open="(?:policy|densityPolicy\(density\))\.(\w+)"/g)) {
      out.add(match[1])
    }
  }
  return out
}

test('DENSITY_POLICY 的每个开关都至少有一个界面消费点', async () => {
  const keys = Object.keys(densityPolicy('duty'))
  assert.ok(keys.length >= 6, `开关数只有 ${keys.length}，预期至少 6`)
  const consumed = consumedKeys(await sources())
  const missing = keys.filter(key => !consumed.has(key))
  assert.deepEqual(missing, [],
    `这些开关没有任何界面消费点：${missing.join(', ')}`
    + ' —— 写在常量里但没人读，切档位时屏幕不会有任何变化')
})

test('档位必须挂在 <details :open> 上，不能挂 v-if / v-show', async () => {
  // 「某一档把内容拿掉」与「某一档把内容收起来」是两种不同的故障：
  // 前者会让三档变成三份不同的产品（M25），而"演示时看不见"与"值班时看不见"
  // 的处置完全不同。所以这里钉的是**只能折叠**。
  for (const { name, text } of await sources()) {
    assert.doesNotMatch(text, /v-(?:if|show)="[^"]*(?:policy|densityPolicy\(density\))\.\w+/,
      `${name} 把信息密度档接到了 v-if / v-show 上 —— 档位只许改默认开合`)
  }
})

test('三个档位不是同一份策略的三个名字', async () => {
  // 负向面：若三档策略两两相同，界面再怎么切也不会变，
  // 而上面两条判据仍然会全绿（它们只问"有没有消费点"）。
  const seen = new Set(DENSITY_TIERS.map(tier => JSON.stringify(densityPolicy(tier.key))))
  assert.equal(seen.size, DENSITY_TIERS.length,
    '有两个档位的 policy 完全相同 —— 等于一个档位换了三个名字')
})

test('检测器本身咬得住：漏一个开关必须报红', async () => {
  // M29 / M74：判据要配"证明自己会失败"的样本，
  // 否则"永远绿"与"根本没在测"给出的是逐字相同的输出。
  const sample = [{ name: 'fake.vue', text: '<details :open="policy.raw"></details>' }]
  const keys = Object.keys(densityPolicy('duty'))
  const missing = keys.filter(key => !consumedKeys(sample).has(key))
  assert.ok(missing.includes('ledger'),
    '只喂一个消费点时，检测器应当报出其余未消费的开关（这里期望包含 ledger）')
  assert.equal(missing.length, keys.length - 1,
    `样本只消费了 1 个开关，应当报出 ${keys.length - 1} 个未消费项，实际 ${missing.length}`)
})
