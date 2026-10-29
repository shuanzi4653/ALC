"""Which algorithm constructs a running request can actually reach.

Why this exists
---------------
`docs/paper-innovations.md` lists the innovations with a "unique implementation
site" and `docs/algorithm-spec.md` §1 indexes them. Neither said whether the
**running service** reaches those sites -- and the answer is not "all of them".

The first version of this probe answered from the **module** import graph, and it
was not good enough. `def` executes at module level and binds a name; it does not
run the body. So a module being in the closure says nothing about whether a
function inside it is ever called. That version reported `NetworkWeather._band_hull`
as reachable -- because `traffic/weather.py` is imported, and the name `_band_hull`
appears inside it -- when in fact the class `NetworkWeather` is referenced by no
executable statement outside the tests. A verdict that cannot tell "imported"
from "called" is the wrong instrument for the question, and the wrong verdict was
reachable-looking, i.e. it failed in the direction that flatters the project.

So this version builds a **scope-level call graph**:

  * nodes are scopes -- `(module, '')` for module level, `(module, 'Class.method')`
    for everything else;
  * an edge A -> B exists when a reference to B occurs inside A, where a bare name
    resolves through the scope chain and `self.x` / `cls.x` resolves to the
    enclosing class;
  * roots are `main.py`'s module scope plus every **decorated** function in
    `main.py` (a decorator is how a handler is handed to the framework; nothing
    else references it);
  * importing a module creates an edge to that module's scope, because the import
    *does* execute the module body.

`__main__` is not special: nothing at module level "calls" a function, so a
function that nothing references is unreachable no matter how public it looks.

What it does not resolve, and why that is reported
--------------------------------------------------
`obj.method()` where `obj` is neither a module, a `self`/`cls`, nor a local
assigned directly from a constructor call is **not resolvable** without type
inference. Those references are dropped rather than guessed, and the count is
printed. It is printed because a small count means the verdicts are trustworthy
and a large one means they are not -- the reader should not have to take that on
faith. The fallback deliberately does **not** match on the bare method name: an
unresolved `.shapes(` would then light up `NetworkWeather.shapes` as well as
`PublicWeather.shapes` and the one distinction this probe exists to draw would
be gone.

What it measures, and what it does not
--------------------------------------
It measures *nominal* reachability: a path exists from a request handler to the
scope. It does not prove the path is taken on any particular scenario, and it
does not prove the numbers are right -- that is the behavioural tests. Verdicts
are worded 可达 / 不可达, never "已执行".

`tests/` is skipped on purpose: a construct reached only by a test is reached by
no running endpoint, which is exactly the distinction being drawn. The `tools/`
tree is outside `BACKEND` and is not walked at all.

Exit codes (three, deliberately -- see M60):
  0  measured: every target got a verdict
  1  measured, and a target the index places at a site that does not exist. That
     is the one case where the probe has failed to look at the right thing. A
     target nothing reaches is **not** an error -- it is the finding.
  2  could not measure: `main.py` missing or unparseable, or the two control
     symbols came back the same, i.e. the instrument cannot discriminate and every
     other number is noise.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND  # noqa: E402
import ast

ENTRY = 'main'
SKIP_DIRS = {'.venv', 'tests', '__pycache__', '.mypy_cache', '.pytest_cache'}
SCOPE_EXTS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

# (label, module, symbol), symbol = module-level name or `Class.member`.
#
# The list is deliberately flat and mixes both sides of the question. Which of
# these run is the *output*; writing the expected grouping in here would be
# assuming the conclusion.
TARGETS = [
    # -- the algorithm that a request actually reaches ------------------------
    ('合成回波帧生成', 'traffic.weather_sim', 'frame'),
    ('反向外层循环（按单体包围盒）', 'traffic.weather_sim', '_raster'),
    ('单体状态单一派生点', 'traffic.weather_sim', '_cell_state'),
    ('谐波方位扰动', 'traffic.weather_sim', '_texture'),
    ('单源连续平流', 'traffic.weather_sim', '_advection'),
    ('队列相位分组', 'traffic.weather_sim', '_cohort_phase'),
    ('沿网络主轴布带', 'traffic.weather_sim', '_band_placement'),
    ('回波帧派生', 'traffic.radar_field', 'derive'),
    ('分级屏蔽几何', 'traffic.radar_field', 'shield'),
    ('同源分层内核（收缩）', 'traffic.radar_field', '_erode_to_core'),
    ('内核收缩常数', 'traffic.radar_field', 'CORE_INSET_M'),
    ('逐窗口扫掠并集', 'traffic.service', '_radar_window_union'),
    ('两级两规则（擦边深度）', 'traffic.service', '_radar_penetration_limit'),
    ('航路成因判定', 'traffic.service', '_route_basis'),
    ('虚拟回波扫掠', 'traffic.service', '_virtual_radar_sweep'),
    ('分级规则发布', 'traffic.service', '_radar_rule_block'),
    ('实测通道包裹类', 'traffic.weather', 'PublicWeather'),
    ('点观测派生', 'traffic.weather', 'point_risk_shapes'),
    ('证据约束问答降级', 'traffic.operations', 'explain'),
    ('气象快照单一入口', 'traffic.weather_sources', 'weather_snapshot'),
    # -- the model that is retained as a geometry fixture ---------------------
    ('保留气象模型', 'traffic.weather', 'NetworkWeather'),
    ('谐波轮廓抽样（保留模型）', 'traffic.weather', 'cell_outline_params'),
    ('凸包剪枝（保留模型）', 'traffic.weather', 'NetworkWeather._band_hull'),
    ('单一运动源（保留模型）', 'traffic.weather', 'NetworkWeather.centre_at'),
    ('扫掠时间窗（保留模型）', 'traffic.weather', 'NetworkWeather._swept_window'),
]

# Controls. The first two must come out different; if they come out the same the
# probe cannot discriminate and every other verdict is noise.
#
# The second pair is here for a more specific reason. "NetworkWeather is
# unreachable" is only trustworthy if the probe can resolve `instance.method()`
# at all -- if it dropped every attribute call on a local object, everything
# would look unreachable and the finding would be an artefact of the instrument.
# Both classes have a `shapes`, both are constructed in a local, and only one of
# them is instantiated on a running path, so the pair tests exactly that.
CONTROLS = [
    ('正向对照：被处理器调用的派生入口', 'traffic.radar_field', 'derive', True),
    ('负向对照：只存在于代码与测试里的名字', 'traffic.weather', 'NetworkWeather', False),
    ('实例解析对照：实测通道的 shapes', 'traffic.weather', 'PublicWeather.shapes', True),
    ('实例解析对照：保留模型的 shapes', 'traffic.weather', 'NetworkWeather.shapes', False),
]


def module_name(path):
    rel = os.path.relpath(path, BACKEND).replace(os.sep, '/')
    return rel[:-3].replace('/', '.')


def collect():
    """module name -> (path, parsed tree) for every non-test python file."""
    found = {}
    for current, dirnames, filenames in os.walk(BACKEND):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for name in filenames:
            if not name.endswith('.py'):
                continue
            path = os.path.join(current, name)
            try:
                with open(path, encoding='utf-8') as handle:
                    found[module_name(path)] = (path, ast.parse(handle.read(), filename=path))
            except (OSError, SyntaxError) as error:
                print('could not parse %s: %s' % (path, error))
                return None
    return found


def qualify(parent, name):
    return (parent + '.' + name) if parent else name


def relative_base(module, node):
    """Module an `ImportFrom` resolves against, honouring the leading dots."""
    if not node.level:
        return node.module or ''
    base = module.rsplit('.', 1)[0] if '.' in module else ''
    for _ in range(node.level - 1):
        base = base.rsplit('.', 1)[0] if '.' in base else ''
    return (base + '.' + node.module) if node.module else base


scopes = {}          # (module, qualname) -> scope dict
unresolved = []      # (module, qualname, spelling) for references we cannot resolve


def walk_body(module, qualname, body, enclosing_class, params=()):
    scope = {'module': module, 'qualname': qualname, 'class': enclosing_class,
             'binds': {}, 'refs': [], 'imports': {}, 'ctors': {}}
    scopes[(module, qualname)] = scope
    for param in params:
        scope['binds'][param] = 'var'

    def visit(node):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Store):
                scope['binds'].setdefault(node.id, 'var')
            else:
                scope['refs'].append(('name', node.id, None))
            return
        if isinstance(node, ast.Attribute):
            # `holder.attr`. Resolvable when the holder is a plain name; the
            # resolution step decides what that name is.
            scope['refs'].append(('attr', node.value.id if isinstance(node.value, ast.Name)
                                  else None, node.attr))
            if not isinstance(node.value, ast.Name):
                visit(node.value)
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split('.')[0]
                scope['binds'][local] = 'module'
                scope['imports'][local] = ('module', alias.name if alias.asname
                                           else alias.name.split('.')[0])
            return
        if isinstance(node, ast.ImportFrom):
            base = relative_base(module, node)
            for alias in node.names:
                if alias.name == '*':
                    continue
                local = alias.asname or alias.name
                target = ((base + '.' + alias.name) if base else alias.name)
                if target in modules:
                    scope['binds'][local] = 'module'
                    scope['imports'][local] = ('module', target)
                else:
                    scope['binds'][local] = 'symbol'
                    scope['imports'][local] = ('symbol', base, alias.name)
            return
        if isinstance(node, SCOPE_EXTS):
            # The `def` itself binds the name; it does **not** run the body, so
            # no edge is added here. Only a *reference* to the name reaches it.
            scope['binds'][node.name] = 'scope'
            for decorator in node.decorator_list:
                visit(decorator)
            if isinstance(node, ast.ClassDef):
                for base_node in node.bases:
                    visit(base_node)
                for keyword in node.keywords:
                    visit(keyword.value)
                walk_body(module, qualify(qualname, node.name), node.body, qualify(qualname, node.name))
            else:
                arguments = node.args
                for default in list(arguments.defaults) + [d for d in arguments.kw_defaults if d]:
                    visit(default)
                names = [a.arg for a in (list(arguments.posonlyargs) + list(arguments.args)
                                         + list(arguments.kwonlyargs))]
                walk_body(module, qualify(qualname, node.name), node.body, enclosing_class, names)
            return
        if isinstance(node, (ast.Global, ast.Nonlocal, ast.Lambda)):
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    # Second pass: `x = SomeClass(...)` so `x.method()` can be resolved to
    # `SomeClass.method`. Without this, every call through a local instance is
    # invisible and a whole live class reads as unreachable.
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Name):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    scope['ctors'][target.id] = (node.value.func.id, node)

    for statement in body:
        visit(statement)
    return scope


def find(module, qualname, name):
    """Resolve `name` through the scope chain. Returns a binding kind or None."""
    key = (module, qualname)
    while True:
        scope = scopes.get(key)
        if scope is None:
            return None
        if name in scope['binds']:
            return scope, scope['binds'][name]
        if not scope['qualname']:
            return None
        key = (module, scope['qualname'].rsplit('.', 1)[0]
               if '.' in scope['qualname'] else '')


def resolve_holder(module, qualname, holder, scope):
    """What does the name `holder` denote? ('module', M) | ('scope', key) | None.

    `('scope', key)` is how a class is denoted, so `holder.attr` can then be
    resolved to `Class.attr` -- which is the whole point, because it is what
    separates `PublicWeather.shapes` from `NetworkWeather.shapes`.
    """
    found = find(module, qualname, holder)
    if found is None:
        return None
    binding_scope, kind = found
    if kind == 'module':
        return ('module', binding_scope['imports'][holder][1])
    if kind == 'symbol':
        _tag, base, original = binding_scope['imports'][holder]
        return ('scope', (base, original))
    if kind == 'scope':
        owner = binding_scope['qualname']
        key = (module, qualify(owner, holder))
        if key in scopes:
            return ('scope', key)
    if kind == 'var' and holder in scope['ctors']:
        name, _node = scope['ctors'][holder]
        inner = find(module, qualname, name)
        if inner is not None:
            if inner[1] == 'scope':
                owner = inner[0]['qualname']
                key = (module, qualify(owner, name))
                if key in scopes:
                    return ('scope', key)
            elif inner[1] == 'symbol':
                _tag, base, original = inner[0]['imports'][name]
                return ('scope', (base, original))
    return None


def edges_of(module, qualname):
    """Scopes this scope references."""
    scope = scopes[(module, qualname)]
    out = set()
    for kind, holder, attr in scope['refs']:
        if kind == 'name':
            found = find(module, qualname, holder)
            if found is None:
                continue
            binding_scope, label = found
            if label == 'module':
                out.add((binding_scope['imports'][holder][1], ''))
            elif label == 'symbol':
                _tag, base, original = binding_scope['imports'][holder]
                out.add((base, original))
                out.add((base, ''))
            elif label == 'scope':
                owner = binding_scope['qualname']
                out.add((module, qualify(owner, holder)))
            continue
        # attribute access
        if holder in ('self', 'cls') and scope['class']:
            out.add((module, scope['class'] + '.' + attr))
            continue
        if holder is None:
            unresolved.append((module, qualname, '?.%s' % attr))
            continue
        if holder in scope['ctors']:
            source = resolve_holder(module, qualname, holder, scope)
            if source and source[0] == 'scope':
                out.add((source[1][0], source[1][1] + '.' + attr))
                continue
        source = resolve_holder(module, qualname, holder, scope)
        if source is None:
            unresolved.append((module, qualname, '%s.%s' % (holder, attr)))
            continue
        if source[0] == 'module':
            out.add((source[1], attr if (source[1], attr) in scopes else ''))
        elif source[0] == 'scope':
            out.add((source[1][0], source[1][1] + '.' + attr))
        else:
            out.add((source[1][0], source[1][1]))
            out.add((source[1][0], ''))
    return {key for key in out if key in scopes}


modules = collect()
if modules is None:
    sys.exit(2)
if ENTRY not in modules:
    print('cannot measure: no %s.py under %s' % (ENTRY, BACKEND))
    sys.exit(2)

for name, (_path, tree) in modules.items():
    walk_body(name, '', tree.body, None)

# Roots: the entry module's own body, plus every decorated function in it. A
# handler with `@app.get(...)` above it is referenced by the framework, not by a
# line of code, so the decorator is what makes it a root.
roots = {(ENTRY, '')}
for node in ast.walk(ast.Module(body=modules[ENTRY][1].body, type_ignores=[])):
    if isinstance(node, SCOPE_EXTS) and node.decorator_list:
        roots.add((ENTRY, node.name))

reachable = set()
frontier = list(roots)
while frontier:
    current = frontier.pop()
    if current in reachable or current not in scopes:
        continue
    reachable.add(current)
    for target in edges_of(*current):
        if target not in reachable:
            frontier.append(target)

SHOWN = {'reachable': '可达', 'unreachable': '不可达', 'unknown': '无法归属'}


def verdict(module, symbol):
    """(state, detail). `symbol` is a scope name, or a module-level binding."""
    if (module, symbol) in scopes:
        if (module, symbol) in reachable:
            return 'reachable', '被运行路径调用'
        return 'unreachable', '无运行路径引用'
    if module not in modules:
        return 'unknown', '模块不在后端树下'
    if symbol in scopes[(module, '')]['binds']:
        # A module-level binding (a constant, an alias). It is evaluated when the
        # module is imported, which is exactly what module-scope reachability says.
        if (module, '') in reachable:
            return 'reachable', '模块导入时求值'
        return 'unreachable', '模块不在运行路径上'
    return 'unknown', '该文件没有这个定义'


print('=== scope graph: %d scope(s) over %d module(s); %d root(s) ==='
      % (len(scopes), len(modules), len(roots)))
print('=== reachable: %d scope(s) ===' % len(reachable))
print('=== repo %s ===' % ROOT)
print('=== %s ===' % BACKEND)
print()

bad = 0
states = {}
for label, module, symbol in TARGETS:
    state, detail = verdict(module, symbol)
    states[(module, symbol)] = state
    if state == 'unknown':
        bad += 1
    print('%-30s %s' % (label, SHOWN[state]))
    print('    定义 %s::%s' % (module, symbol))
    print('    判据 %s' % detail)
    print()

print('=== controls ===')
control = []
for label, module, symbol, _expected in CONTROLS:
    state = verdict(module, symbol)[0]
    control.append(state)
    print('%-34s %s' % (label, SHOWN[state]))
if len(set(control[:2])) != 2:
    print('cannot measure: the two discriminating controls came back the same '
          '(%s). The probe does not distinguish reachable from unreachable.'
          % set(control[:2]))
    sys.exit(2)
for (label, _module, _symbol, expected), state in zip(CONTROLS, control):
    if (state == 'reachable') != expected:
        print('control failed: %s came back %s, expected %s'
              % (label, state, 'reachable' if expected else 'not reachable'))
        sys.exit(2)

# The unresolved count is printed rather than hidden because it bounds how much
# the verdicts are worth: an unresolved attribute call is a possible edge the
# probe did not draw. Most of them are stdlib and third-party objects, which is
# why the traffic-only figure is the one that matters.
inside = [row for row in unresolved if row[0].startswith('traffic.')]
print()
print('=== unresolved attribute references: %d (%d inside traffic/) ==='
      % (len(unresolved), len(inside)))
for module, qualname, spelling in sorted(inside)[:12]:
    print('    %s%s %s' % (module + ':' if qualname else module + '.', qualname, spelling))
if len(inside) > 12:
    print('    ... and %d more' % (len(inside) - 12))
print()

print()
print('=== who names the retained model (executable references only) ===')
# The graph above says the retained model is unreachable. That verdict depends on
# the graph being resolved well enough, and 598 references inside `traffic/` were
# dropped as unresolvable -- so this section answers the same question by a route
# that has no resolution step in it at all: count the statements that *name* the
# class. Reachability requires the name to appear somewhere; if it appears
# nowhere, that holds however many attribute calls went unresolved, and the
# verdict stops being a property of the instrument's quality.
for module, symbol in (('traffic.weather', 'NetworkWeather'),
                       ('traffic.weather', 'cell_outline_params'),
                       ('traffic.weather', 'NetworkWeather._band_hull')):
    bare = symbol.rsplit('.', 1)[-1]
    holders = sorted((mod, qual) for (mod, qual), scope in scopes.items()
                     for kind, left, right in scope['refs']
                     if (kind == 'name' and left == bare)
                     or (kind == 'attr' and right == bare))
    print('  %s::%s -> %d executable reference(s)' % (module, symbol, len(holders)))
    for mod, qual in holders[:10]:
        print('      %s : %s' % (mod, qual or '<module body>'))
print()

if bad:
    print('RESULT %d target(s) could not be attributed -- the index points '
          'somewhere this probe cannot see.' % bad)
    sys.exit(1)

counts = {}
for state in states.values():
    counts[state] = counts.get(state, 0) + 1
print('RESULT %d of %d target(s) reachable from a request handler (%s); both '
      'controls discriminated.'
      % (counts.get('reachable', 0), len(states),
         ', '.join('%d %s' % (counts[key], SHOWN[key])
                   for key in ('reachable', 'unreachable') if key in counts)))
sys.exit(0)
