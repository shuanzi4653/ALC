<template>
  <div class="cb">
    <!-- 左：走廊列表。走廊页与推演页共用同一套，区别只在右边放什么。 -->
    <aside class="cb-list" data-corridor-list>
      <div class="cb-tools">
        <input v-model="query" type="search" placeholder="搜索航线 / 城市" aria-label="搜索走廊"/>
        <button :class="{on:sortKey==='bad'}" @click="sortKey='bad'"
                title="按异常程度排：停飞 > 绕飞 > 延期 > 风险高">异常</button>
        <button :class="{on:sortKey==='id'}" @click="sortKey='id'">编号</button>
      </div>
      <p class="cb-count">{{ rows.length }} 条 · {{ anomalyCount }} 条需关注</p>
      <ul class="cb-rows" data-corridor-rows>
        <li v-for="row in shown" :key="row.id" :class="[row.tone,{on:row.id===activeId}]"
            data-corridor-row @click="pick(row)">
          <b>{{ row.fromShort }} → {{ row.toShort }}</b>
          <span class="meta">{{ row.id }} · {{ row.kindLabel }} · {{ row.lengthKm }} km</span>
          <em :class="row.tone">{{ row.statusText }}</em>
          <i v-if="row.attrText" class="cb-attr" :title="row.attrText">{{ row.attrText }}</i>
          <i v-if="row.review" class="rv" :title="row.review.reason">人工 · {{ reviewLabel(row.review.action) }}</i>
        </li>
        <li v-if="!shown.length" class="empty">没有匹配的走廊</li>
      </ul>
    </aside>

    <!-- 右：地图 + 数据 / 分析 -->
    <div class="cb-main">
      <div class="cb-map" :class="{short:mode==='card'}">
        <NationMap :data="data" :flights="flights" :minute="minute" :frame-minute="-1"
                   :radar-on="true" :fog-on="false" :terrain-on="false" :tilt="false"
                   :zone-bands="zoneBands" :solo-corridor="activeId" :lock-view="true"
                   :selected-corridor="activeId" :line-limit="1"/>
        <p class="cb-mapnote" v-if="active">仅显示本条走廊：{{ active.fromName }} → {{ active.toName }}。本页不支持缩放，周边空域请见「态势」。</p>
      </div>

      <!-- 走廊模式：航旅纵横式数据卡 -->
      <section class="cb-info" v-if="mode==='corridor'" data-corridor-info>
        <template v-if="active">
          <header>
            <b>{{ active.fromName }}</b><span class="arrow">→</span><b>{{ active.toName }}</b>
            <em class="kind">{{ active.kindLabel }}</em>
            <span class="verd" :class="active.tone">{{ verdictText }}</span>
          </header>
          <div class="cb-grid">
            <div><small>航线</small><b>{{ active.id }}</b></div>
            <div><small>航程</small><b>{{ active.lengthKm }} km</b></div>
            <div><small>计划起飞</small><b>{{ active.departAt || '—' }}</b></div>
            <div><small>计划到达</small><b>{{ active.arriveAt || '—' }}</b></div>
            <div><small>巡航高度</small><b>{{ active.altM == null ? '—' : active.altM + ' m' }}</b></div>
            <div><small>高度带</small><b>{{ altBand }}</b></div>
            <div><small>回波暴露</small><b>{{ active.exposureMin == null ? '—' : active.exposureMin + ' 分' }}</b></div>
            <div><small>绕飞增量</small><b>{{ active.detourKm ? active.detourKm + ' km' : '无' }}</b></div>
          </div>
          <p class="cb-why" v-if="active.drivers && active.drivers.length">
            判据：{{ active.drivers.join('；') }}
          </p>
          <p class="cb-why quiet" v-else>
            本帧未越过任何阈值，依据为空即结论。
          </p>

          <!-- 人工审核：1.0.0 的"人说了算"要保留，算法只给建议 -->
          <div class="cb-review" data-review>
            <span class="lb">人工裁决</span>
            <button v-for="opt in REVIEW_OPTS" :key="opt.key"
                    :class="{on:active.review && active.review.action===opt.key, [opt.tone]:true}"
                    @click="setReview(opt.key)">{{ opt.label }}</button>
            <input v-model="reasonText" placeholder="理由（写进日志）" aria-label="人工裁决理由"/>
            <button class="clr" v-if="active.review" @click="clearReview">撤销</button>
          </div>
          <p class="cb-rv-note" v-if="active.review">人工裁决已记录：{{ reviewLabel(active.review.action) }} · {{ active.review.reason || '未填理由' }}。该裁决覆盖算法结论，推演与日志均读取此记录，理由可随时修改。记录存于本浏览器，不写入服务端台账。</p>
        </template>
        <p v-else class="cb-empty">左侧选一条走廊。</p>
      </section>

      <!-- 推演模式：六段链路（复用 NationDeduce，逐班独立取数） -->
      <div class="cb-deduce" v-else>
        <NationDeduce :flight="activeFlight" :corridor="active" :minute="minute" :paused="true"
                      :review="active && active.review ? active.review : null"/>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import NationMap from './NationMap.vue'
import NationDeduce from './NationDeduce.vue'

const props = defineProps({
  mode: { type: String, default: 'corridor' },   // corridor | card
  data: { type: Object, default: null },
  flights: { type: Array, default: () => [] },
  minute: { type: Number, default: 0 },
  zoneBands: { type: Object, default: null },
  focusCorridor: { type: String, default: '' },
})
const emit = defineEmits(['select'])

const REVIEW_KEY = 'alc.review.v1'
const REVIEW_OPTS = [
  { key: 'RELEASE', label: '放行', tone: 'ok' },
  { key: 'DETOUR', label: '改绕飞', tone: 'warn' },
  { key: 'HOLD', label: '停飞', tone: 'bad' },
]
const reviews = ref(readReviews())
function readReviews() {
  try { return JSON.parse(localStorage.getItem(REVIEW_KEY) || '{}') || {} } catch (_) { return {} }
}
function persist() {
  try { localStorage.setItem(REVIEW_KEY, JSON.stringify(reviews.value)) } catch (_) {}
}

const query = ref('')
const sortKey = ref('bad')
const pickedId = ref('')

function short(name) {
  return String(name || '').replace(/(维吾尔|壮族|回族|自治区|特别行政区|省|市|地区|自治州|盟)/g, '')
}

// 走廊 + 该走廊当前班次合成一行：列表里要能直接看出"这条线现在是什么状态"。
const rows = computed(() => {
  const byCorr = new Map()
  for (const f of props.flights || []) byCorr.set(f.corridor, f)
  return (props.data?.corridors || []).map((c) => {
    const f = byCorr.get(c.id)
    const review = reviews.value[c.id] || null
    const blocked = !!c.borderBlocked
    const detour = !!c.detour
    const hold = f ? f.decision === 'HOLD' : false
    // 状态列只表示**此刻这一班**怎么样；走廊自身的属性（有没有绕飞方案、是否边界受限）
    // 另起一列。此前两者挤在 statusText 一个词里：走廊有绕飞方案就写「绕飞」，
    // 于是"有绕飞方案但此刻没班次"的行看起来像在飞，点进去只能看到空面板（实测索引 1-7 全是这样）。
    const tone = review ? 'ok' : (!f ? 'quiet' : (hold || blocked ? 'warn' : 'ok'))
    const statusText = review ? reviewLabel(review.action)
      : !f ? '无班次'
      : blocked ? '边界受限' : (f.decisionLabel || (hold ? '延期' : '直飞'))
    const attrText = [
      detour && c.detour && c.detour.shiftKm ? `绕飞方案 +${Math.round(c.detour.shiftKm)} km` : '',
      blocked ? '穿越限制区' : '',
    ].filter(Boolean).join(' · ')
    return {
      id: c.id, fromName: c.fromName, toName: c.toName,
      fromShort: short(c.fromName), toShort: short(c.toName),
      kindLabel: c.kindLabel || c.kind || '—', lengthKm: c.lengthKm,
      detourKm: (c.detour && c.detour.shiftKm) || 0,
      blocked, detour, hold, tone, statusText, attrText,
      flightId: f ? f.id : '', riskP: f ? f.riskP : 0,
      departAt: f ? f.departAt : '', arriveAt: f ? f.arriveAt : '',
      altM: f ? f.altM : null, decision: f ? f.decision : '',
      decisionLabel: f ? f.decisionLabel : '', drivers: f ? f.drivers : [],
      exposureMin: f && f.exposure ? f.exposure.directMin : null,
      review,
    }
  })
})

// 异常优先：停飞(4) > 绕飞(3) > 延期(2) > 风险分；同档按航程降序（长的更值得看）
const sorted = computed(() => {
  const arr = [...rows.value]
  if (sortKey.value === 'id') return arr.sort((a, b) => a.id.localeCompare(b.id))
  return arr.sort((a, b) => score(b) - score(a) || (b.lengthKm || 0) - (a.lengthKm || 0))
})
function score(r) {
  return (r.blocked ? 4 : 0) + (r.detour ? 3 : 0) + (r.hold ? 2 : 0) + (r.riskP || 0)
}
const shown = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return sorted.value
  return sorted.value.filter(r =>
    r.id.toLowerCase().includes(q) || r.fromName.includes(q) || r.toName.includes(q))
})
const anomalyCount = computed(() =>
  rows.value.filter(r => r.blocked || r.detour || r.hold || r.riskP >= 0.35).length)

// 选中的那条：优先用户点过的，其次外部指定（从处置/日志跳进来），最后第一条异常
const activeId = computed(() => {
  const ids = rows.value.map(r => r.id)
  if (pickedId.value && ids.includes(pickedId.value)) return pickedId.value
  if (props.focusCorridor && ids.includes(props.focusCorridor)) return props.focusCorridor
  // 推演页（card）默认落在**此刻有班次**的走廊上：没有班次就没有观测与判据可讲，
  // 落在空走廊上整页只剩一句"先立题"（实测 09:00 的异常榜首就是这样一条）。
  // 走廊页（corridor）仍按异常排序取第一条 —— 那一页讲的是"这条线能不能飞"。
  const first = props.mode === 'card'
    ? (sorted.value.find(r => r.flightId) || sorted.value[0])
    : sorted.value[0]
  return first ? first.id : ''
})
const active = computed(() => rows.value.find(r => r.id === activeId.value) || null)
const activeFlight = computed(() => {
  const id = active.value && active.value.flightId
  return id ? (props.flights || []).find(f => f.id === id) || null : null
})

// 外部跳进来时清掉用户上一次的点选，否则"从日志点这架"会被旧选择顶掉
watch(() => props.focusCorridor, (id) => { if (id) pickedId.value = id })

function pick(row) {
  pickedId.value = row.id
  emit('select', row)
}
const verdictText = computed(() => {
  const r = active.value
  if (!r) return '—'
  if (r.review) return '人工 · ' + reviewLabel(r.review.action)
  if (r.blocked) return '停飞（边界受限）'
  // V1.1.2：缺字段时**不许默认成最松的结论**。原来兜底写"直飞放行"，
  // 于是字段一缺就显示成"可以直接飞"，而且没人看得出这是兜底。
  return r.decisionLabel || (r.hold ? '延期' : '未判定')
})
const altBand = computed(() => {
  const f = activeFlight.value
  return (f && f.clearance && f.clearance.altitudeBand) || '—'
})

// —— 人工裁决 ——
// 草案（还没裁决时先写的理由）与"已存理由"分开：
// 以前点完按钮就把 reason 清空、而且之后改输入框也不会回写 ——
// 于是"先点改绕飞、再补理由"的人，存下来的永远是空理由，日志里写"未填理由"。
const draft = ref('')
const reasonText = computed({
  get() {
    const cur = reviews.value[active.value?.id || '']
    return cur ? (cur.reason || '') : draft.value
  },
  set(v) {
    const id = active.value?.id || ''
    const cur = reviews.value[id]
    if (!cur) { draft.value = v; return }
    // 已有裁决：改理由就地更新，保留原裁决时刻，另记 updatedAt
    reviews.value = { ...reviews.value, [id]: { ...cur, reason: String(v ?? ''), updatedAt: Date.now() } }
    persist()
  },
})
function setReview(action) {
  const r = active.value
  if (!r) return
  const cur = reviews.value[r.id]
  // 连"算法原判"一起存：日志要写"人工改成 X（算法原判 Y）"，两句话必须同源。
  // 重复点同一个动作 = 只补/改理由，不重置裁决时刻。
  const same = cur && cur.action === action
  reviews.value = { ...reviews.value, [r.id]: {
    action,
    reason: same ? (cur.reason || '') : (draft.value.trim() || (cur ? cur.reason : '') || ''),
    at: same ? cur.at : Date.now(),
    // 这一条会作为"算法原判"写进本地裁决记录与日志：兜底值绝不能是"直飞放行"，
    // 否则留痕里会出现一条从未发生过的放行结论。
    auto: cur?.auto || r.decisionLabel || (r.blocked ? '停飞（边界受限）' : '未判定'),
  } }
  draft.value = ''
  persist()
}
function clearReview() {
  const r = active.value
  if (!r) return
  const next = { ...reviews.value }
  delete next[r.id]
  reviews.value = next
  draft.value = ''
  persist()
}
function reviewLabel(action) {
  const hit = REVIEW_OPTS.find(o => o.key === action)
  return hit ? hit.label : action
}
</script>

<style scoped>
.cb { display: grid; grid-template-columns: 246px minmax(0, 1fr); gap: 10px; min-height: 0; height: 100%; }
.cb-list { display: flex; flex-direction: column; gap: 6px; min-height: 0; }
.cb-tools { display: flex; gap: 4px; }
.cb-tools input { flex: 1 1 auto; min-width: 0; background: rgba(10,26,38,.7);
  border: 1px solid rgba(70,110,140,.45); border-radius: 5px; color: #cfe6f5;
  font-size: 11px; padding: 3px 7px; }
.cb-tools button { background: none; border: 1px solid rgba(70,110,140,.45); color: #9dbccf;
  border-radius: 5px; font-size: 10.5px; padding: 3px 7px; cursor: pointer; }
.cb-tools button.on { background: rgba(126,206,255,.16); border-color: rgba(126,206,255,.7); color: #eaf8ff; }
.cb-count { font-size: 10px; color: #6f92a8; }
.cb-rows { list-style: none; margin: 0; padding: 0; overflow: auto; min-height: 0; display: flex; flex-direction: column; gap: 3px; }
.cb-rows li { border: 1px solid rgba(70,110,140,.3); border-left-width: 3px; border-radius: 6px;
  padding: 5px 7px; cursor: pointer; background: rgba(10,26,38,.55); display: flex;
  flex-direction: column; gap: 1px; }
.cb-rows li:hover { background: rgba(22,52,74,.8); }
.cb-rows li.on { border-color: rgba(126,206,255,.75); background: rgba(24,60,84,.9); }
.cb-rows li.bad { border-left-color: #e2563f; }
.cb-rows li.warn { border-left-color: #e0a23f; }
.cb-rows li.ok { border-left-color: #4fae86; }
.cb-rows li.quiet { border-left-color: rgba(120,170,200,.35); }
.cb-rows b { font-size: 11.5px; color: #eaf8ff; font-weight: 600; }
.cb-rows .meta { font-size: 9.5px; color: #7d9cb3; }
.cb-rows em { font-style: normal; font-size: 9.5px; }
.cb-rows em.bad { color: #ff8d78; } .cb-rows em.warn { color: #ffc857; }
.cb-rows em.ok { color: #6fe0a8; } .cb-rows em.quiet { color: #7d9cb3; }
.cb-rows .rv { font-style: normal; font-size: 9px; color: #8ef0ff; }
/* 走廊属性（绕飞方案 / 穿越限制区）：与班次状态分列，避免"有绕飞方案"被读成"在飞" */
.cb-rows .cb-attr { font-style: normal; font-size: 9px; color: #6f92a8;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cb-rows li.empty { cursor: default; color: #6f92a8; font-size: 10.5px; border-left-color: transparent; }

.cb-main { display: flex; flex-direction: column; gap: 8px; min-height: 0; }
.cb-map { position: relative; flex: 1 1 auto; min-height: 380px; border-radius: 8px; overflow: hidden;
  border: 1px solid rgba(70,110,140,.3); }
.cb-map.short { flex: 0 0 auto; height: clamp(260px, 34vh, 460px); min-height: 260px; }
.cb-mapnote { position: absolute; left: 8px; bottom: 6px; margin: 0; font-size: 9.5px;
  color: #7d9cb3; background: rgba(6,18,28,.7); padding: 2px 6px; border-radius: 3px; }

.cb-info { border: 1px solid rgba(70,110,140,.35); border-radius: 8px; padding: 8px 10px;
  background: rgba(10,26,38,.6); display: flex; flex-direction: column; gap: 6px; }
.cb-info header { display: flex; align-items: center; gap: 6px; }
.cb-info header b { font-size: 13px; color: #eaf8ff; }
.cb-info header .arrow { color: #6f92a8; }
.cb-info header .kind { font-style: normal; font-size: 9.5px; color: #7d9cb3;
  border: 1px solid rgba(70,110,140,.45); border-radius: 4px; padding: 0 4px; }
.cb-info header .verd { margin-left: auto; font-size: 10.5px; padding: 1px 7px; border-radius: 999px;
  border: 1px solid rgba(90,150,190,.5); color: #9fc0d6; }
.cb-info header .verd.bad { color: #ff8d78; border-color: rgba(230,90,70,.55); }
.cb-info header .verd.warn { color: #ffc857; border-color: rgba(220,170,60,.5); }
.cb-info header .verd.ok { color: #6fe0a8; border-color: rgba(80,200,140,.5); }
.cb-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px 10px; }
.cb-grid div { display: flex; flex-direction: column; gap: 1px; }
.cb-grid small { font-size: 9.5px; color: #7d9cb3; }
.cb-grid b { font-size: 12px; color: #dfeefb; font-variant-numeric: tabular-nums; }
.cb-why { font-size: 10px; line-height: 1.55; color: #9fc0d6; }
.cb-why.quiet { color: #6f92a8; }
.cb-review { display: flex; align-items: center; gap: 5px; flex-wrap: wrap;
  border-top: 1px dashed rgba(70,110,140,.3); padding-top: 6px; }
.cb-review .lb { font-size: 10px; color: #7d9cb3; }
.cb-review button { background: none; border: 1px solid rgba(70,110,140,.45); color: #9dbccf;
  border-radius: 5px; font-size: 10.5px; padding: 2px 8px; cursor: pointer; }
.cb-review button.on.ok { background: rgba(40,140,95,.2); border-color: #4fae86; color: #6fe0a8; }
.cb-review button.on.warn { background: rgba(180,130,30,.18); border-color: #e0a23f; color: #ffc857; }
.cb-review button.on.bad { background: rgba(190,60,45,.18); border-color: #e2563f; color: #ff8d78; }
.cb-review input { flex: 1 1 120px; min-width: 90px; background: rgba(10,26,38,.7);
  border: 1px solid rgba(70,110,140,.45); border-radius: 5px; color: #cfe6f5; font-size: 10.5px; padding: 2px 6px; }
.cb-review .clr { color: #7d9cb3; }
.cb-rv-note { font-size: 9.5px; color: #8ef0ff; line-height: 1.5; }
.cb-rv-note .rv-scope { font-style: normal; color: #7d9cb3; }
.cb-deduce { flex: 1 1 auto; min-height: 0; display: flex; }
.cb-empty { font-size: 11px; color: #6f92a8; }

/* 浅色 */
html[data-theme="light"] .cb-tools input,
html[data-theme="light"] .cb-review input { background: #fff; border-color: #cfdcea; color: #12314a; }
html[data-theme="light"] .cb-tools button,
html[data-theme="light"] .cb-review button { border-color: #cfdcea; color: #31556f; }
html[data-theme="light"] .cb-tools button.on { background: #e3f0fb; border-color: #9cc7e8; color: #0d4f74; }
html[data-theme="light"] .cb-rows li { background: #fff; border-color: #dbe6f1; }
html[data-theme="light"] .cb-rows li:hover { background: #eef6fd; }
html[data-theme="light"] .cb-rows li.on { background: #e3f0fb; border-color: #9cc7e8; }
html[data-theme="light"] .cb-rows b { color: #0f3550; }
html[data-theme="light"] .cb-rows .meta,
html[data-theme="light"] .cb-count { color: #6b8399; }
html[data-theme="light"] .cb-info { background: #fff; border-color: #dbe6f1; }
html[data-theme="light"] .cb-info header b { color: #0f3550; }
html[data-theme="light"] .cb-grid b { color: #12314a; }
html[data-theme="light"] .cb-grid small,
html[data-theme="light"] .cb-why.quiet { color: #6b8399; }
html[data-theme="light"] .cb-why { color: #4a6a85; }
html[data-theme="light"] .cb-mapnote { background: rgba(255,255,255,.85); color: #5b7a92; }

/* 列表里的状态字与徽标：深色主题用的是"暗底上的亮色"（#ffc857/#ff8d78/#6fe0a8），
   搬到白底上对比度只有 1.3–1.5，必须换成同色系的深色版，而不是沿用。 */
html[data-theme="light"] .cb-rows em.warn { color: #8a5a00; }
html[data-theme="light"] .cb-rows .cb-attr { color: #5b7386; }
html[data-theme="light"] .cb-rows em.bad { color: #a8321f; }
html[data-theme="light"] .cb-rows em.ok { color: #0f7a52; }
html[data-theme="light"] .cb-rows em.quiet { color: #5b7a92; }
html[data-theme="light"] .cb-rows .rv { color: #0b6b7d; }
html[data-theme="light"] .cb-rows li.empty { color: #5b7a92; }
html[data-theme="light"] .cb-info header .arrow,
html[data-theme="light"] .cb-info header .kind { color: #5b7a92; border-color: #cfdcea; }
html[data-theme="light"] .cb-info header .verd { color: #31556f; border-color: #b9cfe2; }
html[data-theme="light"] .cb-info header .verd.warn { color: #8a5a00; border-color: #e0bd74; }
html[data-theme="light"] .cb-info header .verd.bad { color: #a8321f; border-color: #e3a596; }
html[data-theme="light"] .cb-info header .verd.ok { color: #0f7a52; border-color: #8ecbb0; }
html[data-theme="light"] .cb-review .lb { color: #4a6a85; }
html[data-theme="light"] .cb-review button { color: #31556f; border-color: #cfdcea; }
html[data-theme="light"] .cb-review button.on.ok { background: #e6f6ee; border-color: #7cc4a4; color: #0f7a52; }
html[data-theme="light"] .cb-review button.on.warn { background: #fdf3de; border-color: #dfb96b; color: #8a5a00; }
html[data-theme="light"] .cb-review button.on.bad { background: #fbeae6; border-color: #dd9a89; color: #a8321f; }
html[data-theme="light"] .cb-review .clr { color: #5b7a92; }
html[data-theme="light"] .cb-rv-note { color: #0b6b7d; }
html[data-theme="light"] .cb-rv-note .rv-scope { color: #5b7a92; }
html[data-theme="light"] .cb-empty { color: #5b7a92; }
</style>
