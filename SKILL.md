---
name: news-agent
description: 生成 NEWS AGENT 风格的科技/资本/地缘政治日报——抓取新闻 → agent 生成结构化 JSON → 赤陶暖色 A4 HTML/PDF 排版 → 可选邮件发送。触发词：生成日报、news agent、今日简报、早报、晚报、日报排版、改进日报版面。也可作为"HTML 模板 + 结构化数据填充 + Playwright 导出 PDF"这套模式的参考实现。
---

# NEWS AGENT

一份"科技 · 资本 · 地缘政治"主题的结构化日报生成器。产出是一份赤陶暖色调、A4 排版的 PDF/HTML，可选邮件发送。

## 这个 skill 不做什么

不内置定时任务/cron。它是一次性可调用的 pipeline：你（或你的调度系统）决定什么时候触发它。如果你有自己的 agent 调度框架（cron、Hermes、Airflow 等），在那一层接入即可——本 skill 只管"从新闻到 PDF"这一段。

## Pipeline 总览

```
1. scripts/prefetch_news.py     → 抓取新闻，写入 /tmp/news_agent_news_cache.txt
2. 【你，agent】                 → 读缓存，按下方 JSON schema 生成结构化简报内容
3. 保存为 /tmp/news_agent_data.json
4. scripts/render_and_send.py   → 读 JSON，填充 HTML 模板，Playwright 导出 A4 PDF，(可选)发邮件
```

第 2 步**必须由当前运行本 skill 的 agent 完成**——不要指望脚本自己调 LLM。这是设计上的取舍：不同 agent runtime 调用自身 LLM 的方式不同（`hermes chat`、内部工具、直接生成…），让脚本硬编码某一种反而不可移植。你已经是 LLM，直接把新闻数据变成结构化内容就是你的工作。

## 使用步骤

### Step 1 · 抓新闻

```bash
python3 scripts/prefetch_news.py
```

零配置可跑：绝大多数来源不需要任何 key——HackerNews / Reddit / arXiv，以及 BBC / Bloomberg / CNBC / Economist / TechCrunch / The Verge / Ars Technica / Wired / MIT Technology Review / The Guardian / Al Jazeera / NYT World / NPR 的 RSS。环境变量 `NEWSAPI_KEY`（见 `.env.example`）是**可选**的，配了会追加 NewsAPI 一路补充源，没配会打一行 warning 然后照常跑。抓取结果写入 `/tmp/news_agent_news_cache.txt`。

### Step 1.5 · 补充 web research（你来做，可选但推荐）

RSS 抓的是"过去几小时发生了什么"，但有两类信息它给不了，需要你用自己的 WebSearch / WebFetch 能力补：

1. **市场数据**（`market_data` 板块）——RSS 里没有实时行情。搜"S&P 500 today"、"BTC price"之类，拿当日真实数值；搜不到就用你知识里的近似值并在 `editor_take` 里注明是估算
2. **头条事件的纵深**——缓存里的条目只有标题+两行摘要。对你准备放进 `big_picture` 的 3-4 条大事，值得各搜一次确认细节、时间线、数字，避免凭一行摘要脑补出错误的"事实"

不要为每条新闻都搜（太慢），只给要写进「四大信号」和「地缘政治」板块的重点事件做核实。

### Step 2 · 生成结构化 JSON（你来做这步）

读 `/tmp/news_agent_news_cache.txt`，基于其中的新闻条目，产出符合下面 schema 的 JSON，写入 `/tmp/news_agent_data.json`。

**要求**：
- 全部内容用中文
- `market_data` 5-8 个真实市场指标（S&P 500 / NASDAQ / BTC / USD-CNY / 10Y Yield / VIX / Oil / Gold），`change` 用 up/down/flat/warn
- `probabilities` 至少 3 个，基于当日新闻做合理概率评估
- JSON 字符串内部**不要用 ASCII 双引号 `"`**（会break JSON parsing）——中文引用用「」『』，或者不加引号。这是最常见的解析失败原因，务必遵守
- 只输出 JSON 本体，不要 markdown 代码块

Schema：

```json
{
  "big_picture": [
    {"tag": "技术突破|资本动向|基础设施|地缘风险", "title": "...", "desc": "..."}
  ],
  "quote": {"text": "...", "author": "..."},
  "cross_signal": [
    {"title": "① XX × XX", "body": "..."}
  ],
  "news": [
    {"category": "前沿科技|AI产品|AI安全|AI硬件|开源模型|资本市场|货币政策|市场",
     "impact": "高影响|中影响|社区热度",
     "credibility": "高可信|中可信|低可信",
     "title": "...", "source": "...", "signal": "...",
     "fact": "...", "impact_text": "...", "url": "..."}
  ],
  "geopolitical": [
    {"title": "...", "source": "...", "signal": "...",
     "what": "...", "why": "...", "market": "...", "watch": "..."}
  ],
  "probabilities": [
    {"event": "...", "pct": 65}
  ],
  "scenarios": [
    {"type": "乐观|基准|悲观", "text": "..."}
  ],
  "watch_list": [{"text": "..."}],
  "market_data": [
    {"name": "S&P 500", "value": "...", "change": "up|down|flat|warn"}
  ],
  "editor_take": "...",
  "hashtags": ["#..."],
  "arxiv": [{"title": "...", "authors": "...", "summary": "..."}]
}
```

`arxiv` 字段仅晚报（evening）使用，早报可省略。

新闻数据不够撑起某个板块时，把对应数组留空即可——`render_and_send.py` 会自动显示"今日无突出XX"的兜底文案，不要编造内容填充。

### Step 3 · 渲染 + 导出 PDF (+ 可选发邮件)

```bash
# 只导出 PDF，不发邮件（默认先用这个跑通）
python3 scripts/render_and_send.py /tmp/news_agent_data.json morning --no-email

# 需要发邮件时（先配置好 .env，见下方"配置"）
python3 scripts/render_and_send.py /tmp/news_agent_data.json morning
```

第二个参数是 `morning` 或 `evening`——决定报头标注早报/晚报，以及是否渲染 arxiv 板块。

### Step 4 · 校验（生成后务必做，不要凭感觉说"看起来没问题"）

用 Playwright 截图或 `pdftoppm` 把 PDF 转成图片自己看一遍，检查：卡片是否溢出、网格是否对齐、占位符 `__XXX__` 是否有遗漏未替换（说明 schema 字段名对不上）。完整检查清单见 `references/visual-qa-checklist.md`。

## 配置

复制 `.env.example` 为 `.env`，填入：

| 变量 | 用途 | 必需？ |
|------|------|--------|
| `NEWSAPI_KEY` | newsapi.org 的 key，供 `fetch_news.py` 用 | 抓新闻必需 |
| `GMAIL_APP_PASSWORD` | Gmail 应用专用密码（不是登录密码），16 位 | 发邮件必需 |
| `FROM_EMAIL` | 发件邮箱 | 发邮件必需 |
| `TO_EMAILS` | 收件邮箱，逗号分隔 | 发邮件必需 |
| `SMTP_SERVER` / `SMTP_PORT` | 默认 smtp.gmail.com:587，换邮箱服务商时改 | 可选 |

`.env` 不要提交进 git（已在 `.gitignore` 里）。

## 设计系统

见 `references/design-system.md`——色板、字体层级、v3 版本的设计决策记录（为什么用赤陶橙、为什么地缘板块是 2 列不是 4 列等）。改版面时先看这份，理解现有取舍再动手，不要凭空改。

## 已知坑

- **LLM 生成的 JSON 经常不是干净的 JSON**（夹带 markdown 代码块、前缀文字、CJK 引号冲突）——如果你打算写代码解析而不是自己边生成边校验，参考 `references/json-parsing-quirks.md` 的清洗流程。
- 具体时间戳/概率数字属于你在生成 Step 2 时的合理估计，不是抓取到的精确数据——如实呈现为"估算"，不要暗示是权威数据源。
