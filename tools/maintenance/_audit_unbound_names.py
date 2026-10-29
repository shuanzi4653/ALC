"""Find module-level names a tool uses but never binds, using the real AST.

Why the previous scanner missed `_gen_fixed_zones.py`:
    `_restore_imports.py` scans a *literal-stripped* body (it removes strings and
    docstrings to avoid false positives). `io.StringIO` on line 211 sits in normal
    code, so stripping was not the problem -- the problem was that stripping is
    done with a regex that also removed a chunk of real code, and the module-name
    regex then never saw `io.`. Rather than debug a text scanner that has now
    produced two false negatives, I use the AST: parse the file, collect every
    module-scope Name binding, collect every Name load, and diff.

This is the same conservative test I want for any file, so it doubles as the
gate the apply driver should run after rewriting.
"""
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from _repo import ROOT  # noqa: E402
import ast
import io

# Names the interpreter provides for free in any module.
BUILTINS = set(dir(__builtins__)) if isinstance(__builtins__, type(os)) else set(dir(__builtins__)) if isinstance(__builtins__, dict) else set()
if isinstance(__builtins__, dict):
    BUILTINS = set(__builtins__.keys())
else:
    BUILTINS = set(dir(__builtins__))

STDLIB = {
    'os', 'sys', 'io', 'json', 're', 'math', 'time', 'random', 'subprocess',
    'pathlib', 'hashlib', 'shutil', 'tempfile', 'collections', 'itertools',
    'functools', 'datetime', 'csv', 'glob', 'textwrap', 'typing', 'unittest',
    'sqlite3', 'struct', 'base64', 'gzip', 'zipfile', 'argparse', 'logging',
    'traceback', 'warnings', 'statistics', 'decimal', 'fractions', 'copy',
}

SKIP_DIRS = {'__pycache__'}


def iter_files():
    for base, dirs, names in os.walk(TOOLS):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in sorted(names):
            if name.endswith('.py'):
                yield os.path.join(base, name)


class Binding(ast.NodeVisitor):
    """Every name bound anywhere in the module (module OR function scope).

    Deliberately over-broad: a function-local `import io` satisfies a use two
    functions away. That produces false negatives, but it never produces a
    false positive, and a false positive here would mean editing working code.
    I want the cheap safe direction; the smoke test catches what slips through.
    """

    def __init__(self):
        self.bound = set()

    def visit_Import(self, node):
        for a in node.names:
            self.bound.add((a.asname or a.name).split('.')[0])

    def visit_ImportFrom(self, node):
        for a in node.names:
            self.bound.add(a.asname or a.name)

    def visit_FunctionDef(self, node):
        self.bound.add(node.name)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.bound.add(node.name)
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bound.add(node.id)
        self.generic_visit(node)

    def visit_arg(self, node):
        self.bound.add(node.arg)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_Global(self, node):
        self.bound.update(node.names)

    def visit_Nonlocal(self, node):
        self.bound.update(node.names)

    def visit_comprehension(self, node):
        self.generic_visit(node)

    def visit_Lambda(self, node):
        self.generic_visit(node)

    def visit_alias(self, node):
        pass


def bindings(tree):
    b = Binding()
    b.visit(tree)
    return b.bound


class Uses(ast.NodeVisitor):
    """`mod.attr` references where `mod` is a stdlib module name."""

    def __init__(self):
        self.used = set()

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id in STDLIB:
            self.used.add(node.value.id)
        self.generic_visit(node)


def uses(tree):
    u = Uses()
    u.visit(tree)
    return u.used


def missing(text):
    """Sorted stdlib module names referenced as `mod.x` but never bound.

    Do NOT write `- STDLIB.intersection()` here. `set.intersection()` with no
    arguments returns a *copy of the receiver*, i.e. all of STDLIB, so the
    subtraction silently cancels every finding and the audit reports a clean
    tree while `_gen_fixed_zones.py` dies on `io` being unbound. This bug cost
    one full debug cycle because it produced a false negative, not an exception.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    return sorted(uses(tree) - bindings(tree))


def module_scope_uses_before_binding(text):
    """Names used at module scope *before* the line that binds them.

    Why the plain bound/used diff is not enough:
        `_measure_airport_impact.py` had `import io` on line 110 and
        `io.StringIO(...)` on line 41. Every name is bound *somewhere*, so the
        set-difference audit reported the file clean -- while running it raised
        `NameError: name 'io' is not defined`, because Python executes top to
        bottom. "Bound in the file" and "bound by the time the use executes" are
        different properties, and only the second one keeps the script running.

    Scope modelling: walk module-level statements in order. A Name load is
    checked against what has been bound so far. A function or class body is
    *entirely* skipped -- its name binds when the def executes, and its body runs
    later, after any local imports inside it have taken effect. Reporting a load
    inside a body against module-scope state is a false positive: it fires on
    `build_navigation_aids()` because that function does `import math` on its own
    line 304 and uses `math.dist` at 326.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    findings = []
    bound_so_far = set()

    def binds_of(node):
        bound = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                for a in sub.names:
                    name = (a.asname or a.name).split('.')[0]
                    if name in STDLIB:
                        bound.add(name)
            elif isinstance(sub, ast.ImportFrom):
                for a in sub.names:
                    name = a.asname or a.name
                    if name in STDLIB:
                        bound.add(name)
        return bound

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # The def itself binds only its own name; the body is out of scope.
            bound_so_far.add(node.name)
            continue
        # Loads at this statement's own level. Descend into compound statements
        # (if/for/try at module scope) but never into a def/class body.
        uses = set()

        def scan(current):
            for child in ast.iter_child_nodes(current):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.ClassDef, ast.Lambda)):
                    continue
                if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                    if child.value.id in STDLIB:
                        uses.add(child.value.id)
                scan(child)

        scan(node)
        for name in sorted(uses - bound_so_far):
            findings.append((node.lineno, name))
        bound_so_far |= binds_of(node)
    return findings


def main():
    rows = []
    order_rows = []
    for path in iter_files():
        try:
            text = io.open(path, encoding='utf-8').read()
        except (OSError, UnicodeDecodeError):
            continue
        miss = missing(text)
        if miss:
            rows.append((os.path.relpath(path, TOOLS), miss))
        late = module_scope_uses_before_binding(text)
        if late:
            order_rows.append((os.path.relpath(path, TOOLS), late))

    print('files with unbound stdlib references:', len(rows))
    for rel, miss in rows:
        print('  %-46s %s' % (rel, ', '.join(miss)))
    print()
    print('files using a stdlib name before its import:', len(order_rows))
    for rel, late in order_rows:
        detail = '; '.join('line %d uses %s' % (line, name) for line, name in late[:4])
        print('  %-46s %s' % (rel, detail))


if __name__ == '__main__':
    main()
