你是一名资深的企业汇报材料策划师。请根据以下信息，设计这份幻灯片的叙事大纲。

═══ 材料摘要 ═══

{material_summary}

═══ 用户要求 ═══

{requirement}

═══ 模板信息 ═══

模板有 {template_page_count} 页，页型分布：{page_type_distribution}
{visual_profile_summary}

═══ 输出要求 ═══

输出严格 JSON 格式：

```json
{
  "narrative_type": "叙事类型：problem_solution_impact / achievement_showcase / technical_proposal / product_introduction",
  "target_audience": "从材料摘要的 audience_hint 继承或根据用户要求调整",
  "story_arc": [
    {
      "beat": "节拍名（2-4字，如：开场/痛点/方案总览/核心能力/落地效果/展望）",
      "purpose": "这个节拍要回答读者的什么问题（一句话）",
      "pages": 1
    }
  ],
  "density_bias": "low / medium / high（全局内容密度偏好）",
  "total_new_pages": 8,
  "transition_logic": "一句话描述页与页之间的逻辑衔接方式"
}
```

═══ 策划原则 ═══

0. 封面、目录、致谢页由模板自带，story_arc 和 total_new_pages 只算正文页，不要排「封面/开场页」「致谢」节拍
1. story_arc 的节拍数量和页数跟着模板的节奏走，不要每次都套四页
2. 每个 beat 的 purpose 必须是读者关心的问题，不是制作者的描述
3. 简单课题 6-8 页，复杂课题 10-15 页，不要为了凑数加空洞的页
4. 叙事要有起承转合：先建立场景→再给出方案→最后用事实证明
5. density_bias 参考模板的视觉理解：模板留白多就用 medium，模板信息密就用 high
6. 输出纯 JSON，不要加解释文字
