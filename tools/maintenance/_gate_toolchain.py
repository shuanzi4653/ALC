"""One gate: run every tool-chain audit and fail loudly if any reports damage.

Why this exists
---------------
The damage class this project keeps meeting is *"parses fine, dies at runtime"*:
a rewrite drops an import, re-binds a name to the wrong type, or moves a path
root. None of it shows up in `compile()`, and `_smoke_tools.py` only catches what
it happens to execute inside a 30 s budget.

Between 2026-09-17 and today three separate defects of exactly this kind reached a
test run:

  * `runners/_run_frontend.py` and `runners/_run_java.py` -- `subprocess` used but
    never imported. `NameError` at the first real call, one line in.
  * `generators/_gen_ui_layout_evidence.py` -- `json` used three times, never
    imported.
  * `maintenance/_normalise_all_bootstraps.py` -- reported by `_restore_imports`
    as missing `time`, which was a *false* positive from a text scanner matching
    the substring `time.` inside the English word "runtime".

Every one of those was findable before it ran. The audits already knew how; what
was missing was a single command that *insists*. So: run the audits, treat any
non-zero finding as failure, and make the routine impossible to skip by hand.

Each audit is invoked as a child process rather than imported, because several of
them call `sys.exit()` and one of them (`_restore_imports.py`) writes files when
passed `--apply`. A child keeps their exits and their argv parsing honest.

Three gates, three questions
----------------------------
This file answers "is the *tooling* sane". The other two answer different
questions and are run from here with `--all` so one command covers the set:

    _gate_toolchain.py             static audits (this file)
    _smoke_flows.py                does the product *behave* (behavioural)
    _bench_innovations.py          do the claimed innovations still measure out

`_smoke_tools.py` is deliberately not in the set: it proves each script starts,
which is a different and much weaker claim than any of the three, and it takes
minutes. Run it when the question is "did a refactor break a tool".

    _gate_toolchain.py            # audits + dry-run restore check
    _gate_toolchain.py --all      # also the behavioural gate and the bench
    _gate_toolchain.py --verbose  # also echo each audit's own output
"""

import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from _repo import ROOT  # noqa: E402

PY = sys.executable

# (label, script, argv, predicate) -- predicate gets the child's combined output
# and returns None when clean, or a one-line reason when not.
AUDITS = (
    ("unbound names", "maintenance/_audit_unbound_names.py", [],
     lambda out: _nonzero_summary(out, ("files with unbound stdlib references",
                                        "files using a stdlib name before its import"))),
    ("late re-import", "maintenance/_audit_late_reimport.py", [],
     lambda out: None if re.search(r"\b0\b", out) and "0" in out.split("\n")[0] else
     ("findings reported", out.strip().split("\n")[0][:100])),
    ("payload imports", "maintenance/_audit_payload_imports.py", [],
     lambda out: "detector is inert" if "detector is inert" in out else None),
    ("root climb", "maintenance/_audit_root_climb.py", [],
     lambda out: None if out.strip().startswith("0") or " 0" in out.split("\n")[0] else
     ("findings reported", out.strip().split("\n")[0][:100])),
    ("restore imports", "maintenance/_restore_imports.py", [],
     lambda out: None if re.search(r"\b0 files need imports restored", out) else
     ("missing imports", _first_data_line(out))),
    ("gateway routes", "maintenance/_audit_gateway_routes.py", [],
     lambda out: None if (re.search(r"unmatched calls:\s*0", out)
                          and re.search(r"undecidable calls:\s*0", out)
                          and re.search(r"unverified call sites:\s*0", out)
                          and "detector is inert" not in out) else
     ("unrouted frontend calls", _first_data_line(out))),
    # 2026-10-15 加。`unverified call sites` 是那一天补上的第三类：既不是"路径没有
    # 映射"，也不是"模式看不懂"，而是**这个调用点里根本没有字面量路径、静态看不见**。
    # 当时线上「实测雷达一直不可用」就是这一类的——`radarRelay.js` 写的是
    # `requestJson(relay.postTo || '/api/traffic/radar/tiles', …)`，旧扫描只认
    # 字面量首参，于是那个 POST 在审计里根本不存在，闸门 15 calls / 0 unmatched 全绿。
    # ⚠️ 判据必须**显式列出这一类**：脚本本身会因它 exit 1，但本文件的判断走的是
    # stdout 谓词，谓词不认它的话，"新增一类失败"在闸门里就是不存在的（同 M27）。
    ("gateway routes control", "maintenance/_audit_gateway_routes.py", ["--self-test"],
     lambda out: None if "self-test PASSED" in out else
     ("the gateway-route audit cannot fail", _first_data_line(out))),
    # The prose totals in `changelog/ISSUES.md` are the one kind of claim no
    # other check reads: the link checker reads paths, these audits read code.
    # Paired with the control below, because a counter that cannot fail would
    # report "ok" on a file whose totals had silently drifted (M29/M58).
    ("issue counts", "maintenance/_verify_issue_counts.py", [],
     lambda out: None if out.strip().endswith("-- ok") else
     ("ISSUES.md totals no longer add up", _first_data_line(out))),
    ("counts control", "maintenance/_verify_issue_counts.py", ["--self-test"],
     lambda out: None if "self-test PASSED" in out else
     ("the counts check cannot fail", _first_data_line(out))),
    # The only audit here that does not inspect the tooling: it inspects whether
    # the *documents* are describing code a request can reach. `docs/paper-innovations.md`
    # indexed eight innovations against implementation sites, and five of those
    # sites turned out to be reached by nothing. A document nobody re-checks is
    # how that happens, so the check is now in the routine rather than in a note.
    ("innovation reachability", "probes/_probe_innovation_reachability.py", [],
     lambda out: None if ("both controls discriminated" in out
                          and "could not be attributed" not in out) else
     ("an indexed implementation site is unreachable-by-typo or the probe cannot "
      "discriminate", _first_data_line(out))),
    # 闸门自己的失败路径（0.9.26（Beta） 第十轮）。它平时什么都不打印，所以
    # **唯一的自证方式就是真的调用它一次** —— 而这个审计做的就是这件事。
    # 加进来的理由：那段代码在第十轮之前从来没有被执行过，第一次执行就抛了
    # `TypeError`，症状是"审计失败时闸门不报原因、直接崩"。构建与测试都不覆盖
    # 它，所以它只能靠摆在常规闸门里才不会再烂掉（M27：量具必须自证）。
    ("gate report path", "probes/_probe_gate_report.py", [],
     lambda out: None if "GATE REPORT PASS" in out else
     ("the gate cannot report a failure without crashing", _first_data_line(out))),
    # 迁移文本要**真的在 H2 上跑一次**。V6 曾把列名写成 `day`，而 H2 把 DAY 当保留字
    # （INTERVAL 字面量的单位），建表直接语法错误。Java 套件跑的是 Mockito 假仓库、
    # 里面没有一句 SQL；`mvnw package` 只是把 .sql 塞进 jar。于是这个缺陷**只有在部署
    # 之后才够得着**，而且它的后果不是回滚能修的：Flyway 会把 V6 记成 failed，
    # 之后旧 jar 也会因为面对一条失败迁移而拒启。配一个自检，因为"能跑"与"能判红"
    # 是两件事 —— 只用合法 DDL 试，一个悄悄什么都没执行的 RunScript 也会是绿的。
    ("migrations apply", "maintenance/_verify_migrations.py", [],
     lambda out: None if out.strip().endswith("-- ok") else
     ("a migration does not apply to H2", _first_data_line(out))),
    ("migrations control", "maintenance/_verify_migrations.py", ["--self-test"],
     lambda out: None if "self-test PASSED" in out else
     ("the migration check cannot fail", _first_data_line(out))),
    # 规则阈值被复制成两份：`config/rules-v1.json`（外部）与 classpath 副本（打进 jar）。
    # 2026-10-17 实测两份不等，差的是 classpath 副本里 `thunderProb` 少了 `required: false`
    # —— Java 的 `required` 默认 true，于是"回落到副本"把雷暴概率变成必需字段，
    # 而数据源不发布它 ⇒ **每一轮都以缺字段被拒**，界面上只是"监测一直失败"。
    # 四个环节各自都对（Python 只读外部、Java 单测不走回落、打包只塞不比较、部署才触发），
    # 缺的正是"这两份是不是同一份"这一问。故配一条正向 + 一条自检。
    ("rules parity", "maintenance/_verify_rules_parity.py", [],
     lambda out: None if "[PASS]" in out else
     ("the two rules files have drifted apart", _first_data_line(out))),
    ("rules parity control", "maintenance/_verify_rules_parity.py", ["--self-test"],
     lambda out: None if "self-test PASSED" in out else
     ("the rules-parity check cannot fail", _first_data_line(out))),
    # 2026-10-15 加。这个检查器从有它的那天起就**只打印、不退出非零**，也**不在本
    # 闸门里** —— 两件事是同一个缺陷的两面：谁按它的退出码判断，谁就对它报的每一条
    # 死链都是盲的。这一天一轮文档编辑留下了 **8 条死链**（`NOT_READY/STALE` 这类
    # 带斜杠的状态对一个 IANA 时区名、一条写错的测试路径），而常规闸门全绿。
    # 谓词读 stdout，因为脚本既有 0 也有 1 的出口，而**"报了死链"这件事写在输出里**。
    # 配一条对照，理由与上面几条相同：一个永远不会红的计数，在"总数没漂"的文件上
    # 也会报 ok（M29/M58）。
    ("doc links", "maintenance/_verify_doc_links.py", [],
     lambda out: None if re.search(r"dead links:\s*0\b", out) else
     ("a changelog doc cites a path that does not exist", _first_dead_link(out))),
    ("doc links control", "maintenance/_verify_doc_links.py", ["--self-test"],
     lambda out: None if "self-test PASSED" in out else
     ("the doc-link check cannot fail", _first_data_line(out))),
    # 2026-10-16 加。`maven-resources-plugin` 是 **COPY 不是 mirror**，所以任何没先
    # `clean` 的打包都会把上一代的内容哈希包**并进去**：0.9.31 实测 6 个孤儿 js/css、
    # ~9 MB，构建全绿、测试全绿、运行时报错也没有。两处打包入口只在 2026-10-15 才补上
    # `clean`，而**没有任何东西检查它** —— 于是"修过一次"与"不会再回来"是两句不同的话。
    # 判据的边界要看清：**不是**"index.html 引用了每个文件"。`public/` 的 `beian.png`
    # 与 worker 分块只被 JS 包**从内部**引用，那样写会当场误报（M85：判据的射程由它认得
    # 的写法决定）。真正的规则是"每个内容哈希名都要在包内被某处叫到"。
    ("static bundle", "maintenance/_verify_static_bundle.py", [],
     lambda out: None if _bundle_clean(out) else
     ("the packaged bundle carries a generation nothing references", _first_bundle_finding(out))),
    ("static bundle control", "maintenance/_verify_static_bundle.py", ["--self-test"],
     lambda out: None if "self-test PASSED" in out else
     ("the bundle check cannot fail", _first_data_line(out))),
    # 2026-10-16 加。「哪些端点要计费/限速」写在两处、两种语言里，而**没有任何东西比对
    # 它们**：Java 的 `QuotaProperties.DEFAULT_PATHS` 与 nginx 的 `map`。两边都写了
    # 「改这里要同步改那边」——两句散文，而散文替代不了一次检查（同 0.9.32 ⑦）。
    # 当天实测漏的是 `/api/decisions/explain`：与 `/api/traffic/explain` 并列的**第二条
    # 大模型入口**，第一条在名单里、第二条不在，而"配额生效"这条判据在它身上仍然全绿。
    # 「两边一样」这句判据本身还不够：两份名单一起写错一个字母时它是绿的，所以第三条
    # 检查反查每个路径是否真有 Java 映射。
    # 第五个元素是可选的 `allowed_rc`。只有 `quota coverage` 用得上：它要区分
    # "快照缺席、无法测量"（exit 2）与"两份名单不一致"（exit 1），而这两种结论
    # 在输出里长得完全不像 —— 前者是 SKIP，后者是 FAIL。
    ("quota coverage", "maintenance/_audit_quota_coverage.py", [],
     lambda out: None if _quota_clean(out) else
     ("the charged list and the throttled list are not the same endpoints",
      _first_finding(out)), (0, 1, 2)),
    ("quota coverage control", "maintenance/_audit_quota_coverage.py", ["--self-test"],
     lambda out: None if "self-test PASSED" in out else
     ("the quota-coverage check cannot fail", _first_data_line(out))),
    # 2026-10-18 加。**"当前是哪个版本"从来没有被任何判据读过** —— 0.9.35 那一轮
    # 五个程序落点都改了、闸门全绿，而 README 标题与 NAMING §7 正文都还写着 0.9.33。
    # 本仓已经有专门查"复制出来的数字"的审计（计数、闸门项数、规则两份），
    # 唯独版本号这组复制的次数最多（五处程序 + 若干处散文），却一条判据都没有。
    # 读一处事实（`VERSION`）、核对其余每一处引用，出口分 0/1/2（0 一致 / 1 不一致 /
    # 2 无法测量），因为"文件读不到"与"版本不匹配"必须是两种不同的结论。
    ("version consistency", "maintenance/_check_version_consistency.py", [],
     lambda out: None if out.strip().endswith("-- ok") else
     ("a landing point disagrees with VERSION", _first_data_line(out))),
    ("version consistency control", "maintenance/_check_version_consistency.py", ["--self-test"],
     lambda out: None if "self-test PASSED" in out else
     ("the version check cannot fail", _first_data_line(out))),
    # 2026-10-19 加（0.11.1）。手册 §6.4 给的「穿帮清零」办法是**在控制台粘一段 JS**：
    # 只看得见当前这一页，跑到哪算哪，刷新之后什么都没有留下 —— 它是一次性动作，
    # 不是判据。本轮落成脚本后**必须进闸门**，否则下一轮加一段文案时没有任何东西在读它，
    # 而"文案退回去"这件事在构建、测试、截图三处都不红（它长得像"措辞改了"）。
    # 谓词只认那一整句 `PASS 穿帮文案扫描：0 命中`：写成 `"0 命中" in out` 会被
    # `10 命中` 满足（"1" + "0 命中"），也就是**命中越多越算过**。
    ("copy leaks", "maintenance/_scan_copy_leaks.py", [],
     lambda out: None if any(line.strip().startswith("PASS 穿帮文案扫描：0 命中")
                             for line in out.split("\n")) else
     ("rendered copy contains a phrase that contradicts the current design",
      _first_data_line(out))),
    ("copy leaks control", "maintenance/_scan_copy_leaks.py", ["--self-test"],
     lambda out: None if "PASS 负向验证" in out else
     ("the copy-leak scan cannot fail", _first_data_line(out))),
    # 2026-10-21 加（0.11.6）。`verify-remote.sh` 曾经只存在于服务器上：
    # 重装即丢、改动无法追溯（E-3 那次 `sed` 加 admin 头在版本记录里完全看不见）。
    # 这条闸门只查仓库这份自身的硬性质（LF / shebang / admin 头 / 不是空壳）；
    # 两端 sha256 比对要 SSH，放在 `--remote` 里手动跑，不进闸门 ——
    # 闸门必须能在没网、没密钥的机器上通过。
    ("ops parity", "maintenance/_check_ops_parity.py", [],
     lambda out: None if "ok   bin/verify-remote.sh" in out else
     ("the ops script drifted from what the repo expects", _first_data_line(out))),
    ("ops parity control", "maintenance/_check_ops_parity.py", ["--self-test"],
     lambda out: None if "self-test PASSED" in out else
     ("the ops-parity check cannot fail", _first_data_line(out))),
    # 2026-10-21 加（0.11.8）。**前端唯一能抓 ReferenceError 的网。**
    # `_audit_unbound_names.py` 是 Python AST（射程之外）、`vite build` 只解析语法、
    # Vue 模板里的未知名字退化成 `_ctx.x`（渲染成空、不抛错）。于是"JS 里写了一个本
    # 文件不存在的名字"这一类错，整个工具链一张网都没有（M23 记的就是它）。
    # 当天线上连撞两次：`activeCaseId`（跨文件取变量）让**实时首页气象层整块失效**；
    # 三个雾区函数被补丁追加到 `</script>` 之后，每次重画抛错并跳过 `triggerRepaint()`。
    # 两次都是「构建绿 + 435 测试绿 + 闸门 27 项绿」。所以它不能只是"顺手扫一下"。
    # 出口分 0/1/2：0 干净 / 1 有发现 / 2 无法测量（找不到 node 或 @babel/parser）——
    # "扫不了"绝不能被读成"干净"。
    ("js unbound names", "maintenance/_audit_js_unbound.py", [],
     lambda out: None if "unbound names: 0" in out and "stray blocks: 0" in out
     else ("a component uses a name this file never declares", _first_data_line(out)),
     (0, 1, 2)),
    ("js unbound control", "maintenance/_audit_js_unbound.py", ["--self-test"],
     lambda out: None if "self-test PASSED" in out else
     ("the unbound-name scan cannot fail", _first_data_line(out))),
    # 0.11.13：**prop 当 ref 用**。这条与上面那条是两种病，但都会在浏览器里抛
    # `ReferenceError`，而构建、lint、Python 侧审计全都看不见：
    #   · unbound names  = 这个名字整个文件都没声明；
    #   · prop-as-ref     = 名字声明了（是 prop），但被写成 `name.value`。
    # 后者语法合法，只有在跑到那一行时才炸 —— 0.11.13 就是靠它抓到
    # `OperationsConsole.vue` 的 `session.value`（案例回放判据面板从未加载出来过）。
    ("vue prop refs", "maintenance/_audit_vue_prop_refs.py", [],
     lambda out: None if "prop-ref 审计 -- ok" in out
     else ("a Vue component treats a prop as a ref", _first_data_line(out)),
     (0, 1, 2)),
    ("vue prop refs control", "maintenance/_audit_vue_prop_refs.py", ["--self-test"],
     lambda out: None if "自检通过" in out else
     ("the prop-as-ref scan cannot fail", _first_data_line(out))),
)


def _first_finding(out):
    """Name the offending endpoint, not the header count line."""
    for line in out.split("\n"):
        if line.startswith(("FINDING", "BLIND")):
            return line.strip()[:140]
    return _first_data_line(out)


def _bundle_clean(out):
    """Accept the check's two clean terminators **and nothing else**.

    ``-- skipped`` is accepted on purpose: the gate runs on trees where ``mvn
    clean`` has just removed ``target/``, and failing there would train the
    reader to ignore this line. It is still not silence -- the terminator is its
    own word, so an absent bundle can never be mistaken for a verified one.
    """
    tail = out.strip().split("\n")[-1].strip() if out.strip() else ""
    return tail in ("-- ok", "-- skipped (no built bundle to verify)")


def _quota_clean(out):
    """Same shape as ``_bundle_clean``: two terminators, both their own words.

    2026-10-18：这条审计比的是「Java 的计费名单」与「nginx 的限速名单」，
    而后者是一份**从服务器 pull 下来的快照**（`config/nginx/…upstream.conf`）。
    快照不在时它无法测量 —— 那与"两份名单不一致"是两件完全不同的事。
    所以只接受两个词：量过且干净、或**说清为什么没量**；
    **绝不接受 "-- cannot measure"**（那是"工具链自己坏了"，必须继续红）。
    """
    tail = out.strip().split("\n")[-1].strip() if out.strip() else ""
    return tail == "-- ok" or tail.startswith("-- skipped (nginx snapshot absent:")


def _first_bundle_finding(out):
    """Name the orphan itself, so the gate's one-liner is actionable.

    `_first_data_line` would print the `bundle  <path>` header and say nothing
    about *which* file is stale -- and the whole value of this check is that it
    can name the generation that should not be there.
    """
    for line in out.split("\n"):
        if line.startswith(("ORPHAN", "MISSING")):
            return line.strip()[:120]
    return _first_data_line(out)



def _first_data_line(out):
    for line in out.split("\n"):
        if line.strip().startswith(("generators", "maintenance", "benches",
                                    "probes", "runners", "harness", "recon")):
            return line.strip()[:100]
    return out.strip().split("\n")[0][:100] if out.strip() else "no output"


def _first_dead_link(out):
    """The first ``DEAD <doc> -> <token>`` line, so the gate names the culprit.

    `_first_data_line` cannot serve here: the link checker's lines start with
    `DEAD`, and its first line (`resolved ok: N`) says nothing about which
    document caved in.
    """
    for line in out.split("\n"):
        if line.strip().startswith("DEAD"):
            return line.strip()[:120]
    return out.strip().split("\n")[0][:100] if out.strip() else "no output"


def _nonzero_summary(out, headers):
    """The `_audit_unbound_names` output puts a count after each header line."""
    for header in headers:
        match = re.search(re.escape(header) + r":\s*(\d+)", out)
        if match and int(match.group(1)) != 0:
            return "%s: %s" % (header, match.group(1))
    return None


def run(label, rel, argv, predicate, allowed=(0, 1)):
    path = os.path.join(TOOLS, rel)
    if not os.path.isfile(path):
        return label, None, "audit script missing: " + rel
    env = {k.upper(): v for k, v in os.environ.items()}
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [PY, "-X", "utf8", path] + argv, cwd=ROOT, env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    reason = predicate(out)
    if reason is None and proc.returncode not in allowed:
        # An exit code we do not understand is itself a finding: these audits use
        # 0 for clean and 1 for "findings", so anything else means the audit
        # crashed and its silence must not be read as success.
        #
        # `allowed` 是本文件唯一允许某条审计**自带第三种出口**的地方，只给那些
        # "无法测量"与"量出问题"必须分开的审计用（`quota coverage`：它的 nginx 侧
        # 是一份从服务器 pull 的快照，快照缺席时 exit 2 + 一句 SKIP）。
        # 放宽的是**退出码**，不是谓词 —— 谓词仍然只认那两个词。
        reason = "audit exited %s" % proc.returncode
    return label, out, reason


def main():
    verbose = "--verbose" in sys.argv
    failed = []
    for entry in AUDITS:
        label, rel, argv, predicate = entry[:4]
        allowed = entry[4] if len(entry) > 4 else (0, 1)
        label, out, reason = run(label, rel, argv, predicate, allowed)
        status = "ok" if reason is None else "FAIL"
        print("%-18s %s" % (label, status))
        if verbose and out.strip():
            for line in out.strip().split("\n")[:12]:
                print("        | " + line)
        if reason:
            failed.append((label, reason, out))

    if "--all" in sys.argv:
        failed.extend(_companion_gates(verbose))

    print()
    return _report(failed)


def _report(failed, stream=None):
    """Print the failure summary. **Extracted so it can be exercised without failing.**

    这一小段 0.9.26（Beta） 第十轮之前从来没有被执行过：`reason` 是**二元组**
    `(标题, 第一行证据)`，而这里写的是 `print("  %s" % reason)` —— `"%s" % (a, b)`
    抛 `TypeError: not all arguments converted`。也就是说，**任何一条审计真的失败时，
    闸门不会打印原因，而是崩在打印原因的代码里**。构建与测试都不覆盖这条路径，
    所以它只在需要它的那一刻失效（M27：量具必须自证）。

    抽成函数是为了能**在不制造真实失败的前提下**跑一次：见
    `.run/_gate_report_probe.py`，它喂进一条假的失败并断言输出里出现标题与证据行。
    """
    out_stream = stream or sys.stdout
    if not failed:
        print("GATE PASS -- every tool-chain audit reports zero findings", file=out_stream)
        return 0
    print("GATE FAIL -- %d audit(s) reporting damage" % len(failed), file=out_stream)
    for label, reason, out in failed:
        print("", file=out_stream)
        print("=== %s ===" % label, file=out_stream)
        title, detail = reason if isinstance(reason, tuple) else (reason, "")
        print("  %s" % title, file=out_stream)
        if detail:
            print("  | %s" % detail, file=out_stream)
    return 1


# (label, script, argv) -- each is a gate in its own right; `--all` adds them so a
# single command covers static + behavioural + innovation-reproduction. They are
# listed rather than discovered because a gate that quietly fails to be found
# would read exactly like a gate that passed.
COMPANION_GATES = (
    ("behavioural gate", "maintenance/_smoke_flows.py", ["--timeout", "300"]),
    ("innovation bench", "benches/_bench_innovations.py", []),
)


def _companion_gates(verbose):
    """Run the sibling gates and return their failures in the audits' format."""
    failures = []
    env = {k.upper(): v for k, v in os.environ.items()}
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["PYTHONIOENCODING"] = "utf-8"
    for label, rel, argv in COMPANION_GATES:
        path = os.path.join(TOOLS, rel)
        if not os.path.isfile(path):
            print("%-18s FAIL" % label)
            failures.append((label, "gate script missing: " + rel, ""))
            continue
        proc = subprocess.run(
            [PY, "-X", "utf8", path] + argv, cwd=ROOT, env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        print("%-18s %s" % (label, "ok" if proc.returncode == 0 else "FAIL"))
        if verbose and out.strip():
            for line in out.strip().split("\n")[-14:]:
                print("        | " + line)
        if proc.returncode != 0:
            tail = [line for line in out.strip().split("\n") if line.strip().startswith("!")]
            failures.append((label, tail[0].strip()[:120] if tail
                             else "exited %s" % proc.returncode, out))
    return failures


if __name__ == "__main__":
    sys.exit(main())
