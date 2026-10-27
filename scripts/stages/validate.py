# -*- coding: utf-8 -*-
"""validate：包装 validate_deck，可对两套 pptx 依次检查；可选跑版式策略终检。

    python scripts/stages/validate.py 图片版.pptx [可编辑版.pptx] --original 模板.pptx
    python scripts/stages/validate.py 图片版.pptx 可编辑版.pptx --run 任务/run --original 模板.pptx
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pptx", nargs="+", help="一张或多张待检 pptx")
    ap.add_argument("--original", help="模板/原稿，用于过滤原有关系问题")
    ap.add_argument("--require-text", action="append", default=[])
    ap.add_argument("--diagram-slide", type=int, action="append", default=[])
    ap.add_argument("--run", help="任务 run 目录：额外跑 layout_policy check-run（终检）")
    ap.add_argument("--skip-layout-check", action="store_true", help="跳过版式策略终检")
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
        for t in args.require_text:
            cmd += ["--require-text", t]
        for s in args.diagram_slide:
            cmd += ["--diagram-slide", str(s)]
        print("运行:", " ".join(cmd), flush=True)
        r = subprocess.run(cmd, cwd=str(SCRIPTS))
        if r.returncode != 0:
            rc = r.returncode
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
