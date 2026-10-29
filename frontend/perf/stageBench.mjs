/* Split the per-frame cost into its real stage weights.
 *
 * The first version of `fpsBench.mjs` reported one number for the whole frame,
 * and I optimised `effectiveFlights` / `zoneIntrusions` on the strength of it.
 * A stage breakdown showed those two are ~4% of the frame and that 93.9% sat in
 * `atTime` + `profile` -- which the panel calls once, for the focused flight, not
 * once per flight. So this page measures the *fleet-wide* calls separately:
 *
 *   effectiveFlights   -- once per frame
 *   splitTrajectoryAt  -- once per drawn flight (map draws flown + ahead halves)
 *   zoneIntrusions     -- once per frame
 *   groupFlights       -- once per frame
 *   focusedFlight      -- atTime + profile for the single selected flight
 */

const FRAMES = 120;

function makeFleet(count) {
  const flights = [];
  for (let i = 0; i < count; i += 1) {
    const baseLon = 123.2 + ((i * 37) % 900) / 100;
    const baseLat = 41.1 + ((i * 53) % 700) / 100;
    const startMinute = (i * 7) % 470;
    const steps = 40 + (i % 30);
    const points = [];
    for (let s = 0; s < steps; s += 1) {
      points.push([
        baseLon + s * 0.004,
        baseLat + Math.sin(s / 6) * 0.05,
        600 + s * 40,
        startMinute + s * 5,
      ]);
    }
    flights.push({ id: `FL-${i}`, points });
  }
  return flights;
}

function now() {
  return performance.now();
}

export async function runStageBenchmark(runtime, flightCount) {
  const flights = makeFleet(flightCount);
  const totals = {
    effectiveFlights: 0,
    splitTrajectoryAt: 0,
    zoneIntrusions: 0,
    groupFlights: 0,
    focusedFlight: 0,
    filterLedgerRows: 0,
    // A/B：同一帧里把两种切分实现各跑一遍，让"省了多少"是一个测出来的数，
    // 不是推理出来的。顺序固定（先旧后新）以免交替缓存效应混进差值。
    splitTrajectoryAtLegacy: 0,
    splitTrajectoryIntoHot: 0,
  };
  let frames = 0;
  let minute = 0;

  return new Promise((resolve) => {
    // 复用槽位跨帧存在，与地图里的做法一致（CityTrafficMap.vue 每轮绘制建一次）。
    const slot = [[], []];
    function frame() {
      let t = now();
      runtime.effectiveFlights(flights, [], minute);
      totals.effectiveFlights += now() - t;
      for (const flight of flights) {
        t = now();
        runtime.splitTrajectoryAt(flight.points, minute);
        totals.splitTrajectoryAt += now() - t;
      }
      for (const flight of flights) {
        if (!flight.points.length) continue;
        t = now();
        runtime.splitTrajectoryAt(flight.points, minute);
        totals.splitTrajectoryAtLegacy += now() - t;
      }
      for (const flight of flights) {
        if (!flight.points.length) continue;
        t = now();
        runtime.splitTrajectoryInto(flight.points, minute, slot);
        totals.splitTrajectoryIntoHot += now() - t;
      }
      t = now();
      runtime.zoneIntrusions(flights, minute);
      totals.zoneIntrusions += now() - t;
      t = now();
      runtime.groupFlights(flights, minute);
      totals.groupFlights += now() - t;
      // The focused flight: one flight, not the fleet.
      const focus = flights[Math.floor(flights.length / 2)];
      t = now();
      runtime.atTime(focus.points, minute);
      runtime.profile(focus.points);
      totals.focusedFlight += now() - t;
      // The ledger toolbar re-filters the whole board whenever a toggle or the
      // search box changes. The budget for that is 300 ms, so it is measured on
      // the full fleet rather than on a page of 20 rows.
      t = now();
      runtime.filterLedgerRows(flights, { search: 'FL-1', status: 'ALL', minute });
      totals.filterLedgerRows += now() - t;

      frames += 1;
      minute += 2;
      if (frames < FRAMES) {
        requestAnimationFrame(frame);
      } else {
        const perFrame = (total) => +(total / frames).toFixed(3);
        const legacyPerFrame = perFrame(totals.splitTrajectoryAtLegacy);
        const hotPerFrame = perFrame(totals.splitTrajectoryIntoHot);
        resolve({
          flightCount,
          frames,
          effectiveFlightsMs: perFrame(totals.effectiveFlights),
          splitTrajectoryAtMs: perFrame(totals.splitTrajectoryAt),
          zoneIntrusionsMs: perFrame(totals.zoneIntrusions),
          groupFlightsMs: perFrame(totals.groupFlights),
          focusedFlightMs: perFrame(totals.focusedFlight),
          filterLedgerRowsMs: perFrame(totals.filterLedgerRows),
          // A/B：两次跑的是**同一批航迹、同一批时刻**，唯一差别是实现。
          splitAbLegacyMs: legacyPerFrame,
          splitAbHotMs: hotPerFrame,
          splitAbSavingMs: +(legacyPerFrame - hotPerFrame).toFixed(3),
          splitAbSavingPercent: legacyPerFrame > 0
            ? +(((legacyPerFrame - hotPerFrame) / legacyPerFrame) * 100).toFixed(1)
            : 0,
          totalMs: perFrame(
            totals.effectiveFlights
              + totals.splitTrajectoryAt
              + totals.zoneIntrusions
              + totals.groupFlights
              + totals.focusedFlight
              + totals.filterLedgerRows,
          ),
        });
      }
    }
    requestAnimationFrame(frame);
  });
}
