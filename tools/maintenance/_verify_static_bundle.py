"""Prove that the built frontend bundle carries exactly one generation of assets.

Why this exists
---------------
`maven-resources-plugin` **copies** into `target/classes/static`, it does not
mirror. So a packaging run that is not preceded by `clean` merges the new bundle
on top of whatever the previous run left behind, and the JAR ships both. Measured
on the 0.9.31 build (see `.run/build-noinstall.ps1`): **6 orphan js/css files,
~9 MB**, sitting beside the real ones. Nothing failed. The build was "green".

Two things make that failure mode worth a check of its own:

* **It is silent.** A content-hashed file that nothing references produces no
  warning, no test failure, no runtime error -- it just rides along.
* **It is reachable by a plausible sequence**, not by an exotic one: any entry
  point that runs `package` without `clean` first will do it, and the two entry
  points in this repo only stopped doing it on 2026-10-15.

So the rule the check enforces is *not* "index.html references every file". That
criterion would be wrong here: `frontend/public/` files (`beian.png`) and the
worker chunk (`maplibre-gl-worker-*.js`) are referenced from *inside* the JS
bundle, never from the HTML. The rule is reachability across the whole bundle:

    every file under ``assets/`` must be named somewhere in the bundle itself
    (index.html + every .js / .css / .json shipped beside it)

An orphan generation is unreachable by construction -- nothing points at it,
because the thing that would have pointed at it was replaced by the new hash.

Classification
--------------
* ``ORPHAN``  unreferenced **and** content-hashed by the bundler -- damage, exit 1.
* ``UNREF``   unreferenced and *not* hashed (a stray `public/` file) -- a warning,
              because it can legitimately be intentional; does not fail.
* ``MISSING`` named by index.html but absent -- damage, exit 1.

Exit codes (three, because "nothing to measure" must not look like "measured
clean" -- see notes/2026-10-02-instrument-prerequisites-and-stale-controls.md):

    0  verified clean, or explicitly `-- skipped` when no bundle exists yet
    1  damage found
    2  could not measure (malformed arguments, unreadable archive)

``--self-test`` builds throw-away fixtures and asserts each verdict, including
that the clean fixture is *not* reported as damaged and the damaged one is not
reported as clean. A counter that cannot fail reads exactly like one that passed
(M29/M58), so the control is not optional here.
"""
import argparse
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402

STATIC_PREFIX_JAR = "BOOT-INF/classes/static/"
HASHED_ASSET_RE = re.compile(r"^.+-\w{8}\.(?:js|css)$")
TEXT_SUFFIXES = (".html", ".js", ".css", ".json", ".svg")
REFERENCE_RE = re.compile(r'(?:src|href)\s*=\s*"([^"]+)"')


class Bundle:
    """One built bundle, presented the same way whether it comes from a dir or a jar."""

    def __init__(self, label, files):
        # label: what to print; files: {posix path relative to the static root: bytes}
        self.label = label
        self.files = files

    def entries(self):
        return sorted(self.files)

    def text_of(self, name):
        try:
            return self.files[name].decode("utf-8", "replace")
        except KeyError:
            return ""


def load_dir(path):
    path = Path(path)
    files = {}
    for item in sorted(path.rglob("*")):
        if item.is_file():
            files[item.relative_to(path).as_posix()] = item.read_bytes()
    return Bundle(str(path), files)


def load_jar(path):
    with zipfile.ZipFile(path) as archive:
        files = {}
        for name in archive.namelist():
            if name.endswith("/") or not name.startswith(STATIC_PREFIX_JAR):
                continue
            files[name[len(STATIC_PREFIX_JAR):]] = archive.read(name)
    return Bundle(str(path), files)


def find_bundle(explicit=None):
    """Newest available product, preferring the JAR because that is what ships."""
    if explicit:
        return Path(explicit)
    target = Path(ROOT) / "backend-java" / "target"
    jars = sorted(target.glob("tianchuang-server-*.jar"), key=lambda p: p.stat().st_mtime)
    if jars:
        return jars[-1]
    classes_static = target / "classes" / "static"
    if (classes_static / "index.html").is_file():
        return classes_static
    dist = Path(ROOT) / "frontend" / "dist"
    if (dist / "index.html").is_file():
        return dist
    return None


def analyse(bundle):
    """Return (orphans, unref, missing). Pure -- takes a loaded bundle, so the
    self-test can drive it with fixtures instead of a real build.

    Two scan passes, because the two questions have different answers:

    * **orphan** -- applies to *any* file in the bundle, but only to names that
      look content-hashed. A hashed name has exactly one legitimate consumer: the
      referrer it was minted for. If nothing in the bundle names it, the referrer
      was replaced and this file is the previous generation.
    * **unref** -- applies to files under ``assets/`` only, and only to names that
      do *not* look hashed. Those come from ``frontend/public/`` (copied verbatim)
      and can legitimately be reached by a URL assembled at runtime, so they are
      a warning rather than damage.

    A file's own text never counts as a reference to itself, which is why the
    haystack is rebuilt without the candidate rather than computed once.
    """
    entries = bundle.entries()
    if "index.html" not in entries:
        raise ValueError("bundle has no index.html: " + bundle.label)

    texts = {name: bundle.text_of(name) for name in entries if name.endswith(TEXT_SUFFIXES)}

    referenced = set()
    for target in REFERENCE_RE.findall(bundle.text_of("index.html")):
        referenced.add(target.lstrip("/"))

    missing, orphans, unref = [], [], []
    for name in entries:
        if name in referenced or name == "index.html":
            continue
        basename = os.path.basename(name)
        haystack = "\n".join(text for other, text in texts.items() if other != name)
        if basename in haystack:
            continue
        if HASHED_ASSET_RE.match(basename):
            orphans.append(name)
        elif name.startswith("assets/"):
            unref.append(name)

    for target in sorted(referenced):
        if target not in entries:
            missing.append(target)

    return sorted(orphans), sorted(unref), sorted(missing)


def report(bundle, orphans, unref, missing):
    print("bundle           %s" % bundle.label)
    print("entries          %d" % len(bundle.entries()))
    print("orphans          %d" % len(orphans))
    print("unreferenceable  %d" % len(unref))
    print("missing          %d" % len(missing))
    for name in orphans:
        print("ORPHAN  %s" % name)
    for name in unref:
        print("UNREF   %s" % name)
    for name in missing:
        print("MISSING %s" % name)
    if orphans or missing:
        print("-- damaged")
        return 1
    print("-- ok")
    return 0


def verify(explicit=None):
    found = find_bundle(explicit)
    if found is None:
        # Not a failure: the gate runs on working trees where `target/` has just
        # been cleaned. It must not read as "checked and clean" either, so the
        # terminator is its own word and the gate's predicate only accepts the
        # two terms it means something by.
        print("bundle           ABSENT")
        print("-- skipped (no built bundle to verify)")
        return 0
    if explicit and not Path(explicit).exists():
        print("bundle           %s" % explicit)
        print("-- cannot measure (path does not exist)")
        return 2
    try:
        bundle = load_jar(found) if str(found).endswith(".jar") else load_dir(found)
        orphans, unref, missing = analyse(bundle)
    except (zipfile.BadZipFile, ValueError, OSError) as exc:
        print("bundle           %s" % found)
        print("-- cannot measure (%s)" % exc)
        return 2
    return report(bundle, orphans, unref, missing)


# --------------------------------------------------------------------------- #
# self-test
# --------------------------------------------------------------------------- #
def _write_fixture(root, entry_js, entry_css, extra_referenced=None):
    assets = Path(root) / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (Path(root) / "index.html").write_text(
        '<!DOCTYPE html><html><head>'
        '<script type="module" src="/assets/%s"></script>'
        '<link rel="stylesheet" href="/assets/%s">'
        "</head><body></body></html>" % (entry_js, entry_css),
        encoding="utf-8",
    )
    # The entry JS is the referrer for everything a page does not name directly.
    referrers = "".join(extra_referenced or ())
    (assets / entry_js).write_text(
        'console.log("app");' + referrers, encoding="utf-8")
    (assets / entry_css).write_text(".a{color:#fff}", encoding="utf-8")
    return assets


def self_test():
    failures = []
    root = Path(tempfile.mkdtemp(prefix="static-bundle-selftest-"))
    try:
        # --- 1. clean: the shipped shape, including a public/ file the HTML never
        #        names and a worker chunk only the JS names.
        clean = root / "clean"
        _write_fixture(clean, "index-AAAAAAAA.js", "index-BBBBBBBB.css",
                       extra_referenced=['"beian.png"', '"worker-CCCCCCCC.js"'])
        (clean / "assets" / "beian.png").write_bytes(b"\x89PNG")
        (clean / "assets" / "worker-CCCCCCCC.js").write_text("postMessage(1)",
                                                             encoding="utf-8")
        (clean / "build-info.json").write_text('{"buildId":"x"}', encoding="utf-8")
        got = report(load_bundle_for_test(clean), *analyse(load_dir(clean)))
        if got != 0:
            failures.append("clean fixture was reported as damaged")

        # --- 2. orphan: a previous generation of the entry chunk, exactly the
        #        0.9.31 shape (6 such files rode along in the JAR).
        orphan = root / "orphan"
        _write_fixture(orphan, "index-AAAAAAAA.js", "index-BBBBBBBB.css")
        (orphan / "assets" / "index-C8eg7WTr.js").write_text("stale", encoding="utf-8")
        orphans, _unref, _missing = analyse(load_dir(orphan))
        got = report(load_bundle_for_test(orphan), orphans, _unref, _missing)
        if got != 1 or orphans != ["assets/index-C8eg7WTr.js"]:
            failures.append("orphan generation not detected: %r" % (orphans,))

        # --- 3. missing: index.html names a stylesheet that is not there. Without
        #        this the check could pass by ignoring index.html entirely.
        missing_root = root / "missing"
        _write_fixture(missing_root, "index-AAAAAAAA.js", "index-BBBBBBBB.css")
        (missing_root / "assets" / "index-BBBBBBBB.css").unlink()
        _o, _u, missing = analyse(load_dir(missing_root))
        got = report(load_bundle_for_test(missing_root), _o, _u, missing)
        if got != 1 or missing != ["assets/index-BBBBBBBB.css"]:
            failures.append("missing asset not detected: %r" % (missing,))

        # --- 4. unref is a warning, not damage: must stay exit 0, or the check
        #        cries wolf on the first stray public/ file and gets ignored.
        warn = root / "warn"
        _write_fixture(warn, "index-AAAAAAAA.js", "index-BBBBBBBB.css")
        (warn / "assets" / "leftover-notes.txt").write_text("hi", encoding="utf-8")
        _o, unref, _m = analyse(load_dir(warn))
        if not unref or report(load_bundle_for_test(warn), _o, unref, _m) != 0:
            failures.append("a non-hashed stray file was treated as damage")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    if failures:
        for line in failures:
            print("FAIL  %s" % line)
        print("self-test FAILED")
        return 1
    print("self-test PASSED (4 fixtures: clean / orphan / missing / warning)")
    return 0


def load_bundle_for_test(path):
    return load_dir(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--jar", help="verify this jar instead of the newest build")
    parser.add_argument("--dir", help="verify this static directory instead")
    parser.add_argument("--self-test", action="store_true",
                        help="run the fixture control and assert every verdict")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.jar and args.dir:
        print("-- cannot measure (give --jar or --dir, not both)")
        return 2
    return verify(args.jar or args.dir)


if __name__ == "__main__":
    sys.exit(main())
