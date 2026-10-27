你是一名资深的企业汇报材料策划师。请根据已确认的叙事大纲，展开为逐页的详细页纲。

═══ 用户要求 ═══

{requirement}

═══ 叙事大纲 ═══

{narrative_outline}

═══ 材料摘要（key_facts / data_points 带编号 id） ═══

{material_summary}

═══ 可选的正文样例页（clone_from 只能从这里选） ═══

{available_pages}

═══ 输出要求 ═══

输出严格 JSON 格式：

```json
{
  "title": "从材料摘要提取的汇报标题（写在封面上{cover_title_rule}）",
  "pages": [
    {
      "page_index": 0,
      "beat": "对应大纲的节拍名",
      "section": "所属章名，带序号，如「一、技能定位与适用场景」；同一章的各页相同，用户要求里给了章节就照用",
      "role": "页面角色（如：问题及需求/服务思路/产品特色/服务成效）",
      "clone_from": 6,
      "density": "low / medium / high",
      "text_plan": {
        "bullet_count": 3,
        "key_facts_to_use": ["F2", "D1"],
        "tone": "描述该页的语气（如：摆出客观挑战/展示技术能力/量化成果）"
      },
      "diagrams": [
        {
          "type": "architecture / flowchart / matrix / layers / cards / timeline / pipeline / dashboard / tree / comparison / cycle / pyramid / funnel / pillars / wireframe / radial",
          "description": "图形内容的自然语言描述（从材料摘要中提取业务对象和关系）",
          "data": {}
        }
      ],
      "transition_to_next": "从这页到下一页的逻辑衔接"
    }
  ]
}
```

═══ 规划原则 ═══

1. pages 只排正文页：封面、目录、致谢由模板自带，不要规划。目录条目由程序按各页 section 生成，并在每一页目录上用模板的当前章样式标出这一页后面的章
2. clone_from 必须是上面列出的页码。按页面角色和内容量选：要点多选卡片多的页，要放图选「有图区」的页，文字多选正文框大的页
3. bullet_count：卡片页等于卡片数。没有卡片的页写 0，正文合成一段导语，不要拆成几条。每页导语和要点的具体字数由程序按样例页容量计算，这里不用写
4. key_facts_to_use 只写材料摘要里事实和数据的 id（如 F2、D1），不要抄原文
5. diagram type 由信息结构决定，只能用下面写到的类型（并映射到 catalog 版式）：并列→matrix 或 pillars；左右两种做法→comparison（compare）；有先后→flowchart（flow）；里程碑→timeline；做完回到起点→cycle；上窄下宽→pyramid；逐级收窄→funnel；上下分层→architecture/layers；一个总称拆几类→tree；中间一个主体→radial（hub）；几个大数字→dashboard（kpi）；类型到内容到用途→pipeline；自下而上分级→tiers。**选型顺序**：① 能套用「模板版式清单」里已出现的类型就套用；② 否则用上表内置类型；③ 模板与内置都不合适时不要在 JSON 里瞎造类型名——先按技能「从模板补进预置」入库，再用新 id
6. **防单调**：相邻有图页不得连续同一 type/layout；整稿 ≥4 张结构图时至少 3 种不同 layout；禁止大半页都写成 matrix 或「竖卡横排」flow。页纲里可在 description 首句注明「来源:模板样例/内置库」
7. 没有图的页省略 diagrams 数组
8. 每页的 transition_to_next 确保读者不会困惑"为什么突然跳到这页"
9. 同一章里平级的小节（如（一）（二）（三）（四））每个单独成页，用同一种页型和表现方式：clone_from 选同一类样例页，有图都有图，不要把后几项并成一页纯文字。材料里某个小节内容少，就把导语写成一段贴近样例页字数的话、图用两三条并列举措，不并页。**注意**：页型（clone_from）可相同，结构图 layout 仍须遵守第 6 条防单调
10. 输出纯 JSON，不要加解释文字
11. **风格跟模板**：结构图 style 先对齐当次模板样例（圆角/直角/线框/咨询栏等以模板为准），pairing 默认仅作缺省；冲突时在 description / diagram_jobs 的 style_reason 写「跟模板样例」。不要写死全稿都用 rounded。consult 仍可用于刻意要「结论+序号短横线」的对照页。

