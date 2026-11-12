<template>
  <!-- 行内 flex 而不是靠类：父组件的 `.nrn-side>*{flex:0 0 auto}` 带了两个 scope 属性，
       同特异性时谁后加载谁生效（实测压不住），于是板子按内容高度撑破侧栏、盖住下面的卡片。 -->
  <div class="dd" data-deduce-board :style="{ flex: '1 1 auto', minHeight: 0 }">
    <!-- 没有选中班次：这一页的立题行在上方，这里说清"下一步做什么" -->
    <div v-if="!flight" class="dd-empty">
      <b>先立题</b>
      <p>在上方选一个城市，再选一架班次 —— 这一页才会给出它的观测、判据、概率、反事实与代价对比。</p>
      <p class="quiet">没有选中班次时这一页不给默认结果：套模板生成的链路看起来像真的，其实和这架飞机无关。</p>
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
        <!-- ① 观测 -->
        <section class="dd-seg" data-seg="observe">
          <h4><i>1</i>观测 <em>PUBLIC</em></h4>
          <div class="dd-vis" v-for="row in visRows" :key="row.name">
            <span class="nm">{{ short(row.name) }}</span>
            <span class="track">
              <i class="fill" :class="{low: row.low}" :style="{ width: row.pct + '%' }"></i>
              <i class="mark" :style="{ left: row.thresholdPct + '%' }" title="判据阈值"></i>
            </span>
            <b :class="{low: row.low}">{{ row.text }}</b>
          </div>
          <p class="dd-line">
            <span>端点风速</span><b>{{ windText }}</b>
            <span class="src" :class="data.observed.radarOk ? 'ok' : 'absent'">
              {{ data.observed.radarOk ? '回波可用' : '回波不可用' }}
            </span>
          </p>
          <p class="dd-echo" :class="{hit: data.observed.hasDetour}">
            {{ data.observed.echo }}
            <template v-if="data.observed.echoTs"><em>· {{ clock(data.observed.echoTs) }}</em></template>
          </p>
        </section>

        <!-- ② 判据：逐条过/不过 -->
        <section class="dd-seg" data-seg="criteria">
          <h4><i>2</i>判据 <em>{{ passCount }}/{{ (data.criteria || []).length }} 通过</em></h4>
          <div class="dd-crit" v-for="c in data.criteria" :key="c.key" :class="{fail: !c.pass}">
            <div class="row">
              <span class="flag">{{ c.pass ? '✓' : '✗' }}</span>
              <span class="lb">{{ c.label }}</span>
              <span class="th">阈值 {{ thresholdText(c) }}</span>
              <b>{{ c.display }}</b>
            </div>
            <div class="bar">
              <i :class="{fail: !c.pass}" :style="{ width: Math.max(3, c.ratio * 100) + '%' }"></i>
            </div>
            <p v-if="c.note" class="note">{{ c.note }}</p>
          </div>
          <p v-if="!(data.criteria || []).length" class="dd-line quiet">该班次无此项</p>
        </section>

        <!-- ③ 概率与裁决 -->
        <section class="dd-seg" data-seg="verdict">
          <h4><i>3</i>概率与裁决 <em>DERIVED</em></h4>
          <div class="dd-risk">
            <b :class="tone">{{ num(data.flight.riskP, 2) }}</b>
            <div class="meter">
              <i class="zone watch"></i><i class="zone hold"></i>
              <i class="needle" :style="{ left: Math.min(100, data.flight.riskP * 100) + '%' }"></i>
            </div>
            <div class="scale"><span>0</span><span>预警 0.35</span><span>延期 0.75</span><span>1</span></div>
          </div>
          <p class="dd-verd-line">裁决：<b :class="tone">{{ data.flight.decisionLabel }}</b></p>
          <ul class="dd-drivers" v-if="(drivers || []).length">
            <li v-for="(text, i) in drivers" :key="'d' + i">{{ text }}</li>
          </ul>
          <p v-else class="dd-line quiet">本班次无触发项（依据为空 = 没有任何阈值被越过，不是"没算"）</p>
        </section>

        <!-- ④ 反事实 -->
        <section class="dd-seg" data-seg="counter">
          <h4><i>4</i>反事实 <em>DERIVED</em></h4>
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
          <p class="dd-line quiet" v-if="!bothExposureZero">两行是同一架、同一分钟下的两个反事实：不绕会暴露多久，绕了还剩多久。</p>
          <p class="dd-line quiet" v-else>两行都是 0：本帧航路没有压上强回波，不存在"不绕"这个选项。这是结论，不是缺数据。</p>
        </section>

        <!-- ⑤ 期望损失 -->
        <section class="dd-seg" data-seg="loss">
          <h4><i>5</i>期望损失 <em>三个方案对比</em></h4>
          <div class="dd-opt" v-for="opt in options" :key="opt.key"
               :class="{ best: opt.recommended, off: !opt.available }">
            <div class="row">
              <span class="lb">{{ opt.label }}</span>
              <b>{{ opt.available ? num(opt.cost, 2) : '不可用' }}</b>
              <span v-if="opt.recommended" class="badge">推荐</span>
            </div>
            <div class="bar">
              <i :style="{ width: costPct(opt) + '%' }"></i>
            </div>
            <p class="parts">
              风险 {{ num(opt.riskP, 2) }} · 时间 {{ num(opt.delayMin, 0) }} 分
              · 增量 {{ num(opt.extraKm, 0) }} km
            </p>
            <p class="note" v-if="!opt.available">{{ opt.note }}</p>
          </div>
          <p class="dd-formula">{{ data.expectedLoss.formula }}</p>
          <p class="dd-line quiet">
            系数写在这里，读者可以自己复算：风险 1.0 / 每小时 0.6 / 每公里 0.02。
            延期按推迟 60 分钟计，且<b>不假设</b>天气会好转。
          </p>
        </section>

        <!-- ⑥ 结论与边界 -->
        <section class="dd-seg" data-seg="conclusion">
          <h4><i>6</i>结论与边界 <em>OFFICIAL 边界</em></h4>
          <p class="dd-concl">{{ finalConclusion }}</p>
          <p class="dd-rv" v-if="review">
            这条人工裁决写在「{{ flight.id }}」上，走廊页、推演页与日志同步同一份记录。
          </p>
          <p class="dd-disc">{{ data.discipline }}</p>
          <p class="dd-line quiet" v-if="data.generatedAt">生成于 {{ clock(data.generatedAt) }} · 第 {{ data.minute }} 分钟</p>
        </section>
      </template>
    </template>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  flight: { type: Object, default: null },
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
</style>
