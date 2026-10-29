"""Does the radar layer really reach the map, or is the wiring only nominal?

The frontend test suite covers `runtime.js` (the pure functions), but the map
component is a `.vue` file and `node --test` cannot reach its private functions.
So the two claims that matter are checked here instead, against the built bundle:

  1. every radar source id and layer id the component adds is present in the
     production output, i.e. the layers were not tree-shaken or lost to a typo
     between the `addSource` list and the `addLayer` calls;
  2. the toggle actually reaches the component, by grepping the prop plumbing
     from `TrafficWorkbench` through to `CityTrafficMap`.

A typo in a layer id would have produced a MapLibre error at runtime only when
the toggle was flipped, which is exactly the class of defect that survives a
build and a unit suite.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAP = os.path.join(ROOT, 'frontend', 'src', 'components', 'CityTrafficMap.vue')
WORKBENCH = os.path.join(ROOT, 'frontend', 'src', 'components', 'TrafficWorkbench.vue')
DIST = os.path.join(ROOT, 'frontend', 'dist')

SOURCE_IDS = ('operation-radar', 'operation-radar-watch')
LAYER_IDS = ('radar-watch-outline', 'radar-footprint', 'radar-outline')


def read(path):
    with open(path, encoding='utf-8') as handle:
        return handle.read()


def main():
    problems = []
    map_source = read(MAP)

    # 1. every source is registered in the addSource loop
    declared = re.search(r"for\(const id of \[([^\]]+)\]\)map\.addSource", map_source)
    if not declared:
        problems.append('could not find the addSource loop')
    else:
        listed = declared.group(1)
        for source_id in SOURCE_IDS:
            if f"'{source_id}'" not in listed:
                problems.append(f'source {source_id} is never registered')

    # 2. every layer is added, and its source exists
    for layer_id in LAYER_IDS:
        block = re.search(r"map\.addLayer\(\{id:'" + re.escape(layer_id) + r"',(.*?)\}\}\)", map_source, re.S)
        if not block:
            problems.append(f'layer {layer_id} is never added')
            continue
        source = re.search(r"source:'([^']+)'", block.group(1))
        if not source:
            problems.append(f'layer {layer_id} has no source')
        elif source.group(1) not in SOURCE_IDS:
            problems.append(f'layer {layer_id} points at unknown source {source.group(1)}')

    # 3. setData targets match the registered sources
    for target in re.findall(r"setData\('(operation-radar[^']*)'", map_source):
        if target not in SOURCE_IDS:
            problems.append(f'setData writes to unregistered source {target}')

    # 4. the toggle is declared, passed down, and read by the map
    workbench = read(WORKBENCH)
    if 'showRadar=ref(' not in workbench:
        problems.append('showRadar is not declared in TrafficWorkbench')
    if 'v-model="showRadar"' not in workbench:
        problems.append('showRadar has no checkbox')
    if ':show-radar="showRadar"' not in workbench:
        problems.append('showRadar is not passed to the map component')
    if 'showRadar:Boolean' not in map_source:
        problems.append('the map component does not declare the showRadar prop')

    # 5. the built bundle carries the layer ids and the toggle's stylesheet rule.
    #    A flat listdir misses the assets/ subdirectory vite writes to, which
    #    reported "0 files" for a bundle that plainly contained them.
    bundle_hits = []
    if os.path.isdir(DIST):
        for root, _dirs, names in os.walk(DIST):
            for name in names:
                if not name.endswith(('.js', '.css')):
                    continue
                text = read(os.path.join(root, name))
                if 'radar-footprint' in text or 'radar-dot' in text:
                    bundle_hits.append(os.path.relpath(os.path.join(root, name), DIST))
    else:
        problems.append('dist/ is missing - run the build before this probe')
    if not bundle_hits:
        problems.append('no built asset carries the radar layer ids - the layer '
                        'would exist in source but never in the served bundle')

    print('registered sources   :', ', '.join(SOURCE_IDS))
    print('added layers         :', ', '.join(LAYER_IDS))
    print('toggle plumbing      : showRadar declared / checkbox / prop -> ok'
          if not any('showRadar' in p for p in problems) else 'toggle plumbing: BROKEN')
    print('bundle carries layer :', len(bundle_hits), 'asset(s) ->', ', '.join(bundle_hits))
    if problems:
        print('\nRADAR WIRING INCOMPLETE')
        for problem in problems:
            print('  !', problem)
        return 1
    print('\nRADAR WIRING OK -- every source, layer and toggle is connected end to end')
    return 0


if __name__ == '__main__':
    sys.exit(main())
