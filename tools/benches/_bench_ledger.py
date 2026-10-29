"""Measure the ledger filter and virtual window against their 300 ms budget.

The acceptance target for the ledger is 300 ms, but it has only ever been asserted,
never measured -- the evidence file says FPS and ledger response "need checking in a
real interface". The two hot paths are pure functions in frontend/src/traffic/
runtime.js, so they can be timed on the real 7760-flight payload without a browser.

This measures the filter + group + virtual-window path that `DispatchBoard.vue`
runs on every keystroke, over a realistic sweep of filter states and scroll
positions, and reports the worst case. It does NOT measure render/FPS -- that
needs a real browser and is reported separately as still unmeasured.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, artifact  # noqa: E402
from _node import NODE, NODE_PATH  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ROOT = Path(ROOT)
import json
import subprocess

PY = ROOT / 'backend-python' / '.venv' / 'Scripts' / 'python.exe'
FLIGHTS = Path(artifact('_ledger_flights.json'))
BENCH_OUT = Path(artifact('_ledger_bench.json'))

# Produce the real flight payload the frontend receives.
# The child interpreter is fresh, so this payload imports its own sys.
GEN = """
import json
import sys
sys.path.insert(0, r'{root}/backend-python')
from traffic import service
plan = service.simulate(seed=42, scenario='moving')
rows = []
for f in plan['flights']:
    rows.append({{
        'id': f['id'], 'mode': f.get('mode'), 'status': f['status'],
        'reason': f.get('reason'), 'departureMinute': f.get('departureMinute'),
        'arrivalMinute': f.get('arrivalMinute'), 'from': f.get('from'), 'to': f.get('to'),
    }})
json.dump(rows, open(r'{out}', 'w', encoding='utf-8'))
print(len(rows))
""".format(root=str(ROOT).replace('\\', '/'), out=str(FLIGHTS).replace('\\', '/'))

result = subprocess.run([str(PY), '-X', 'utf8', '-c', GEN], capture_output=True, text=True)
if result.returncode != 0:
    print(result.stdout, result.stderr, flush=True)
    sys.exit(1)
flights = json.loads(FLIGHTS.read_text(encoding='utf-8'))
print(f'payload: {len(flights)} flights', flush=True)

# Run the same pure functions the component uses, via node.
# The payload and the data it reads both live under artifacts/, and the flights
# file is addressed absolutely: node resolves a bare relative path against its
# own cwd, which is the repo root, so a name-only reference looked in the wrong
# directory once the artifact moved.
#
# Substitution is by replace, not str.format: the script is JavaScript and is
# full of braces (`{groupFlights, virtualWindow}`, object literals), every one of
# which format() would try to interpret as a field.
BENCH = r"""
import {groupFlights, virtualWindow} from '@@RUNTIME@@';
import fs from 'node:fs';

const flights = JSON.parse(fs.readFileSync(String.raw`@@FLIGHTS@@`, 'utf8'));
const modes = ['ALL', 'CAR', 'DELIVERY'];
const reasons = [...new Set(flights.map(f => f.reason).filter(Boolean))];

function scoped(modeFilter, reasonFilter) {
  return flights.filter(f =>
    (modeFilter === 'ALL' || f.mode === modeFilter) &&
    (!reasonFilter || f.reason === reasonFilter));
}

function bench(label, fn, iterations) {
  fn(); // warm
  const t0 = process.hrtime.bigint();
  for (let i = 0; i < iterations; i++) fn();
  const ms = Number(process.hrtime.bigint() - t0) / 1e6 / iterations;
  return {label, ms};
}

const results = [];
for (const mode of modes) {
  for (const reason of [null, ...reasons]) {
    const rows = scoped(mode, reason);
    results.push(bench(`filter mode=${mode} reason=${reason || 'ALL'} (${rows.length} rows)`,
      () => scoped(mode, reason), 60));
  }
}

// groupFlights is the heavier step: it buckets and sorts every scoped row.
const all = scoped('ALL', null);
for (const minute of [0, 60, 240, 479]) {
  results.push(bench(`groupFlights minute=${minute}`, () => groupFlights(all, minute), 20));
}

// The virtual window is the per-scroll-frame cost.
const grouped = groupFlights(all, 240);
const list = grouped[Object.keys(grouped)[0]] || all;
for (const scrollTop of [0, 20000, 200000]) {
  results.push(bench(`virtualWindow scrollTop=${scrollTop}`,
    () => virtualWindow(list.length, scrollTop, 640, 28, 6), 200));
}

const worst = results.reduce((a, b) => (b.ms > a.ms ? b : a));
console.log(JSON.stringify({results, worst}, null, 2));
"""
BENCH = (BENCH
         .replace('@@RUNTIME@@',
                  Path(ROOT / 'frontend' / 'src' / 'traffic' / 'runtime.js').as_uri())
         .replace('@@FLIGHTS@@', FLIGHTS.as_posix()))

# The generated module sits beside the data it reads, so its imports resolve
# without depending on the caller's working directory.
BENCH_FILE = Path(artifact('_bench_ledger.mjs'))
BENCH_FILE.write_text(BENCH, encoding='utf-8')

env = dict(os.environ)
# Both come from `_node`, so the runtime and its shared module directory cannot
# point at two different managed installs after a patch bump.
env['NODE_PATH'] = NODE_PATH
result = subprocess.run([NODE, str(BENCH_FILE)], cwd=str(ROOT),
                        capture_output=True, text=True, encoding='utf-8', env=env)
if result.returncode != 0:
    print(result.stdout, result.stderr, flush=True)
    sys.exit(1)
data = json.loads(result.stdout)
print(f"worst: {data['worst']['label']} = {data['worst']['ms']:.3f} ms", flush=True)
print(f"budget 300 ms -> {'PASS' if data['worst']['ms'] < 300 else 'FAIL'}", flush=True)
print('--- all measurements (ms) ---', flush=True)
for row in sorted(data['results'], key=lambda r: -r['ms']):
    print(f"  {row['ms']:9.3f}  {row['label']}", flush=True)
BENCH_OUT.write_text(json.dumps(data, indent=2), encoding='utf-8')
