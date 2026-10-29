export const KNOWN_CASES = Object.freeze([
  {
    caseId: 'fog-20250105',
    label: '2025-01-05 沈阳大雾',
    durationMinutes: 360,
    note: '案例起点 T+00:00 · ZYTX 能见度 997.8 m、云底 152 m · 哈尔滨 1593 m · 长春 2993 m',
  },
])

export function activeCase() {
  try {
    const params = new URLSearchParams(window.location.search)
    const value = (params.get('case') || '').trim()
    return /^[a-z0-9-]{3,40}$/.test(value) ? value : ''
  } catch (_) {
    return ''
  }
}

export function caseQuery() {
  const value = activeCase()
  return value ? `&case=${encodeURIComponent(value)}` : ''
}

export function withCase(url) {
  const value = activeCase()
  if (!value) return url
  const glue = url.includes('?') ? '&' : '?'
  return `${url}${glue}case=${encodeURIComponent(value)}`
}

export function caseMeta() {
  const value = activeCase()
  if (!value) return null
  return KNOWN_CASES.find(item => item.caseId === value) || { caseId: value, label: value, note: '' }
}

export function isCaseMode() {
  return Boolean(activeCase())
}
