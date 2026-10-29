
import {groupFlights, virtualWindow} from './frontend/src/traffic/runtime.js';
import fs from 'node:fs';

const flights = JSON.parse(fs.readFileSync('_ledger_flights.json', 'utf8'));
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
