# -*- coding: utf-8 -*-
"""对交付包做「齐备性 + 排除项」双向复验，独立于打包脚本本身。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo import ROOT, package_dir  # noqa: E402

PKG = Path(package_dir())

REQUIRED = [
    # 一键脚本
    "start.bat", "stop.bat", "build.bat", "check-env.bat",
    "README.md", "VERSION",
    # 启动链路依赖的 ps1
    "scripts/dev.ps1", "scripts/start.ps1", "scripts/stop.ps1",
    "scripts/build.ps1", "scripts/check-environment.ps1",
    "scripts/check-powershell.ps1",
    # 配置
    "config/application.yml", "config/application.example.yml",
    "config/rules-v1.json",
    # Python 服务
    "backend-python/main.py",
    "backend-python/requirements.txt", "backend-python/requirements-lock.txt",
    "backend-python/requirements-dev.txt",
    "backend-python/real_weather.py", "backend-python/track2_agent.py",
    "backend-python/agent_tools.py", "backend-python/rules.py",
    "backend-python/traffic/service.py",
    "backend-python/traffic/weather_control.py",
    "backend-python/traffic/weather_sim.py",
    "backend-python/traffic/cma_tiles.py",
    "backend-python/traffic/radar_field.py",
    "backend-python/traffic/secret_store.py",
    "backend-python/weather/engine.py",
    "backend-python/weather/geometry.py",
    "backend-python/data/northeast.geojson",
    "backend-python/data/traffic/city-centers.json",
    "backend-python/data/traffic/aircraft-profiles.json",
    "backend-python/data/traffic/fixed-zones.json",
    "backend-python/data/stations/catalog.json",
    # Java 服务（源码 + wrapper）
    "backend-java/pom.xml", "backend-java/mvnw.cmd", "backend-java/mvnw",
    # mvnw 是「脚本 + properties」的配对物：只列脚本不列 properties，本清单就会
    # 对着一个跑不起来的包装器报「应有项齐备」。2026-10-07 的 `.mvn` 事故正是这样
    # 穿过所有闸门的（打包脚本把它当会话目录排除、复验脚本没列它、包看起来干净）。
    "backend-java/.mvn/wrapper/maven-wrapper.properties",
    "backend-java/src/main/resources/application.yml",
    # 前端
    "frontend/package.json", "frontend/package-lock.json",
    "frontend/index.html", "frontend/vite.config.js",
    "frontend/src/main.js",
    # 文档
    "changelog/CHANGELOG.md", "changelog/ISSUES.md",
    "changelog/DECISIONS.md", "changelog/README.md",
    "contracts",
]

MUST_ABSENT = [
    ".git", ".gitignore", ".gitattributes", ".editorconfig",
    ".workbuddy", ".run", ".audit", ".pytest_cache",
    "backups", "data_backup_20260911_0006",
    "tools", "tests", "archive", "artifacts",
    "frontend/node_modules", "frontend/dist",
    "backend-python/.venv", "backend-java/target",
    "backend-python/_sim_bench.py",
    "config/alc_secret.key",
    "config/qweather/qweather_private_key.pem",
    "config/qweather/qweather_public_key.pem",
    "backend-python/data/secrets.db",
]


def main() -> int:
    if not PKG.exists():
        print(f"[FAIL] 交付包不存在：{PKG}")
        return 1

    missing = [r for r in REQUIRED if not (PKG / r).exists()]
    leaked = [m for m in MUST_ABSENT if (PKG / m).exists()]

    print(f"包路径：{PKG}")
    files = [p for p in PKG.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    print(f"文件数：{len(files)}    体积：{size / 1024 / 1024:.1f} MB")
    print()

    if missing:
        print(f"[FAIL] 应有而缺失 {len(missing)} 项：")
        for m in missing:
            print(f"       - {m}")
    else:
        print(f"[OK] 应有项齐备（{len(REQUIRED)} 项全部存在）")

    if leaked:
        print(f"[FAIL] 应排除却存在 {len(leaked)} 项：")
        for m in leaked:
            print(f"       - {m}")
    else:
        print(f"[OK] 排除项干净（{len(MUST_ABSENT)} 项目标均不存在）")

    cred_hits = [
        p.relative_to(PKG).as_posix()
        for p in files
        if p.suffix.lower() in {".key", ".p12", ".pfx", ".jks", ".secret", ".pem"}
    ]
    if cred_hits:
        print(f"[FAIL] 仍存在密钥类文件：{cred_hits}")
    else:
        print("[OK] 无 .key/.pem/.p12/.pfx/.jks/.secret 类文件（凭据全部排除）")

    # 配对物检查 —— **问对象自己**，不从旁边推断。
    # REQUIRED 是一份人手维护的清单，它对「清单作者没想到的依赖」完全沉默：
    # 2026-10-07 的 `.mvn` 事故里，清单列了 mvnw.cmd 与 mvnw 却没人想到 properties，
    # 于是「应有项齐备」全额通过，而双击 start.bat 在 dev.ps1:35 抛「源码编译失败」。
    # 所以这里改成让包装器脚本自己交代它要读哪个文件：脚本里写了，就必须在包里。
    wrapper_deps = []
    for wrapper in ("backend-java/mvnw.cmd", "backend-java/mvnw"):
        w = PKG / wrapper
        if not w.exists():
            continue
        text = w.read_text(encoding="utf-8", errors="replace")
        # 首字符可能是点（`.mvn`），所以不能写成 [\w][\w./\\-]*
        for m in re.finditer(r"\$scriptDir[\\/]+([\w.][\w./\\-]*\.properties)", text):
            dep = m.group(1).replace("\\", "/")
            if (wrapper, dep) not in wrapper_deps:  # 同一依赖常被引用多次，去重
                wrapper_deps.append((wrapper, dep))

    broken_pairs = []
    for wrapper, dep in wrapper_deps:
        # 脚本自己在 backend-java/ 下，它写的相对路径就是相对脚本所在目录
        if not (PKG / Path(wrapper).parent / dep).exists():
            broken_pairs.append(f"{wrapper} 要读 {dep}，但包里没有")

    # 「解析出 0 条依赖」= 量具自己没量成，不能当通过。
    # 出口三类：0 通过 / 1 量出来坏 / 2 无法测量 —— 这里先判 2。
    # 之前这条只 print WARN 不进退出码，等于给「正则写错了」留了一个静默出口。
    cannot_measure = bool([w for w in ("backend-java/mvnw.cmd", "backend-java/mvnw")
                           if (PKG / w).exists()]) and not wrapper_deps

    if cannot_measure:
        print("[FAIL] 无法测量：包装器脚本在包里，却没能从它自述里解析出任何依赖 —— "
              "先修检查器（Maven Wrapper 的写法可能变了），不要在未测量的情况下放行。")
    elif broken_pairs:
        print(f"[FAIL] 包装器配对物缺失 {len(broken_pairs)} 项：")
        for b in broken_pairs:
            print(f"       - {b}")
    else:
        print(f"[OK] 包装器配对物齐备（{len(wrapper_deps)} 项依赖均由脚本自述而来）")

    return 1 if (missing or leaked or cred_hits or broken_pairs or cannot_measure) else 0


if __name__ == "__main__":
    sys.exit(main())
