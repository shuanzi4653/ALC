"""Assert the key product *flows*, not just that the scripts start.

Where this sits
---------------
``_gate_toolchain.py`` is static: it finds names used before their import, paths
rooted one directory too high, payloads that import at module scope. It catches
the whole "parses fine, dies at runtime" family before anything runs.

``_smoke_tools.py`` proves each script *starts*, by classifying the way it stops.

Neither one can tell whether the *system* still behaves. A plan can build while
returning the wrong status, a command can be accepted twice, two hazard tiers can
silently start overlapping — every one of those keeps all the existing checks
green. So this file asserts behaviour at the level a user experiences it, and it
is the only one of the three that can fail on a *logic* regression rather than a
mechanical one.

Why it runs in-process rather than over HTTP
--------------------------------------------
The HTTP hop adds a Java service, a Vite dev server and a port race, and it
proves nothing extra about the flows below: every route in ``main.py`` is a thin
wrapper whose only logic is the ``ValueError`` -> 409 mapping. That mapping *is*
worth pinning, so it is asserted directly against the route objects (flow
`http-contract`) without binding a socket. The end-to-end chain is a separate
concern and already has its own script, ``probes/_probe_e2e_chain.py``.

Cost
----
``service.simulate()`` costs ~13-17 s once the network is at 7760 flights, and it
runs on a worker thread behind ``session()``. Only the flows that genuinely need a
built plan wait for it; the weather and HTTP-contract flows are geometry-only and
finish in a couple of seconds. A hard cap (``--timeout``, default 420 s) bounds
the whole run so a wedged build fails the gate instead of hanging it.

    _smoke_flows.py                  # every flow
    _smoke_flows.py --only session   # one flow (substring match)
    _smoke_flows.py --verbose        # echo each passing assertion
    _smoke_flows.py --timeout 600    # raise the whole-run cap
"""

import argparse
import io
import json
import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from _repo import ROOT, BACKEND  # noqa: E402

REPORT = os.path.join(ROOT, "artifacts", "_smoke_flows.txt")

# `weather_frame()` returns dissolved *regions*, not cells: these six keys are the
# whole contract the renderer has. It draws `field` as the area, `ban` as the flat
# core and `caution` as the ring, and it needs `sources` to answer "which cell
# caused this patch?" — a question the operator asks whenever a route is closed.
#
# There is deliberately no `polygon` / `radiusM` here. Those belong to the per-cell
# shapes from ``NetworkWeather.shapes()``; ``frame()`` has already replaced them
# with the dissolved tiers. An earlier version of this gate demanded `polygon` and
# failed on the band, whose id carries a `::CLUSTER` suffix because one cell spans
# many regions. That was the assertion being wrong, not the payload, and the two
# shapes are easy to re-confuse.
REQUIRED_REGION_KEYS = ("id", "kind", "field", "ban", "caution", "sources")

# The snapshot the browser opens the panel with. It must contain real geometry:
# the band/chain case is where the discontinuous-coverage behaviour is observable,
# and a fleet pinned to an airport snapshot would exercise none of it.
#
# Two scenarios, because the project now serves only real weather and the two uses
# are no longer the same string:
#
#   * GEOMETRY_SCENARIO drives ``NetworkWeather`` *directly*. The class is retained
#     as the demanding-geometry fixture (a 20-cluster chain with staggered life
#     cycles) and never reaches an endpoint -- ``moving`` is rejected by every
#     route. These flows pin properties of the shared outline/hull/merge code the
#     real point observations also flow through, so they keep the richest input.
#   * HTTP_SCENARIO is what goes over the wire, and must be one of the three the
#     service declares: 'live' (real snapshot), 'clear', 'unknown'.
GEOMETRY_SCENARIO = "moving"
HTTP_SCENARIO = "live"
SCENARIO = GEOMETRY_SCENARIO
SEED = 42
MINUTE = 30.0

# A seed used only to observe the "plan not ready yet" state. It must not be the
# shared SEED, whose plan is cached by design and therefore always READY.
COLD_SEED = 99999

# The command journal is a single file on disk shared by every run and every tool.
# Flows that drive it must scope their entries, or a later run inherits the
# earlier one's state: a SUSPEND left behind makes the next SUSPEND fail with
# "该班次已经处于此状态". Each run tags its entries with this prefix and only ever
# reasons about its own.
JOURNAL_TAG = "smoke-%d-%04x" % (os.getpid(), os.urandom(2)[0] * 256 + os.urandom(2)[0])


class Check:
    """One assertion with a name, so a failure says *what* broke."""

    __slots__ = ("name", "ok", "detail")

    def __init__(self, name, ok, detail=""):
        self.name, self.ok, self.detail = name, bool(ok), detail


def close(a, b, tol):
    return abs(a - b) <= tol


def _expect(checks, name, ok, detail=""):
    checks.append(Check(name, ok, detail))
    return bool(ok)


# --------------------------------------------------------------------------
# helpers shared by the flows
# --------------------------------------------------------------------------

def _band_kind_counts(cells):
    counts = {}
    for cell in cells:
        counts[cell.get("kind")] = counts.get(cell.get("kind"), 0) + 1
    return counts


def _polygon_parts(geometry):
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    return []


def _exterior_coords(geometry):
    for part in _polygon_parts(geometry):
        yield list(part.exterior.coords)
        for ring in part.interiors:
            yield list(ring.coords)


def _turn_degrees(points):
    """Exterior turn angles of one ring, in degrees, plus the ring's own size."""
    turns = []
    count = len(points)
    if count < 4:
        return turns
    for index in range(1, count - 1):
        ax, ay = points[index - 1]
        bx, by = points[index]
        cx, cy = points[index + 1]
        first = math.atan2(by - ay, bx - ax)
        second = math.atan2(cy - by, cx - bx)
        turn = second - first
        while turn > math.pi:
            turn -= 2 * math.pi
        while turn < -math.pi:
            turn += 2 * math.pi
        turns.append(math.degrees(abs(turn)))
    return turns


# --------------------------------------------------------------------------
# flow: http-contract
# --------------------------------------------------------------------------

def flow_http_contract(checks, verbose):
    """Every open plan must surface as 409, never as a 500 or a silent success.

    409 is a *wait* instruction: the browser polls until the plan is ready. If a
    domain ``ValueError`` ever escaped as an unhandled exception the poll would
    read as a hard failure and the panel would stop retrying, so the mapping is
    part of the contract rather than an implementation detail.

    This flow needs a session that is genuinely *not* ready, and readiness is
    cached to `.run/traffic/<key>.json` and to an in-process `JOBS` dict. Using the
    shared scenario would mean this flow's result depends on whether another flow
    (or another tool) happened to warm that key first — it passed in isolation and
    failed in the suite for exactly that reason. A seed no other flow uses is cheap
    and makes the precondition a property of this function.
    """
    from fastapi import HTTPException
    import main
    from traffic import service as traffic_service

    seed = COLD_SEED
    ok = _expect(checks, "main.py imports without side effects on the app object",
                 hasattr(main, "app") and len(getattr(main.app, "routes", [])) > 20,
                 "routes=%d" % len(getattr(main.app, "routes", [])))

    # Drop the in-process job *and* the on-disk cache, so "not ready" is true no
    # matter what ran before this in the same suite.
    from traffic.service import identity, JOBS, LOCK, STORE
    key = identity(seed, HTTP_SCENARIO, None)
    with LOCK:
        JOBS.pop(key, None)
    stale = STORE / ("%s.json" % key)
    if stale.exists():
        try:
            stale.unlink()
        except OSError:
            pass

    for label, call in (
        ("/traffic/plan", lambda: traffic_service.plan_meta(seed, HTTP_SCENARIO)),
        ("/traffic/hubs", lambda: traffic_service.hubs(seed, HTTP_SCENARIO)),
        ("/traffic/delivery", lambda: traffic_service.delivery_plan(seed, HTTP_SCENARIO)),
    ):
        try:
            call()
            _expect(checks, "%s raises before READY" % label, False,
                    "returned a payload instead of raising")
        except ValueError as exc:
            _expect(checks, "%s raises ValueError before READY" % label, True,
                    str(exc)[:60])

    # ...and the wrapper turns exactly that into HTTP 409.
    try:
        main.traffic_plan(seed=seed, scenario=HTTP_SCENARIO)
        _expect(checks, "route maps ValueError -> 409", False, "route returned normally")
    except HTTPException as exc:
        _expect(checks, "route maps ValueError -> 409", exc.status_code == 409,
                "status=%s" % exc.status_code)
    except ValueError:
        _expect(checks, "route maps ValueError -> 409", False,
                "ValueError escaped the route handler")

    # The weather route maps its own failure to 422, a different promise.
    try:
        main.traffic_weather(seed=SEED, scenario=HTTP_SCENARIO, minute=MINUTE, cityId="no-such-city")
        _expect(checks, "weather route 422 on unknown city", False, "no error raised")
    except HTTPException as exc:
        _expect(checks, "weather route 422 on unknown city", exc.status_code == 422,
                "status=%s" % exc.status_code)

    return ok


# --------------------------------------------------------------------------
# flow: weather-geometry
# --------------------------------------------------------------------------

def flow_weather_geometry(checks, verbose):
    """The drawn hazard must be one hazard, not two overlapping ones.

    ``shapes(t)`` returns ``(cell, field, ban, caution)`` and the renderer paints
    the core red on top of the outer ring. The invariant that makes that readable
    is ``ban`` disjoint from ``caution``: the moment they overlap, an amber ring
    is painted over a red core and the more severe statement is lost. That bug
    has been fixed once at the per-cell level and once at the merged level, so it
    is worth an assertion rather than a comment.
    """
    from traffic import weather as weather_mod
    # `boundary` lives with the other geographic primitives in weather.geometry,
    # not in traffic.spatial (which is metric-only helpers).
    from weather.geometry import boundary

    world = weather_mod.NetworkWeather(SEED, SCENARIO)
    shapes = list(world.shapes(MINUTE))
    ok = _expect(checks, "shapes() returns cells at minute %.0f" % MINUTE, len(shapes) > 0,
                 "count=%d" % len(shapes))

    kinds = _band_kind_counts([cell for cell, _f, _b, _c in shapes])
    _expect(checks, "scenario %r carries a BAND cell" % SCENARIO,
            any(cell.get("shape") == "BAND" for cell, _f, _b, _c in shapes),
            "kinds=%s" % kinds)

    overlap_worst = 0.0
    overlap_cell = "—"
    empty_tiers = []
    for cell, field, ban, caution in shapes:
        overlap = ban.intersection(caution).area
        if overlap > overlap_worst:
            overlap_worst, overlap_cell = overlap, cell.get("id", "?")
        if not (field.area > 0 and ban.area > 0 and caution.area > 0):
            empty_tiers.append(cell.get("id", "?"))
    _expect(checks, "ban and caution are disjoint per cell", overlap_worst < 1.0,
            "worst overlap %.3f m^2 on %s" % (overlap_worst, overlap_cell))
    _expect(checks, "no cell has an empty tier", not empty_tiers,
            "empty: %s" % empty_tiers[:5])

    # The band is a chain of clusters, so its own polygon must be spatially
    # separate from the point cells: a chain that merged into one blob would mean
    # the gaps closed and the discontinuous coverage the design promises is gone.
    band_parts = []
    for cell, field, _ban, _caution in shapes:
        if cell.get("shape") == "BAND":
            band_parts = _polygon_parts(field)
            break
    _expect(checks, "band field is a multi-part chain", len(band_parts) >= 4,
            "parts=%d" % len(band_parts))

    # Its extent is the other half of the registration check. The band geometry
    # once carried raw metres that never went through ``geometry.project`` and sat
    # ~4300 km north, which clipped to an empty field -- valid, and therefore
    # silent. A plausible extent is cheap to assert and catches exactly that.
    if band_parts:
        minx = min(part.bounds[0] for part in band_parts)
        maxx = max(part.bounds[2] for part in band_parts)
        miny = min(part.bounds[1] for part in band_parts)
        maxy = max(part.bounds[3] for part in band_parts)
        span_x, span_y = maxx - minx, maxy - miny
        # The three provinces span roughly 1.2 Mm x 0.9 Mm in the local metric CRS.
        _expect(checks, "band extent is inside the operating area",
                0 < span_x < 2_000_000 and 0 < span_y < 2_000_000,
                "span %.0f x %.0f m" % (span_x, span_y))
        _expect(checks, "band extent intersects the boundary",
                boundary().intersects(
                    __import__("shapely.geometry", fromlist=["box"]).box(minx, miny, maxx, maxy)),
                "bbox (%.0f,%.0f)-(%.0f,%.0f)" % (minx, miny, maxx, maxy))

    # The frame is the clipped, dissolved payload the browser actually draws.
    frame = weather_mod.NetworkWeather(SEED, SCENARIO).frame(MINUTE)
    ok = _expect(checks, "frame() returns drawable regions", len(frame) > 0,
                 "regions=%d" % len(frame)) and ok
    bad_region = None
    for region in frame:
        for key in REQUIRED_REGION_KEYS:
            if key not in region:
                bad_region = "%s missing %s" % (region.get("id", "?"), key)
                break
        if bad_region:
            break
    _expect(checks, "every region carries its provenance", bad_region is None,
            bad_region or "all %d regions complete" % len(frame))

    # A region's filled field is what is drawn as one area, so it must be a real
    # polygon and not an empty geometry left behind by the dissolve step.
    empty_regions = [r.get("id") for r in frame
                     if not _polygon_parts(_load_geometry(r.get("field")))]
    _expect(checks, "no region draws an empty field", not empty_regions,
            "empty: %s" % empty_regions[:5])

    # The band survives as a chain of `::CLUSTER` regions: one cell, many drawn
    # areas. Losing the suffix would mean the chain collapsed back into a single
    # blob, which is the state the discontinuity fix removed. This lives here
    # rather than in ``flow_weather_payload`` because that flow can only reach
    # servable scenarios, and the chain is a property of the retained fixture.
    clusters = [r for r in frame if str(r.get("id", "")).endswith("::CLUSTER")]
    _expect(checks, "%s: the band dissolves into separated cluster regions" % SCENARIO,
            len(clusters) >= 4, "cluster regions=%d" % len(clusters))

    return ok


def _clear_journal(operations, session_id):
    """Remove one session's entries from the shared command journal.

    The journal is append-only by design and lives at a fixed path, so a gate that
    drives it has to put back what it used. Deleting *only* this session's rows
    keeps other sessions' history intact, and returns how many went so the report
    can show whether the run actually started clean.
    """
    with operations.LOCK:
        try:
            data = json.loads(operations.JOURNAL.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return 0
        kept = [row for row in data if row.get("sessionId") != session_id]
        removed = len(data) - len(kept)
        if removed:
            operations.JOURNAL.parent.mkdir(parents=True, exist_ok=True)
            temp = operations.JOURNAL.with_suffix(".tmp")
            temp.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
            temp.replace(operations.JOURNAL)
        return removed


def _load_geometry(payload):
    from shapely.geometry import shape
    if not payload:
        return None
    try:
        return shape(payload)
    except Exception:  # noqa: BLE001 - a malformed payload is the finding
        return None


# --------------------------------------------------------------------------
# flow: band-coverage
# --------------------------------------------------------------------------

def flow_band_coverage(checks, verbose):
    """After the band has passed, the restriction must break up, not vanish.

    A real front leaves scattered rain behind it: the no-fly area drawn from it is
    discontinuous and irregular, and it spreads out over time instead of sliding
    as one rigid sheet. The counterfactual is what the code used to do — translate
    the whole chain by a single (dx, dy) and a fixed core — which produces a
    picture that looks identical at every minute.

    So this measures shape, not position: the part count and the total area of the
    drawn band, sampled across the run. Rigid translation keeps both constant to
    within a polygon's worth of clipping; evolution moves them.
    """
    from traffic import weather as weather_mod

    sample_minutes = [0.0, 60.0, 150.0, 260.0, 380.0, 470.0]
    series = []
    for minute in sample_minutes:
        try:
            frame = weather_mod.NetworkWeather(SEED, SCENARIO).frame(minute)
        except Exception as exc:  # noqa: BLE001 - reported as a finding below
            _expect(checks, "frame builds at minute %.0f" % minute, False,
                    "%s: %s" % (type(exc).__name__, exc))
            return False
        parts = 0
        area = 0.0
        for region in frame:
            geometry = _load_geometry(region.get("field"))
            pieces = _polygon_parts(geometry)
            parts += len(pieces)
            area += sum(piece.area for piece in pieces)
        series.append((minute, parts, area))

    _expect(checks, "frame builds at every sampled minute", len(series) == len(sample_minutes),
            "%d/%d" % (len(series), len(sample_minutes)))

    counts = [parts for _m, parts, _a in series]
    areas = [area for _m, _p, area in series]

    _expect(checks, "coverage stays multi-part across the run", min(counts) >= 4,
            "part counts %s" % counts)
    _expect(checks, "part count is not constant (the field evolves)", len(set(counts)) > 1,
            "part counts %s" % counts)

    if areas and areas[0] > 0:
        # Total drawn hazard area should neither freeze (rigid translation) nor
        # decay to nothing (a band that "leaves" the map entirely).
        low, high = min(areas) / areas[0], max(areas) / areas[0]
        _expect(checks, "hazard area changes over the run",
                not close(low, 1.0, 0.02) or not close(high, 1.0, 0.02),
                "area ratio %.3f..%.3f of t=0" % (low, high))
        _expect(checks, "hazard area stays in a plausible band",
                0.05 <= low and high <= 6.0,
                "area ratio %.3f..%.3f of t=0" % (low, high))

    # Irregular means the outline has real harmonics, not a circle. Compare the
    # radius against the mean: a smooth ellipse stays within a few percent, a
    # ragged front does not.
    worst_ratio = 0.0
    for minute in (0.0, 260.0):
        frame = weather_mod.NetworkWeather(SEED, SCENARIO).frame(minute)
        for region in frame:
            for ring in _exterior_coords(_load_geometry(region.get("field"))):
                if len(ring) < 8:
                    continue
                cx = sum(x for x, _y in ring) / len(ring)
                cy = sum(y for _x, y in ring) / len(ring)
                radii = [math.hypot(x - cx, y - cy) for x, y in ring]
                mean = sum(radii) / len(radii)
                if mean > 0:
                    worst_ratio = max(worst_ratio, (max(radii) - min(radii)) / mean)
    _expect(checks, "outlines are irregular, not circular", worst_ratio > 0.15,
            "max (r_max-r_min)/r_mean = %.3f" % worst_ratio)

    return True


# --------------------------------------------------------------------------
# flow: session-lifecycle
# --------------------------------------------------------------------------

def flow_session_lifecycle(checks, verbose, deadline):
    """The full operator path: poll to READY, then drive one flight.

    Two properties matter here and neither is checkable statically.

    1. Delivery is *once*. READY returns every flight with its full trajectory, so
       the poll loop stops re-fetching megabytes on every tick. If READY ever
       regressed to sending a token payload, the panel would render an empty map
       with all the status checks still green.
    2. A repeated ``commandId`` is idempotent. The operator clicks SUSPEND, the
       request times out after the write, and the UI retries. A second journal
       entry would leave the record claiming two suspensions for one action.
    """
    import json as _json
    from traffic import operations as traffic_operations
    from traffic import service as traffic_service

    started = time.monotonic()
    state = None
    while True:
        state = traffic_service.session(SEED, HTTP_SCENARIO)
        status = state.get("status")
        if status == "READY":
            break
        if status in ("ERROR",):
            _expect(checks, "plan reaches READY", False, state.get("message", "ERROR"))
            return False
        if status == "BUSY":
            _expect(checks, "plan build is not contended", False, "BUSY: %s" % state.get("message"))
            return False
        if time.monotonic() > deadline:
            _expect(checks, "plan reaches READY", False,
                    "still %s after %.0fs" % (status, time.monotonic() - started))
            return False
        time.sleep(0.5)

    elapsed = time.monotonic() - started
    ok = _expect(checks, "plan reaches READY", state.get("status") == "READY",
                 "%.1fs (cached) " % elapsed if elapsed < 2 else "%.1fs" % elapsed)

    # --- delivery is once, and complete ---
    flights = state.get("flights") or []
    scheduled = [f for f in flights if f.get("status") == "SCHEDULED"]
    with_points = [f for f in flights if f.get("points")]
    _expect(checks, "READY carries the full fleet", len(flights) > 1000,
            "flights=%d" % len(flights))
    # Every SCHEDULED flight must carry its trajectory. A CLOSED one carries an
    # empty `points` list on purpose: it was never released, so there is no path to
    # draw, and sending one would invite the client to render a route the plan
    # refuses to fly. The measured split is 6035 of 6035 scheduled with points
    # against 0 of 1725 closed, which is the shape asserted here.
    _expect(checks, "every SCHEDULED flight carries a trajectory",
            bool(scheduled) and len(with_points) >= len(scheduled),
            "with points %d, scheduled %d" % (len(with_points), len(scheduled)))
    _expect(checks, "CLOSED flights deliberately carry no trajectory",
            len(with_points) == len(scheduled),
            "with points %d vs scheduled %d" % (len(with_points), len(scheduled)))

    # `scheduledMinute` is the field name, not `departureMinute`; the latter is
    # only a key on the *command* request.
    required = ("id", "name", "status", "mode", "scheduledMinute", "reason",
                "requestedDepartureAt", "points")
    missing = None
    for flight in flights[:200]:
        for key in required:
            if key not in flight:
                missing = "%s missing %s" % (flight.get("id", "?"), key)
                break
        if missing:
            break
    _expect(checks, "flight records are complete", missing is None,
            missing or "checked 200 of %d" % len(flights))

    session_id = state.get("sessionId")
    _expect(checks, "sessionId is a stable 24-hex key",
            isinstance(session_id, str) and len(session_id) == 24
            and all(ch in "0123456789abcdef" for ch in session_id),
            "sessionId=%r" % session_id)

    # `riskRules` and `staticAirspace` belong to `/traffic/network`, not to the
    # session: they describe the static scene and are fetched once, while the
    # session is polled. Asserting them here would have been asserting the wrong
    # endpoint's contract.
    for key in ("stats", "planRevision", "layerUsage", "weatherSnapshot"):
        if key not in state:
            _expect(checks, "READY payload carries %s" % key, False, "missing")
    _expect(checks, "stats are present",
            isinstance(state.get("stats"), dict) and state["stats"].get("accepted", 0) > 0,
            "stats keys=%s" % sorted((state.get("stats") or {}).keys())[:8])

    # The scene endpoint does carry them, and the browser reads both to draw the
    # fixed-zone layer and to label the derived risk layer.
    from traffic import service as _service
    scene = _service.network()
    _expect(checks, "network() carries riskRules and staticAirspace",
            isinstance(scene.get("riskRules"), dict) and "staticAirspace" in scene,
            "keys=%s" % sorted(scene.keys())[:10])

    # --- the command journal ---
    #
    # The journal is one file shared by every run: entries from a previous run of
    # this flow (or a manual poke through `/traffic/command`) are still there, and
    # "the latest entry for this flight" is what defines its current state. A stale
    # SUSPEND therefore makes this run's first SUSPEND fail with
    # "该班次已经处于此状态" — which is correct behaviour from an interface
    # perspective and a false alarm from a gate's. This run's own entries are
    # removed at the end, and the first command of the run is made idempotent-safe
    # by choosing a driver whose state is known.
    #
    # 选 driver 的谓词必须**读守卫读的那个字段**，而且要多留一分钟。
    # `operations.command` 的守卫是 `if minute >= flight['departureMinute']: raise`，
    # 而 `departureMinute` 与 `scheduledMinute` **不是同一个数**：地面等待会让前者更晚
    # （实测 `DEL-1-04-06-1-23` scheduled=23 / departure=33）。本流程随后要在
    # `MINUTE + 1` 发一条 RESUME，所以候选必须满足 `departureMinute > MINUTE + 1`。
    # 旧谓词读的是 `scheduledMinute > MINUTE`：2026-10-17 实测选中的是
    # `DEL-2-05-01-0-31`（scheduled=31 / departure=31），于是 MINUTE+1 = 31 时守卫
    # 判"已起飞"，整条流程抛 ValueError 而**看上去像产品缺陷**——其实判据自己选错了对象。
    # 这一条只在"恰好有一班 SCHEDULED 落在 MINUTE+1"时才炸，所以它能连着很多轮都是绿的。
    driver = next((f for f in flights
                   if f.get("status") == "SCHEDULED"
                   and (f.get("departureMinute") or 0) > MINUTE + 1),
                  None)
    if driver is None:
        _expect(checks, "a suspendable flight exists to drive", False,
                "no SCHEDULED flight departing after minute %.0f" % (MINUTE + 1))
        return ok

    # Journal entries for the whole fleet are cleared for this session so the run
    # starts from "nothing has been touched", which is the state a fresh operator
    # sees. Only this session's entries go; anything else in the file is left alone.
    cleared = _clear_journal(traffic_operations, session_id)
    _expect(checks, "journal state was reset for this run", True,
            "removed %d previous entry/entries for %s" % (cleared, session_id))

    token = JOURNAL_TAG + "-1"
    first = traffic_operations.command(SEED, HTTP_SCENARIO, driver["id"], MINUTE, "SUSPEND",
                                      state.get("planRevision"), token)
    _expect(checks, "SUSPEND is journalled", first.get("action") == "SUSPEND"
            and first.get("commandId") == token, "id=%s" % first.get("id", "?"))

    replay = traffic_operations.command(SEED, HTTP_SCENARIO, driver["id"], MINUTE, "SUSPEND",
                                      state.get("planRevision"), token)
    _expect(checks, "a repeated commandId is idempotent",
            replay.get("idempotent") is True and replay.get("id") == first.get("id"),
            "idempotent=%r same_id=%r" % (replay.get("idempotent"),
                                          replay.get("id") == first.get("id")))

    records = traffic_operations.records(session_id)
    _expect(checks, "the journal holds exactly one entry for the first command",
            sum(1 for r in records if r.get("commandId") == token) == 1,
            "entries=%d" % sum(1 for r in records if r.get("commandId") == token))

    # Repeating the same state with a *new* id is rejected: the id is the
    # idempotency key, not a licence to write the same state twice.
    try:
        traffic_operations.command(SEED, HTTP_SCENARIO, driver["id"], MINUTE + 1, "SUSPEND",
                                 state.get("planRevision"), token + "b")
        _expect(checks, "duplicate state with a new id is rejected", False,
                "second SUSPEND was accepted")
    except ValueError as exc:
        _expect(checks, "duplicate state with a new id is rejected", True, str(exc)[:50])

    # RESUME has to move the minute forward -- the journal is monotonic in time,
    # which is what makes "the latest entry" a well-defined current state.
    try:
        traffic_operations.command(SEED, HTTP_SCENARIO, driver["id"], MINUTE - 1, "RESUME",
                                 state.get("planRevision"), token + "c")
        _expect(checks, "a command cannot rewind the timeline", False,
                "minute earlier than the last entry was accepted")
    except ValueError as exc:
        _expect(checks, "a command cannot rewind the timeline", True, str(exc)[:50])

    second = traffic_operations.command(SEED, HTTP_SCENARIO, driver["id"], MINUTE + 1, "RESUME",
                                      state.get("planRevision"), token + "d")
    _expect(checks, "RESUME reverses SUSPEND", second.get("action") == "RESUME", "")

    # A flight the algorithm already closed is not manually releasable. If this
    # ever started succeeding, the "human cannot override the algorithm" promise
    # would be broken silently. A CLOSED flight has an empty `points`, which is why
    # the selector must not filter on `points` being non-empty.
    closed = next((f for f in flights if f.get("status") == "CLOSED"), None)
    if closed is not None:
        try:
            traffic_operations.command(SEED, HTTP_SCENARIO, closed["id"], MINUTE, "RESUME",
                                     state.get("planRevision"), token + "e")
            _expect(checks, "an algorithm-closed flight cannot be manually released",
                    False, "flight %s (status %s) was released" % (closed["id"], closed.get("status")))
        except ValueError as exc:
            _expect(checks, "an algorithm-closed flight cannot be manually released",
                    True, str(exc)[:50])
    else:
        _expect(checks, "an algorithm-closed flight exists to test", False,
                "no non-SCHEDULED flight in the payload")

    # An expired planRevision is a 409 by design; the UI refreshes on it.
    if isinstance(state.get("planRevision"), str):
        try:
            traffic_operations.command(SEED, HTTP_SCENARIO, driver["id"], MINUTE + 2, "SUSPEND",
                                     "stale-revision", token + "f")
            _expect(checks, "a stale planRevision is rejected", False, "accepted")
        except ValueError as exc:
            _expect(checks, "a stale planRevision is rejected", True, str(exc)[:50])

    # Put the journal back. The state this flow created — a suspended flight at
    # minute 30, resumed at 31 — would otherwise be inherited by the next run, and
    # would also be inherited by a real operator opening the panel afterwards.
    #
    # The assertion is on what remains, not on what was removed: the removal count
    # is expected to be non-zero (that is the cleanup doing its job), whereas the
    # *remaining* count has to be zero for the journal to be back to its start.
    _clear_journal(traffic_operations, session_id)
    left = len(traffic_operations.records(session_id))
    _expect(checks, "journal was restored after the run", left == 0,
            "%d entr(ies) left behind" % left)

    return ok


# --------------------------------------------------------------------------
# flow: weather-payload
# --------------------------------------------------------------------------

def flow_weather_payload(checks, verbose):
    """The payload the panel draws must satisfy the template the renderer assumes.

    Note carefully what this payload contains: `weather_frame()` puts
    ``NetworkWeather.frame()`` under the ``cells`` key, and ``frame()`` has already
    clipped each shape to the province boundary and dissolved connected components
    into *regions*. So a `cells` entry is a region — it carries ``field``/``ban``/
    ``caution`` and a ``sources`` list, **not** the per-cell ``polygon`` or
    ``radiusM`` that ``shapes()`` produces. The names are confusing and were the
    source of a wrong assertion here once; the key lists above record the split.

    A key dropped in a refactor shows up as a silently flat or missing volume on
    the map — no error, no test failure, just an empty panel. So they are asserted
    by name.
    """
    from traffic import service as traffic_service

    ok = True
    for scenario, expected_source in (("clear", "NONE"), ("live", "OPEN_METEO")):
        try:
            frame = traffic_service.weather_frame(SEED, scenario, MINUTE)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            _expect(checks, "weather payload builds for %r" % scenario, False,
                    "%s: %s" % (type(exc).__name__, exc))
            ok = False
            continue
        regions = frame.get("cells") or []
        _expect(checks, "%s: payload declares its source" % scenario,
                frame.get("source") == expected_source,
                "source=%r" % frame.get("source"))
        _expect(checks, "%s: riskRules travel with the payload" % scenario,
                isinstance(frame.get("riskRules"), dict)
                and "labels" in frame["riskRules"]
                and "derivation" in frame["riskRules"],
                "keys=%s" % sorted((frame.get("riskRules") or {}).keys())[:6])
        if not regions:
            # `clear` and `live` both legitimately have no regions when no
            # observation crosses a threshold. Absence is a real state, not a
            # failure: the payload still has to be complete and self-describing,
            # which is asserted above.
            _expect(checks, "%s: regions present" % scenario, True, "regions=0")
            continue

        missing = None
        for region in regions:
            for key in REQUIRED_REGION_KEYS:
                if key not in region:
                    missing = "%s missing %s" % (region.get("id", "?"), key)
                    break
            if missing:
                break
        _expect(checks, "%s: regions match the render template" % scenario, missing is None,
                missing or "%d regions complete" % len(regions))

        _expect(checks, "%s: every region declares a vertical extent" % scenario,
                all(isinstance(r.get("ceilingAglM"), (int, float))
                    and isinstance(r.get("floorAglM"), (int, float)) for r in regions),
                "floor/ceiling must be numbers")

        # `sources` is how the operator answers "which cell closed my route?".
        # A region that cannot name its own cause is not traceable, and the
        # `::CLUSTER` suffix is what keeps the band's 17 regions distinguishable
        # from each other instead of all claiming the same cell id.
        untraceable = [r.get("id") for r in regions
                       if not isinstance(r.get("sources"), list) or not r["sources"]]
        _expect(checks, "%s: every region can name its source cells" % scenario,
                not untraceable, "untraceable: %s" % untraceable[:4])

        # A tier is drawn as a filled surface, so it must be valid GeoJSON the
        # renderer can read. `ban` is allowed to be an *empty* polygon — low
        # visibility with no strong gust genuinely has no hard core — but it must
        # never be `null`: that is a shape the drawing code cannot parse, and it is
        # what a zero-radius `buffer(0)` used to produce. The distinction between
        # "no core" and "core missing due to a bug" has to survive into the payload.
        broken = []
        for region in regions:
            for key in ("field", "ban", "caution"):
                payload = region.get(key)
                if payload == {"type": "Polygon", "coordinates": []}:
                    if key == "field":
                        broken.append("%s field is empty" % region.get("id"))
                    continue
                geometry = _load_geometry(payload)
                if geometry is None or not _polygon_parts(geometry):
                    if key == "field":
                        broken.append("%s field is %r" % (region.get("id"), payload))
        _expect(checks, "%s: every drawn tier is valid GeoJSON" % scenario, not broken,
                "; ".join(broken[:4]))

        null_tiers = [r.get("id") for r in regions
                      if r.get("ban") is None or r.get("caution") is None]
        _expect(checks, "%s: no tier is a bare null" % scenario, not null_tiers,
                "null tiers on: %s" % null_tiers[:4])

        # The invariant that actually constrains a *region*: its core and its ring
        # must lie inside the area being drawn, and must not overlap each other.
        #
        # This is not the same test as the per-cell one in `weather-geometry`, and
        # the difference cost a mutation test to find. At cell level `ban ∩ caution`
        # is a real constraint on two independently-built shapes. At region level
        # `caution` is *constructed* as `outer.difference(ban)`, so disjointness is
        # true by definition and asserting it is a no-op -- the earlier mutation of
        # exactly that line went undetected. What is not automatic is containment:
        # a chained band is one cell whose ban is a MultiPolygon spread over 1.14 Mm,
        # and unioning every member's whole ban handed every region all ~20 cores.
        # Measured in the source comments at 142,047,519,714 m^2 of core lying
        # outside its own field. So containment is what gets asserted here.
        spill = []
        for region in regions:
            field = _load_geometry(region.get("field"))
            core = _load_geometry(region.get("ban"))
            ring = _load_geometry(region.get("caution"))
            if field is None:
                continue
            for label, tier in (("ban", core), ("caution", ring)):
                if tier is None or tier.is_empty:
                    continue
                outside = tier.difference(field.buffer(1.0)).area
                if outside > 1.0:
                    spill.append("%s %s outside field by %.0f m^2"
                                 % (region.get("id"), label, outside))
        _expect(checks, "%s: no region draws a tier outside its own field" % scenario,
                not spill, "; ".join(spill[:3]))

        # The painted tiers must not cover each other: the renderer stacks the core
        # over the ring, and an overlapping ring would paint amber across a red
        # core, deleting the more severe statement.
        #
        # Note for whoever changes the merge next: this assertion is currently
        # satisfied *by construction* — region `caution` is built as
        # `outer.difference(ban)` — so a mutation that stops subtracting is not
        # observable here (verified). It is kept because the construction is an
        # implementation choice and this is the property the map depends on; if the
        # merge is ever rewritten to union the rings, this is the line that fails.
        overlaps = []
        for region in regions:
            core = _load_geometry(region.get("ban"))
            ring = _load_geometry(region.get("caution"))
            if core is None or ring is None or core.is_empty or ring.is_empty:
                continue
            shared = core.intersection(ring).area
            if shared > 1.0:
                overlaps.append("%s %.0f m^2" % (region.get("id"), shared))
        _expect(checks, "%s: core and ring do not cover each other" % scenario,
                not overlaps, "; ".join(overlaps[:3]))

        if scenario == "moving":
            # The band survives as a chain of `::CLUSTER` regions: one cell, many
            # drawn areas. Losing the suffix would mean the chain collapsed back
            # into a single blob, which is the state the discontinuity fix removed.
            #
            # Unreachable now that `moving` is not a servable scenario — the check
            # moved to ``flow_weather_geometry``, which drives the retained
            # ``NetworkWeather`` fixture directly. Kept as a no-op guard so a
            # future re-introduction of a servable synthetic scene cannot silently
            # skip it.
            clusters = [r for r in regions if str(r.get("id", "")).endswith("::CLUSTER")]
            _expect(checks, "moving: the band is drawn as separated clusters",
                    len(clusters) >= 4, "cluster regions=%d" % len(clusters))

    return ok
# --------------------------------------------------------------------------
# flow: frontend-build
# --------------------------------------------------------------------------

def flow_frontend_build(checks, verbose):
    """The built bundle must exist and still contain the colours the legend claims.

    This is deliberately a *string* assertion on the artefact rather than a source
    check. MapLibre throws on a malformed paint expression and the failure only
    appears when the layer is added, so a `.vue` edit that breaks an expression
    passes every JS test that does not compile the template. Checking that the
    built CSS/JS carries the expected colour tokens is a cheap proxy for "the
    bundle was rebuilt after the change", which is the thing that silently rots.
    """
    dist = os.path.join(ROOT, "frontend", "dist")
    index = os.path.join(dist, "index.html")
    ok = _expect(checks, "frontend build artefact exists", os.path.isfile(index), dist)
    if not ok:
        return False

    assets = os.path.join(dist, "assets")
    bundles = []
    if os.path.isdir(assets):
        bundles = [os.path.join(assets, name) for name in sorted(os.listdir(assets))
                   if name.endswith((".js", ".css"))]
    _expect(checks, "bundle files were emitted", len(bundles) > 0,
            "files=%d" % len(bundles))
    if not bundles:
        return False

    blob = ""
    for path in bundles:
        try:
            with io.open(path, encoding="utf-8", errors="replace") as handle:
                blob += handle.read()
        except OSError:
            continue
    newest = max(os.path.getmtime(path) for path in bundles)

    # ---- the two palettes, and the rule that keeps them apart ----
    from pathlib import Path
    source = Path(ROOT, "frontend", "src", "components", "CityTrafficMap.vue").read_text(encoding="utf-8")

    import re
    risk = re.search(r"const RISK_COLORS=\{(.*?)\n\}", source, re.S)
    fixed = re.search(r"const FIXED_ZONE_COLORS=\{(.*?)\n\}", source, re.S)
    ratio, risk_block, fixed_block = 0, "", ""
    if risk and fixed:
        risk_block, fixed_block = risk.group(1), fixed.group(1)
        fixed_hex = re.findall(r"#[0-9a-f]{6}", fixed_block)
        risk_hex = re.findall(r"#[0-9a-f]{6}", risk_block)
        for fh in set(fixed_hex):
            for rh in set(risk_hex):
                fa = tuple(int(fh[i:i + 2], 16) for i in (1, 3, 5))
                ra = tuple(int(rh[i:i + 2], 16) for i in (1, 3, 5))
                rd = sum((a - b) ** 2 for a, b in zip(ra, fa)) ** 0.5
                ratio = max(ratio, rd)

    _expect(checks, "risk palette and fixed-zone palette are far apart",
            bool(risk_block) and bool(fixed_block) and ratio > 150,
            "max RGB distance %.0f" % ratio)

    # The colour rule the legend and the banner both depend on. If this ever
    # fails, the map has started conflating a published legal boundary with this
    # system's own weather threshold.
    _expect(checks, "risk palette is warm and fixed palette is cool",
            bool(risk_block) and bool(fixed_block)
            and _is_warmist(risk_block) and _is_coolist(fixed_block),
            "risk warm=%s fixed cool=%s" % (_is_warmist(risk_block), _is_coolist(fixed_block)))

    # The bundle must post-date the source it was built from, otherwise the page
    # served to the operator does not contain the change under test.
    source_mtime = max(os.path.getmtime(os.path.join(ROOT, "frontend", "src", "components",
                                                     "CityTrafficMap.vue")),
                       os.path.getmtime(os.path.join(ROOT, "frontend", "src", "traffic",
                                                     "runtime.js")))
    _expect(checks, "bundle is not older than the traffic sources",
            newest >= source_mtime - 1.0,
            "bundle %.0f vs source %.0f" % (newest, source_mtime))

    return ok


def _is_warmist(block):
    hexes = __import__("re").findall(r"#[0-9a-f]{6}", block)
    if not hexes:
        return False
    total = 0.0
    for value in hexes:
        red, green, blue = (int(value[i:i + 2], 16) for i in (1, 3, 5))
        total += (red - blue)
    return total / len(hexes) > 40


def _is_coolist(block):
    hexes = __import__("re").findall(r"#[0-9a-f]{6}", block)
    if not hexes:
        return False
    total = 0.0
    for value in hexes:
        red, green, blue = (int(value[i:i + 2], 16) for i in (1, 3, 5))
        total += (blue - red)
    return total / len(hexes) > 40


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

FLOWS = (
    ("http-contract", flow_http_contract, 30),
    ("weather-payload", flow_weather_payload, 60),
    ("weather-geometry", flow_weather_geometry, 120),
    ("band-coverage", flow_band_coverage, 180),
    ("session-lifecycle", flow_session_lifecycle, 300),
    ("frontend-build", flow_frontend_build, 15),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="run only flows whose name contains this substring")
    parser.add_argument("--verbose", action="store_true", help="echo every passing check")
    parser.add_argument("--timeout", type=float, default=420.0,
                        help="whole-run cap in seconds (default 420)")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    started = time.monotonic()
    deadline = started + args.timeout

    sys.path.insert(0, BACKEND)

    results = []
    for name, runner, budget in FLOWS:
        if args.only and args.only not in name:
            continue
        checks = []
        began = time.monotonic()
        try:
            if runner is flow_session_lifecycle:
                runner(checks, args.verbose, deadline)
            else:
                runner(checks, args.verbose)
        except Exception:  # noqa: BLE001 - a crash is a failed flow, never a stopped run
            checks.append(Check("flow raised", False,
                                traceback.format_exc().strip().split("\n")[-1][:160]))
        results.append((name, checks, time.monotonic() - began, budget))

    lines = []
    failures = []
    for name, checks, elapsed, budget in results:
        failed = [c for c in checks if not c.ok]
        status = "PASS" if not failed else "FAIL"
        lines.append("%-4s %-20s %5.1fs  %2d/%2d checks" %
                     (status, name, elapsed, len(checks) - len(failed), len(checks)))
        for check in checks:
            if check.ok and args.verbose:
                lines.append("       . %s" % check.name)
            elif not check.ok:
                lines.append("       ! %s -- %s" % (check.name, check.detail))
        failures.extend((name, check) for check in failed)

    total = time.monotonic() - started
    lines.append("")
    lines.append("%d flow(s) in %.1fs (cap %.0fs)" % (len(results), total, args.timeout))

    with io.open(REPORT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")

    for line in lines:
        print(line)

    if failures:
        print()
        print("SMOKE FLOWS FAIL -- %d check(s) across %d flow(s)" %
              (len(failures), len({name for name, _c in failures})))
        return 1
    print()
    print("SMOKE FLOWS PASS -- every flow satisfied its pass criteria")
    return 0


if __name__ == "__main__":
    sys.exit(main())
