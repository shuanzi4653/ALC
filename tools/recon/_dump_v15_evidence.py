"""Dump the v1.5 evidence blocks that the evidence index needs.

Recon script: read-only, prints JSON to stdout, writes nothing.
"""

import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
import io
import json


SRC = os.path.join(ROOT, "docs", "evaluation-v1.5", "risk-merge-and-flat-render.json")

with io.open(SRC, encoding="utf-8") as handle:
    data = json.load(handle)

for key in ("rejectedSatelliteVariant", "crossings", "rainBand", "alignment", "uiLayout"):
    print("=== " + key)
    print(json.dumps(data.get(key), ensure_ascii=False, indent=1)[:2600])
    print()
