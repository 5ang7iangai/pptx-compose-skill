# -*- coding: utf-8 -*-
"""prepare：建 run 目录、写 manifest、可选跑 profile_deck。

    python scripts/stages/prepare.py --template 模板.pptx [--materials a.docx b.pdf] -o 任务目录
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description="pptx-unit prepare")
    ap.add_argument("--template", required=True)
    ap.add_argument("--materials", nargs="*", default=[])
    ap.add_argument("-o", "--out", required=True, help="任务目录（将创建 run/）")
    ap.add_argument("--skip-profile", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    run = out / "run"
    diagrams = run / "diagrams"
    run.mkdir(parents=True, exist_ok=True)
    diagrams.mkdir(exist_ok=True)

    template = Path(args.template).resolve()
    if not template.exists():
        raise SystemExit(f"找不到模板: {template}")
    dest_tpl = out / template.name
    if template.resolve() != dest_tpl.resolve():
        shutil.copy2(template, dest_tpl)

    materials = []
    mat_dir = out / "材料"
    if args.materials:
        mat_dir.mkdir(exist_ok=True)
        for m in args.materials:
            p = Path(m)
            if not p.exists():
                raise SystemExit(f"找不到材料: {p}")
            target = mat_dir / p.name
            if p.resolve() != target.resolve():
                shutil.copy2(p, target)
            materials.append(str(Path("材料") / p.name))

    style_card = run / "风格卡.json"
    if not args.skip_profile:
        py = sys.executable
        cmd = [py, str(SCRIPTS / "profile_deck.py"), str(dest_tpl), "-o", str(style_card)]
        print("运行:", " ".join(cmd), flush=True)
        r = subprocess.run(cmd, cwd=str(SCRIPTS))
        if r.returncode != 0:
            raise SystemExit(r.returncode)

    inventory_path = run / "模板版式清单.json"
    if style_card.exists():
        inv_cmd = [sys.executable, str(SCRIPTS / "layout_policy.py"), "inventory",
                   "--style-card", str(style_card), "-o", str(inventory_path)]
        print("运行:", " ".join(inv_cmd), flush=True)
        r = subprocess.run(inv_cmd, cwd=str(SCRIPTS))
        if r.returncode != 0:
            raise SystemExit(r.returncode)

    manifest = {
        "template": dest_tpl.name,
        "materials": materials,
        "title": "",
        "run_dir": "run",
        "stages": {
            "prepare": "done",
            "text": "pending",
            "assemble": "pending",
            "diagrams": "pending",
            "apply": "pending",
            "validate": "pending",
        },
        "outputs": {"图片版": None, "可编辑版": None},
        "layout_inventory": "模板版式清单.json" if inventory_path.exists() else None,
    }
    (run / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "run": str(run), "manifest": str(run / "manifest.json"),
                      "style_card": str(style_card) if style_card.exists() else None,
                      "layout_inventory": str(inventory_path) if inventory_path.exists() else None},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
