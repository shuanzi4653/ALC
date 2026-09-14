// 前端共享小工具

/**
 * 统一等级样式表（A05）。
 * 所有图元（点、线、边框、填充、标签、图例）都必须引用本表，避免四处硬编码颜色造成语义漂移。
 * 语义约定：
 * - CAUTION 为橙色，**不再与 FIT 共用绿色**（M4 缺陷修复）
 * - 只有 BAN 使用「禁入」措辞；DANGER 用「危险影响区」，不得写「禁入」
 * - 未知等级（null / UNDETERMINED）为灰色「不可判定」，不冒充适飞
 */
export const LEVEL_STYLES = {
  FIT: {
    color: '#2e8b57',
    label: '适飞',
    fill: 'rgba(46,139,87,.10)',
    border: 'rgba(46,139,87,.60)',
    areaLabel: '作业影响范围'
  },
  CAUTION: {
    color: '#d98a2b',
    label: '谨慎',
    fill: 'rgba(217,138,43,.12)',
    border: 'rgba(217,138,43,.70)',
    areaLabel: '谨慎作业区'
  },
  DANGER: {
    color: '#d85a30',
    label: '危险',
    fill: 'rgba(216,90,48,.14)',
    border: 'rgba(216,90,48,.75)',
    areaLabel: '危险影响区'
  },
  BAN: {
    color: '#c0392b',
    label: '禁飞',
    fill: 'rgba(192,57,43,.16)',
    border: 'rgba(255,107,90,.80)',
    areaLabel: '禁飞区（禁入）'
  }
}

/** 未知 / 不可判定：灰色，不作为第五种可排序等级参与运算。 */
export const UNKNOWN_STYLE = {
  color: '#6f95c4',
  label: '不可判定',
  fill: 'rgba(111,149,196,.08)',
  border: 'rgba(111,149,196,.40)',
  areaLabel: '数据不足'
}

/** 兼容旧引用：由统一表派生，避免颜色定义分叉。 */
export const LEVEL_COLORS = Object.fromEntries(
  Object.entries(LEVEL_STYLES).map(([k, v]) => [k, v.color])
)

export const LEVEL_LABELS = Object.fromEntries(
  Object.entries(LEVEL_STYLES).map(([k, v]) => [k, v.label])
)

export function levelStyle(level) {
  return LEVEL_STYLES[level] || UNKNOWN_STYLE
}

export function levelColor(level) {
  return levelStyle(level).color
}

export function levelLabel(level) {
  return level ? levelStyle(level).label : UNKNOWN_STYLE.label
}

/** 该等级是否需要提示风险影响区（危险/禁飞） */
export function isRiskLevel(level) {
  return level === 'DANGER' || level === 'BAN'
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
  SAFETY_FIRST: '安全优先',
  TRACK1_ONLY: '仅规则结果'
}

/** 数据新鲜度文案 */
export const DATA_STATUS_LABELS = {
  FRESH: '数据新鲜',
  STALE: '数据已过期',
  NO_DATA: '无数据',
  UNAVAILABLE: '数据源不可用',
  UNKNOWN: '时间未知'
}

/** 运行状态文案 */
export const RUN_STATUS_LABELS = {
  WAITING: '等待首轮',
  RUNNING: '采集中',
  RULE_READY: '规则已出（AI 补充中）',
  COMPLETE: '本轮完成',
  FAILED: '本轮失败'
}
