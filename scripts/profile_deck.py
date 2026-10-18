# -*- coding: utf-8 -*-
"""抽模板风格卡：画布、主题色与字体、每页角色、文字槽、图片分类、重复版式。

    python scripts/profile_deck.py 模板.pptx -o 风格卡.json

字段说明见 docs/模板分析与风格卡.md。实现在 pptkit/profile.py。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pptkit.profile import analyze


def main() -> None:
    parser = argparse.ArgumentParser(description="抽取 pptx 风格卡")
    parser.add_argument("pptx")
    parser.add_argument("-o", "--output", help="写入 JSON 文件；缺省打印到标准输出")
    args = parser.parse_args()
    text = json.dumps(analyze(Path(args.pptx)), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(args.output)
    else:
        print(text)


if __name__ == "__main__":
    main()
