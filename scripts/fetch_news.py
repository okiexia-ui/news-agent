#!/usr/bin/env python3
"""News aggregator: NewsAPI + HN + Reddit + arXiv + 3x Economist RSS + BBC + Bloomberg + CNBC"""
import json, os, sys, time, urllib.request, urllib.error, urllib.parse, html, re, pathlib, email.utils
from datetime import datetime, timezone, timedelta

# Read API key from env or a local .env file (project-relative, not a hardcoded fallback)
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY") or ""
if not NEWSAPI_KEY:
    env_path = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("NEWSAPI_KEY="):
                NEWSAPI_KEY = line.strip().split("=", 1)[1].strip('"').strip("'")
                break

if not NEWSAPI_KEY:
    print("ERROR: NEWSAPI_KEY not set. Set it in the environment or in .env (see .env.example).", file=sys.stderr)
    sys.exit(1)
TIER_1 = {"Reuters", "AP News", "Bloomberg", "Financial Times", "BBC News", "The Economist"}
TIER_2 = {"TechCrunch", "The Verge", "Wired", "Ars Technica", "CNBC", "NPR",
          "MIT Technology Review", "Nature"}
TIER_3 = {"HackerNews", "Reddit"}
ALL_TRUSTED = TIER_1 | TIER_2

# ── Freshness helper ──
NOW_UTC = datetime.now(timezone.utc)

def parse_date_rfc2822(s):
    """Parse RSS pubDate ('Mon, 01 Jun 2026 12:00:00 GMT') or ISO 8601 ('2026-06-20T12:00:00Z')
    -> datetime(utc) or None. Always returns offset-aware datetimes."""
    if not s:
        return None
    # Try RFC 2822 (RSS feeds)
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    # Try ISO 8601 (NewsAPI)
    try:
        dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    # Try just the date
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None

def is_fresh(article, max_hours):
    """Check if article's 'published' field is within max_hours of now."""
    pub = article.get("published", "")
    if not pub:
        return True  # keep if no date
    try:
        dt = parse_date_rfc2822(pub)
        if dt is None:
            return True  # keep on parse failure
        return (NOW_UTC - dt) < timedelta(hours=max_hours)
    except Exception:
        return True  # keep on exception

# ── URL dedup ──
SEEN_FILE = pathlib.Path("/tmp/frontier_brief_seen_urls.txt")
def load_seen_urls():
    if SEEN_FILE.exists():
        return set(u for u in SEEN_FILE.read_text().strip().split("\n") if u.strip())
    return set()

def save_seen_urls(urls):
    SEEN_FILE.write_text("\n".join(sorted(urls)))

MARKET_KEYWORDS = ["stock","market","NVIDIA","semiconductor","chip","Fed","Federal Reserve",
    "interest rate","inflation","IPO","merger","acquisition","valuation",
    "earnings","trade war","tariff","sanction","export control"]

def fetch_json(url, timeout=6):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FrontierBrief/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except: return {"_error": "timeout"}

def napi_url(endpoint, params):
    return f"https://newsapi.org/v2/{endpoint}?{params}&apiKey={NEWSAPI_KEY}"

def source_tier(n):
    if n in TIER_1: return 1
    if n in TIER_2: return 2
    if n in TIER_3: return 3
    return 0

def cred_score(t): return {1:40, 2:25, 3:10, 0:0}[t]
def mkt_impact(t):
    return min(sum(10 for kw in MARKET_KEYWORDS if kw.lower() in (t or "").lower()), 20)

def guess_section(a):
    t = ((a.get("title")or"")+" "+(a.get("desc")or"")).lower()
    s = a.get("source","")
    geo=["china","us","tariff","sanction","export control","regulation","military","ukraine","russia","congress","trade war"]
    eco=["stock","market","nvidia","semiconductor","chip","fed","inflation","economy","valuation","billion","earnings"]
    ai=["ai","artificial intelligence","machine learning","openai","anthropic","llm","gpt","claude","gemini","agent"]
    if s in {"Reuters","AP News","BBC News"}:
        return "geopolitics" if any(k in t for k in geo) else "general"
    if s in {"Bloomberg","Financial Times","CNBC"}: return "economics"
    if s in {"TechCrunch","The Verge","Wired","Ars Technica","MIT Technology Review"}: return "technology"
    if s == "The Economist": return "economics"
    gs = sum(2 for k in geo if k in t)
    es = sum(2 for k in eco if k in t)
    as_ = sum(2 for k in ai if k in t)
    if as_ >= gs and as_ >= es and as_ >= 2: return "technology"
    if gs >= es and gs >= 2: return "geopolitics"
    if es >= 2: return "economics"
    return "general"

# ── Source: NewsAPI (supplemental, often stale on free tier) ──
def fetch_newsapi():
    results = []
    for cat in ["technology","business","general"]:
        url = napi_url("top-headlines", f"category={cat}&language=en&pageSize=20")
        data = fetch_json(url)
        for a in data.get("articles",[]):
            src = a.get("source",{}).get("name","")
            if src not in ALL_TRUSTED: continue
            results.append({"source":src,"tier":source_tier(src),
                "section":guess_section({"source":src,"title":a["title"],"desc":a.get("description","")}),
                "title":a["title"],"desc":a.get("description","")or"","url":a["url"],
                "published":(a.get("publishedAt")or"")[:10]})
    queries = [("AI","technology"),("semiconductor","geopolitics"),("OpenAI","technology"),
               ("NVIDIA","economics"),("AI regulation","geopolitics"),("China tech","geopolitics"),
               ("machine learning","technology"),("sanctions","geopolitics"),("defense","geopolitics"),
               ("election","geopolitics"),("foreign policy","geopolitics"),("Iran","geopolitics"),
               ("Ukraine","geopolitics"),("China","geopolitics"),("Middle East","geopolitics"),
               ("tariff","economics"),("trade war","geopolitics"),("IPO","economics"),
               ("Federal Reserve","economics")]
    seen = {a["url"] for a in results}
    for q,ds in queries:
        url = napi_url("everything", f"q={urllib.parse.quote(q)}&language=en&pageSize=3&sortBy=publishedAt")
        data = fetch_json(url, timeout=6)
        for a in data.get("articles",[]):
            src = a.get("source",{}).get("name","")
            u = a["url"]
            if src not in ALL_TRUSTED or u in seen: continue
            seen.add(u)
            results.append({"source":src,"tier":source_tier(src),
                "section":guess_section({"source":src,"title":a["title"],"desc":a.get("description","")}),
                "title":a["title"],"desc":a.get("description","")or"","url":u,
                "published":(a.get("publishedAt")or"")[:10]})
    # Date-filter and cap NewsAPI results
    results = [r for r in results if is_fresh(r, 48)]
    return results[:30]

# ── Source: HackerNews (consistently fresh) ──
def fetch_hackernews():
    results = []
    ids = fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json")
    if isinstance(ids, list):
        for sid in ids[:25]:
            item = fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
            if item and item.get("type")=="story" and item.get("title"):
                results.append({"source":"HackerNews","tier":3,"section":"community",
                    "title":item["title"],
                    "desc":f"Score:{item.get('score',0)}|Comments:{item.get('descendants',0)}",
                    "url":item.get("url")or f"https://news.ycombinator.com/item?id={sid}",
                    "published":datetime.fromtimestamp(item.get("time",0),tz=timezone.utc
                        ).strftime("%Y-%m-%d"),"_score":item.get("score",0)})
            time.sleep(0.05)
    results.sort(key=lambda x:x.get("_score",0),reverse=True)
    return results[:12]

# ── Source: Reddit ──
def fetch_reddit():
    results = []
    for sub in ["artificial","MachineLearning"]:
        try:
            req = urllib.request.Request(f"https://www.reddit.com/r/{sub}/hot.json?limit=12",
                headers={"User-Agent":"FrontierBrief/1.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                for post in json.loads(r.read().decode()).get("data",{}).get("children",[]):
                    d = post.get("data",{})
                    if d.get("stickied"): continue
                    results.append({"source":f"Reddit r/{sub}","tier":3,"section":"community",
                        "title":d.get("title",""),
                        "desc":f"Score:{d.get('score',0)}|Comments:{d.get('num_comments',0)}",
                        "url":f"https://reddit.com{d.get('permalink','')}",
                        "published":datetime.fromtimestamp(d.get("created_utc",0),tz=timezone.utc
                            ).strftime("%Y-%m-%d"),"_score":d.get("score",0)})
        except: pass
        time.sleep(0.3)
    results.sort(key=lambda x:x.get("_score",0),reverse=True)
    return results[:8]

# ── Source: arXiv ──
def fetch_arxiv():
    results = []
    url="http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=10"
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"FrontierBrief/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = r.read().decode()
        import xml.etree.ElementTree as ET
        ns={"a":"http://www.w3.org/2005/Atom","arxiv":"http://arxiv.org/schemas/atom"}
        for entry in ET.fromstring(data).findall("a:entry",ns):
            title=html.unescape(" ".join(entry.find("a:title",ns).text.strip().split()))
            summary=html.unescape(" ".join(entry.find("a:summary",ns).text.strip().split()[:40]))
            link=entry.find("a:id",ns).text
            pub=entry.find("a:published",ns).text[:10]
            authors=[au.find("a:name",ns).text for au in entry.findall("a:author",ns) if au.find("a:name",ns) is not None]
            results.append({"source":"arXiv","tier":3,"section":"research",
                "title":title,"desc":summary+"...","url":link,"published":pub,
                "_authors":", ".join(authors[:3])})
    except: pass
    return results

# ── Source: Economist RSS (podcast feeds, editorial signal) ──
def fetch_economist_rss():
    results=[]
    for name,url in [
        ("The Economist Weekly","https://feeds.economist.com/v1/rss/weekly/58f882cb-21c4-4f19-aa4e-fc3b425d2e9d"),
        ("The Intelligence","https://feeds.economist.com/v1/rss/the-intelligence/b41cc30e-db0c-4a90-a773-02a6817ca53a"),
        ("The World in Brief","https://feeds.economist.com/v1/rss/the-world-in-brief/558c580d-7a74-40b4-8c9e-e55a79022c4b"),
    ]:
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"FrontierBrief/1.0"})
            with urllib.request.urlopen(req,timeout=8) as r:
                data=r.read().decode()
            import xml.etree.ElementTree as ET
            ns={"itunes":"http://www.itunes.com/dtds/podcast-1.0.dtd"}
            tag = {"The Economist Weekly":"weekly","The Intelligence":"intel","The World in Brief":"brief"}[name]
            for item in ET.fromstring(data).findall(".//item")[:30]:
                t=item.findtext("title","")
                s=""
                if tag=="weekly":
                    s=re.sub(r'<[^>]+>','',(item.findtext("itunes:summary","",ns)or"")).strip()
                elif tag=="intel":
                    s=re.sub(r'<[^>]+>','',(item.findtext("itunes:summary","",ns)or"")).strip()[:200]
                else:
                    s=re.sub(r'<[^>]+>','',(item.findtext("description","")or"")).strip()[:200]
                pd=item.findtext("pubDate","")
                lk=item.findtext("link","")
                results.append({"source":name,"tag":tag,"title":t,"desc":s,"url":lk,"section":"economist_daily","published":pd[:31]if pd else ""})
        except: pass
    return results[:15]  # limit per source

# ── Source: BBC News RSS (direct, more timely than NewsAPI) ──
def fetch_bbc_rss():
    results = []
    feeds = [
        ("BBC News","https://feeds.bbci.co.uk/news/rss.xml"),
        ("BBC Technology","https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ]
    for name, url in feeds:
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"FrontierBrief/1.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = r.read().decode()
            import xml.etree.ElementTree as ET
            for item in list(ET.fromstring(data).findall(".//item"))[:20]:
                t = item.findtext("title","")
                d = re.sub(r'<[^>]+>','',(item.findtext("description","")or"")).strip()[:200]
                pd = item.findtext("pubDate","")
                lk = item.findtext("link","")
                results.append({"source":name,"tier":1,"section":"general",
                    "title":t,"desc":d,"url":lk,"published":pd[:31] if pd else ""})
        except:
            pass
    return results[:20]

# ── Source: Bloomberg RSS (direct, fresh markets + tech) ──
def fetch_bloomberg_rss():
    results = []
    feeds = [
        ("Bloomberg","https://feeds.bloomberg.com/markets/news.rss"),
        ("Bloomberg","https://feeds.bloomberg.com/technology/news.rss"),
    ]
    for name, url in feeds:
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"FrontierBrief/1.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = r.read().decode()
            import xml.etree.ElementTree as ET
            for item in list(ET.fromstring(data).findall(".//item"))[:20]:
                t = item.findtext("title","")
                d = re.sub(r'<[^>]+>','',(item.findtext("description","")or"")).strip()[:200]
                pd = item.findtext("pubDate","")
                lk = item.findtext("link","")
                # Bloomberg RSS sometimes has dc:date fallback
                if not pd:
                    pd = item.findtext("{http://purl.org/dc/elements/1.1/}date","")
                section = "economics"
                for kw in ["ai","artificial","machine learning","openai","anthropic","llm","gpt","gemini","agent","robot","autonomous","chip","semiconductor"]:
                    if kw in (t or "").lower():
                        section = "technology"
                        break
                results.append({"source":name,"tier":1,"section":section,
                    "title":t,"desc":d,"url":lk,"published":pd[:31] if pd else ""})
        except:
            pass
    return results[:20]

# ── Source: CNBC Tech RSS ──
def fetch_cnbc_rss():
    results = []
    try:
        url = "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910"
        req = urllib.request.Request(url, headers={"User-Agent":"FrontierBrief/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = r.read().decode()
        import xml.etree.ElementTree as ET
        for item in list(ET.fromstring(data).findall(".//item"))[:20]:
            t = item.findtext("title","")
            d = re.sub(r'<[^>]+>','',(item.findtext("description","")or"")).strip()[:200]
            pd = item.findtext("pubDate","")
            lk = item.findtext("link","")
            results.append({"source":"CNBC","tier":2,"section":"economics",
                "title":t,"desc":d,"url":lk,"published":pd[:31] if pd else ""})
    except:
        pass
    return results[:15]


def compute_score(article, all_articles):
    score = cred_score(article.get("tier",0))
    title_words = set((article.get("title")or"").lower().split())-{"the","a","an","is","are","was","were","to","of","in","for","on","and","or","with"}
    matches = sum(1 for other in all_articles if other is not article and other.get("url")!=article.get("url")
        and len(title_words & set((other.get("title")or"").lower().split()))>=3)
    score += 30 if matches >= 2 else 15 if matches >= 1 else 0
    score += mkt_impact((article.get("title")or"")+" "+(article.get("desc")or""))
    s = article.get("_score",0)
    if s > 500: score += 10
    elif s > 200: score += 5
    return min(score, 100)

def fmt_score(s):
    f = s // 10
    return f"{'█'*f}{'░'*(10-f)} {s}/100"

# ── MAIN ──
all_a = []
all_a.extend(fetch_newsapi())        # supplemental
all_a.extend(fetch_bbc_rss())        # fresh, tier-1
all_a.extend(fetch_bloomberg_rss())  # fresh, tier-1
all_a.extend(fetch_cnbc_rss())       # fresh, tier-2
all_a.extend(fetch_hackernews())     # fresh community
all_a.extend(fetch_reddit())         # community
all_a.extend(fetch_arxiv())          # research
all_a.extend(fetch_economist_rss())  # editorial signal

# ── Freshness filter ──
fresh_all = []
seen_urls = load_seen_urls()
for a in all_a:
    sec = a.get("section", "")
    url = a.get("url", "")
    # NewsAPI / arXiv: >48h stale
    if sec not in ("community", "economist_daily", "economist_all", "research") and not is_fresh(a, 48):
        continue
    # Economist RSS: >72h stale (podcast feeds have back-catalog)
    if sec in ("economist_daily", "economist_all") and not is_fresh(a, 72):
        continue
    # arXiv papers: >72h stale (papers persist for days)
    if sec == "research" and not is_fresh(a, 72):
        continue
    # Skip already-seen URLs
    if url and url in seen_urls:
        continue
    fresh_all.append(a)

all_a = fresh_all

# ── Sort economist items by date descending ──
econ_items = [a for a in all_a if a.get("section") == "economist_daily"]
for a in econ_items:
    dt = parse_date_rfc2822(a.get("published", ""))
    a["_sort_dt"] = dt or datetime.min.replace(tzinfo=timezone.utc)

if econ_items:
    econ_items.sort(key=lambda x: x["_sort_dt"], reverse=True)
    econ_urls = {a["url"] for a in econ_items}
    non_econ = [a for a in all_a if a.get("section") != "economist_daily" or a.get("url") not in econ_urls]
    all_a = non_econ + econ_items

# ── Save seen URLs for next run ──
new_urls = set()
for a in all_a:
    url = a.get("url", "")
    sec = a.get("section", "")
    if sec in ("economist_daily", "economist_all") and is_fresh(a, 72):
        new_urls.add(url)
    elif is_fresh(a, 48):
        new_urls.add(url)
save_seen_urls(new_urls | seen_urls)

# ── Compute signal scores and sort ──
for a in all_a:
    a["signal_score"] = compute_score(a, all_a)

all_a.sort(key=lambda x:x.get("signal_score",0), reverse=True)

secs = {}
for a in all_a:
    s = a.get("section","general")
    secs.setdefault(s,[]).append(a)

now = datetime.now(timezone.utc)
print(f"=== Daily Briefing Data ===")
print(f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}")
print(f"Total articles: {len(all_a)}")
print()

for sec_name, sec_label in [("technology","AI & Tech"),("geopolitics","Geopolitics"),
                              ("economics","Economics & Markets"),("community","Community"),
                              ("research","Research"),("general","Other"),("economist_daily","Economist Daily")]:
    items = secs.get(sec_name, [])[:6]
    if not items: continue
    print(f"==SECTION:{sec_name}==")
    for a in items:
        tag = a.get("tag","")
        prefix = {"weekly":"[WEEKLY]","intel":"[INTEL]","brief":"[BRIEF]"}.get(tag,"")
        title_str = f"{prefix} {a['title']}" if prefix else a['title']
        print(f"[{a['signal_score']}] {title_str}")
        print(f"  Source:{a['source']}|{a.get('published','')}|Signal:{fmt_score(a['signal_score'])}")
        print(f"  URL:{a['url']}")
        if a.get('desc'):
            d = a['desc'][:150]
            print(f"  >{d}")
        print()

# Also print Economist-only list at end for clarity
econ_items = [a for a in all_a if a.get("tag") in ("weekly","intel","brief")]
if econ_items:
    print("==SECTION:economist_all==")
    for a in econ_items[:8]:
        t = a.get("tag","")
        print(f"[{t.upper()}] {a['title']}|{a.get('published','')}")
        if a.get('desc'):
            print(f"  >{a['desc'][:150]}")
        print()
