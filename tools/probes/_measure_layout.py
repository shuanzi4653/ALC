"""Measure the workbench's vertical budget in a real browser, A/B against the old CSS.

Item 1 of the 0.9.24 request was 「首页和多个页面存在显示不全」. That is a claim about
layout, and this project has a standing rule about layout claims: a build does not
run CSS layout, so overlap and clipping have to be *measured* by a means independent
of the code that produced them (M28 -- "print the actual bounding box").

What this probe does:

  1. serves nothing; it drives Edge headless against an already-running URL
     (`tools/probes/_serve_dist_stub.py` provides dist + the Python API);
  2. injects a measuring script into the *built* `frontend/dist/index.html`
     (a build artifact, restored afterwards) so the numbers come from the shipped
     bundle rather than from a copy of it;
  3. samples the geometry as the page settles, then re-applies the four declarations
     the fix removed and samples again.

Step 3 is the part that makes the reading mean something. Comparing "before" and
"after" across two builds, two data sets or two viewports compares two skies; the A/B
here runs in one page, on one build, on one plan, at one viewport.

Run:
    backend-python\\.venv\\Scripts\\python.exe tools\\probes\\_measure_layout.py [url]
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / 'frontend' / 'dist' / 'index.html'
EDGE_CANDIDATES = (
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
)
DEFAULT_URL = 'http://127.0.0.1:10087/'
VIEWPORT = '1672,951'

HARNESS = r'''
<script>
(function () {
  var samples = [];
  function box(sel) {
    var el = document.querySelector(sel);
    if (!el) return null;
    var r = el.getBoundingClientRect();
    return { top: Math.round(r.top), bottom: Math.round(r.bottom), h: Math.round(r.height),
             scroll: el.scrollHeight, client: el.clientHeight };
  }
  function snap(tag) {
    var root = document.querySelector('.traffic-workbench');
    var style = root ? getComputedStyle(root) : null;
    // `overflow:hidden` still has `scrollHeight > clientHeight`, and script can still
    // set scrollTop -- so the naive test reports an `overflow:hidden` root as
    // "scrollable" and the probe then lies about the very defect it exists to find.
    // What matters is whether the *user* can reach the overflow.
    var userScrollable = !!style && (style.overflowY === 'auto' || style.overflowY === 'scroll')
      && root.scrollHeight > root.clientHeight + 1;
    samples.push({
      tag: tag,
      viewport: window.innerWidth + 'x' + window.innerHeight,
      overflowY: style ? style.overflowY : null,
      display: style ? style.display : null,
      rootScroll: root ? root.scrollHeight : null,
      rootClient: root ? root.clientHeight : null,
      scrollable: userScrollable,
      unreachablePx: root ? Math.max(0, root.scrollHeight - root.clientHeight) : null,
      main: box('.traffic-main'),
      mapPanel: box('.traffic-map-panel'),
      board: box('.dispatch-board'),
      playback: box('.traffic-playback'),
      overlay: !!document.querySelector('.traffic-build-overlay'),
      percent: (document.querySelector('.traffic-build-figure strong') || {}).textContent || null
    });
  }
  var OLD = '.traffic-workbench{display:block!important;overflow:hidden!important}' +
    '.traffic-workbench .traffic-main{flex:none!important;height:calc(100vh - 340px)!important;' +
    'min-height:460px!important;grid-template-rows:none!important}' +
    '.traffic-playback{position:sticky!important;bottom:-30px!important}';
  [0, 6000, 20000, 45000].forEach(function (at) {
    setTimeout(function () { snap('A-shipped t+' + at); }, at);
  });
  setTimeout(function () {
    var style = document.createElement('style');
    style.textContent = OLD;
    document.head.appendChild(style);
    void document.body.offsetHeight;
    snap('B-legacy');
  }, 50000);
  setTimeout(function () {
    var pre = document.createElement('pre');
    pre.textContent = 'MB' + JSON.stringify(samples) + 'ME';
    document.body.appendChild(pre);
  }, 52000);
})();
</script>
'''


def find_edge():
    for candidate in EDGE_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise SystemExit('no headless browser found in ' + repr(EDGE_CANDIDATES))


def measure(url):
    original = INDEX.read_text(encoding='utf-8')
    if '</head>' not in original:
        raise SystemExit(f'{INDEX} has no </head> to inject into')
    try:
        INDEX.write_text(original.replace('</head>', HARNESS + '</head>', 1),
                         encoding='utf-8')
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / 'dom.html'
            with dump.open('w', encoding='utf-8') as handle:
                subprocess.run([find_edge(), '--headless=new', '--disable-gpu',
                                '--no-sandbox', f'--window-size={VIEWPORT}',
                                '--virtual-time-budget=70000', '--dump-dom', url],
                               stdout=handle, stderr=subprocess.DEVNULL, timeout=300)
            html = dump.read_text(encoding='utf-8', errors='replace')
    finally:
        INDEX.write_text(original, encoding='utf-8')
    match = re.search(r'MB(\[.*?\])ME', html, re.S)
    if not match:
        raise SystemExit('measurement block not found in the DOM dump')
    return json.loads(match.group(1))


def report(rows):
    for row in rows:
        if 'viewport' not in row:
            print(row)
            continue
        print(f"\n[{row['tag']}]  viewport {row['viewport']}  "
              f"display={row['display']}  overflow-y={row['overflowY']}")
        print(f"  root  scroll={row['rootScroll']}  client={row['rootClient']}  "
              f"user-scrollable={row['scrollable']}  "
              f"overflow={row['unreachablePx']} px")
        for key in ('main', 'mapPanel', 'board', 'playback'):
            value = row.get(key)
            if not value:
                print(f'  {key:<10} (absent)')
                continue
            flag = ''
            if value['scroll'] > value['client'] + 1:
                flag = f"  <-- INNER CONTENT CROPPED by {value['scroll'] - value['client']} px"
            print(f"  {key:<10} h={value['h']:<5} top={value['top']:<5} "
                  f"bottom={value['bottom']:<5} scroll={value['scroll']:<5} "
                  f"client={value['client']:<5}{flag}")
        if row.get('overlay') is not None:
            print(f"  build overlay present={row['overlay']}  percent={row['percent']}")
    reachable = [row for row in rows if row.get('scrollable') is False]
    print('\nHow to read this: `scrollable=False` together with content taller than the')
    print('viewport is the reported defect -- the overflow is unreachable. `INNER CONTENT')
    print('CROPPED` inside a panel with overflow:hidden is a second, independent clip.')


if __name__ == '__main__':
    report(measure(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL))
