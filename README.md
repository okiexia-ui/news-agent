# News Agent · 新闻侠

一份「科技 · 资本 · 地缘政治」主题的结构化日报生成器：抓新闻 → agent 生成结构化内容 → 赤陶暖色调 A4 排版 → 导出 PDF → 可选邮件发送。

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
cp .env.example .env   # 填入 NEWSAPI_KEY（发邮件的话还要填 Gmail 相关）
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
│   ├── fetch_news.py           # 聚合 NewsAPI + HN + Reddit + arXiv + BBC/Bloomberg/CNBC/Economist RSS
│   ├── prefetch_news.py        # 跑 fetch_news.py 并写入缓存文件
│   └── render_and_send.py      # JSON → HTML → PDF（Playwright）→ 可选发邮件
├── references/
│   ├── design-system.md        # 色板/字体/占位符列表/设计决策记录
│   ├── json-parsing-quirks.md  # LLM 生成 JSON 时的常见解析坑
│   └── visual-qa-checklist.md  # 生成后怎么校验版面没崩
├── .env.example
└── requirements.txt
```

## 配置

见 `.env.example`。核心是两组：
- `NEWSAPI_KEY`——抓新闻用，[newsapi.org](https://newsapi.org/register) 免费注册拿
- `GMAIL_APP_PASSWORD` / `FROM_EMAIL` / `TO_EMAILS`——发邮件用，Gmail 要用「应用专用密码」而不是登录密码

不发邮件的话，`render_and_send.py` 加 `--no-email` 参数即可，只导出 PDF 不需要配邮箱。

## 为什么"生成结构化 JSON"这步不是脚本自动做的

早期版本里这步是脚本调用一个特定 CLI（`hermes chat -q ...`）来完成的。这个仓库把这步显式交还给**当前运行 skill 的 agent 自己做**：不同 agent runtime 调用自身 LLM 能力的方式天差地别，脚本层硬编码某一种反而不可移植。`SKILL.md` 里给了完整的 JSON schema 和填写规则，agent 照着填就行——这也是 Claude Code 这类工具里 skill 的标准写法：机械步骤交给脚本，需要判断力的步骤留给 agent。

## License

MIT，见 [LICENSE](LICENSE)。
