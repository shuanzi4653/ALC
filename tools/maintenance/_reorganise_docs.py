"""Move historical reports and generated artifacts out of the repository root.

Two groups, both real files that must be preserved rather than deleted:

* **plan / completion documents** -- the per-version ``UPDATE_*`` and
  ``FINAL_MAJOR_UPDATE_PLAN_V1.0`` files. They are the primary source for the
  changelog, so they are gathered under ``archive/plans`` and
  ``archive/completions`` by kind, not by version, and stay readable.
* **generated JSON artifacts** -- the ``_*.json`` outputs of the benchmark and
  simulation scripts. These are working data, not evidence (evidence lives in
  ``docs/evaluation-*``), so they go to ``artifacts/``. The large simulation
  dumps are the main reason the root listing was unreadable.

``README.md``, ``VERSION`` and the batch launchers stay where they are: they are
entry points, not history.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import shutil


# Documents: (filename, destination directory)
DOCUMENTS = [
    ('UPDATE_PLAN_2026-09-11.md', 'archive/plans'),
    ('UPDATE_PLAN_2026-09-12_V0.12.md', 'archive/plans'),
    ('UPDATE_PLAN_V1.3.md', 'archive/plans'),
    ('UPDATE_PLAN_V1.4.md', 'archive/plans'),
    ('FINAL_MAJOR_UPDATE_PLAN_V1.0.md', 'archive/plans'),
    ('CODING_PLAN.md', 'archive/plans'),
    ('OPTIMIZATION_PLAN.md', 'archive/plans'),
    ('UPDATE_COMPLETION_2026-09-11.md', 'archive/completions'),
    ('UPDATE_COMPLETION_2026-09-12_V0.12.md', 'archive/completions'),
    ('UPDATE_COMPLETION_V1.0.md', 'archive/completions'),
    ('UPDATE_COMPLETION_V1.1.md', 'archive/completions'),
    ('UPDATE_COMPLETION_V1.2.md', 'archive/completions'),
    ('UPDATE_COMPLETION_V1.3.md', 'archive/completions'),
    ('ALC_0.9续作完成报告.md', 'archive/legacy-reports'),
    ('ALC_完成度核查报告.md', 'archive/legacy-reports'),
]

# Keep these in the root: entry points and the version stamp.
KEEP = {'README.md', 'VERSION'}


def main():
    moved = []
    skipped = []

    for name, destination in DOCUMENTS:
        source = os.path.join(ROOT, name)
        if not os.path.isfile(source):
            skipped.append((name, 'not present'))
            continue
        target_dir = os.path.join(ROOT, destination)
        os.makedirs(target_dir, exist_ok=True)
        shutil.move(source, os.path.join(target_dir, name))
        moved.append((name, destination))

    # Generated artifacts: underscore-prefixed JSON in the root.
    artifact_dir = os.path.join(ROOT, 'artifacts')
    os.makedirs(artifact_dir, exist_ok=True)
    for name in sorted(os.listdir(ROOT)):
        if not (name.startswith('_') and name.endswith('.json')):
            continue
        source = os.path.join(ROOT, name)
        if not os.path.isfile(source):
            continue
        shutil.move(source, os.path.join(artifact_dir, name))
        moved.append((name, 'artifacts'))

    # The rendered radar check image is a probe output too.
    for name in ('_radar_tile_check.png',):
        source = os.path.join(ROOT, name)
        if os.path.isfile(source):
            shutil.move(source, os.path.join(artifact_dir, name))
            moved.append((name, 'artifacts'))

    print(f'moved {len(moved)} items')
    for name, destination in moved:
        print(f'  {destination}/  {name}')
    if skipped:
        print()
        print('not found (nothing to do):')
        for name, reason in skipped:
            print(f'  {name}: {reason}')

    print()
    print('=== root listing now ===')
    for name in sorted(os.listdir(ROOT)):
        kind = 'DIR ' if os.path.isdir(os.path.join(ROOT, name)) else '    '
        print(f'  {kind}{name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
