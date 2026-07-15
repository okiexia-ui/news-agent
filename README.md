<sub>🌐 <b>中文</b> · <a href="README.en.md">English</a></sub>

# News Agent · 新闻侠

一份「科技 · 资本 · 地缘政治」主题的结构化日报生成器：抓新闻 → agent 生成结构化内容 →排版 → 导出 PDF → 可选邮件发送。(别管用就完了)

作为 [Agent Skill](https://github.com/anthropics/skills) 使用（Claude Code / 其他兼容 agent runtime），也可以单独当命令行工具用。

## 这是什么 / 不是什么

- **是**：一套"HTML 模板 + 结构化 JSON 填充 + Playwright 导出 PDF"的日报生成 pipeline，配合一份让 agent 自己生成结构化内容的 skill 说明
- **不是**：定时任务系统。它不内置 cron，不帮你在后台自动跑——什么时候触发、要不要每天定时发，由你自己的调度层决定（cron、系统级任务计划、其他 agent 框架都行）

## 快速开始

```bash
git clone <this-repo>
cd news-agent
pip install -r requirements.txt
python3 -m playwright install chromium
cp .env.example .env   # 全部可选：抓新闻零配置就能跑，发邮件才需要填 Gmail 相关
```

在 Claude Code（或其他支持 Agent Skills 的 runtime）里把这个目录放进 skills 目录，然后直接说话：

```
「生成今天的 News Agent 日报」
```

Agent 会照着 `SKILL.md` 里的步骤：抓新闻 → 自己生成结构化 JSON → 渲染 PDF → 询问是否要发邮件。

也可以纯命令行手动跑：

```bash
python3 scripts/prefetch_news.py
# 手动或用别的方式生成 /tmp/news_agent_data.json（结构见 SKILL.md 里的 schema）
python3 scripts/render_and_send.py /tmp/news_agent_data.json morning --no-email
```

## 目录结构

```
news-agent/
├── SKILL.md                    # agent 读的主文档：pipeline 步骤 + JSON schema
├── templates/
│   └── news_agent.html     # A4 HTML 模板，__PLACEHOLDER__ 占位符
├── scripts/
│   ├── fetch_news.py           # 聚合 17 路来源（16 路免 key + 可选 NewsAPI），见下方"新闻来源"
│   ├── prefetch_news.py        # 跑 fetch_news.py 并写入缓存文件
│   └── render_and_send.py      # JSON → HTML → PDF（Playwright）→ 可选发邮件
├── references/
│   ├── design-system.md        # 色板/字体/占位符列表/设计决策记录
│   ├── json-parsing-quirks.md  # LLM 生成 JSON 时的常见解析坑
│   └── visual-qa-checklist.md  # 生成后怎么校验版面没崩
├── .env.example
└── requirements.txt
```

## 新闻来源

抓新闻**零配置可跑**——绝大多数来源不需要任何 API key：

| 类型 | 来源 | key |
|------|------|-----|
| 社区/研究 | HackerNews · Reddit (r/artificial, r/MachineLearning) · arXiv (cs.AI/cs.LG) | 不需要 |
| 通讯社/大报 RSS | BBC ×2 · Bloomberg ×2 · CNBC · The Guardian · NYT World · Al Jazeera · NPR | 不需要 |
| 科技媒体 RSS | TechCrunch · The Verge · Ars Technica · Wired · MIT Technology Review | 不需要 |
| 编辑信号 | The Economist RSS ×3 | 不需要 |
| 补充 | NewsAPI（可选，配 `NEWSAPI_KEY` 才启用） | 免费注册 |

此外 `SKILL.md` 里还有一步「agent 自己做 web research」：实时市场行情和头条事件核实由跑 skill 的 agent 用自己的 WebSearch 能力补充——RSS 管广度，agent 搜索管纵深。

## 配置

见 `.env.example`，全部可选：
- `NEWSAPI_KEY`——想多一路 NewsAPI 补充源再配，[newsapi.org](https://newsapi.org/register) 免费注册
- `GMAIL_APP_PASSWORD` / `FROM_EMAIL` / `TO_EMAILS`——发邮件才需要，Gmail 要用「应用专用密码」而不是登录密码

不发邮件的话，`render_and_send.py` 加 `--no-email` 参数即可，只导出 PDF 不需要配邮箱。

## License

MIT，见 [LICENSE](LICENSE)。
