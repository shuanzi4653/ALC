// WebGL 能力探测 + 帧率看门狗。
//
// 为什么进出三维之前必须先探测：V1.0.1 期间 NationGlobe 两次把 Edge 主线程拖到
// 完全无响应（截图、点击、扩展通信全部超时，只能手动关标签页）。当时的判断是
// 「全量重建太频繁」，但那只能解释一部分。真正的原因是那台机器跑在**软件渲染**
// （SwiftShader / llvmpipe）上：没有 GPU 加速，WebGL 每一帧的深度缓冲都在 CPU 上算，
// 一个 pitched + fill-extrusion 的样式足以让渲染进程喘不过气。
//
// 所以三维不是「要不要做」的问题，是「这台机器能不能看」的问题：
//   ① 软件渲染一律不进三维，直接给倾斜视图 + 明确原因；
//   ② 进了三维也要有看门狗，连续 3 秒 < 20 fps 就自己退出来，不让人在卡死里等。
//
// 探测本身很便宜（建一个 8×8 的离屏 canvas），结果缓存，一次会话只做一次。

let cached = null

function contextOf(caveat) {
  let canvas = null
  try {
    canvas = document.createElement('canvas')
    canvas.width = 8
    canvas.height = 8
    const options = {
      // 关键：allowSoftware=false 的语义由这个开关表达 —— 传 true 时，
      // 浏览器若只能用软件光栅化实现，会直接返回 null 而不是给你一个坑。
      failIfMajorPerformanceCaveat: !!caveat,
      antialias: false,
      depth: true,
      alpha: false,
      powerPreference: 'high-performance',
    }
    return canvas.getContext('webgl2', options)
      || canvas.getContext('webgl', options)
      || canvas.getContext('experimental-webgl', options)
  } catch (e) {
    return null
  }
}

function release(gl) {
  try {
    const ext = gl && gl.getExtension('WEBGL_lose_context')
    if (ext) ext.loseContext()
  } catch (e) { /* 释放失败不影响结论 */ }
}

function readRenderer(gl) {
  let renderer = ''
  let vendor = ''
  try {
    const info = gl.getExtension('WEBGL_debug_renderer_info')
    if (info) {
      renderer = String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL) || '')
      vendor = String(gl.getParameter(info.UNMASKED_VENDOR_WEBGL) || '')
    } else {
      renderer = String(gl.getParameter(gl.RENDERER) || '')
      vendor = String(gl.getParameter(gl.VENDOR) || '')
    }
  } catch (e) { /* 部分浏览器屏蔽了该扩展，只是拿不到名字 */ }
  return { renderer, vendor }
}

// 名字里带这些字样，基本可以判定没有硬件加速
const SOFTWARE_RE = /swiftshader|llvmpipe|softpipe|mesa offscreen|software|basic render|microsoft basic|angle \(google, vulkan [\d.]+ \(swiftshader/i

/** 单看渲染器名字判软件渲染。抽出来是为了能单测 —— 这条判据一旦放宽，护栏就形同虚设。 */
export function classifyRenderer(renderer) {
  return SOFTWARE_RE.test(String(renderer || ''))
}

export function probeGPU() {
  if (cached) return cached
  const base = { ok: false, software: false, renderer: '', vendor: '', cores: 0, memory: 0, reason: '' }

  if (typeof document === 'undefined' || typeof window === 'undefined') {
    cached = { ...base, reason: '非浏览器环境' }
    return cached
  }

  const cores = Number(navigator.hardwareConcurrency || 0)
  // deviceMemory 只有 Chromium 系支持，单位 GB，且被粗化到 0.5/1/2/4/8
  const memory = Number(navigator.deviceMemory || 0)

  // 先按「拒绝软件光栅化」的方式取一次；拿不到就说明没有硬件加速。
  const strict = contextOf(true)
  const loose = strict || contextOf(false)
  if (!loose) {
    cached = {
      ...base, cores, memory,
      reason: '浏览器未启用 WebGL（多为硬件加速被关闭，或显卡驱动被浏览器拉黑）',
    }
    return cached
  }

  const { renderer, vendor } = readRenderer(loose)
  release(loose)
  if (strict && strict !== loose) release(strict)

  const named = classifyRenderer(renderer)
  // strict 拿不到 = 浏览器自己判定「这是软件实现」，比字符串匹配更权威
  const software = !strict || named

  let reason = ''
  if (software) {
    reason = `当前浏览器在用软件渲染${renderer ? `（${renderer}）` : ''}，没有 GPU 加速，三维会拖死页面`
  }

  cached = { ...base, ok: !software, software, renderer, vendor, cores, memory, reason }
  return cached
}

/** 给界面用的一句话：显卡名 + 核心数，拿不到就写"未识别"。 */
export function gpuLabel(gpu) {
  const info = gpu || probeGPU()
  const name = (info.renderer || '').replace(/^ANGLE \((.*)\)$/, '$1')
  const short = name.length > 46 ? name.slice(0, 44) + '…' : name
  const parts = []
  if (short) parts.push(short)
  if (info.cores) parts.push(`${info.cores} 线程`)
  if (info.memory) parts.push(`${info.memory} GB`)
  return parts.join(' · ') || '未识别'
}

/**
 * 帧率看门狗：连续 `seconds` 秒低于 `threshold` 就回调一次并自行停止。
 * 只统计真正渲染过的帧 —— 标签页切到后台时 rAF 不触发，不会误判成低帧率。
 */
export function startFpsWatch({ threshold = 20, seconds = 3, grace = 2000, onLow, onSample } = {}) {
  let frames = 0
  let low = 0
  let stopped = false
  let raf = 0
  let last = 0
  const t0 = typeof performance !== 'undefined' ? performance.now() : Date.now()

  const tick = (now) => {
    if (stopped) return
    raf = requestAnimationFrame(tick)
    // 启动后的宽限期：瓦片解码、样式首次编译都会掉帧，这段不算数
    if (now - t0 < grace) { last = now; return }
    if (!last) last = now
    frames += 1
    const span = now - last
    if (span < 1000) return
    const fps = Math.round((frames * 1000) / span)
    frames = 0
    last = now
    if (onSample) {
      try { onSample(fps) } catch (e) { /* 回调异常不该打断统计 */ }
    }
    if (fps < threshold) {
      low += 1
      if (low >= seconds) {
        stopped = true
        cancelAnimationFrame(raf)
        if (onLow) {
          try { onLow(fps) } catch (e) { /* 同上 */ }
        }
      }
    } else {
      low = 0
    }
  }
  raf = requestAnimationFrame(tick)

  return {
    stop() {
      stopped = true
      if (raf) cancelAnimationFrame(raf)
    },
  }
}
