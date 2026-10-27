# -*- coding: utf-8 -*-
"""包装 validate_deck + 可选版式策略终检。

    python checks/run_all.py 图片版.pptx 可编辑版.pptx --original 模板.pptx --run 任务/run
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def main() -> None:
    ap = argparse.ArgumentParser(description="pptx-unit checks/run_all")
    ap.add_argument("pptx", nargs="+")
    ap.add_argument("--original")
    ap.add_argument("--run", help="任务 run 目录，跑 layout_policy check-run")
    ap.add_argument("--skip-layout-check", action="store_true")
    args = ap.parse_args()
    rc = 0
    if args.run and not args.skip_layout_check:
        cmd = [sys.executable, str(SCRIPTS / "layout_policy.py"), "check-run", "--run", args.run]
        print("运行:", " ".join(cmd), flush=True)
        r = subprocess.run(cmd, cwd=str(SCRIPTS))
        if r.returncode != 0:
            rc = r.returncode
    for pptx in args.pptx:
        cmd = [sys.executable, str(SCRIPTS / "validate_deck.py"), pptx]
        if args.original:
            cmd += ["--original", args.original]
        print("运行:", " ".join(cmd), flush=True)
        r = subprocess.run(cmd, cwd=str(SCRIPTS))
        if r.returncode != 0:
            rc = r.returncode
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
