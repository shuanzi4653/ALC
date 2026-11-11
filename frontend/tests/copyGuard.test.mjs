import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync, readdirSync, statSync} from 'node:fs'
import {join, extname} from 'node:path'
import {fileURLToPath} from 'node:url'

// 口径守卫：这几个词在任何一层都不许出现 —— 源码、注释、本届文档。
//
// 背景：2026-11-11 用户明确要求「边境停飞不要写，这个是删掉的东西，写了会扣分」。
// 这类东西一旦回流（改一句话、复制一段旧文案），单测和构建都发现不了，
// 只有评委看界面时才会发现。所以用一条守卫钉住。
const BANNED = ['边境', '实际控制线', '我方一侧']

// tests/ → frontend/ → 仓库根（两级，别多写一级：多一级会扫到 Desktop 而扫 0 个文件）
const ROOT = fileURLToPath(new URL('../../', import.meta.url))
const SCAN = [
  'frontend/src',
  'backend-python/traffic',
  'docs/V1.0.2-发布说明.md',
  'docs/V1.0.2-更新方案.md',
]
const TEXT = new Set(['.js', '.mjs', '.vue', '.css', '.py', '.md'])

function walk(entry, out = []) {
  const full = join(ROOT, entry)
  let st
  try { st = statSync(full) } catch { return out }
  if (st.isFile()) {
    if (TEXT.has(extname(full))) out.push(full)
    return out
  }
  for (const name of readdirSync(full)) {
    if (name === 'node_modules' || name === '__pycache__' || name.startsWith('.')) continue
    walk(join(entry, name), out)
  }
  return out
}

test('「边境 / 实际控制线 / 我方一侧」不许回流到源码、注释或本届文档', () => {
  const files = SCAN.flatMap((p) => walk(p))
  assert.ok(files.length > 40, `扫描面太小，可能路径变了：只找到 ${files.length} 个文件`)
  const hits = []
  for (const file of files) {
    const text = readFileSync(file, 'utf8')
    for (const word of BANNED) {
      if (!text.includes(word)) continue
      const line = text.slice(0, text.indexOf(word)).split('\n').length
      hits.push(`${file.replace(ROOT, '').replace(/\\/g, '/')}:${line} → ${word}`)
    }
  }
  assert.deepEqual(hits, [], '出现了不该出现的表述：\n  ' + hits.join('\n  '))
})
