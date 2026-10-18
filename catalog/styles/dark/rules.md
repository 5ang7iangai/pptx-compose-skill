风格：深色科技（参照 Microsoft Fluent 2 深色主题：中性深底分级、圆角 4–8、发光描边表达焦点）

- 画布第一个元素是铺满画布的深色底：rect x=0 y=0 宽高等于画布，rx 12，填 {night}。之后所有内容都画在这块深底上。
- 分区：{night2} 底，1 像素 {nightline} 细边，rx 8；分区标题用 {glow} 色粗体文字，前面一个 {glow} 小竖条（宽 4、高同字号），旁边一行 {line} 说明。
- 卡片：{night2} 底或比它稍亮一档（自行在 {night2} 与 {nightline} 之间取色），rx 6，1 像素 {nightline} 边；卡片标题白色 #FFFFFF 粗体，说明用 {light}。
- 焦点卡片（每张图 1–3 个，通常是核心能力）：边框改为 1.5 宽 {glow}，并加同色发光：feDropShadow dx 0 dy 0 stdDeviation 6，flood-color {glow}，透明度 0.45。
- 图标：{glow} 线条图形，无底色或 {nightline} 圆底（线宽 2，圆头）。
- 连线：{glow} 线宽 1.5–2，三角箭头；可用虚线 stroke-dasharray="6 4" 表示数据流。
- 底座/平台：{dominant} 实底 rx 6 的通栏，白字。
- 不用白色或浅色大面积色块；最亮的面积只能是文字和细线。
