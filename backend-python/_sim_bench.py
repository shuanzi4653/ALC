import io, json, os, sys, time

sys.path.insert(0, os.getcwd())

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ARTIFACTS = os.path.join(ROOT, 'artifacts')
os.makedirs(ARTIFACTS, exist_ok=True)

t_import = time.perf_counter()
from traffic import service            # noqa: E402
import_seconds = time.perf_counter() - t_import

results = {'importSeconds': round(import_seconds, 3)}

t0 = time.perf_counter()
first = service.simulate(42, 'live')
results['simulateColdSeconds'] = round(time.perf_counter() - t0, 3)
results['firstFlights'] = len(first['flights'])

t0 = time.perf_counter()
second = service.simulate(42, 'live')
results['simulateWarmSeconds'] = round(time.perf_counter() - t0, 3)
results['secondFlights'] = len(second['flights'])

results['identicalFingerprint'] = first['fingerprint'] == second['fingerprint']
results['identicalFlightIds'] = [f['id'] for f in first['flights']] == [f['id'] for f in second['flights']]
results['identicalPoints'] = [f['points'] for f in first['flights']] == [f['points'] for f in second['flights']]
results['stats'] = first.get('stats')
results['layerUsage'] = first.get('layerUsage')

with io.open(os.path.join(ARTIFACTS, '_sim_bench.json'), 'w', encoding='utf-8') as fh:
    json.dump(results, fh, ensure_ascii=False, indent=2)

print(json.dumps(results, ensure_ascii=False, indent=2))
