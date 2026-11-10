// 全局作用域：全国 → 大区 → 省 → 市。
//
// 为什么要有它：V1.0.1 把"全国"做成了一个 tab（`national`），其余九个视图
// （home / overview / weather / alerts / assistant / profile / card / reference / history）
// 各自去读东北的 session。于是"切到河北"这件事只有全国地图自己知道，
// 气象、台账、处置、取证全不知道——用户看到的就是"处置没跟随国区省市变动"。
//
// 作用域提升到全局之后，任何一个视图都只读 `store.scope`，不再各自猜"现在看哪一级"。
//
// 三条规则（方案 §3.2）：
//   1. **写在 URL 里**：刷新、分享、评委点链接都能还原同屏。V1.0.1 的下钻一刷新就丢。
//   2. **切层即清选择**：换 scope 要清班次/走廊/跟随，避免"跟着上一级那架跑"。
//   3. **下钻只有一个入口**：地图点区块、右栏点条目、命令面板输地名，都走 setScope。

export const SCOPE_LEVELS = Object.freeze(['nation', 'region', 'province', 'city'])

// 与后端 `traffic/nation.py::REGION_LABEL` 保持一致。这里必须有一份，
// 因为从 URL 直接进入某大区时，前端还没有任何数据可以取名字。
export const REGION_LABEL = Object.freeze({
  north: '华北', northeast: '东北', east: '华东',
  central: '中南', southwest: '西南', northwest: '西北',
})

export const SCOPE_LEVEL_LABEL = Object.freeze({
  nation: '全国', region: '大区', province: '省', city: '市',
})

export function scopeLabel(level, id) {
  if (!level || level === 'nation') return '全国'
  if (level === 'region') return REGION_LABEL[id] || id
  return id || '全国'
}

/** `scope` 对象 → URL 键（`nation` / `region:north` / `province:河北省`）。 */
export function scopeKey(level, id) {
  if (!level || level === 'nation' || !id) return 'nation'
  return `${level}:${id}`
}

/** URL 键 → `{level,id,label}`。任何不认识的值都回落全国，不猜。 */
export function parseScope(key) {
  const text = String(key || '').trim()
  if (!text || text === 'nation') return { level: 'nation', id: '', label: '全国' }
  const cut = text.indexOf(':')
  if (cut < 0) return { level: 'nation', id: '', label: '全国' }
  const level = text.slice(0, cut)
  const id = text.slice(cut + 1)
  if (!SCOPE_LEVELS.includes(level) || !id) return { level: 'nation', id: '', label: '全国' }
  return { level, id, label: scopeLabel(level, id) }
}

/** 从地址栏读作用域。放在 hash 之前（`?scope=province:河北省#/situation/home`），
 *  这样不动项目自己的 hash 路由解析。 */
export function readScopeFromUrl() {
  try {
    const text = new URLSearchParams(window.location.search).get('scope')
    return parseScope(text)
  } catch (_) {
    return parseScope('nation')
  }
}

/** 写回地址栏。全国层不写参数，保持地址干净。 */
export function writeScopeToUrl(scope) {
  try {
    const url = new URL(window.location.href)
    const key = scopeKey(scope?.level, scope?.id)
    if (key === 'nation') url.searchParams.delete('scope')
    else url.searchParams.set('scope', key)
    window.history.replaceState(null, '', url)
  } catch (_) {
    // 地址栏写不进去不影响功能：作用域在内存里照样生效
  }
}
