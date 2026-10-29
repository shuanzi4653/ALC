"""The quota list and the nginx throttle list must be the same six paths.

Why this exists
---------------
"Which endpoints are charged" is written in two places, in two languages, and
until 2026-10-16 nothing compared them:

    backend-java/.../config/QuotaProperties.java   DEFAULT_PATHS   (daily quota)
    config/nginx/AIC-tianchuang-upstream.conf      map $uri ...    (rate limit)

The Java file says so in prose -- "改这里就要同步改 ... 的 map" -- and the nginx
file says the mirror image. Two prose instructions and no check is the shape this
project has already been bitten by more than once: the sentence stays true-looking
while the lists drift, and a path missing from one of them produces **no error at
all**. It simply is not charged, or not throttled, and the criterion for "the
quota works" still passes on the paths that are present.

What was actually missing on 2026-10-16: `/api/decisions/explain` -- a second
LLM-backed explain entry beside `/api/traffic/explain`, first one listed, second
one not. Plus `/api/scenario/switch` (same monitor round as `run-now`) and
`/api/traffic/weather/mode` (the machine-wide weather channel).

Three checks, because "the two lists agree" alone would be satisfied by two
identical typos:

1. **Same set.** Every path in one list is in the other, both directions.
2. **Every path is real.** Each path must be reachable -- a Spring mapping must
   exist for it, matched with the same alternation-aware matcher the gateway-route
   audit uses. A misspelled path in *both* lists is a silent no-op, and this is the
   only check that can see it.
3. **Method discipline.** Every entry in the nginx map must be method-qualified
   (`~^POST /api/...$`). An unqualified entry would throttle/charge page-load GETs,
   and `/api/traffic/weather/mode` is read by the workbench on every open while
   only its POST changes the channel.

``--self-test`` mutates a copy of each side and asserts each check goes red on its
own evidence. A criterion that cannot fail is indistinguishable from one that
passed (M29/M58), and the failure this file guards against is exactly the silent
kind.

Exit codes: 0 clean, 1 findings, 2 could not measure (a file is missing or its
declared block cannot be located -- which must not read as clean).
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402

JAVA_PROPS = os.path.join(
    ROOT, "backend-java", "src", "main", "java", "com", "tianchuang",
    "config", "QuotaProperties.java")
NGINX_CONF = os.path.join(ROOT, "config", "nginx", "AIC-tianchuang-upstream.conf")
# 2026-10-18：这份快照**原来住在 `.run/cloud/`**，而 `.run/` 是本仓每轮清理都会整目录删掉的
# 临时区 —— 于是"闸门需要的输入"住在"用完即弃"的目录里（**ISS-0.9.26-06 / M93 的第二次发生**：
# 上一次是发布脚本住在 `.run/`，这一次是**审计的输入**）。当天清理 `.run` 之后，本审计报
# `BLIND: No such file ...`，而它读起来像"配置坏了"。已把快照的落点改到仓库内的
# `config/nginx/`，并让"快照缺席"成为一条**说得出口的 SKIP**，而不是假装测过或长期红灯。
NGINX_SKIP_TERMINATOR = ("-- skipped (nginx snapshot absent: "
                         "config/nginx/AIC-tianchuang-upstream.conf)")
JAVA_CONTROLLERS = os.path.join(
    ROOT, "backend-java", "src", "main", "java", "com", "tianchuang", "controller")

# `public static final List<String> DEFAULT_PATHS = List.of("a", "b", ...);`
PATHS_BLOCK_RE = re.compile(
    r"DEFAULT_PATHS\s*=\s*List\.of\((.*?)\)\s*;", re.S)
PATH_LITERAL_RE = re.compile(r'"([^"]+)"')

# The map block: `map "$request_method $uri" $AIC_tianchuang_llm_key { ... }`
MAP_BLOCK_RE = re.compile(
    r"map\s+\"[^\"]*request_method[^\"]*\"\s+\$(\w+)\s*\{(.*?)\n\}", re.S)
# The method is captured **optionally on purpose**. Requiring it would make an
# unqualified entry simply not parse -- it would vanish from the list and be
# reported as "charged but not throttled", i.e. the wrong diagnosis for the right
# symptom, and the "no method" rule itself would never be exercised. The whole
# point of check ③ is that this shape is recognised rather than dropped.
MAP_ENTRY_RE = re.compile(r'"~?\^?(?:([A-Za-z]+)\s+)?(/api/[^"$]+)\$"')

_MAPPING_RE = re.compile(
    r"""@(Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*(?:value\s*=\s*)?"([^"]*)\"""")
_CLASS_RE = re.compile(r"@RequestMapping\s*\(\s*\"([^\"]*)\"\s*\)\s*public\s+class")


def read(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def quota_paths(text):
    """The declared default list from the Java properties record."""
    block = PATHS_BLOCK_RE.search(text)
    if not block:
        return None
    return PATH_LITERAL_RE.findall(block.group(1))


def throttle_paths(text):
    """(path, method) pairs from the nginx map, in declaration order.

    ``method`` is ``''`` for an entry that is not method-qualified; check ③ turns
    that into a finding rather than letting the entry disappear.
    """
    block = MAP_BLOCK_RE.search(text)
    if not block:
        return None
    body = block.group(2)
    return [((method or "").upper(), path)
            for method, path in MAP_ENTRY_RE.findall(body)], body


def java_mappings():
    """[(methods, full_pattern, file)] -- class prefix + method path, as Spring sees it."""
    mappings = []
    for base, _dirs, names in os.walk(JAVA_CONTROLLERS):
        for name in sorted(names):
            if not name.endswith(".java"):
                continue
            path = os.path.join(base, name)
            text = read(path)
            class_match = _CLASS_RE.search(text)
            prefix = class_match.group(1) if class_match else ""
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            for kind, pattern in _MAPPING_RE.findall(text):
                if not pattern.startswith("/"):
                    continue
                if class_match and pattern == prefix:
                    continue
                full = (prefix + pattern).replace("//", "/")
                methods = ("GET", "POST", "PUT", "DELETE", "PATCH") if kind == "Request" \
                    else (kind.upper(),)
                mappings.append((methods, full, rel))
    return mappings


def _pattern_matches(pattern, path):
    """Spring pattern vs concrete path. True / False / None (did not understand)."""
    if "{" not in pattern:
        return pattern.rstrip("/") == path.rstrip("/")
    segments = pattern.split("/")
    parts = path.split("/")
    if len(segments) != len(parts):
        return False
    for seg, part in zip(segments, parts):
        match = re.fullmatch(r"\{([^{}]*)\}", seg)
        if not match:
            if seg != part:
                return False
            continue
        inner = match.group(1)
        if ":" in inner:
            _name, _, alternatives = inner.partition(":")
            if not re.fullmatch(r"[A-Za-z0-9_|.\-]+", alternatives):
                return None
            if part not in alternatives.split("|"):
                return False
    return True


def reachable(path, mappings):
    """Is there any mapping at all for this path (any method)?"""
    seen = set()
    for methods, pattern, _f in mappings:
        verdict = _pattern_matches(pattern, path)
        if verdict is None:
            seen.add("undecidable")
        elif verdict:
            return "yes"
    return "undecidable" if "undecidable" in seen else "no"


def audit(java_text, conf_text, mappings):
    """Return (problems, details). Pure, so the self-test can drive mutated copies."""
    problems = []
    quota = quota_paths(java_text)
    parsed = throttle_paths(conf_text)
    if quota is None:
        return ["BLIND: cannot locate DEFAULT_PATHS in QuotaProperties.java"], {}
    if parsed is None:
        return ["BLIND: cannot locate the throttle map in the nginx conf"], {}
    throttle, block_body = parsed

    # A mapping line the pattern does not understand would silently shrink the
    # list -- the same blindness that let a method-less entry vanish before. Count
    # the `/api/` occurrences in the block against what parsed.
    mentioned = block_body.count("/api/")
    if mentioned != len(throttle):
        problems.append("BLIND: nginx map 里有 %d 处 /api，只解析出 %d 条 —— "
                        "有写法逃出了这条判据" % (mentioned, len(throttle)))

    quota_set = set(quota)
    throttle_set = {path for _method, path in throttle}

    for path in sorted(quota_set - throttle_set):
        problems.append("计费的端点没有限速：%s（只在 DEFAULT_PATHS 里）" % path)
    for path in sorted(throttle_set - quota_set):
        problems.append("限速的端点没有计费：%s（只在 nginx map 里）" % path)

    for path in sorted(quota_set & throttle_set):
        if len([p for p in quota if p == path]) > 1:
            problems.append("DEFAULT_PATHS 里重复列出：%s" % path)

    # Method qualification: without it, a page-load GET gets throttled -- and
    # /api/traffic/weather/mode is GET once per workbench open.
    for method, path in throttle:
        if not method:
            problems.append("nginx map 的条目没有限定方法（会拦到只读的 GET）：%s" % path)

    # Each path must actually exist, or both lists agree on a typo.
    for path in sorted(quota_set):
        verdict = reachable(path, mappings)
        if verdict == "no":
            problems.append("路径不存在于任何 Java 映射（两份名单一起写错了？）：%s" % path)
        elif verdict == "undecidable":
            problems.append("无法判定这个路径是否有映射：%s" % path)

    details = {
        "quota": sorted(quota_set),
        "throttle": sorted(throttle_set),
        "mappings": len(mappings),
    }
    return problems, details


def report(java_text, conf_text, mappings):
    problems, details = audit(java_text, conf_text, mappings)
    print("java paths        %d" % len(details.get("quota", [])))
    print("nginx paths       %d" % len(details.get("throttle", [])))
    print("java mappings     %d" % details.get("mappings", 0))
    for line in problems:
        print("FINDING %s" % line)
    if problems:
        print("-- coverage gap")
        return 1
    print("-- ok")
    return 0


# --------------------------------------------------------------------------- #
# self-test
# --------------------------------------------------------------------------- #
def synth_conf(paths):
    """A map block built **from the Java list** — used only when the snapshot is absent.

    The control's job is to prove *the checker* can fail, so the input it mutates
    does not have to be the server's copy. Building it from the Java side makes the
    base case clean by construction, and every mutation below still exercises the
    real code paths (set comparison / typo / missing method).
    """
    lines = ['map "$request_method $uri" $AIC_tianchuang_llm_key {']
    for path in paths or []:
        lines.append('    "~^POST %s$"  "%s";' % (path, path.strip('/').replace('/', '_')))
    lines.append('}')
    return "\n".join(lines) + "\n"


def self_test():
    java_text = read(JAVA_PROPS)
    try:
        conf_text = read(NGINX_CONF)
        source = "repo snapshot"
    except OSError:
        conf_text = synth_conf(quota_paths(java_text))
        source = "built-in fixture (snapshot absent)"
    mappings = java_mappings()
    failures = []
    print("self-test input: nginx side from %s" % source)

    base, _details = audit(java_text, conf_text, mappings)
    if base:
        print("BROKEN: the real files already report %d finding(s); "
              "the control needs a clean input" % len(base))
        for line in base:
            print("  %s" % line)
        print("self-test FAILED")
        return 1

    def mutate_drop_java():
        # Drop one path from the Java list only -> "charged but not throttled".
        block = PATHS_BLOCK_RE.search(java_text)
        body = block.group(1)
        first = PATH_LITERAL_RE.search(body).group(1)
        return java_text.replace('"%s",' % first, "", 1)  # noqa: E501

    def mutate_typo_both():
        # Same typo on both sides -> the only check that can see it is reachability.
        path = "/api/agent/ask"
        return (java_text.replace('"%s"' % path, '"/api/agent/askk"'),
                conf_text.replace("/api/agent/ask$", "/api/agent/askk$"))

    def mutate_unqualified():
        return conf_text.replace('"~^POST /api/agent/ask$"', '"~^/api/agent/ask$"')

    cases = (
        ("java list loses one path", lambda: (mutate_drop_java(), conf_text),
         "限速的端点没有计费"),
        ("both lists carry a typo", lambda: mutate_typo_both(),
         "两份名单一起写错了"),
        ("nginx entry loses its method", lambda: (java_text, mutate_unqualified()),
         "没有限定方法"),
    )
    for label, build, expected in cases:
        mutated_java, mutated_conf = build()
        problems, _d = audit(mutated_java, mutated_conf, mappings)
        if not problems:
            failures.append("%s: 没有报出任何问题" % label)
        elif not any(expected in line for line in problems):
            failures.append("%s: 报出的问题不是期待的那一类（%r）"
                            % (label, problems[0]))

    if failures:
        for line in failures:
            print("FAIL  %s" % line)
        print("self-test FAILED")
        return 1
    print("self-test PASSED (3 mutations: dropped path / typo in both / "
          "unqualified method)")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--self-test", action="store_true",
                        help="mutate a copy of each side and assert each check goes red")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    try:
        java_text = read(JAVA_PROPS)
    except OSError as exc:
        print("BLIND: %s" % exc)
        print("-- cannot measure")
        return 2
    try:
        conf_text = read(NGINX_CONF)
    except OSError:
        # 快照缺席与"两份名单不一致"是两件完全不同的事：前者无法测量、后者量出问题。
        # 这里只允许前者以**它自己的一句话**结束，绝不回落成 "-- ok"。
        print("snapshot absent: %s" % NGINX_CONF)
        print("（这份快照要从服务器 pull：`ssh … 'cat /etc/nginx/conf.d/…upstream.conf'`）")
        print(NGINX_SKIP_TERMINATOR)
        return 2
    return report(java_text, conf_text, java_mappings())


if __name__ == "__main__":
    sys.exit(main())
