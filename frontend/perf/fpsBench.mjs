/* Measure the per-frame client cost of the traffic panel, in a real browser.
 *
 * Why this exists
 * ---------------
 * `docs/evaluation-v1.6` carried the line "browser 30 FPS ... still unmeasured".
 * An unmeasured claim is not a finding, so this page drives the *actual*
 * per-frame algorithms from `frontend/src/traffic/runtime.js` -- the same module
 * the panel imports -- under `requestAnimationFrame` and reports the frame time
 * distribution. It is deliberately not the whole app: booting the panel needs
 * MapLibre tiles, three services and a plan build, and none of that changes what
 * the per-frame CPU cost is. What it measures is the work the panel does on every
 * tick, which is the thing the 30 FPS budget is about.
 *
 * The shapes here are read off `runtime.js` rather than assumed, because getting
 * them wrong would make the benchmark measure a different program:
 *   * a trajectory point is `[lon, lat, altM, minute]` -- an array, not an object;
 *   * `effectiveFlights(flights, operations, minute)` takes an operations journal;
 *   * `profile(points)` takes one flight's point array and returns an SVG string;
 *   * `flightState` reads `departureMinute` / `scheduledMinute` / `arrivalMinute`.
 *
 * Frequency matters as much as shape
 * ----------------------------------
 * The first version of this file called `atTime` and `profile` once per flight,
 * which made a 7760-flight run report 86 ms/frame and 11.6 FPS. Both are
 * single-flight views in the panel -- `profile` draws the altitude chart of the
 * *selected* flight (TrafficWorkbench.vue:130) and `atTime` gives the current
 * position of the followed one (CityTrafficMap.vue:297,453) -- so that benchmark
 * was measuring a program nobody runs, and a stage breakdown put 93.9% of the
 * frame inside those two calls. Two rounds of work were aimed at the wrong
 * functions before the breakdown caught it. The fleet-wide per-frame work is
 * `effectiveFlights` + `splitTrajectoryAt` over drawn flights, plus
 * `zoneIntrusions` and `groupFlights`. Reproduce the real call frequency or the
 * number is worthless.
 *
 * How it reports
 * --------------
 * Results are written to `window.__ALC_FPS__` and into the document title, so the
 * driver can read them from a DOM dump or a single `Runtime.evaluate`.
 */

const MINUTE_STEP = 2;
const FRAMES = 240;

function makeFleet(count) {
  const flights = [];
  const operations = [];
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
    const endMinute = startMinute + (steps - 1) * 5;
    flights.push({
      id: `FL-${i}`,
      status: i % 5 === 0 ? 'CLOSED' : 'SCHEDULED',
      group: ['DELIVERY', 'CAR', 'PATROL'][i % 3],
      scheduledMinute: Math.max(0, startMinute - 10),
      departureMinute: startMinute,
      arrivalMinute: endMinute,
      points,
    });
    // A realistic sprinkle of manual suspensions: the panel applies the journal
    // before drawing, so leaving it out would skip a per-frame pass.
    if (i % 97 === 0) {
      operations.push({ flightId: `FL-${i}`, minute: startMinute + 20, action: 'SUSPEND' });
    }
  }
  return { flights, operations };
}

function now() {
  return (typeof performance !== 'undefined' && performance.now)
    ? performance.now()
    : Date.now();
}

// How many trajectories the map actually draws, read off CityTrafficMap.vue:216-229.
// The map skips a flight outright unless it is selected, airborne, landed-and-recent,
// or about to launch (`!selected&&!flying&&!landed&&!imminent -> continue`), and it
// caps how many landed lines stay on screen. Splitting every flight in the fleet
// would overstate the cost, so the benchmark applies the same gate.
const ARRIVED_KEEP_MINUTES = 12;
const MAX_ARRIVED_LINES = 120;

function drawnFlights(runtime, active, minute) {
  const drawn = [];
  let arrived = 0;
  for (const flight of active) {
    if (!flight.points || !flight.points.length) continue;
    const state = runtime.flightState(flight, minute);
    const flying = state === 'AIRBORNE';
    const landed = state === 'ARRIVED';
    const imminent = (state === 'PENDING' || state === 'HOLD')
      && flight.departureMinute >= minute
      && flight.departureMinute < minute + 2;
    if (!flying && !landed && !imminent) continue;
    if (landed) {
      if (minute - flight.arrivalMinute > ARRIVED_KEEP_MINUTES
        || arrived >= MAX_ARRIVED_LINES) continue;
      arrived += 1;
    }
    drawn.push(flight);
  }
  return drawn;
}

export async function runBenchmark(runtime, flightCount) {
  const { flights, operations } = makeFleet(flightCount);
  const samples = [];
  // Per-stage totals. A single frame number says the panel is slow; it does not
  // say *which* call is slow, and guessing has already been wrong once here.
  const stages = { effectiveFlights: 0, perFlight: 0, zoneIntrusions: 0, groupFlights: 0 };
  let drawnPeak = 0;
  let minute = 0;
  let frames = 0;

  return new Promise((resolve) => {
    function frame() {
      const started = now();
      // The three things the panel does every tick, in the order it does them.
      const stageA = now();
      const active = runtime.effectiveFlights(flights, operations, minute);
      const stageB = now();
      // `splitTrajectoryAt` runs per *drawn* flight.
      const drawn = drawnFlights(runtime, active, minute);
      if (drawn.length > drawnPeak) drawnPeak = drawn.length;
      for (const flight of drawn) {
        runtime.splitTrajectoryAt(flight.points, minute);
      }
      const stageC = now();
      // `atTime` and `profile` are *not* fleet-wide. `atTime` is the current
      // position of the followed / hovered flight (CityTrafficMap.vue:297,453;
      // FlightStrip.vue:20,26), and `profile` builds the altitude chart of the
      // single selected flight (TrafficWorkbench.vue:130). Calling them for all
      // 7760 flights measured a program the panel does not run.
      const focus = active.length ? active[Math.floor(active.length / 2)] : null;
      if (focus) {
        runtime.atTime(focus.points, minute);
        runtime.profile(focus.points);
      }
      const stageD = now();
      runtime.zoneIntrusions(flights, minute);
      const stageE = now();
      runtime.groupFlights(flights, minute);
      const stageF = now();
      stages.effectiveFlights += stageB - stageA;
      stages.perFlight += stageC - stageB;
      stages.zoneIntrusions += stageE - stageD;
      stages.groupFlights += stageF - stageE;
      samples.push(stageF - started);
      frames += 1;
      minute += MINUTE_STEP;
      if (frames < FRAMES) {
        requestAnimationFrame(frame);
      } else {
        resolve(summarise(samples, flightCount, stages, drawnPeak));
      }
    }
    requestAnimationFrame(frame);
  });
}

export function summarise(samples, flightCount, stages, drawnPeak) {
  const sorted = samples.slice().sort((a, b) => a - b);
  const at = (q) => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * q))];
  const mean = samples.reduce((a, b) => a + b, 0) / samples.length;
  // Frame time to FPS uses the *slowest* frame, because a single 40 ms frame is
  // what the operator perceives as a stutter; a mean that hides it would flatter
  // the result.
  const p95 = at(0.95);
  const max = sorted[sorted.length - 1];
  const result = {
    flightCount,
    // The map never draws the whole fleet; report how many trajectories were live
    // so the frame time is attributable to a known line count.
    drawnFlightsPeak: drawnPeak,
    frames: samples.length,
    meanMs: +mean.toFixed(3),
    p50Ms: +at(0.50).toFixed(3),
    p95Ms: +p95.toFixed(3),
    maxMs: +max.toFixed(3),
    meanFps: +(1000 / mean).toFixed(1),
    p95Fps: +(1000 / p95).toFixed(1),
    worstFps: +(1000 / max).toFixed(1),
    // The budget is 30 FPS, i.e. 33.3 ms per frame. Judged on the worst frame.
    meets30Fps: max <= 1000 / 30,
  };
  if (stages && samples.length) {
    // `total` accumulates ms across all frames, so divide by the frame count.
    const per = (total) => +(total / samples.length).toFixed(3);
    result.stageMeanMs = {
      effectiveFlights: per(stages.effectiveFlights),
      perFlight: per(stages.perFlight),
      zoneIntrusions: per(stages.zoneIntrusions),
      groupFlights: per(stages.groupFlights),
    };
  }
  return result;
}

export { makeFleet };
