<sub>🌐 <a href="README.md">中文</a> · <b>English</b></sub>

# News Agent · 新闻侠

A structured daily-brief generator for tech, capital markets, and geopolitics: fetch news → the agent writes structured content → layout → PDF export → optional email delivery. (It just works.)

Use it as an [Agent Skill](https://github.com/anthropics/skills) (Claude Code or any compatible agent runtime), or run it as a plain command-line tool.

## What it is / isn't

- **Is**: an "HTML template + structured JSON fill + Playwright PDF export" daily-brief pipeline, plus a skill document that has the agent generate the structured content itself
- **Isn't**: a scheduler. There is no built-in cron — when it runs and whether it sends daily is up to your own scheduling layer (cron, OS task scheduler, or another agent framework)

## Quick start

```bash
git clone <this-repo>
cd news-agent
pip install -r requirements.txt
python3 -m playwright install chromium
cp .env.example .env   # everything is optional: news fetching works with zero config; email needs Gmail settings
```

In Claude Code (or any runtime that supports Agent Skills), drop this directory into your skills folder and just say:

```
"Generate today's News Agent brief"
```

The agent follows the steps in `SKILL.md`: fetch news → generate structured JSON itself → render the PDF → ask whether to email it.

Or run it manually from the command line:

```bash
python3 scripts/prefetch_news.py
# produce /tmp/news_agent_data.json by hand or by other means (schema in SKILL.md)
python3 scripts/render_and_send.py /tmp/news_agent_data.json morning --no-email
```

> **Note on language**: the default brief content is written in Chinese (the JSON-generation rules in `SKILL.md` say so). For an English brief, tell your agent to generate the JSON in English instead — the template and renderer are language-agnostic except for a few fixed section labels.

## Directory layout

```
news-agent/
├── SKILL.md                    # the agent-facing doc: pipeline steps + JSON schema
├── templates/
│   └── news_agent.html         # A4 HTML template with __PLACEHOLDER__ slots
├── scripts/
│   ├── fetch_news.py           # aggregates 17 sources (16 keyless + optional NewsAPI), see "News sources"
│   ├── prefetch_news.py        # runs fetch_news.py and writes the cache file
│   └── render_and_send.py      # JSON → HTML → PDF (Playwright) → optional email
├── references/
│   ├── design-system.md        # palette / typography / placeholder list / design decisions (Chinese)
│   ├── json-parsing-quirks.md  # common pitfalls parsing LLM-generated JSON (Chinese)
│   └── visual-qa-checklist.md  # how to verify the layout didn't break (Chinese)
├── .env.example
└── requirements.txt
```

## News sources

News fetching **runs with zero configuration** — most sources need no API key at all:

| Type | Sources | Key |
|------|---------|-----|
| Community / research | HackerNews · Reddit (r/artificial, r/MachineLearning) · arXiv (cs.AI/cs.LG) | none |
| Wire / major outlets (RSS) | BBC ×2 · Bloomberg ×2 · CNBC · The Guardian · NYT World · Al Jazeera · NPR | none |
| Tech press (RSS) | TechCrunch · The Verge · Ars Technica · Wired · MIT Technology Review | none |
| Editorial signal | The Economist RSS ×3 | none |
| Supplemental | NewsAPI (optional, enabled only when `NEWSAPI_KEY` is set) | free signup |

`SKILL.md` also includes an "agent does its own web research" step: live market data and headline verification come from the running agent's own WebSearch capability — RSS for breadth, agent search for depth.

## Configuration

See `.env.example`; everything is optional:
- `NEWSAPI_KEY` — only if you want NewsAPI as an extra supplemental source; free signup at [newsapi.org](https://newsapi.org/register)
- `GMAIL_APP_PASSWORD` / `FROM_EMAIL` / `TO_EMAILS` — only for email delivery; Gmail requires an App Password, not your login password

If you don't send email, pass `--no-email` to `render_and_send.py` and no mail settings are needed.

## License

MIT, see [LICENSE](LICENSE).
