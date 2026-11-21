"""本地启动器：用固定参数拉起 Streamlit 服务（无需 Docker 时使用）。

用法：python tests/start_streamlit.py
等价于在项目根目录执行：
    streamlit run app.py --server.port=8501 --server.headless=true
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]

cmd = [
    sys.executable,
    "-m",
    "streamlit",
    "run",
    str(root / "app.py"),
    "--server.port=8501",
    "--server.headless=true",
    "--server.address=0.0.0.0",
    "--browser.gatherUsageStats=false",
]

print("START:", " ".join(cmd), flush=True)
subprocess.run(cmd, cwd=str(root), check=False)
