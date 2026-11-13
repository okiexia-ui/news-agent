<sub>🌐 <b>中文</b> · <a href="README.en.md">English</a></sub>

# News Agent · 新闻侠

一份「科技 · 资本 · 地缘政治」主题的结构化日报生成器：抓新闻 → agent 生成结构化内容 → 排版 → 导出 PDF → 可选邮件发送。

作为 [Agent Skill](https://github.com/anthropics/skills) 使用（Claude Code / 其他兼容 agent runtime），也可以单独当命令行工具用。

## 这是什么 / 不是什么

- **是**：一套"HTML 模板 + 结构化 JSON 填充 + Playwright 导出 PDF"的日报生成 pipeline，配合一份让 agent 自己生成结构化内容的 skill 说明
- **不是**：定时任务系统。它不内置 cron，不帮你在后台自动跑——什么时候触发、要不要每天定时发，由你自己的调度层决定（cron、系统级任务计划、其他 agent 框架都行）

## 快速开始

```bash
git clone https://github.com/okiexia-ui/news-agent.git
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
# 读取脚本输出的 news_cache.json，生成简报 JSON（结构见 SKILL.md）
# 复制 run_id；article_urls 只填写本期实际采用的缓存文章
python3 scripts/render_and_send.py /tmp/news_agent_data.json morning --no-email
```

无需联网的排版示例（全部为演示数据，不发送邮件）：

```bash
python3 scripts/render_and_send.py examples/brief.sample.json evening --no-email --output /tmp/news-agent-sample.pdf
```

## 可信度与失败处理

- 行情数值须同时带来源链接、带时区的数据时间和单位；不完整时显示“暂无数据”。不允许模型凭记忆估算行情。来源字段是追溯信息，不等于程序已核实原文事实。
- 预测概率可留空；显示时明确标为主观估计，并附依据和期限。
- 每路 RSS/API 独立报告状态、条数、耗时和错误。默认 6 路并发；单次网络尝试最多 6 秒、最多 2 次，单个来源预算 40 秒，整个预抓取子进程超时 240 秒。
- 全部来源失败或输出异常时返回非零退出码并保留旧缓存；部分来源失败时标为 `degraded`。成功但没有新文章与抓取失败是不同状态。
- 只有成功生成 PDF 后，实际采用的缓存 URL 才会标记为已生成。抓取、入选、生成和发送状态分开保存，重跑不会吞掉未采用的候选。

默认状态目录为 `~/.cache/news-agent`，可用 `.env` 或环境变量 `NEWS_AGENT_STATE_DIR` 覆盖：`news_cache.json` 是权威缓存，`news_cache.txt` 是阅读版，`fetch_status.json` 是最近一次抓取状态，`state.sqlite3` 保存运行及条目记录。三个脚本须使用同一目录；历史记录保留 30 天。

升级后不读取旧 `/tmp/news_agent_seen_urls.txt`，避免继承错误的已读记录；首次运行可能重新看到旧版本已发布的文章。旧的手工简报 JSON 仍可渲染，但缺少行情元数据时数值会隐藏；省略 `run_id` 和 `article_urls` 时不更新去重状态。邮件失败可使用原 JSON 重试，程序不会自动重发或保证 SMTP 恰好一次投递。

## 目录结构

```
news-agent/
├── SKILL.md                    # agent 读的主文档：pipeline 步骤 + JSON schema
├── templates/
│   └── news_agent.html     # A4 HTML 模板，__PLACEHOLDER__ 占位符
├── scripts/
│   ├── fetch_news.py           # 多路 RSS/API 聚合、筛选和来源健康报告
│   ├── prefetch_news.py        # 跑 fetch_news.py 并写入缓存文件
│   ├── news_state.py           # SQLite 状态、URL 规范化、原子缓存写入
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

## 验证

```bash
python3 -m unittest discover -s tests -v
```

离线测试覆盖来源失败、缓存保护、去重、时间解析、行情来源约束、渲染及发送状态；实际来源可用性以每次抓取报告为准。

## License

MIT，见 [LICENSE](LICENSE)。

