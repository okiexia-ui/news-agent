#!/usr/bin/env python3
"""
Render a FRONTIER BRIEF structured-JSON payload into the HTML template,
export it to an A4 PDF via Playwright, and (optionally) email it out.

This script does NOT call an LLM. The agent running this skill is expected
to generate the structured JSON itself (see SKILL.md) and pass it in as a
file. That keeps this script portable across any agent runtime instead of
shelling out to a specific CLI.

Usage:
    python3 render_and_send.py <data.json> <morning|evening> [--no-email]
"""

import os, sys, smtplib, tempfile
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from datetime import datetime
import json

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
TEMPLATE_PATH = PROJECT_DIR / "templates" / "frontier_brief.html"


def load_env():
    """Load KEY=VALUE pairs from .env next to the project root, without overriding
    variables already set in the real environment."""
    env_path = PROJECT_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_env()

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
FROM_EMAIL = os.environ.get("FROM_EMAIL", "")
TO_EMAILS = [e.strip() for e in os.environ.get("TO_EMAILS", "").split(",") if e.strip()]


def _safe_items(items) -> list:
    """Filter a list to dict-only items, skipping strings (malformed LLM output)."""
    if not isinstance(items, list):
        return []
    good = []
    for item in items:
        if isinstance(item, dict):
            good.append(item)
        else:
            print(f"Skipping non-dict item in list: {type(item).__name__} ({str(item)[:80]})")
    return good


def render_html(data: dict, time_label: str) -> str:
    """Fill the FRONTIER BRIEF HTML template with data."""
    html = TEMPLATE_PATH.read_text()

    # Big picture
    bp_html = ""
    for i, item in enumerate(_safe_items(data.get("big_picture", []))):
        tag_map = {"技术突破": "bp-t1", "资本动向": "bp-t2", "基础设施": "bp-t3", "地缘风险": "bp-t4"}
        cls = tag_map.get(item.get("tag", ""), "bp-t1")
        bp_html += f'<div class="bp-card"><div class="bp-n">{i+1:02d}</div><div class="bp-b"><div class="bp-tag {cls}">{item.get("tag","")}</div><div class="bp-title">{item.get("title","")}</div><div class="bp-desc">{item.get("desc","")}</div></div></div>'
    html = html.replace("__BIG_PICTURE__", bp_html)

    # Quote
    q = data.get("quote", {})
    html = html.replace("__QUOTE__", q.get("text", ""))
    html = html.replace("__QUOTE_AUTHOR__", q.get("author", ""))

    # Cross-signal
    cs_html = ""
    for item in _safe_items(data.get("cross_signal", [])):
        cs_html += f'<div class="cross-item"><div class="ci-title">{item.get("title","")}</div><div class="ci-body">{item.get("body","")}</div></div>'
    html = html.replace("__CROSS_SIGNAL__", cs_html)

    # News cards
    news_html = ""
    tag_map = {"前沿科技": "nct1", "AI产品": "nct1", "AI安全": "nct3", "AI硬件": "nct5",
               "开源模型": "nct1", "资本市场": "nct2", "货币政策": "nct2", "市场": "nct2",
               "中东局势": "nct4", "美国政治": "nct4", "定价信号": "nct5", "编程语言": "nct1", "开源": "nct1"}
    impact_map = {"高影响": "imp-h", "中影响": "imp-m", "社区热度": "imp-hot"}
    cred_map = {"高可信": "cred-h", "中可信": "cred-m", "低可信": "cred-l"}

    for item in _safe_items(data.get("news", [])):
        tc = tag_map.get(item.get("category", ""), "nct1")
        ic = impact_map.get(item.get("impact", ""), "imp-m")
        cc = cred_map.get(item.get("credibility", ""), "cred-m")
        news_html += f'''<div class="nc">
<div class="nc-top"><span class="nc-tag {tc}">{item.get("category","")}</span><div class="badge-group"><span class="imp-badge {ic}">{item.get("impact","")}</span><span class="cred-badge {cc}">📡 {item.get("credibility","")}</span></div></div>
<div class="nc-title">{item.get("title","")}</div>
<div class="nc-meta">{item.get("source","")} · {item.get("signal","")}</div>
<div class="nc-l"><span class="nl">📋 事实：</span>{item.get("fact","")}</div>
<div class="nc-l"><span class="nl">🎯 影响：</span>{item.get("impact_text","")}</div>
<div class="nc-link">🔗 {item.get("url","")}</div>
</div>'''
    html = html.replace("__NEWS_CARDS__", news_html)

    # Geopolitical
    geo_html = ""
    for item in _safe_items(data.get("geopolitical", [])):
        geo_html += f'''<div class="geo">
<div class="geo-tag">⚠ 高影响</div>
<div class="geo-title">{item.get("title","")}</div>
<div class="geo-src">{item.get("source","")} · {item.get("signal","")}</div>
<div class="geo-4">
<div class="geo-4-item"><div class="g4l">发生了什么</div><div class="g4t">{item.get("what","")}</div></div>
<div class="geo-4-item"><div class="g4l">为什么重要</div><div class="g4t">{item.get("why","")}</div></div>
<div class="geo-4-item"><div class="g4l">市场影响</div><div class="g4t">{item.get("market","")}</div></div>
<div class="geo-4-item"><div class="g4l">关注下一步</div><div class="g4t">{item.get("watch","")}</div></div>
</div>
</div>'''
    html = html.replace("__GEOPOLITICAL__", geo_html)

    # Market news (filtered)
    market_news = [n for n in _safe_items(data.get("news", [])) if isinstance(n, dict) and n.get("category") in ("资本市场", "货币政策", "市场")]
    mn_html = ""
    for item in market_news:
        tc = tag_map.get(item.get("category", ""), "nct2")
        ic = impact_map.get(item.get("impact", ""), "imp-m")
        cc = cred_map.get(item.get("credibility", ""), "cred-m")
        mn_html += f'''<div class="nc">
<div class="nc-top"><span class="nc-tag {tc}">{item.get("category","")}</span><div class="badge-group"><span class="imp-badge {ic}">{item.get("impact","")}</span><span class="cred-badge {cc}">📡 {item.get("credibility","")}</span></div></div>
<div class="nc-title">{item.get("title","")}</div>
<div class="nc-meta">{item.get("source","")} · {item.get("signal","")}</div>
<div class="nc-l"><span class="nl">📋 事实：</span>{item.get("fact","")}</div>
<div class="nc-l"><span class="nl">🎯 影响：</span>{item.get("impact_text","")}</div>
<div class="nc-link">🔗 {item.get("url","")}</div>
</div>'''
    if not mn_html:
        mn_html = "<div style='color:#888;font-size:11px;padding:8px;'>（今日无突出市场新闻）</div>"
    html = html.replace("__MARKET_NEWS__", mn_html)

    # Probabilities
    prob_html = '<div class="prob-hdr">概率评估</div>'
    for item in _safe_items(data.get("probabilities", [])):
        pct = item.get("pct", 50)
        if pct >= 55:
            cls = "prb-h"
        elif pct >= 30:
            cls = "prb-m"
        else:
            cls = "prb-l"
        prob_html += f'<div class="prob-row"><span class="pr-name"><strong>{item.get("event","")}</strong></span><div class="pr-bar-wrap"><div class="pr-bar {cls}" style="width:{pct}px"></div><span class="pr-pct">{pct}%</span></div></div>'

    # Scenarios
    scen_html = '<div class="scen-hdr">未来 30 天情景规划</div>'
    for item in _safe_items(data.get("scenarios", [])):
        t = item.get("type", "基准")
        si = {"乐观": "si-bull", "基准": "si-base", "悲观": "si-bear"}.get(t, "si-base")
        emoji = {"乐观": "🟢", "基准": "🔵", "悲观": "🔴"}.get(t, "🔵")
        scen_html += f'<div class="scen-item"><span class="si-tag {si}">{emoji} {t}</span><span class="si-text">{item.get("text","")}</span></div>'

    html = html.replace("__PROB_SCENARIO__", f'<div class="ps-grid"><div class="prob-box">{prob_html}</div><div class="scen-box">{scen_html}</div></div>')

    # Community
    community = [n for n in _safe_items(data.get("news", [])) if isinstance(n, dict) and n.get("credibility") == "低可信"]
    com_html = ""
    for item in community:
        tc = tag_map.get(item.get("category", ""), "nct1")
        com_html += f'''<div class="nc">
<div class="nc-top"><span class="nc-tag {tc}">{item.get("category","")}</span><div class="badge-group"><span class="imp-badge imp-hot">💬 社区热议</span><span class="cred-badge cred-l">📡 低可信</span></div></div>
<div class="nc-title">{item.get("title","")}</div>
<div class="nc-meta">{item.get("source","")}</div>
<div class="nc-l"><span class="nl">💡</span> {item.get("impact_text","")}</div>
<div class="nc-link">🔗 {item.get("url","")}</div>
</div>'''
    if not com_html:
        com_html = "<div style='color:#888;font-size:11px;padding:8px;'>（今日无突出社区讨论）</div>"
    html = html.replace("__COMMUNITY__", com_html)

    # ArXiv papers (evening only)
    arxiv_items = data.get("arxiv", [])
    if arxiv_items and time_label == "evening":
        arx_html = '<div class="sh"><span class="sh-label">📄 ArXiv 论文精选</span><span class="sh-line"></span></div>'
        for paper in _safe_items(arxiv_items):
            arx_html += f'''<div class="nc" style="border-left:3px solid #7c3aed">
<div class="nc-title">{paper.get("title","")}</div>
<div class="nc-meta" style="color:#7c3aed">👤 {paper.get("authors","")}</div>
<div class="nc-l" style="font-size:9.5px">{paper.get("summary","")}</div>
</div>'''
        html = html.replace('<!-- WATCH + MARKET -->', arx_html + '<!-- WATCH + MARKET -->')

    # Watch list
    wl_html = ""
    colors = ["wd1", "wd2", "wd3", "wd4"]
    for i, item in enumerate(_safe_items(data.get("watch_list", []))):
        c = colors[i % 4]
        wl_html += f'<div class="wi"><span class="wd {c}"></span>{item.get("text","")}</div>'
    html = html.replace("__WATCH_LIST__", wl_html)

    # Hashtags
    ht_html = "\n".join([f'<span class="ht">{h}</span>' for h in data.get("hashtags", [])])
    html = html.replace("__HASHTAGS__", ht_html)

    # Market dash
    md_html = '<div class="mkt-hdr">📊 市场仪表盘</div><div class="mkt-g">'
    change_map = {"up": "m-up", "down": "m-down", "flat": "", "warn": "m-warn"}
    for item in _safe_items(data.get("market_data", [])):
        cc = change_map.get(item.get("change", ""), "")
        md_html += f'<div class="mkt-item"><span class="mn">{item.get("name","")}</span><span class="mv {cc}">{item.get("value","")}</span></div>'
    md_html += '</div>'
    html = html.replace("__MARKET_DASH__", md_html)

    # Editor take
    et = data.get("editor_take", "")
    if isinstance(et, dict):
        et = " ".join(str(v) for v in et.values() if isinstance(v, str))
    elif not isinstance(et, str):
        et = str(et)
    html = html.replace("__EDITOR_TAKE__", et)

    # Date / Vol / Source
    today = datetime.now()
    weekday_map = {"Monday": "星期一", "Tuesday": "星期二", "Wednesday": "星期三",
                   "Thursday": "星期四", "Friday": "星期五", "Saturday": "星期六", "Sunday": "星期日"}
    date_str = today.strftime("%Y年%m月%d日 %A")
    for en, cn in weekday_map.items():
        date_str = date_str.replace(en, cn)
    html = html.replace("__DATE__", date_str)
    html = html.replace("__VOL__", f"VOL.{today.strftime('%m%d')}")
    brief_type = "早报" if time_label == "morning" else "晚报"
    html = html.replace("FRONTIER BRIEF", f"FRONTIER BRIEF · {brief_type}")
    html = html.replace("__DATA_SOURCE__", f"数据采集 · {today.strftime('%Y-%m-%d %H:%M UTC')}")

    return html


def html_to_pdf(html_content: str, pdf_path: str):
    """Render HTML to PDF via Playwright."""
    with tempfile.NamedTemporaryFile(suffix=".html", mode="w", encoding="utf-8", delete=False) as f:
        f.write(html_content)
        html_path = f.name

    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1200, "height": 1600})
            page.goto(f"file://{html_path}", wait_until="networkidle")
            page.pdf(path=pdf_path, format="A4", print_background=True, margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"})
            browser.close()
        print(f"PDF generated: {pdf_path}")
    finally:
        os.unlink(html_path)


def send_email(pdf_path: str, time_label: str):
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not app_password:
        cred_file = os.environ.get("GMAIL_APP_PASSWORD_FILE", "")
        if cred_file and os.path.exists(cred_file):
            app_password = Path(cred_file).read_text().strip()
    if not app_password:
        print("ERROR: GMAIL_APP_PASSWORD not set (env var or GMAIL_APP_PASSWORD_FILE)", file=sys.stderr)
        sys.exit(1)
    if not FROM_EMAIL or not TO_EMAILS:
        print("ERROR: FROM_EMAIL / TO_EMAILS not configured (see .env.example)", file=sys.stderr)
        sys.exit(1)

    brief_type = "早报" if time_label == "morning" else "晚报"
    today = datetime.now()
    subject = f"FRONTIER BRIEF · {brief_type} | {today.strftime('%Y/%m/%d')}"

    msg = MIMEMultipart("mixed")
    msg["From"] = FROM_EMAIL
    msg["To"] = ", ".join(TO_EMAILS)
    msg["Subject"] = subject

    text_body = f"请查收今日 FRONTIER BRIEF {brief_type} PDF。\n\nFRONTIER BRIEF · Tech · Capital · Geopolitics\n在事件影响市场之前理解它"
    msg.attach(MIMEText(text_body, "plain", "utf-8"))

    with open(pdf_path, "rb") as f:
        pdf_attachment = MIMEBase("application", "pdf")
        pdf_attachment.set_payload(f.read())
        encoders.encode_base64(pdf_attachment)
        pdf_attachment.add_header(
            "Content-Disposition",
            f'attachment; filename="FRONTIER_BRIEF_{time_label.capitalize()}_{today.strftime("%Y%m%d")}.pdf"',
        )
        msg.attach(pdf_attachment)

    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    try:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(FROM_EMAIL, app_password)
        server.sendmail(FROM_EMAIL, TO_EMAILS, msg.as_string())
    finally:
        server.quit()
    print(f"Email sent with PDF: {subject} -> {TO_EMAILS}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    data_path = Path(sys.argv[1])
    time_label = sys.argv[2] if len(sys.argv) >= 3 and sys.argv[2] in ("morning", "evening") else "morning"
    no_email = "--no-email" in sys.argv

    if not data_path.exists():
        print(f"ERROR: data file not found: {data_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(data_path.read_text())

    print("Rendering HTML...")
    html = render_html(data, time_label)

    print("Generating PDF...")
    pdf_path = f"/tmp/frontier_brief_{time_label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    html_to_pdf(html, pdf_path)

    if no_email:
        print(f"Skipping email (--no-email). PDF at: {pdf_path}")
        return

    print("Sending email...")
    send_email(pdf_path, time_label)


if __name__ == "__main__":
    main()
