/**
 * 0.11.4（W-22a）投影模式的字号下限 —— 一条**能红**的静态判据。
 *
 * 为什么不在浏览器里量：`node --test` 不跑渲染，量字号需要 Playwright；
 * 而这里要守的不是"某个元素多大了"，是"那条兜底规则还在不在"。
 * 规则一旦被谁顺手删掉，投影档就会静默退回"只隐藏字段"，而截图看不出异常
 * （字号小一点也不报错）。所以钉住规则本身，并在真机上人工复核一次。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const css = await readFile(new URL('../src/style.css', import.meta.url), 'utf8')

test('投影档必须真的抬高字号，而不只是隐藏工程字段', () => {
  const projectionBlocks = css.match(/html\[data-projection="on"\][^{]*\{[^}]*\}/g) || []
  assert.ok(projectionBlocks.length >= 3, '投影档的规则块少于 3 个，疑似被删')

  const joined = projectionBlocks.join('\n')
  assert.match(joined, /clamp\(16px,\s*1em,\s*18px\)/,
    '缺少正文下限 clamp(16px, 1em, 18px) —— 81 处 9/10/11px 字面量会原样留在投影档')
  assert.match(joined, /clamp\(20px,\s*1em,\s*40px\)/,
    '缺少标题下限 clamp(20px, 1em, 40px)')
})

test('下限规则必须带 !important，否则被 scoped 规则压回去', () => {
  // scoped 规则的典型形态是 `.hs-f-item[data-v-xxx]{font-size:9px}`，特异性 (0,2,0)。
  // 我们的 `:where()` 是零特异性 (0,1,0)，不加 !important 就一定输。
  const rule = /html\[data-projection="on"\] :where\([^)]*\)\s*\{[^}]*\}/g
  const blocks = css.match(rule) || []
  assert.ok(blocks.length >= 2, '找不到两条 :where 下限规则')
  for (const block of blocks) {
    assert.match(block, /font-size:\s*clamp\([^)]*\)\s*!important/,
      '下限规则缺 !important，投影档不会生效')
  }
})

test('令牌提升仍然保留（用令牌排版的部分跟着涨）', () => {
  const block = /html\[data-projection="on"\]\s*\{[^}]*\}/.exec(css)?.[0] ?? ''
  assert.match(block, /--alc-fs-aux:\s*1[46]px/, '投影档的辅助字号令牌没变')
  assert.match(block, /--alc-fs-hero:\s*(5[2-9]|6\d)px/, '投影档的主数字令牌没变')
})
