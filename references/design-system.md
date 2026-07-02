# 设计系统（v3）

## 色彩

| Token | 值 | 用途 |
|-------|-----|------|
| `--bg` | `#f0e8da` | 暖色纸底 |
| `--card` | `#fcf8f0` | 卡片背景 |
| `--fg` | `#1a1816` | 主文字（近黑偏暖） |
| `--accent` | `#c04a1a` | 赤陶 — 全页面统一强调色 |
| `--accent2` | `#1a5c4a` | 森林绿 — 次要强调 |
| `--dark` | `#161412` | 深暗底（四信号、市场概览） |

## 排版层级

| 元素 | 字体 | 字号 | 字重 |
|------|------|------|------|
| 报头 | Newsreader 衬线 | 38px | 800 |
| 新闻标题 | Newsreader 衬线 | 16px | 700 |
| 区块标签 | Inter | 10px | 700 |
| 正文 | Noto Sans SC / Inter | 10.5px | 400 |
| 数字数据 | JetBrains Mono | 13-32px | 700-800 |
| 概率百分比 | JetBrains Mono | 13px | 800 |

## 数据突出设计

- Big Picture 编号：32px JetBrains Mono（暗底反白）
- 概率条：8px 高 + 背景对比轨道
- 市场数据：绿涨/红跌/黄警 三色 + font-weight 800
- 新闻正文：左赤陶边线（2.5px）分隔事实与影响

## 占位符列表

模板 (`templates/frontier_brief.html`) 里全部 `__PLACEHOLDER__`：

`__DATE__`, `__VOL__`, `__BIG_PICTURE__`, `__QUOTE__`, `__QUOTE_AUTHOR__`,
`__CROSS_SIGNAL__`, `__NEWS_CARDS__`, `__GEOPOLITICAL__`, `__MARKET_NEWS__`,
`__PROB_SCENARIO__`, `__COMMUNITY__`, `__WATCH_LIST__`, `__HASHTAGS__`,
`__MARKET_DASH__`, `__EDITOR_TAKE__`, `__DATA_SOURCE__`

改模板时如果新增/改名占位符，`scripts/render_and_send.py` 里对应的 `html.replace(...)` 调用要同步改，否则占位符会原样出现在 PDF 里而不报错——**每次改完模板务必按 `references/visual-qa-checklist.md` 跑一遍校验**，不要只看代码没跑渲染。

## 版面改动时的选型参考

改版面前建议先看这两类风格作为锚点：
- **Warm Editorial** — 暖色出版物（奶油纸底 + 赤陶橙 + 衬线混排），这是当前版本的主基调
- **Dense Research Report** — 研报风格，适合数据密集的区块（市场仪表盘、概率评估）

如果你装了 `huashu-design` skill，它的 40 种 HTML 原生风格库（`references/design-styles.md`）可以作为更大范围的弹药库，但别为了套风格牺牲这份日报本身的信息密度和可读性——它的定位是"5 分钟读完的结构化简报"，不是视觉 demo。

## 设计决策记录

| 决策 | 原因 |
|------|------|
| 报头用 Newsreader 衬线 | 出版感，与「日报」定位契合 |
| 赤陶 `#c04a1a` 统一 accent | 区分于其他科技早报的蓝色系，品牌识别 |
| 地缘从 4 列改 2 列 | A4 纸宽 210mm，4 列每列仅 45mm，2 列 95mm 可读性大幅提升 |
| BP 数字 32px | 数据信息第一视觉锚点，比旧版 18px 翻倍 |
| 底色 `#f0e8da` | 比 `#f5efe6` 更深更有质感 |
| 深暗底 `#161412` | 比 `#1e293b` 更深，增加视觉重量 |
| 概率条 8px | 比旧版 4px 翻倍，更易阅读 |
