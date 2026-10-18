# -*- coding: utf-8 -*-
"""改 spec 里某一页的出图标记：打上 regen、写入/清空审阅意见 feedback。

    python scripts/edit_spec.py spec.json 5 --regen               # 第 5 页下次重画
    python scripts/edit_spec.py spec.json 5 --feedback 意见.txt    # 意见.txt 每行一条，配合 --fix 在原图上修补
    python scripts/edit_spec.py spec.json 0 --clear               # 清掉全部页的 regen 和 feedback

页码：重做原稿的 spec 按 slides[].slide（原稿页码）；加章节的 spec 按 slides 的顺序（第几张正文页，从 1 起）。
跑完任务后记得 --clear，否则下次还会重画/修补。
"""

import argparse
import json
from pathlib import Path


def page_no(i: int, s: dict) -> int:
    return s.get("slide") or i + 1


def main() -> None:
    ap = argparse.ArgumentParser(description="设置或清除 spec 页上的 regen / feedback")
    ap.add_argument("spec")
    ap.add_argument("slide", type=int, help="页码；0 表示全部页")
    ap.add_argument("--regen", action="store_true")
    ap.add_argument("--feedback", help="意见文件，每行一条")
    ap.add_argument("--clear", action="store_true")
    args = ap.parse_args()

    path = Path(args.spec)
    spec = json.loads(path.read_text(encoding="utf-8"))
    for i, s in enumerate(spec["slides"]):
        if args.slide and page_no(i, s) != args.slide:
            continue
        s.pop("regen", None)
        s.pop("feedback", None)
        if args.regen:
            s["regen"] = True
        if args.feedback and not args.clear:
            s["feedback"] = [ln.strip() for ln in Path(args.feedback).read_text(encoding="utf-8").splitlines()
                             if ln.strip()]
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print({page_no(i, s): {"regen": s.get("regen", False), "feedback": len(s.get("feedback", []))}
           for i, s in enumerate(spec["slides"])})


if __name__ == "__main__":
    main()
