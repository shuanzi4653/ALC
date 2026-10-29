#!/usr/bin/env node
/**
 * 未绑定名扫描（0.11.8）。**这是前端唯一能抓 "ReferenceError" 的网。**
 *
 * 起因（2026-10-21 线上）：`TrafficWorkbench.vue` 的 weather 请求里写了
 * `${activeCaseId?...}`，而 `activeCaseId` 只存在于 `OperationsConsole.vue`。
 * 结果：**实时首页的气象层整块加载失败**（`activeCaseId is not defined`），
 * 横幅写"本帧已作废"，而构建、430 条测试、工具链闸门 27 项全部是绿的。
 *
 * 为什么所有现成的闸门都漏了它：
 *   · `vite build` 不做未绑定名检查（它只解析语法）；
 *   · Vue 模板里的未知名字会退化成 `_ctx.x`（渲染成空，不抛错）；
 *   · `_audit_unbound_names.py` 是 Python AST —— 结构上不在它射程里（M23）。
 *
 * 判据的取舍（写在代码里，因为它决定了这个扫描器的**边界**）：
 *   只做"**这个名字在整个文件里有没有被声明过**"，不做作用域解析。
 *   于是它**只会漏**"声明了但在另一个作用域"（那类由测试兜），
 *   而**不会误报**——一个会误报的闸门，两天内就会被加进白名单然后永久失效。
 *
 * 用法：
 *   node js_unbound_scan.mjs [目录...]     默认扫 frontend/src 全部 .js/.vue
 *   出口：0 干净 / 1 有未绑定名 / 2 无法测量（找不到 babel、文件读不到…）
 */

import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..', '..')
const FRONTEND = join(ROOT, 'frontend')
const require = createRequire(join(FRONTEND, 'package.json'))

let parse
try {
  ;({ parse } = require('@babel/parser'))
} catch (err) {
  console.error('SKIP  no @babel/parser under frontend/node_modules —— 无法测量，不是"干净"')
  process.exit(2)
}

/**
 * 浏览器/JS 内建 + Vue 编译器宏。
 *
 * 这张表**只放"真的可以在任何文件里直接写"的名字**。往里面塞项目内的名字
 * （比如某个 util），这个扫描器就退化成"什么都查不到"。
 */
const GLOBALS = new Set([
  // 语言内建
  'undefined', 'NaN', 'Infinity', 'globalThis', 'arguments',
  'Object', 'Array', 'Function', 'String', 'Number', 'Boolean', 'Symbol', 'BigInt',
  'Math', 'JSON', 'Date', 'RegExp', 'Error', 'TypeError', 'RangeError', 'SyntaxError',
  'Map', 'Set', 'WeakMap', 'WeakSet', 'Promise', 'Proxy', 'Reflect', 'Intl',
  'ArrayBuffer', 'DataView', 'Uint8Array', 'Uint16Array', 'Int8Array', 'Int32Array',
  'Float32Array', 'Float64Array', 'BigInt64Array',
  'parseInt', 'parseFloat', 'isNaN', 'isFinite',
  'encodeURIComponent', 'decodeURIComponent', 'encodeURI', 'decodeURI',
  'structuredClone', 'queueMicrotask', 'atob', 'btoa',
  // 定时器与帧
  'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval',
  'requestAnimationFrame', 'cancelAnimationFrame', 'requestIdleCallback',
  // 浏览器对象
  'window', 'document', 'navigator', 'location', 'history', 'screen', 'self',
  'localStorage', 'sessionStorage', 'console', 'performance', 'crypto',
  'fetch', 'URL', 'URLSearchParams', 'FormData', 'Headers', 'Request', 'Response',
  'AbortController', 'AbortSignal', 'Blob', 'File', 'FileReader', 'Image', 'Audio',
  'WebSocket', 'Worker', 'TextEncoder', 'TextDecoder',
  'ResizeObserver', 'IntersectionObserver', 'MutationObserver',
  'matchMedia', 'getComputedStyle', 'devicePixelRatio',
  'Event', 'CustomEvent', 'KeyboardEvent', 'MouseEvent', 'PointerEvent', 'TouchEvent',
  'HTMLElement', 'SVGElement', 'Node', 'DOMParser',
  'alert', 'confirm', 'prompt', 'open', 'close', 'postMessage', 'addEventListener',
  'removeEventListener', 'scrollTo', 'scrollBy',
  'setProperty', 'getPropertyValue',
  'process', 'module', 'exports', 'require',
  // Vue 编译器宏（<script setup>）
  'defineProps', 'defineEmits', 'defineExpose', 'defineSlots', 'defineModel',
  'withDefaults', 'defineOptions',
])

function maskVue(source) {
  // 只留 `<script>` 块。模板里的未绑定名会退化成 `_ctx.x`（渲染成空、不抛错），
  // 属于**另一类**问题（静默空白），扫进来会让这个闸门的结论变得不可读。
  const blocks = [...source.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1])
  if (!blocks.length) return null
  // 用等长空白替换非 script 部分，让行号仍然对得上原文
  let out = source.replace(/<script[^>]*>[\s\S]*?<\/script>/g, m => m)
  out = out.replace(/<template[\s\S]*?<\/template>/g, m => m.replace(/[^\n]/g, ' '))
  out = out.replace(/<style[\s\S]*?<\/style>/g, m => m.replace(/[^\n]/g, ' '))
  // Vue 的 `<script>` 在 .vue 里不是合法 JS 文件整体，需按块拼回去
  return blocks.map(b => b).join('\n;\n')
}

function collectPattern(node, declared) {
  if (!node) return
  switch (node.type) {
    case 'Identifier':
      declared.add(node.name)
      break
    case 'ObjectPattern':
      for (const prop of node.properties || []) {
        if (prop.type === 'RestElement') collectPattern(prop.argument, declared)
        else collectPattern(prop.value, declared)
      }
      break
    case 'ArrayPattern':
      for (const el of node.elements || []) collectPattern(el, declared)
      break
    case 'AssignmentPattern':
      collectPattern(node.left, declared)
      break
    case 'RestElement':
      collectPattern(node.argument, declared)
      break
    default:
      break
  }
}

const FUNCTION_TYPES = new Set([
  'FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression',
  'ObjectMethod', 'ClassMethod', 'ClassPrivateMethod',
])

/** 一遍遍历：收集"声明过的名字"和"引用位置的名字"。 */
function scan(ast) {
  const declared = new Set()
  const refs = [] // {name, line}

  const isRefSlot = (parent, key, node) => {
    if (!parent) return true
    const t = parent.type
    if (t === 'MemberExpression' && key === 'property' && !parent.computed) return false
    if (t === 'OptionalMemberExpression' && key === 'property' && !parent.computed) return false
    if ((t === 'ObjectProperty' || t === 'ObjectMethod' || t === 'ClassProperty' ||
         t === 'ClassMethod' || t === 'ClassPrivateProperty' || t === 'ClassPrivateMethod') &&
        key === 'key' && !parent.computed) return false
    if (t === 'LabeledStatement' && key === 'label') return false
    if ((t === 'BreakStatement' || t === 'ContinueStatement') && key === 'label') return false
    if (t === 'MetaProperty') return false
    return true
  }

  const visit = (node, parent, key) => {
    if (!node || typeof node !== 'object') return
    if (Array.isArray(node)) {
      for (const item of node) visit(item, parent, key)
      return
    }
    if (!node.type) return

    const t = node.type

    // —— 声明 ——
    if (t === 'VariableDeclarator') {
      collectPattern(node.id, declared)
      visit(node.init, node, 'init')
      return
    }
    if (t === 'ImportDeclaration') {
      for (const spec of node.specifiers || []) declared.add(spec.local.name)
      return
    }
    if (t === 'CatchClause') {
      collectPattern(node.param, declared)
      visit(node.body, node, 'body')
      return
    }
    if (FUNCTION_TYPES.has(t)) {
      if (node.id) declared.add(node.id.name)
      for (const p of node.params || []) collectPattern(p, declared)
      // 参数默认值是**引用**，要单独走：`f(a = b)` 里 b 是引用、a 是声明
      for (const p of node.params || []) {
        if (p && p.type === 'AssignmentPattern') visit(p.right, p, 'right')
        if (p && p.type === 'ObjectPattern') {
          for (const prop of p.properties || []) {
            if (prop && prop.value && prop.value.type === 'AssignmentPattern') visit(prop.value.right, prop, 'right')
          }
        }
      }
    }
    if ((t === 'ClassDeclaration' || t === 'ClassExpression') && node.id) declared.add(node.id.name)
    if (t === 'TSEnumDeclaration' || t === 'TSInterfaceDeclaration') {
      if (node.id) declared.add(node.id.name)
    }
    if (t === 'ExportSpecifier' && node.local && node.local.type === 'Identifier') {
      refs.push({ name: node.local.name, line: node.loc ? node.loc.start.line : 0 })
      return
    }

    // —— 引用 ——
    if (t === 'Identifier') {
      if (isRefSlot(parent, key, node)) {
        refs.push({ name: node.name, line: node.loc ? node.loc.start.line : 0 })
      }
      return
    }

    for (const k of Object.keys(node)) {
      if (k === 'loc' || k === 'start' || k === 'end' || k === 'leadingComments' ||
          k === 'trailingComments' || k === 'innerComments' || k === 'extra' ||
          k === 'comments' || k === 'tokens') continue
      visit(node[k], node, k)
    }
  }

  visit(ast, null, null)
  return { declared, refs }
}

function listFiles(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    const st = statSync(full)
    if (st.isDirectory()) {
      if (name === 'node_modules' || name === 'dist') continue
      listFiles(full, acc)
    } else if (/\.(js|mjs|vue)$/.test(name)) {
      acc.push(full)
    }
  }
  return acc
}

/**
 * `.vue` 的"越界块"：`</script>` 与 `<template>` 之间还有可执行代码。
 *
 * 这条是**根因判据**，不是副产品。2026-10-21 的雾区函数就是这样丢的：
 * 补丁把它们追加到了 `</script>` 之后，Vite 照样打包成功、430 条测试全绿，
 * 只有运行时每次重画抛一次 ReferenceError —— 而那一次抛错连
 * `map.triggerRepaint()` 都一并跳过了，地图看着"画了一半"。
 *
 * 之前扫描器只是**间接**抓到它（因为调用点变成未绑定名）。间接判据的射程取决于
 * "有没有人调用它"：一个定义了、暂未被调用的越界函数会完全静默。所以单列一条。
 */
function strayBlocks(source) {
  const out = []
  const close = source.indexOf('</script>')
  if (close < 0) return out
  const nextBlock = ['<template', '<style'].map(tag => source.indexOf(tag, close))
    .filter(i => i > 0)
    .sort((a, b) => a - b)[0]
  if (nextBlock === undefined) return out
  const between = source.slice(close + '</script>'.length, nextBlock)
  const codeLines = between.split('\n').filter(line => {
    const s = line.trim()
    return s && !s.startsWith('//') && !s.startsWith('/*') && !s.startsWith('*') && !s.startsWith('*/')
  })
  if (codeLines.length) {
    const lineNo = source.slice(0, close).split('\n').length + 1 +
      (between.split('\n').findIndex(line => line.trim() && !line.trim().startsWith('//')) - 1)
    out.push({ kind: 'STRAY', line: Math.max(lineNo, 1), name: codeLines[0].slice(0, 60) })
  }
  return out
}

function scanFile(file) {
  const raw = readFileSync(file, 'utf8')
  let code
  if (file.endsWith('.vue')) {
    const stray = strayBlocks(raw)
    if (stray.length) return stray.map(hit => ({ ...hit, file }))
    code = maskVue(raw)
    if (code === null || !code.trim()) return []
  } else {
    code = raw
  }
  let ast
  try {
    ast = parse(code, {
      sourceType: 'module',
      allowAwaitOutsideFunction: true,
      allowReturnOutsideFunction: true,
      errorRecovery: true,
      plugins: ['optionalChaining', 'nullishCoalescingOperator', 'classProperties',
               'classPrivateProperties', 'classPrivateMethods', 'topLevelAwait',
               'numericSeparator', 'logicalAssignment', 'objectRestSpread'],
    })
  } catch (err) {
    // 解析不了**不能**算干净。这条出口与"通过"必须分开（0 / 1 / 2 三出口）。
    return [{ kind: 'PARSE_ERROR', file, line: 0, name: String(err.message).slice(0, 120) }]
  }
  const { declared, refs } = scan(ast)
  const hits = []
  const seen = new Set()
  for (const ref of refs) {
    if (declared.has(ref.name) || GLOBALS.has(ref.name)) continue
    const key = `${ref.name}:${ref.line}`
    if (seen.has(key)) continue
    seen.add(key)
    hits.push({ kind: 'UNBOUND', file, line: ref.line, name: ref.name })
  }
  return hits
}

function main() {
  const args = process.argv.slice(2).filter(a => !a.startsWith('--'))
  const targets = args.length ? args.map(a => resolve(a)) : [join(FRONTEND, 'src')]
  const files = []
  for (const t of targets) {
    if (!existsSync(t)) {
      console.error(`SKIP  路径不存在：${t}`)
      process.exit(2)
    }
    if (statSync(t).isDirectory()) listFiles(t, files)
    else files.push(t)
  }
  if (!files.length) {
    console.error('SKIP  没有可扫的文件 —— 无法测量')
    process.exit(2)
  }

  let parseErrors = 0
  const findings = []
  for (const f of files) {
    for (const hit of scanFile(f)) {
      if (hit.kind === 'PARSE_ERROR') parseErrors += 1
      findings.push(hit)
    }
  }

  const rel = p => p.replace(ROOT + '\\', '').replace(ROOT + '/', '').replace(/\\/g, '/')
  for (const hit of findings) {
    if (hit.kind === 'PARSE_ERROR') console.log(`FAIL  parse  ${rel(hit.file)}: ${hit.name}`)
    else if (hit.kind === 'STRAY') console.log(`FAIL  stray  ${rel(hit.file)}:${hit.line}  </script> 之后有代码：${hit.name}`)
    else console.log(`FAIL  unbound  ${rel(hit.file)}:${hit.line}  ${hit.name}`)
  }
  console.log(`scanned ${files.length} files`)
  console.log(`unbound names: ${findings.filter(h => h.kind === 'UNBOUND').length}`)
  console.log(`stray blocks: ${findings.filter(h => h.kind === 'STRAY').length}`)
  console.log(`parse errors: ${parseErrors}`)
  if (parseErrors) process.exit(2)
  process.exit(findings.length ? 1 : 0)
}

main()
