# 检查（checks）

三层校验（与 [references/校验与验收.md](../references/校验与验收.md) 一致）：

1. **包完整**：zip/关系/幻灯片列表（`validate_deck.py`）
2. **改动到位**：导语–图重叠、页签 gap、空壳卡、同行等宽、字体角色等（`pptkit.layout_check` + 报告字段）
3. **逐页看**：`preview.py` 导出后肉眼；看完删预览

入口：

```text
python checks/run_all.py <图片版.pptx> <可编辑版.pptx> --original 模板.pptx
# 或
python scripts/stages/validate.py …
```

检查项名称清单见 `deck.yaml`。前两层不过，不得交付。

## 版式策略终检

交付前加 `--run <run目录>`，会先跑 `scripts/layout_policy.py check-run`（防单调 / 未知 layout），不过则退出码非 0。
