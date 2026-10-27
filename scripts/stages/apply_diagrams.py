# -*- coding: utf-8 -*-
"""apply_diagrams：读已有 SVG + brief，写入图片版与可编辑版。

    python scripts/stages/apply_diagrams.py --pptx 中间稿.pptx --jobs jobs.json -o 题目.pptx
    python scripts/stages/apply_diagrams.py --run 任务目录/run -o 题目.pptx
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from diagram.catalog import bind_styles
from diagram.palette import palette_from
from diagram.pipeline import deck_font, figure_dir, finish, make_job, prepare_svgs, variant_path
from pptkit.ooxml import load_pptx, require_different
from pptkit.profile import analyze


def _load_jobs(run: Path | None, jobs_path: Path | None, fig_dir: Path, svg_dir: Path) -> list[dict]:
    path = jobs_path or ((run / "diagram_jobs.json") if run else None)
    if not path or not path.exists():
        raise SystemExit(
            f"找不到 jobs 文件: {path}。请先跑 assemble，或提供 --jobs；"
            "每项含 slide、diagram（含 bbox）、可选 svg 文件名。"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("jobs") or raw.get("diagrams") or []
    jobs = []
    missing = []
    for it in items:
        diag = it.get("diagram") or it
        slide = int(it.get("slide") or diag.get("slide"))
        label = int(it.get("label") or slide)
        job = make_job(fig_dir, slide, label, diag, False)
        svg_name = it.get("svg") or Path(job["svg_path"]).name
        candidates = [
            svg_dir / Path(svg_name).name,
            fig_dir / Path(svg_name).name,
            Path(svg_name) if Path(svg_name).is_absolute() else None,
        ]
        found = next((p for p in candidates if p and p.exists()), None)
        if found:
            job["svg_path"] = found
            job["png_path"] = found.with_suffix(".png")
        else:
            missing.append(f"第 {slide} 页 → {Path(svg_name).name}")
            job["svg_path"] = svg_dir / Path(svg_name).name
        jobs.append(job)
    if missing:
        raise SystemExit(
            "缺少助手写好的 SVG（pptx-unit 不调用外部模型）。缺页：\n  "
            + "\n  ".join(missing)
            + "\n请按 prompts/diagram/generate_svg.md 写到 run/diagrams/ 后重试。"
        )
    return jobs


def main() -> None:
    ap = argparse.ArgumentParser(description="应用已有 SVG → 两套 pptx")
    ap.add_argument("--run", help="run 目录")
    ap.add_argument("--pptx", help="中间稿/现稿；默认 run/中间稿.pptx")
    ap.add_argument("--jobs", help="jobs JSON")
    ap.add_argument("-o", "--output", required=True, help="基准名（写出 -图片版/-可编辑版）")
    ap.add_argument("--style-card", help="风格卡 JSON；默认 run/风格卡.json 或从 pptx 分析")
    args = ap.parse_args()

    run = Path(args.run) if args.run else None
    pptx = Path(args.pptx) if args.pptx else (run / "中间稿.pptx" if run else None)
    if not pptx or not pptx.exists():
        raise SystemExit("需要 --pptx 或 run/中间稿.pptx")
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for tag in ("图片版", "可编辑版"):
        require_different(pptx, variant_path(dest, tag))

    fig_dir = figure_dir(dest)
    svg_dir = (run / "diagrams") if run and (run / "diagrams").is_dir() else fig_dir

    jobs = _load_jobs(run, Path(args.jobs) if args.jobs else None, fig_dir, svg_dir)

    try:
        bind_styles([j["diagram"] for j in jobs])
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    card = None
    sc = Path(args.style_card) if args.style_card else (run / "风格卡.json" if run else None)
    if sc and sc.exists():
        card = json.loads(sc.read_text(encoding="utf-8"))
    else:
        card = analyze(pptx)

    parts = load_pptx(pptx)
    prepare_svgs(jobs, palette_from(card), svg_dir=svg_dir)
    result = finish(parts, jobs, dest, deck_font(card), {}, (card.get("fonts") or {}).get("roles"))

    if run and (run / "manifest.json").exists():
        man = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
        man.setdefault("stages", {})["apply"] = "done"
        man.setdefault("stages", {})["diagrams"] = "done"
        man["outputs"] = result.get("outputs")
        (run / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, default=str, indent=1))


if __name__ == "__main__":
    main()
