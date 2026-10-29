"""把 Python 后端以**脱离父进程**的方式起起来（供探针使用）。

为什么不能直接在 Bash 工具里 `nohup ... &`：工具调用结束时它的进程树会被收掉，
服务随之消失 —— 表现是"下一条命令看不到端口"，而日志里一切正常。
用 DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP 让它不属于任何会话。
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "backend-python" / ".venv" / "Scripts" / "python.exe"
LOG = ROOT / ".run"
LOG.mkdir(exist_ok=True)

DETACHED = 0x00000008
NEW_GROUP = 0x00000200

proc = subprocess.Popen(
    [str(PY), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8600"],
    cwd=str(ROOT / "backend-python"),
    stdout=open(LOG / "bg-py.out.log", "w"),
    stderr=open(LOG / "bg-py.err.log", "w"),
    stdin=subprocess.DEVNULL,
    creationflags=DETACHED | NEW_GROUP,
    close_fds=True,
)
print("launched pid", proc.pid)
