# -*- coding: utf-8 -*-
"""用本机 PowerPoint 把页导出成 PNG，看最终效果（两版都要看）。仅 Windows + 已装 PowerPoint。

    python scripts/preview.py 稿.pptx 输出目录 [页码 ...]     # 不写页码导出全部页

文件名：<稿名>-p<页码>.png，1600×900。
"""

import argparse
from pathlib import Path


def export(pptx: Path, out: Path, pages: list[int] | None = None, width: int = 1600, height: int = 900) -> list[Path]:
    import win32com.client

    out.mkdir(parents=True, exist_ok=True)
    app = win32com.client.Dispatch("PowerPoint.Application")
    pres = app.Presentations.Open(str(pptx.resolve()), ReadOnly=True, WithWindow=False)
    done = []
    try:
        for p in pages or range(1, pres.Slides.Count + 1):
            png = out.resolve() / f"{pptx.stem}-p{p}.png"
            pres.Slides(p).Export(str(png), "PNG", width, height)
            done.append(png)
    finally:
        pres.Close()
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description="导出幻灯片预览 PNG")
    ap.add_argument("pptx")
    ap.add_argument("out")
    ap.add_argument("pages", nargs="*", type=int)
    args = ap.parse_args()
    for png in export(Path(args.pptx), Path(args.out), args.pages):
        print(png)


if __name__ == "__main__":
    main()
