# -*- coding: utf-8 -*-
"""
构建「交给同学试跑」的交付包。

判据来源：
  scripts/dev.ps1                  源码模式的真实入口（start.bat -> dev.ps1）
  scripts/check-environment.ps1    自检消费哪些文件
  backend-python/traffic/secret_store.py   密钥与密文库的配对关系

排除原则：
  1. 依赖目录（对方自己安装；dev.ps1:71 硬编码 frontend/node_modules/vite/bin/vite.js）
  2. 构建产物（target / dist / __pycache__ / *.pyc）
  3. 运行时临时件（.run / .pytest_cache / .audit / *.log）
  4. 我方会话资料与版本控制（.workbuddy / .git / .idea / .vscode）
     —— 注意 **不含 `.mvn`**。它曾按名字被归进这一类，结果把 `backend-java/.mvn/wrapper/
     maven-wrapper.properties`（mvnw.cmd 的运行时输入、git 跟踪文件）一起排除掉了：
     同学机器上双击 start.bat 一路报到 `Cannot start maven from wrapper` -> `dev.ps1:35`
     抛「源码编译失败（未执行打包）」。**排除的判据是「启动脚本会不会读它」，不是
     「这个名字像不像会话目录」。** 见 notes/2026-10-07-handoff-pack-missing-mvn-wrapper.md
  5. 体积大且与「跑起来」无关（backups / data_backup_* / tools / archive / artifacts）
  6. **凭据配对**：config/alc_secret.key 与 backend-python/data/secrets.db 必须同时排除 ——
     一个是 Fernet 密钥、一个是用它加密的密文库，两者一起给出等于交出明文凭据。
     对方首次运行会自建新 key（resolve_key 的 FILE_CREATED 分支），源码链路不依赖它。

实现要点：用 os.walk(topdown=True) 并在原地剪枝 dirnames。
第一版用 rglob 导致「先访问孩子再想跳过父亲」，frontend/dist 的 5852 个文件全部漏进来了。
"""
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, package_dir  # noqa: E402

SRC = Path(ROOT)
# Named from VERSION rather than hard-coded: it used to say "0.9.25-beta" long
# after VERSION had moved on, which silently produced a directory the verifier
# was also still pointing at (see _repo.package_dir).
DST = Path(package_dir())

# ---- 根级条目：允许清单（显式列举，不用否定式匹配） ----
ROOT_FILES = [
    "README.md", "VERSION",
    "start.bat", "stop.bat", "build.bat", "check-env.bat",
    # 面向收件人的运行说明。它原先**只存在于交付包里**、仓库里没有 —— 于是
    # 「从仓库重新打包」会把它和 config/凭据说明.md 一起静默删掉，而负向自检
    # 只会说「排除项干净」。交付物必须能从仓库复现，所以它现在归位到仓库根。
    "运行说明.md",
]
ROOT_DIRS = [
    "backend-python", "backend-java", "frontend",
    "scripts", "config", "contracts", "data", "docs",
    "changelog", "competition",
    # 0.10.1：`models/ml-v1.json` 是 `/track1/ml` 的**运行期输入**（纯 Python 打分读它），
    # 不是训练残留。0.9.x 时它还不存在，所以 ROOT_DIRS 里没有 `models` —— 漏掉它的
    # 后果是**静默的**：接口照常 200，只是 `available:false`、`reason:'model file not found'`，
    # 读起来像"模型没训练"而不像"包少带了一个文件"（正是下面 must_have 那段记的那类）。
    "models",
]

# ---- 任意层级的目录名：见到就整棵剪掉 ----
SKIP_DIR_NAMES = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", "target", ".venv", "venv", ".idea", ".vscode",
    ".run", ".audit", ".workbuddy", ".git", "backups",
    "dist", "archive",
}

# `.mvn` 曾经被放进上面的排除集，与 .git / .idea 归成一类 —— 这是错的，而且错得极隐蔽。
# `backend-java/.mvn/wrapper/maven-wrapper.properties` 是 **mvnw.cmd 的运行时输入**，不是
# 会话残留；它是 git 跟踪文件（`git ls-files backend-java/.mvn` 有输出），按本仓库自己的
# 口径就该随包发出。缺了它的后果链条 2026-10-07 在同学机器上实测复现：
#     mvnw.cmd:54  Get-Content "$scriptDir/.mvn/wrapper/maven-wrapper.properties" 找不到
#   -> mvnw.cmd:44  打印 "Cannot start maven from wrapper" 并 exit /b 1
#   -> dev.ps1:35   if ($LASTEXITCODE -ne 0) { throw '源码编译失败（未执行打包）。' }
#   -> start.bat    打印 "Start FAILED (exit code 1)"
# 表象读起来是「源码编译失败」，真因是「少了一个 3 行的配置文件」。教训：排除项的判据不能
# 按「这个名字像不像会话目录」定，要按「**启动脚本会不会读它**」定。

# ---- 任意层级的文件后缀：见到就跳过 ----
SKIP_SUFFIX = {".pyc", ".pyo", ".log", ".tmp", ".temp", ".bak", ".db"}
# .key / .pem / .secret 一律不带 —— 密钥对与本项目的凭据存储是配对设计，
# 只给密文库不给密钥（或反之）没有意义，给全了就是明文泄露。见 EXCLUDE_EXACT 注释。
SKIP_SUFFIX_CREDENTIAL = {".key", ".pem", ".secret", ".p12", ".pfx", ".jks"}

# ---- 精确排除的文件（相对 SRC 的 posix 路径） ----
EXCLUDE_EXACT = {
    # 凭据配对：密钥 + 密文库，必须成对排除
    "config/alc_secret.key",
    "backend-python/data/secrets.db",
    "backend-python/data/secrets.db-journal",
    "backend-python/data/secrets.db-wal",
    # 和风 Ed25519 私钥：.gitignore:47 明确忽略、git 未跟踪 —— 按本仓库自己的口径
    # 它就是凭据。给出去等于给出发起和风请求的签名能力。
    # 缺失后果已被验证是「诚实降级」而非崩溃：MonitorService 在第 164-180 行
    # catch 掉和风失败后改走 python.currentWeather()（open-meteo），
    # 并置 degraded=true / QWEATHER_UNAVAILABLE_PUBLIC_SOURCE_USED。
    "config/qweather/qweather_private_key.pem",
    # 唯一 import tools/ 的文件；tools/ 与根级 tests/ 不在包内，留着必然 ImportError
    "backend-python/_sim_bench.py",
    # 0.10.1：标注流水线的**请求缓存**（1 133 个单样本 JSON，2.9 MB）。它不是交付物 ——
    # 有它没它，`samples-v1.jsonl` + `labels-v1.jsonl` 都能直接训练；把它带进包只会让
    # 收件人看到一千多个看不懂的碎片文件，并让"包里的东西是不是都该在"变成一句空话。
    "data/training/annotate-cache",
    # 0.11.1：METAR 训练集的**原料**（三站 7 年逐时值，`series.csv` 20.5 MB、
    # `raw/` 21 MB、三份 `om-*.csv` 10.6 MB）。它们全部可由
    # `tools/ml/build_metar_dataset.py` 与 `build_om_history.py` 重拉，
    # 而模型卡与概率推理要的只有两样小文件（`model-v2-metrics.json` 与 `dataset.json`，
    # 合计 39 KB）—— 那两样进 `must_have`，原料不进包。
    # 判据不是"大就排除"，而是**"启动脚本与运行期会不会读它"**：
    # 原料只在训练时被读，训练脚本本身在包内（`tools/` 不进包，见上面那条注释），
    # 所以带原料进包等于带一份没人会打开的数据。
    "data/training/metar/series.csv",
    "data/training/metar/raw",
    "data/training/metar/om-ZYCC.csv",
    "data/training/metar/om-ZYHB.csv",
    "data/training/metar/om-ZYTX.csv",
}


def should_skip_dir(rel_posix: str, name: str) -> bool:
    if name in SKIP_DIR_NAMES:
        return True
    # 备份目录（data_backup_*）与前缀排除
    if name.startswith("data_backup_"):
        return True
    for ex in EXCLUDE_EXACT:
        if rel_posix == ex or rel_posix.startswith(ex + "/"):
            return True
    return False


def should_skip_file(rel_posix: str, name: str) -> bool:
    if rel_posix in EXCLUDE_EXACT:
        return True
    suffix = Path(name).suffix.lower()
    if suffix in SKIP_SUFFIX or suffix in SKIP_SUFFIX_CREDENTIAL:
        return True
    return False


def copy_tree(src_root: Path, dst_root: Path, dst_base: Path,
              pkg_prefix: str = "") -> list:
    """把 src_root 整棵复制到 dst_root；返回**相对 dst_base** 的路径清单。

    pkg_prefix 是该子树相对**仓库根**的前缀（如 'backend-python'）。
    EXCLUDE_EXACT 里写的都是仓库根相对路径，所以在子树内部匹配时必须把
    前缀接回去 —— 否则 'backend-python/data/secrets.db' 在一个以
    backend-python 为根的同名兄弟项上永远匹配不上。
    """
    copied = []
    for dirpath, dirnames, filenames in os.walk(src_root, topdown=True):
        here = Path(dirpath)
        rel_here = here.relative_to(src_root).as_posix()
        rel_here = "" if rel_here == "." else rel_here

        def full(rel: str) -> str:
            return f"{pkg_prefix}/{rel}" if pkg_prefix else rel

        # 原地剪枝：os.walk 是 topdown，改 dirnames 能阻止它下去
        kept = []
        for d in sorted(dirnames):
            rel = f"{rel_here}/{d}" if rel_here else d
            if should_skip_dir(full(rel), d):
                continue
            kept.append(d)
        dirnames[:] = kept

        for f in sorted(filenames):
            rel = f"{rel_here}/{f}" if rel_here else f
            if should_skip_file(full(rel), f):
                continue
            target = dst_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(here / f, target)
            # 清单统一存相对 dst_base 的路径，便于最后求和与负向自检
            copied.append(target.relative_to(dst_base).as_posix())
    return copied


def main() -> int:
    if DST.exists():
        print(f"[ABORT] 目标已存在，先人工确认再删：{DST}")
        return 2
    DST.mkdir(parents=True)

    manifest = []
    for f in ROOT_FILES:
        p = SRC / f
        if not p.exists():
            print(f"[WARN] 缺失根级文件：{f}")
            continue
        if should_skip_file(f, f):
            print(f"[SKIP] 按排除清单跳过根级文件：{f}")
            continue
        shutil.copy2(p, DST / f)
        manifest.append(f)

    for d in ROOT_DIRS:
        sd = SRC / d
        if not sd.exists():
            print(f"[WARN] 缺失根级目录：{d}")
            continue
        manifest.extend(copy_tree(sd, DST / d, DST, pkg_prefix=d))

    total = sum((DST / r).stat().st_size for r in manifest)
    print(f"[OK] 复制 {len(manifest)} 个文件 -> {DST}")
    print(f"[OK] 合计 {total / 1024 / 1024:.1f} MB")

    # 负向自检：这些路径必须不存在
    must_absent = [
        ".git", ".gitignore", ".workbuddy", ".run", "backups",
        "data_backup_20260911_0006", "tools", "tests",
        "frontend/node_modules", "frontend/dist",
        "backend-python/.venv", "backend-java/target",
        "config/alc_secret.key", "backend-python/data/secrets.db",
    ]
    bad = [m for m in must_absent if (DST / m).exists()]
    if bad:
        print(f"[FAIL] 不该存在的路径却存在：{bad}")
        return 1
    # 0.11.1 追加：训练原料必须**不在**包内（上面 EXCLUDE_EXACT 那五条）。
    must_absent += [
        "data/training/metar/series.csv",
        "data/training/metar/raw",
        "data/training/metar/om-ZYTX.csv",
    ]
    print(f"[OK] 负向自检通过：{len(must_absent)} 项排除目标均不存在")

    # 正向自检：启动链路必需的输入必须**在包里**。
    # 这一条是本文件最贵的一课：负向自检只回答「不该有的没多带」，它对「该有的没带」
    # 完全沉默 —— 而后者正是 2026-10-07 那个 `.mvn` 事故的形态（包看起来干净、
    # 复验也全绿，双击 start.bat 却在 35 行抛「源码编译失败」）。
    must_have = [
        "backend-java/mvnw.cmd",
        # 与 mvnw.cmd 成对：只有脚本没有 properties 时，脚本能启动、一跑就 exit 1
        "backend-java/.mvn/wrapper/maven-wrapper.properties",
        "backend-python/requirements.txt",
        "backend-python/requirements-lock.txt",
        "frontend/package.json",
        "frontend/package-lock.json",
        "scripts/dev.ps1",
        "scripts/start.ps1",
        "config/application.yml",
        # 0.10.1 起是**启动后第一次调 `/track1/ml` 就会读**的运行期输入。
        "models/ml-v1.json",
        # 判据与阈值（标签的唯一来源）；缺了它 `/track1/ml` 能跑，但一致性核对与
        # 数据卡引用全部悬空。
        "config/labels-v1.json",
        # 0.11.1：`/api/traffic/v2/*` 的**运行期输入**。三个树文件缺任何一个，
        # 对应任务的概率就变成 `None`，而接口仍然 200 —— 症状是"走廊全是可飞"，
        # 读起来像"今天天气很好"而不像"包少带了模型"。指标文件缺了则模型卡整页
        # `MODEL_CARD_MISSING`。所以四样都写进正向自检。
        "models/ml-v2-vis.json",
        "models/ml-v2-vis3k.json",
        "models/ml-v2-gust.json",
        "data/training/metar/model-v2-metrics.json",
        "data/training/metar/dataset.json",
    ]
    lack = [m for m in must_have if not (DST / m).exists()]
    if lack:
        print(f"[FAIL] 启动链路必需却缺失：{lack}")
        return 1
    print(f"[OK] 正向自检通过：{len(must_have)} 项启动输入均在包内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
