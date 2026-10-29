"""诊断：地图上那条「全宽水平红线」来自哪一层（2026-10-11）。

用户报「怎么有未知红线」。先用几何口径判据自证，再让页面**自己**说出是哪一层。

判据（不是"看起来像"）：
  把每个 line/fill 图层的每个环投影到屏幕像素，若
    屏幕横向跨度 > 视口宽 * 0.75  且  纵向跨度 < 10 px
  则该环是一条"全宽水平线"。谁满足谁就是嫌疑，并把 layer id 印出来。

前置条件与截图探针完全相同：**必须先起后端**（探针要等页面自述「计划就绪」）。

用法：
  python tools/probes/_probe_map_band.py
退出码：0 找到（并印出层名）· 1 没找到 · 2 无法测量
"""
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _probe_workbench_layout as probe  # noqa: E402

VIEWPORT = (2150, 1250)

FIND_BAND_JS = r"""
(() => {
  let map = null;
  for (const el of document.querySelectorAll('.maplibregl-map')) {
    for (const k of Object.keys(el)) {
      const v = el[k];
      if (v && typeof v.getStyle === 'function' && typeof v.project === 'function') {
        map = v; break;
      }
    }
    if (map) break;
  }
  if (!map) return JSON.stringify({error: 'no map instance found'});

  const w = map.getCanvas().clientWidth, h = map.getCanvas().clientHeight;
  const style = map.getStyle();
  const found = [];
  const scanned = [];
  for (const layer of style.layers) {
    if (!layer.source) continue;
    if (layer.type !== 'line' && layer.type !== 'fill') continue;
    let feats;
    try {
      feats = map.querySourceFeatures(layer.source, {sourceLayer: layer['source-layer']});
    } catch (e) { continue; }
    if (!feats || !feats.length) continue;
    scanned.push(layer.id);
    for (const f of feats) {
      const g = f.geometry;
      if (!g) continue;
      const rings = [];
      if (g.type === 'LineString') rings.push(g.coordinates);
      else if (g.type === 'MultiLineString') g.coordinates.forEach(c => rings.push(c));
      else if (g.type === 'Polygon') g.coordinates.forEach(c => rings.push(c));
      else if (g.type === 'MultiPolygon') g.coordinates.forEach(p => p.forEach(c => rings.push(c)));
      for (const ring of rings) {
        if (!ring || ring.length < 2) continue;
        // 顶点太多时抽样：全宽线只需要两个端点，抽样不会漏掉它。
        const step = Math.max(1, Math.floor(ring.length / 400));
        let minX = 1e9, maxX = -1e9, minY = 1e9, maxY = -1e9, bad = 0;
        const samp = [];
        for (let i = 0; i < ring.length; i += step) {
          const c = ring[i];
          const p = map.project([c[0], c[1]]);
          if (!isFinite(p.x) || !isFinite(p.y)) { bad++; continue; }
          samp.push(c);
          minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
          minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
        }
        if (minX > 1e8) continue;
        const dw = maxX - minX, dh = maxY - minY;
        if (dw > w * 0.75 && dh < 10) {
          const lons = samp.map(c => c[0]), lats = samp.map(c => c[1]);
          found.push({
            layer: layer.id, layerType: layer.type, source: layer.source,
            geomType: g.type, pts: ring.length,
            screenW: Math.round(dw), screenH: Math.round(dh), yMid: Math.round((minY + maxY) / 2),
            lonMin: Math.min.apply(null, lons), lonMax: Math.max.apply(null, lons),
            latMin: Math.min.apply(null, lats), latMax: Math.max.apply(null, lats),
            offscreenVerts: bad
          });
        }
      }
    }
  }
  const seen = new Set(), uniq = [];
  for (const o of found) {
    const k = o.layer + '|' + o.yMid + '|' + Math.round(o.latMin * 100);
    if (seen.has(k)) continue;
    seen.add(k); uniq.push(o);
  }
  uniq.sort((a, b) => a.yMid - b.yMid);
  return JSON.stringify({viewport: [w, h], bands: uniq, scannedLayers: scanned});
})()
"""


async def run(port, debug_port):
    import websockets

    targets = None
    for _ in range(60):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/json/list' % debug_port,
                                        timeout=2) as resp:
                targets = json.loads(resp.read().decode('utf-8'))
            if targets:
                break
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.5)
    if not targets:
        raise RuntimeError('Edge did not expose a debug target')
    page = next((t for t in targets if t.get('type') == 'page'), None)
    if page is None:
        raise RuntimeError('no page target')

    async with websockets.connect(page['webSocketDebuggerUrl'],
                                  max_size=64 * 1024 * 1024) as ws:
        counter = [0]

        async def call(method, params=None):
            counter[0] += 1
            mid = counter[0]
            await ws.send(json.dumps({'id': mid, 'method': method, 'params': params or {}}))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=probe.PAGE_TIMEOUT_S)
                data = json.loads(raw)
                if data.get('id') == mid:
                    if 'error' in data:
                        raise RuntimeError('%s -> %s' % (method, data['error']))
                    return data.get('result', {})

        async def js(expression):
            result = await call('Runtime.evaluate', {'expression': expression,
                                                     'returnByValue': True})
            if result.get('exceptionDetails'):
                raise RuntimeError('page-side error: %s'
                                   % json.dumps(result['exceptionDetails'])[:400])
            return (result.get('result') or {}).get('value')

        async def wait_for(expr, what):
            deadline = time.monotonic() + probe.PAGE_TIMEOUT_S
            while time.monotonic() < deadline:
                if await js(expr):
                    return
                await asyncio.sleep(0.5)
            raise RuntimeError('%s never became true' % what)

        await call('Page.enable')
        await call('Runtime.enable')
        await call('Emulation.setDeviceMetricsOverride',
                   {'width': VIEWPORT[0], 'height': VIEWPORT[1],
                    'deviceScaleFactor': 1, 'mobile': False})
        await call('Page.navigate', {'url': 'http://127.0.0.1:%d/index.html' % port})
        await wait_for("!!document.querySelector('.hstage')", 'home stage')
        await wait_for(probe.READY_JS, 'page self-reported readiness')
        await asyncio.sleep(2.5)

        raw = await js(FIND_BAND_JS)
        return json.loads(raw) if raw else {}


def main():
    edge = probe.find_edge()
    if edge is None:
        print('no Edge binary -- cannot measure')
        return 2
    if not (probe.DIST / 'index.html').is_file():
        print('missing build output -- run `vite build` first')
        return 2
    if not probe.backend_up():
        print('no service on 127.0.0.1:%d -- start it first' % probe.BACKEND_PORT)
        return 2
    probe.API_MODE = probe.detect_api_mode()
    if probe.API_MODE is None:
        print('service up but no route prefix answered 200')
        return 2
    if probe.check_generation() != 'ok':
        print('backend generation unverified -- exit 2')
        return 2

    httpd, port = probe.start_server(probe.DIST)
    debug_port = probe.free_port()
    profile = tempfile.mkdtemp(prefix='alc-band-profile-')
    proc = subprocess.Popen(
        [edge, '--headless=new', '--disable-gpu', '--no-first-run',
         '--no-default-browser-check', '--disable-extensions',
         '--remote-debugging-port=%d' % debug_port,
         '--user-data-dir=%s' % profile,
         '--window-size=%d,%d' % VIEWPORT, 'about:blank'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        data = asyncio.run(run(port, debug_port))
    except Exception as exc:  # noqa: BLE001
        print('FAILED: %s' % exc)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()
        httpd.shutdown()
        shutil.rmtree(profile, ignore_errors=True)

    if data.get('error'):
        print('probe error: %s' % data['error'])
        return 2
    bands = data.get('bands') or []
    print('viewport %s   layers scanned: %s'
          % (data.get('viewport'), ', '.join(data.get('scannedLayers') or [])))
    if not bands:
        print('NO full-width horizontal band found')
        return 1
    print('FOUND %d full-width horizontal band(s):' % len(bands))
    for b in bands:
        print('  layer=%-26s %-4s src=%-22s pts=%-6d screenW=%-5d screenH=%-3d y=%-5d '
              'lon %.3f..%.3f lat %.3f..%.3f offscreen=%d'
              % (b['layer'], b['layerType'], b['source'], b['pts'], b['screenW'],
                 b['screenH'], b['yMid'], b['lonMin'], b['lonMax'],
                 b['latMin'], b['latMax'], b['offscreenVerts']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
