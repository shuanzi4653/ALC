// 前端共享小工具

export const LEVEL_COLORS = {
  FIT: '#2e8b57',
  CAUTION: '#d98a2b',
  DANGER: '#d85a30',
  BAN: '#c0392b'
}

export const LEVEL_LABELS = {
  FIT: '适飞', CAUTION: '谨慎', DANGER: '危险', BAN: '禁飞'
}

export function levelColor(level) {
  return LEVEL_COLORS[level] || '#6f95c4'
}

export function levelLabel(level) {
  return LEVEL_LABELS[level] || level || '-'
}

/** ISO 时间 → HH:mm:ss */
export function fmtTime(iso) {
  if (!iso) return '--:--:--'
  const t = String(iso).replace('T', ' ')
  return t.length > 8 && t.includes(' ') ? t.slice(11, 19) : t.slice(0, 8)
}

/** ISO 时间 → MM-dd HH:mm */
export function fmtDateTime(iso) {
  if (!iso) return '-'
  const t = String(iso).replace('T', ' ')
  return t.slice(5, 16)
}

export const AGREEMENT_LABELS = {
  CONSISTENT: '双轨一致',
  WEIGHTED: '加权融合',
  SAFETY_FIRST: '安全优先'
}
