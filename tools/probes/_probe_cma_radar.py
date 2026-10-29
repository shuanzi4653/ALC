"""Verify the unauthenticated CMA radar tile endpoint before building on it.

A research agent reported this URL serves tiles without login. That claim is
the foundation of the whole "use real weather data" plan, so it is re-tested
here rather than trusted. Every check prints the raw evidence.

The tile format is the interesting part: it is NOT an image. It is a raw
256x256 big-endian int16 grid where value * 0.1 is dBZ and 32767 is missing,
stored with the rows upside down. That is checked against a tile's own bytes.
"""
import datetime as dt
import struct
import urllib.request
import urllib.error

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

TEMPLATE = ('https://image.data.cma.cn/tiles/China/RADAR_L3_MST_CREF_GISJPG_Tiles_CR/'
            '{date}/{hh}/{mm}/{z}/{y}/{x}.bin')

# Recent times, walking back in 6-minute steps (the product cadence).
now = dt.datetime.now(dt.timezone.utc)
print(f'now (UTC) = {now:%Y-%m-%d %H:%M}')
print()

found = []
for step in range(0, 40):
    stamp = now - dt.timedelta(minutes=6 * step)
    # Round down to the 6-minute grid the product is published on.
    minute = (stamp.minute // 6) * 6
    url = TEMPLATE.format(date=f'{stamp:%Y%m%d}', hh=f'{stamp:%H}',
                          mm=f'{minute:02d}', z=3, y=3, x=6)
    request = urllib.request.Request(url, headers={'User-Agent': 'ALC-verify/1.0'})
    try:
        with OPENER.open(request, timeout=15) as response:
            body = response.read()
            print(f'{stamp:%Y-%m-%d %H:%M}  {response.status}  '
                  f'{len(body):>7} bytes  {response.headers.get("Content-Type")}')
            found.append((stamp.strftime('%Y-%m-%d %H:%M'), url, body))
            if len(found) >= 3:
                break
    except urllib.error.HTTPError as error:
        print(f'{stamp:%Y-%m-%d %H:%M}  HTTP {error.code}')
    except Exception as error:  # noqa: BLE001
        print(f'{stamp:%Y-%m-%d %H:%M}  {type(error).__name__}: {error}')

if not found:
    raise SystemExit('\nno tile found -- the endpoint is NOT usable as reported')

label, url, body = found[0]
print()
print('=== decoding the first fetched tile ===')
print(f'url = {url}')
print(f'bytes = {len(body)}  (expect 256*256*2 = {256 * 256 * 2})')

values = struct.unpack(f'>{len(body) // 2}h', body)
missing = sum(1 for v in values if v == 32767)
finite = [v for v in values if v != 32767]
print(f'grid = 256x256 = {len(values)} values')
print(f'missing (32767) = {missing}  ({missing / len(values):.1%})')
if finite:
    dbz = [v * 0.1 for v in finite]
    print(f'dBZ range over present cells = {min(dbz):.1f} .. {max(dbz):.1f}')
    # A radar mosaic over land is mostly clear air; a meaningful echo fraction
    # well below 100% is what shows the grid is really reflectivity and not noise.
    echo = [d for d in dbz if d >= 15.0]
    print(f'cells >= 15 dBZ = {len(echo)} ({len(echo) / len(values):.2%}) of the tile')

print()
print(f'usable tiles found: {len(found)} at {", ".join(t for t, _, _ in found)}')
