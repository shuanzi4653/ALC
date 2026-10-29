"""Reorganise the repository root: sort the underscore scripts into tools/.

Every ``_*.py`` in the root is a development instrument the project actually
ships -- they are not gitignored, and several are cited by the evidence documents
as the tools that produced the numbers. So this is a move, not a delete, and the
classification has to be right or the citations break.

The classes come from what each script does:

  generators  write a document under docs/ or contracts/      (_gen_*, _rerun_*)
  runners     run a test or build suite                       (_run_*, _build_*)
  benches     measure a cost or a budget                      (_bench_*, _measure_*, _profile_*)
  harness     drive the three services end to end             (_sim_*, _start_*, _wait_*, _verify_*)
  recon       one-off reconnaissance of external data         (_recon_*)
  probes      everything else: a single question answered by measurement

``git mv`` was tried first and does not work here: these files exist on disk but
were never added to the index, so git refuses to move them. A plain rename is
correct -- the move is within the same repository and nothing about the content
changes. The running total is verified afterwards and any script that did not
land in a known class is reported rather than silently left behind.
"""


import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
def classify(name):
    stem = name[:-3]  # strip .py
    if stem.startswith(('_gen_', '_rerun_')):
        return 'generators'
    if stem.startswith(('_run_', '_build_')):
        return 'runners'
    if stem.startswith(('_bench_', '_measure_', '_profile_')):
        return 'benches'
    if stem.startswith(('_sim_', '_start_', '_wait_', '_verify_', '_test_strict')):
        return 'harness'
    if stem.startswith('_recon_'):
        return 'recon'
    if stem.startswith(('_probe_', '_diag_', '_scan_', '_smoke_', '_ab_')):
        return 'probes'
    if stem.startswith(('_append_', '_reorganise_')):
        # Maintenance scripts for this repository itself, not evidence tools.
        return 'maintenance'
    return None


def main():
    os.makedirs(os.path.join(ROOT, 'tools', 'maintenance'), exist_ok=True)
    scripts = sorted(name for name in os.listdir(ROOT)
                     if name.startswith('_') and name.endswith('.py')
                     and os.path.isfile(os.path.join(ROOT, name)))
    print(f'found {len(scripts)} underscore scripts in the root')

    unknown = []
    moved = {}
    for name in scripts:
        if name == '_reorganise_root.py':
            continue  # this very script; moved by hand at the end
        bucket = classify(name)
        if bucket is None:
            unknown.append(name)
            continue
        directory = os.path.join(ROOT, 'tools', bucket)
        os.makedirs(directory, exist_ok=True)
        os.rename(os.path.join(ROOT, name), os.path.join(directory, name))
        moved.setdefault(bucket, []).append(name)

    print()
    for bucket in sorted(moved):
        print(f'tools/{bucket}/  ({len(moved[bucket])})')
        for name in moved[bucket]:
            print(f'    {name}')
    if unknown:
        print()
        print('未分类（保留在根目录，需人工判断）:')
        for name in unknown:
            print(f'    {name}')

    left = sorted(name for name in os.listdir(ROOT)
                  if name.startswith('_') and name.endswith('.py'))
    print()
    print(f'根目录剩余 _*.py: {len(left)}  {left}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

