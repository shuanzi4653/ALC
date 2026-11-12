<template>
  <!-- 行内 flex 而不是靠类：父组件的 `.nrn-side>*{flex:0 0 auto}` 带了两个 scope 属性，
       同特异性时谁后加载谁生效（实测压不住），于是板子按内容高度撑破侧栏、盖住下面的卡片。 -->
  <div class="dd" data-deduce-board :style="{ flex: '1 1 auto', minHeight: 0 }">
    <!-- 没有班次可推：区分「没选」与「选了但这条走廊此刻没班次」。
         此前两种情况共用一句"先立题"，点了一条只有绕飞方案、没有在飞班次的走廊时，
         读者会以为是自己没选中。 -->
    <div v-if="!flight" class="dd-empty" data-deduce-empty>
      <b>{{ corridor ? '该走廊此刻没有在飞班次' : '等待选择班次' }}</b>
      <p v-if="corridor">
        {{ short(corridor.fromName) }} → {{ short(corridor.toName) }}（{{ corridor.id }}）在当前时刻没有班次<template
          v-if="corridor.attrText">；走廊属性：{{ corridor.attrText }}</template>。
        <template v-if="corridor.statusText && corridor.statusText !== '无班次'">它的班次状态是「{{ corridor.statusText }}」。</template>
      </p>
      <p v-else>请在地图或左侧列表中选择一个班次，本页给出该班次的观测、判据、概率与处置代价。</p>
      <p class="quiet">推演按「这一班、这一分钟」取数。换一条有班次的走廊，或把时间轴移到该走廊有班的时刻。</p>
    </div>

    <template v-else>
      <header class="dd-head">
        <div>
          <b>{{ flight.callsign }}</b>
          <code>{{ flight.id }}</code>
        </div>
        <span class="dd-verd" :class="tone">
          <template v-if="review">人工 · {{ reviewText }}</template>
          <template v-else>{{ data?.flight?.decisionLabel || flight.decisionLabel }}</template>
        </span>
      </header>
      <p class="dd-sub">
        {{ short(flight.fromName) }} → {{ short(flight.toName) }}
        <span v-if="data">· 风险 {{ num(data.flight.riskP, 2) }}（{{ data.flight.riskLevelLabel }}）</span>
      </p>

      <p v-if="busy" class="dd-state">正在按这一架重算链路…</p>
      <p v-else-if="err" class="dd-state bad">链路取不到 · {{ err }}<button @click="load">重试</button></p>

      <template v-else-if="data">
        <!-- 八段各自折叠：折叠态留一行关键值，展开才铺图与表 -->
        <div class="dd-tools" data-deduce-tools>
          <button type="button" @click="forceAll(1)">全部展开</button>
          <button type="button" @click="forceAll(-1)">全部折叠</button>
          <span>共八段 · 点标题折叠或展开</span>
        </div>

        <!-- ① 观测 -->
        <DeduceSection name="observe" no="1" title="观测" tag="PUBLIC"
                       :summary="sumObserve" :default-open="true" :force="forceSeq" :force-dir="forceDir">
          <BarThreshold :rows="visChartRows" title="端点能见度与阈值" unit="虚线＝判据阈值 5 km"
                        aria="两端机场能见度与阈值对照" />
          <table class="dd-tbl" data-tbl="stations">
            <thead><tr><th>站</th><th>能见度</th><th>风</th><th>本班次中的作用</th></tr></thead>
            <tbody>
              <tr>
                <td>{{ short(data.observed.fromName) }}</td>
                <td>{{ data.observed.fromVis || '无实况' }}</td>
                <td>{{ data.observed.fromWind == null ? '—' : data.observed.fromWind + ' m/s' }}</td>
                <td>起点</td>
              </tr>
              <tr>
                <td>{{ short(data.observed.toName) }}</td>
                <td>{{ data.observed.toVis || '无实况' }}</td>
                <td>{{ data.observed.toWind == null ? '—' : data.observed.toWind + ' m/s' }}</td>
                <td>终点</td>
              </tr>
            </tbody>
          </table>
          <p class="dd-line">
            <span>端点风速</span><b>{{ windText }}</b>
            <span class="src" :class="data.observed.radarOk ? 'ok' : 'absent'">
              {{ data.observed.radarOk ? '回波可用' : '回波不可用' }}
            </span>
          </p>
          <p class="dd-echo" :class="{ hit: data.observed.hasDetour }">
            {{ data.observed.echo }}
            <template v-if="data.observed.echoTs"><em>· {{ clock(data.observed.echoTs) }}</em></template>
          </p>
        </DeduceSection>

        <!-- ② 判据 -->
        <DeduceSection name="criteria" no="2" title="判据" tag="RULE"
                       :summary="sumCriteria" :force="forceSeq" :force-dir="forceDir"
                       :tone="passCount === (data.criteria || []).length ? 'ok' : 'bad'">
          <BarThreshold :rows="criteriaRows" title="各判据的实测值与阈值" unit="条长＝实测占阈值的比例，越过 100% 即不通过"
                        aria="各判据实测值与阈值对照" />
          <table class="dd-tbl" data-tbl="criteria">
            <thead><tr><th>判据</th><th>阈值</th><th>实测</th><th>结论</th></tr></thead>
            <tbody>
              <tr v-for="c in data.criteria" :key="c.key" :class="{ bad: !c.pass }">
                <td>{{ c.label }}</td>
                <td>{{ thresholdText(c) }}</td>
                <td>{{ c.display }}</td>
                <td>{{ c.pass ? '通过' : '不通过' }}</td>
              </tr>
              <tr v-if="!(data.criteria || []).length"><td colspan="4">该班次无此项</td></tr>
            </tbody>
          </table>
        </DeduceSection>

        <!-- ③ 概率与裁决 -->
        <DeduceSection name="verdict" no="3" title="概率与裁决" tag="DERIVED"
                       :summary="sumVerdict" :force="forceSeq" :force-dir="forceDir" :tone="tone">
          <Gauge :p="data.flight.riskP || 0" title="不可飞概率落在哪一档" unit="阈值由后端单一常量给出"
                 aria="不可飞概率与三档区间" />
          <p class="dd-verd-line">裁决：<b :class="tone">{{ data.flight.decisionLabel }}</b></p>
          <ul class="dd-drivers" v-if="(drivers || []).length">
            <li v-for="(text, i) in drivers" :key="'d' + i">{{ text }}</li>
          </ul>
          <p v-else class="dd-line quiet">本班次无触发项（依据为空＝没有任何阈值被越过，不是「没算」）</p>
        </DeduceSection>

        <!-- ④ 反事实 -->
        <DeduceSection name="counter" no="4" title="反事实" tag="DERIVED"
                       :summary="sumCounter" :force="forceSeq" :force-dir="forceDir">
          <div class="dd-cf">
            <span>不绕飞暴露</span>
            <span class="track"><i :style="{ width: expPct(data.observed.exposureDirect) + '%' }"></i></span>
            <b>{{ num(data.observed.exposureDirect, 1) }} 分</b>
          </div>
          <div class="dd-cf">
            <span>绕飞后暴露</span>
            <span class="track"><i class="good" :style="{ width: expPct(data.observed.exposureDetour) + '%' }"></i></span>
            <b>{{ num(data.observed.exposureDetour, 1) }} 分</b>
          </div>
          <table class="dd-tbl" data-tbl="counter">
            <thead><tr><th>方案</th><th>暴露时长</th><th>差值</th></tr></thead>
            <tbody>
              <tr><td>不绕飞（直飞）</td><td>{{ num(data.observed.exposureDirect, 1) }} 分</td><td>基准</td></tr>
              <tr><td>绕飞</td><td>{{ num(data.observed.exposureDetour, 1) }} 分</td>
                <td>{{ exposureGain }}</td></tr>
            </tbody>
          </table>
          <p class="dd-line quiet" v-if="!bothExposureZero">两行是同一架、同一分钟下的两个反事实：不绕会暴露多久，绕了还剩多久。</p>
          <p class="dd-line quiet" v-else>两行都是 0：本帧航路没有压上强回波，不存在「不绕」这个选项。这是结论，不是缺数据。</p>
        </DeduceSection>

        <!-- ⑤ 期望损失 -->
        <DeduceSection name="loss" no="5" title="期望损失" tag="三方案"
                       :summary="sumLoss" :force="forceSeq" :force-dir="forceDir">
          <OptionBars :rows="lossRows" title="三个方案的期望代价" unit="条越短越好；推荐项标绿"
                      aria="三个处置方案的期望代价对比" />
          <p class="dd-formula">{{ data.expectedLoss.formula }}</p>
          <table class="dd-tbl" data-tbl="coefficients">
            <thead><tr><th>项</th><th>系数</th><th>说明</th></tr></thead>
            <tbody>
              <tr><td>风险</td><td>1.0</td><td>概率 × 事故代价</td></tr>
              <tr><td>时间</td><td>0.6 / 小时</td><td>延期按推迟 60 分钟计，不假设天气会好转</td></tr>
              <tr><td>里程</td><td>0.02 / km</td><td>绕飞带来的额外航程</td></tr>
              <tr><td>取消</td><td>固定项</td><td>兜底项，不参与最优比较</td></tr>
            </tbody>
          </table>
        </DeduceSection>

        <!-- ⑥ 结论与边界 -->
        <DeduceSection name="conclusion" no="6" title="结论与边界" tag="OFFICIAL"
                       :summary="sumConclusion" :force="forceSeq" :force-dir="forceDir" :tone="tone">
          <Timeline :points="timelinePoints" title="本班次的时刻轴" unit="申请 / 计划 / 实际 / 当前"
                    aria="班次申请、计划、实际与当前时刻" />
          <p class="dd-concl">{{ finalConclusion }}</p>
          <p class="dd-rv" v-if="review">
            这条人工裁决写在「{{ flight.id }}」上，走廊页、推演页与日志同步同一份记录。
          </p>
          <p class="dd-disc">{{ data.discipline }}</p>
          <p class="dd-line quiet" v-if="data.generatedAt">生成于 {{ clock(data.generatedAt) }} · 第 {{ data.minute }} 分钟</p>
        </DeduceSection>

        <!-- ⑦ 网络层对照：同一帧、同一规则，移除模型层 -->
        <DeduceSection name="compare" no="7" title="网络层对照" tag="A/B"
                       :summary="sumCompare" :force="forceSeq" :force-dir="forceDir">
          <CounterfactualPanel :minute="minute" />
        </DeduceSection>

        <!-- ⑧ 分歧台账：人与算法不一致的逐条记录 -->
        <DeduceSection name="ledger" no="8" title="分歧台账" tag="人工"
                       :summary="sumLedger" :force="forceSeq" :force-dir="forceDir">
          <DivergencePanel compact :focus-corridor="data.corridorId" />
        </DeduceSection>
      </template>
    </template>
  </div>
</template>


<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import DeduceSection from './DeduceSection.vue'
import CounterfactualPanel from './CounterfactualPanel.vue'
import DivergencePanel from './DivergencePanel.vue'
import BarThreshold from '../charts/BarThreshold.vue'
import Gauge from '../charts/Gauge.vue'
import OptionBars from '../charts/OptionBars.vue'
import Timeline from '../charts/Timeline.vue'

const props = defineProps({
  flight: { type: Object, default: null },
  // 当前所在走廊（走廊行对象）：没有班次时用它把"没有班次"和"没有选中"分开
  corridor: { type: Object, default: null },
  minute: { type: Number, default: 0 },
  paused: { type: Boolean, default: true },
  // 人工裁决（走廊页记录的那一条）。有它就以它为准：
  // 日志写什么、推演结论就写什么 —— 两处读同一份，不许各说各话。
  review: { type: Object, default: null },
})

const data = ref(null)
const busy = ref(false)
const err = ref('')
let seq = 0

// 只在这一架 / 这一分钟（且已暂停）时重算。
// 播放中不按秒重算：证据链要拉气象与回波，一秒一次会把后端当成轮询靶子；
// 而推演是"看一眼这一架为什么这样裁决"，暂停在某一分钟才是它真实的用法。
function key() {
  const id = props.flight?.id || ''
  return id + '|' + (props.paused ? props.minute : 'run')
}

async function load() {
  const f = props.flight
  if (!f) { data.value = null; return }
  const my = ++seq
  busy.value = true
  err.value = ''
  try {
    const res = await fetch(
      `/api/traffic/v2/nation/evidence?flight=${encodeURIComponent(f.id)}&minute=${Math.round(props.minute)}`,
      { headers: { Accept: 'application/json' } },
    )
    if (!res.ok) throw new Error('HTTP ' + res.status)
    const body = await res.json()
    if (my !== seq) return            // 已经切到别的班次，丢弃这次的迟到结果
    if (body.status !== 'OK') {
      data.value = null
      err.value = body.note || body.status || '该班次此刻不在飞'
      return
    }
    data.value = body
  } catch (e) {
    if (my === seq) { err.value = e.message || String(e); data.value = null }
  } finally {
    if (my === seq) busy.value = false
  }
}

let timer = null
watch(key, () => {
  if (timer) clearTimeout(timer)
  timer = setTimeout(load, 260)     // 切班次时连续两次变更只发一次请求
}, { immediate: true })
onUnmounted(() => { if (timer) clearTimeout(timer) })

const drivers = computed(() => props.flight?.drivers || [])
const REVIEW_LABEL = { RELEASE: '放行', DETOUR: '改绕飞', HOLD: '停飞' }
const reviewText = computed(() => {
  const r = props.review
  if (!r) return ''
  return REVIEW_LABEL[r.action] || r.action
})
const tone = computed(() => {
  if (props.review) return props.review.action === 'HOLD' ? 'bad' : (props.review.action === 'DETOUR' ? 'warn' : 'good')
  const lv = props.flight?.riskLevel
  return lv === 'HIGH' ? 'bad' : (lv === 'MEDIUM' ? 'warn' : 'good')
})
// 结论句：有人工裁决就照人工的写，并且把"算法怎么判"留在后面 ——
// 两句话都在，读者才知道是谁改的、改成了什么。
const finalConclusion = computed(() => {
  const auto = data.value?.conclusion || ''
  const r = props.review
  if (!r) return auto
  return `人工裁决：${reviewText.value}${r.reason ? '（' + r.reason + '）' : ''}；算法原判 ${auto}`
})
const passCount = computed(() => (data.value?.criteria || []).filter(c => c.pass).length)
const bothExposureZero = computed(() => {
  const o = data.value?.observed
  return !!o && !o.exposureDirect && !o.exposureDetour
})

// 能见度条：以 10 km 为满格（专业上的"很好"），阈值 5 km 画一根竖线。
// 不用"实测/阈值"做比例 —— 那样 48 km 和 58 km 都顶到 100%，看不出差别。
const visRows = computed(() => {
  const o = data.value?.observed
  if (!o) return []
  const floor = 5 // km
  return [
    { name: o.fromName, text: o.fromVis || '无实况', ...band(o.fromVis) },
    { name: o.toName, text: o.toVis || '无实况', ...band(o.toVis) },
  ]
  function band(text) {
    const m = /([\d.]+)/.exec(String(text || ''))
    const km = m ? parseFloat(m[1]) : null
    const pct = km == null ? 0 : Math.min(100, (km / 10) * 100)
    return { pct, thresholdPct: (floor / 10) * 100, low: km != null && km < floor }
  }
})
const windText = computed(() => {
  const o = data.value?.observed || {}
  const a = o.fromWind, b = o.toWind
  if (a == null && b == null) return '无实况'
  return `${a == null ? '—' : a} / ${b == null ? '—' : b} m/s`
})

const options = computed(() => data.value?.expectedLoss?.options || [])

// ── 折叠：批量展开/折叠用"计数 + 方向"，连续两次同向点击也能触发 ──
const forceSeq = ref(0)
const forceDir = ref(1)
function forceAll(dir) { forceDir.value = dir; forceSeq.value += 1 }

// ── 段 1：能见度图（数值统一折算成 km，缺测按 0 画、文本写"无实况"） ──
const visChartRows = computed(() => {
  const o = data.value?.observed
  if (!o) return []
  const mk = (name, text) => {
    const m = /([\d.]+)\s*(km|m)?/.exec(String(text || ''))
    let km = null
    if (m) { const v = parseFloat(m[1]); km = m[2] === 'm' ? v / 1000 : v }
    return { label: short(name), value: km == null ? 0 : km, threshold: 5,
             display: text || '无实况', fail: km != null && km < 5 }
  }
  return [mk(o.fromName, o.fromVis), mk(o.toName, o.toVis)]
})

// ── 段 2：判据图（条长＝实测占阈值的比例，阈值线固定在 100%） ──
const criteriaRows = computed(() => (data.value?.criteria || []).map((c) => ({
  label: c.label,
  value: Math.round((c.ratio || 0) * 100),
  threshold: 100,
  display: c.display,
  fail: !c.pass,
})))

// ── 段 5：三方案代价 ──
const lossRows = computed(() => (options.value || []).map((o) => ({
  label: o.label,
  cost: o.cost || 0,
  display: o.available === false ? '不可用' : num(o.cost, 2),
  parts: `风险 ${num(o.riskP, 2)} · 时间 ${num(o.delayMin, 0)} 分 · 增量 ${num(o.extraKm, 0)} km`,
  recommended: !!o.recommended,
  available: o.available !== false,
})))

// ── 段 6：时刻轴 ──
const timelinePoints = computed(() => {
  const f = props.flight || {}
  const out = []
  const push = (label, iso, kind) => {
    const m = /(\d{2}):(\d{2})/.exec(String(iso || ''))
    if (!m) return
    out.push({ label, minute: (+m[1]) * 60 + (+m[2]), text: `${m[1]}:${m[2]}`, kind })
  }
  push('申请', f.requestAt, 'request')
  push('计划', f.planAt, 'planned')
  push('实际', f.actualAt, 'actual')
  if (typeof props.minute === 'number') {
    const h = String(Math.floor(props.minute / 60)).padStart(2, '0')
    const mm = String(props.minute % 60).padStart(2, '0')
    out.push({ label: '当前', minute: props.minute, text: `${h}:${mm}`, kind: 'now' })
  }
  return out
})

// ── 折叠态的一行摘要：折叠不等于"没了"，读者要能一眼看到这一段判成什么 ──
const sumObserve = computed(() => {
  const o = data.value?.observed
  if (!o) return ''
  const a = o.fromVis || '无实况'
  const b = o.toVis || '无实况'
  return `${short(o.fromName)} ${a} · ${short(o.toName)} ${b}${o.radarOk ? '' : ' · 回波不可用'}`
})
const sumCriteria = computed(() => `${passCount.value}/${(data.value?.criteria || []).length} 通过`)
const sumVerdict = computed(() => {
  const f = data.value?.flight
  return f ? `${f.decisionLabel} · 概率 ${num(f.riskP, 2)}（${f.riskLevelLabel}）` : ''
})
const exposureGain = computed(() => {
  const o = data.value?.observed
  if (!o) return '—'
  const d = (o.exposureDirect || 0) - (o.exposureDetour || 0)
  if (d > 0) return `少 ${d.toFixed(1)} 分`
  if (d < 0) return `多 ${Math.abs(d).toFixed(1)} 分`
  return '无变化'
})
const sumCounter = computed(() => {
  const o = data.value?.observed
  if (!o) return ''
  return `暴露 ${num(o.exposureDirect, 1)} → ${num(o.exposureDetour, 1)} 分`
})
const sumLoss = computed(() => {
  const r = (options.value || []).find((o) => o.recommended)
  return r ? `推荐 ${r.label} · 代价 ${num(r.cost, 2)}` : '无推荐项'
})
const sumConclusion = computed(() => (finalConclusion.value || '').slice(0, 46))
const sumCompare = computed(() => '同一帧移除模型层后的差异，展开读取')
const sumLedger = computed(() => '人与算法判定不一致的逐条记录，展开读取')

const maxCost = computed(() => Math.max(0.01, ...options.value.map(o => o.cost || 0)))
function costPct(opt) {
  // 不可用方案不参与比较：画成一根灰条，否则它会被误读成"最便宜"
  if (!opt.available) return 6
  return Math.max(4, (opt.cost / maxCost.value) * 100)
}
function expPct(v) {
  const max = Math.max(1, data.value?.observed?.exposureDirect || 1)
  return Math.min(100, ((v || 0) / max) * 100)
}

function thresholdText(c) {
  if (c.key === 'vis') return '≥ ' + c.threshold + ' km'
  if (c.key === 'wind') return '< ' + c.threshold + ' m/s'
  if (c.key === 'echo') return '= 0 km'
  if (c.key === 'pmodel') return '< ' + Math.round(c.threshold * 100) + '%'
  return '< ' + c.threshold
}
function num(v, d = 1) {
  return (v == null || Number.isNaN(Number(v))) ? '—' : Number(v).toFixed(d)
}
function short(name) {
  return String(name || '').replace(/(维吾尔|壮族|回族|自治区|特别行政区|省|市|地区|自治州)/g, '') || '—'
}
function clock(iso) {
  const m = /T(\d{2}:\d{2})/.exec(String(iso || ''))
  return m ? m[1] + 'Z' : String(iso || '')
}
</script>

<style scoped>
.dd{display:flex;flex-direction:column;gap:7px;min-height:0;overflow:auto;padding-right:2px}
/* 侧栏的通用规则是 `.nrn-side>*{flex:0 0 auto}`（每块按内容高度），
   但推演板内容比一屏高：不改成可收缩，它会把侧栏撑破、压到下面的详情卡上。 */
/* 特异性要和父组件的 `.nrn-side>*`（带两个 scope 属性）打平还要高一点，
   否则谁后加载谁生效 —— 实测父组件的 0 0 auto 赢，板子照样撑破侧栏。
   别写 `:global(.nrn-side)`：当前 Vue 编译会把 `:global()` 之后的复合选择器整段丢掉，
   规则变成只作用于 <html>，等于没写。作用域属性只加在最后一个复合选择器（.dd）上，
   祖先 `.nrn-side` 不需要它，所以直接写普通后代选择器即可。 */
.nrn-side>.dd.dd{flex:1 1 auto;min-height:0}
.dd-head{display:flex;align-items:center;gap:8px}
.dd-head b{font-size:14px;letter-spacing:.3px;color:#eaf8ff}
.dd-head code{font-size:10.5px;color:#6f92a8;margin-left:6px}
.dd-verd{margin-left:auto;font-size:11px;padding:2px 8px;border-radius:999px;
  border:1px solid rgba(90,150,190,.5);color:#9fc0d6}
.dd-verd.good{color:#6fe0a8;border-color:rgba(80,200,140,.5);background:rgba(40,140,95,.12)}
.dd-verd.warn{color:#ffc857;border-color:rgba(220,170,60,.5);background:rgba(180,130,30,.12)}
.dd-verd.bad{color:#ff8d78;border-color:rgba(230,90,70,.55);background:rgba(190,60,45,.14)}
.dd-sub{font-size:11px;color:#8fb2c8;margin-top:-3px}
.dd-empty b{display:block;font-size:12.5px;color:#dfeefb;margin-bottom:4px}
.dd-empty p{font-size:11px;line-height:1.65;color:#8fb2c8}
.dd-empty p.quiet{color:#6f92a8;margin-top:4px}
.dd-state{font-size:11px;color:#8fb2c8}
.dd-state.bad{color:#ff9c86}
.dd-state button{margin-left:6px;background:none;border:1px solid #2c4a60;color:#9dbccf;
  border-radius:5px;padding:1px 7px;font-size:10.5px;cursor:pointer}

/* 每一段：左侧数字徽标 + 标题 + 来源标签，段间用一根竖线串起来 */
.dd-seg{position:relative;border:1px solid rgba(70,110,140,.34);border-radius:8px;
  background:rgba(10,26,38,.6);padding:7px 9px 8px 9px;display:flex;flex-direction:column;gap:5px}
.dd-seg h4{display:flex;align-items:center;gap:6px;font-size:11.5px;font-weight:600;color:#cfe6f5}
.dd-seg h4 i{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;
  border-radius:50%;background:rgba(126,206,255,.16);color:#8ef0ff;font-size:9.5px;
  font-style:normal;flex:0 0 auto}
.dd-seg h4 em{margin-left:auto;font-style:normal;font-size:9.5px;letter-spacing:.4px;
  color:#6f92a8;text-transform:uppercase}

/* ① 观测 */
.dd-vis{display:grid;grid-template-columns:52px minmax(0,1fr) 58px;align-items:center;gap:6px}
.dd-vis .nm,.dd-cf span:first-child{font-size:10.5px;color:#9fc0d6;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.dd-vis b,.dd-cf b{font-size:10.5px;color:#dfeefb;text-align:right;font-variant-numeric:tabular-nums}
.dd-vis b.low{color:#ff9c86}
.track{position:relative;display:block;height:5px;border-radius:3px;background:rgba(120,170,200,.16)}
.track .fill{position:absolute;inset:0 auto 0 0;border-radius:3px;background:linear-gradient(90deg,#3f8fb8,#7fd6ff)}
.track .fill.low{background:linear-gradient(90deg,#b8452f,#ff8d78)}
.track .mark{position:absolute;top:-2px;bottom:-2px;width:1px;background:rgba(255,200,90,.75)}
.dd-line{display:flex;align-items:center;gap:7px;font-size:10.5px;color:#8fb2c8}
.dd-line b{color:#dfeefb;font-variant-numeric:tabular-nums}
.dd-line .src{margin-left:auto;font-size:9.5px;padding:1px 5px;border-radius:4px}
.dd-line .src.ok{color:#6fe0a8;background:rgba(40,140,95,.14)}
.dd-line .src.absent{color:#ff9c86;background:rgba(190,60,45,.14)}
/* 说明段落必须走 block：.dd-line 是 flex，混排的文字节点会被拆成一个个 flex item，
   "且 <b>不假设</b> 天气会好转" 会被拆成三列竖排（实测）。 */
.dd-line.quiet{display:block}
.dd-line.quiet,.dd-formula{color:#6f92a8;font-size:10px;line-height:1.55}
.dd-echo{font-size:10.5px;color:#bcd6e8}
.dd-echo.hit{color:#ffc857}
.dd-echo em{font-style:normal;color:#6f92a8;font-size:9.5px}

/* ② 判据 */
.dd-crit{display:flex;flex-direction:column;gap:3px;padding:5px 0;border-top:1px dashed rgba(70,110,140,.22)}
.dd-crit:first-of-type{border-top:none;padding-top:0}
.dd-crit .row{display:flex;align-items:center;gap:6px;font-size:10.5px}
.dd-crit .flag{width:12px;color:#6fe0a8;font-weight:700}
.dd-crit.fail .flag{color:#ff7a63}
.dd-crit .lb{color:#9fc0d6;flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dd-crit b{color:#dfeefb;font-variant-numeric:tabular-nums}
.dd-crit .bar{position:relative;height:4px;border-radius:2px;background:rgba(120,170,200,.14)}
.dd-crit .bar i{position:absolute;inset:0 auto 0 0;border-radius:2px;background:#5aa8cf}
.dd-crit .bar i.fail{background:#e2603f}
.dd-crit .th{font-size:9.5px;color:#6f92a8;flex:0 0 auto;white-space:nowrap}
.dd-crit .note{font-size:9.5px;color:#6f92a8}

/* ③ 概率与裁决 */
.dd-risk{display:grid;grid-template-columns:44px minmax(0,1fr);align-items:center;gap:8px}
.dd-risk> b{font-size:19px;line-height:1;font-variant-numeric:tabular-nums}
.dd-risk> b.good{color:#6fe0a8}.dd-risk> b.warn{color:#ffc857}.dd-risk> b.bad{color:#ff7a63}
.meter{position:relative;height:8px;border-radius:4px;background:rgba(120,170,200,.16);overflow:hidden}
.meter .zone{position:absolute;top:0;bottom:0}
.meter .zone.watch{left:35%;width:40%;background:rgba(220,170,60,.20)}
.meter .zone.hold{left:75%;right:0;background:rgba(220,70,50,.24)}
.meter .needle{position:absolute;top:-2px;bottom:-2px;width:2px;background:#eaf8ff;
  box-shadow:0 0 5px rgba(255,255,255,.7)}
.dd-risk .scale{grid-column:2;display:flex;justify-content:space-between;font-size:9px;color:#6f92a8}
.dd-verd-line{font-size:11px;color:#9fc0d6}
.dd-verd-line b{font-size:12px}
.dd-verd-line b.good{color:#6fe0a8}.dd-verd-line b.warn{color:#ffc857}.dd-verd-line b.bad{color:#ff7a63}
.dd-drivers{margin:0;padding-left:14px;font-size:10px;color:#8fb2c8;line-height:1.6}
.dd-drivers li::marker{color:#5f8299}

/* ④ 反事实 */
.dd-cf{display:grid;grid-template-columns:66px minmax(0,1fr) 54px;align-items:center;gap:6px}
.dd-cf .track i{position:absolute;inset:0 auto 0 0;border-radius:3px;background:#e2603f}
.dd-cf .track i.good{background:#4fae86}

/* ⑤ 期望损失 */
.dd-opt{display:flex;flex-direction:column;gap:3px;padding:3px 0;border-top:1px dashed rgba(70,110,140,.22)}
.dd-opt:first-of-type{border-top:none}
.dd-opt .row{display:flex;align-items:center;gap:6px;font-size:10.5px}
.dd-opt .lb{color:#9fc0d6;flex:1 1 auto}
.dd-opt b{color:#dfeefb;font-variant-numeric:tabular-nums}
.dd-opt .badge{font-size:9px;padding:1px 5px;border-radius:4px;color:#0a1a26;
  background:#8ef0ff;font-weight:700}
.dd-opt .bar{height:5px;border-radius:3px;background:rgba(120,170,200,.14);overflow:hidden}
.dd-opt .bar i{display:block;height:100%;border-radius:3px;background:#4a90b8}
.dd-opt.best .bar i{background:linear-gradient(90deg,#3f9fb0,#8ef0ff)}
.dd-opt.off .bar i{background:rgba(120,170,200,.28)}
.dd-opt.off .lb,.dd-opt.off b{color:#6f92a8}
.dd-opt .parts{font-size:9.5px;color:#7d9cb3;font-variant-numeric:tabular-nums}
.dd-opt .note{font-size:9.5px;color:#6f92a8}
.dd-formula{font-family:ui-monospace,Consolas,monospace;font-size:9.5px;color:#7d9cb3;
  background:rgba(120,170,200,.08);border-radius:4px;padding:3px 6px}

/* ⑥ 结论 */
.dd-concl{font-size:11px;line-height:1.6;color:#dfeefb}
.dd-rv{font-size:10px;line-height:1.55;color:#8ef0ff}
html[data-theme="light"] .dd-rv{color:#0b7ea6}
.dd-disc{font-size:9.5px;line-height:1.55;color:#6f92a8;border-left:2px solid rgba(120,170,200,.3);
  padding-left:6px}

/* ---------- 浅色 ---------- */
html[data-theme="light"] .dd-head b{color:#0f3550}
html[data-theme="light"] .dd-head code{color:#7d97ad}
html[data-theme="light"] .dd-seg{background:#ffffff;border-color:#dbe6f1}
html[data-theme="light"] .dd-seg h4{color:#12314a}
html[data-theme="light"] .dd-seg h4 i{background:rgba(11,126,166,.12);color:#0b7ea6}
html[data-theme="light"] .dd-seg h4 em{color:#7d97ad}
html[data-theme="light"] .dd-sub{color:#5b7a92}
html[data-theme="light"] .dd-vis .nm,html[data-theme="light"] .dd-crit .lb,
html[data-theme="light"] .dd-line,html[data-theme="light"] .dd-opt .lb{color:#5b7a92}
html[data-theme="light"] .dd-vis b,html[data-theme="light"] .dd-line b,
html[data-theme="light"] .dd-crit b,html[data-theme="light"] .dd-opt b,
html[data-theme="light"] .dd-cf b{color:#12314a}
html[data-theme="light"] .dd-echo{color:#3f5c76}
html[data-theme="light"] .dd-echo.hit{color:#a4610a}
html[data-theme="light"] .track,html[data-theme="light"] .dd-crit .bar,
html[data-theme="light"] .meter,html[data-theme="light"] .dd-opt .bar{background:rgba(60,100,140,.14)}
html[data-theme="light"] .track .fill{background:linear-gradient(90deg,#3f8fb8,#2a8fc0)}
html[data-theme="light"] .dd-crit .bar i{background:#2a6f9e}
html[data-theme="light"] .dd-opt .bar i{background:#4a8cb0}
html[data-theme="light"] .dd-opt.best .bar i{background:linear-gradient(90deg,#0b7ea6,#3aa8c4)}
html[data-theme="light"] .meter .needle{background:#12314a;box-shadow:0 0 4px rgba(20,50,80,.5)}
html[data-theme="light"] .dd-verd-line,html[data-theme="light"] .dd-drivers{color:#4a6a85}
html[data-theme="light"] .dd-concl{color:#12314a}
html[data-theme="light"] .dd-disc,html[data-theme="light"] .dd-line.quiet,
html[data-theme="light"] .dd-formula,html[data-theme="light"] .dd-opt .parts{color:#6b8399}
html[data-theme="light"] .dd-formula{background:rgba(60,100,140,.07)}
html[data-theme="light"] .dd-verd{border-color:#cfdcea;color:#31556f}
html[data-theme="light"] .dd-empty p{color:#5b7a92}
html[data-theme="light"] .dd-empty p.quiet{color:#6b8399}

/* 折叠工具栏与段内表格 */
.dd-tools{display:flex;align-items:center;gap:6px;margin:1px 0 5px 0}
.dd-tools button{background:none;border:1px solid rgba(90,150,190,.45);color:#9dbccf;
  border-radius:4px;padding:1px 7px;font-size:10px;cursor:pointer}
.dd-tools button:hover{background:rgba(30,70,100,.5)}
.dd-tools span{font-size:9.5px;color:#6f92a8;margin-left:auto}
.dd-tbl{width:100%;border-collapse:collapse;font-size:10px;margin:3px 0 5px 0}
.dd-tbl th{text-align:left;font-weight:600;color:#8fb2c8;padding:2px 4px;
  border-bottom:1px solid rgba(70,110,140,.45)}
.dd-tbl td{padding:2px 4px;color:#cfe0ec;border-bottom:1px solid rgba(70,110,140,.18)}
.dd-tbl tr.bad td{color:#ff8d78}
.dd-tbl tr:last-child td{border-bottom:0}
.dd-empty b{display:block;font-size:12.5px;color:#dfeefb;margin-bottom:4px}
.dd-empty p{font-size:11px;line-height:1.65;color:#8fb2c8}
.dd-empty p.quiet{color:#6f92a8;margin-top:4px}
html[data-theme="light"] .dd-tools button{color:#3d637d;border-color:#c9dced}
html[data-theme="light"] .dd-tools button:hover{background:#eef5fb}
html[data-theme="light"] .dd-tools span{color:#5b7386}
html[data-theme="light"] .dd-tbl th{color:#40607a;border-bottom-color:#c9dced}
html[data-theme="light"] .dd-tbl td{color:#17364d;border-bottom-color:#e6eef6}
html[data-theme="light"] .dd-tbl tr.bad td{color:#a8321f}
html[data-theme="light"] .dd-empty b{color:#12395c}
html[data-theme="light"] .dd-empty p{color:#40607a}
</style>
