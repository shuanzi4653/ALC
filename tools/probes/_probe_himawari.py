"""Himawari-9 access probe and HSD calibration helper.

Written to answer three questions with observed bytes rather than recollection,
after the first attempt at guessing the HSD header layout from memory proved
wrong. Run it before touching the infrared channel; it prints what is actually
there.

  python _probe_himawari.py tree            # what product trees exist, how fresh
  python _probe_himawari.py frame           # sizes, cadence and latency of one time step
  python _probe_himawari.py decode          # download one B13 granule and report its layout

Findings as of 2026-09-16 (granule HS_H09_20260916_1000_B13_FLDK_R20_S0110):

  * the buckets answer anonymous HTTPS with HTTP 200; no credentials, no proxy
  * AHI-L2-FLDK-Clouds/CHGT is 736 MB per 10 min - not downloadable per frame
  * AHI-L1b-FLDK band 13 is 1.1-3.0 MB per segment, ~20 MB for a whole disk
  * the granule is bz2 of raw big-header + uint16 counts, fill value 65534
  * the counts are LITTLE-endian (the fill run reads `fe ff`, i.e. 0xFFFE)
  * frame the counts at 5500 wide and the fill mask shows a symmetric Earth
    limb, which is the signature of (550 rows x 5500 cols)

The header length and row width are NOT yet pinned to the byte. Until a
calibration test locks them, treat the decoder as unverified - see
docs/ir-cloud-track.md section 5.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
import bz2
import re
import struct
from datetime import datetime, timezone

import httpx


BASE = 'https://noaa-himawari9.s3.amazonaws.com/'
BASE8 = 'https://noaa-himawari8.s3.amazonaws.com/'
CACHE = os.path.join(ROOT, '.run', 'himawari_probe')
FILL = 65534


def listing(base, params):
    with httpx.Client(timeout=httpx.Timeout(30, connect=10), trust_env=False,
                      follow_redirects=True) as client:
        response = client.get(base, params=params)
        response.raise_for_status()
        return response.text


def prefixes(text):
    return re.findall(r'<Prefix>([^<]+)</Prefix>', text or '')


def objects(text):
    keys = re.findall(r'<Key>([^<]+)</Key>', text or '')
    sizes = re.findall(r'<Size>([^<]+)</Size>', text or '')
    stamps = re.findall(r'<LastModified>([^<]+)</LastModified>', text or '')
    keys += ['?'] * max(0, len(sizes) - len(keys))
    stamps += ['?'] * max(0, len(keys) - len(stamps))
    return list(zip(keys, sizes, stamps))


def human(size):
    try:
        value = float(size)
    except (TypeError, ValueError):
        return str(size)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return f'{value:.1f}{unit}' if unit != 'B' else f'{int(value)}B'
        value /= 1024


def cmd_tree():
    for name, base in (('himawari9', BASE), ('himawari8', BASE8)):
        text = listing(base, {'list-type': '2', 'delimiter': '/', 'max-keys': '40'})
        print(f'{name} trees:')
        for item in prefixes(text):
            if item.count('/') == 1:
                print(f'  {item}')
    return 0


def cmd_frame():
    now = datetime.now(timezone.utc)
    day = now.strftime('%Y/%m/%d')
    for tree in ('AHI-L2-FLDK-Clouds', 'AHI-L2-FLDK-Winds', 'AHI-L1b-FLDK'):
        text = listing(BASE, {'list-type': '2', 'delimiter': '/',
                              'prefix': f'{tree}/{day}/', 'max-keys': '200'})
        hours = sorted(p for p in prefixes(text) if p != f'{tree}/{day}/')
        if not hours:
            print(f'{tree}: no data for {day}')
            continue
        newest = hours[-1]
        text = listing(BASE, {'list-type': '2', 'delimiter': '/', 'prefix': newest})
        minutes = sorted(p for p in prefixes(text) if p != newest)
        leaf = minutes[-1] if minutes else newest
        text = listing(BASE, {'list-type': '2', 'prefix': leaf, 'max-keys': '200'})
        rows = [row for row in objects(text) if row[0] != leaf]
        print(f'{tree} @ {leaf}  ({len(rows)} objects)')
        for key, size, stamp in rows[:6]:
            print(f'  {key.split("/")[-1]}  {human(size)}  {stamp}')
        if len(rows) > 6:
            print(f'  ... {len(rows) - 6} more')
    return 0


def cmd_decode():
    day = datetime.now(timezone.utc).strftime('%Y/%m/%d')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d')
    keys = [row[0] for row in objects(listing(
        BASE, {'list-type': '2', 'prefix': f'AHI-L1b-FLDK/{day}/1000/HS_H09_{stamp}_1000_B13',
               'max-keys': '40'}))]
    keys = [key for key in keys if key.endswith('.bz2')]
    if not keys:
        print('no B13 granule for today; try cmd_tree to find a populated date')
        return 1
    os.makedirs(CACHE, exist_ok=True)
    local = os.path.join(CACHE, os.path.basename(keys[0]).replace('.bz2', ''))
    if os.path.exists(local):
        raw = open(local, 'rb').read()
        print(f'cached: {local}')
    else:
        with httpx.Client(timeout=httpx.Timeout(120, connect=10), trust_env=False) as client:
            packed = client.get(BASE + keys[0]).content
        raw = bz2.decompress(packed)
        open(local, 'wb').write(raw)
        print(f'downloaded {os.path.basename(keys[0])}: {len(packed)} bz2 -> {len(raw)} bytes')
    print(f'total bytes {len(raw)}  odd={len(raw) % 2 == 1}  (an odd total forces an odd header '
          f'or an odd trailer)')
    for header in (1523, 1604):
        shift = header - 1523
        subset = raw[header:]
        array = struct.unpack_from(f'<{len(subset) // 2}H', raw, header)
        fill_share = sum(1 for value in array if value == FILL) / max(1, len(array))
        print(f'  header={header}: fill share {fill_share:.1%}')
        del shift
    print('ASCII map at header=1523, width=5500 (correct limb is a symmetric widening arc):')
    import numpy as np
    array = np.frombuffer(raw[1523:1523 + 3025000 * 2], dtype='<u2')
    grid = (array != FILL).reshape(550, 5500).astype(float)
    blocks = grid.reshape(22, 25, 100, 55).mean(axis=(1, 3))
    for line in blocks:
        print('  ' + ''.join('#' if v > 0.6 else ('+' if v > 0.15 else '.') for v in line))
    return 0


COMMANDS = {'tree': cmd_tree, 'frame': cmd_frame, 'decode': cmd_decode}

if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else 'tree'
    if command not in COMMANDS:
        print(f'usage: {sys.argv[0]} {{{"|".join(COMMANDS)}}}')
        sys.exit(2)
    sys.exit(COMMANDS[command]())
