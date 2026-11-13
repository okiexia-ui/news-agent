#!/usr/bin/env python3
"""Collect attributed news with bounded requests and explicit source health."""
import argparse
import email.utils
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__:
    from .news_state import NewsState, canonical_url
else:
    from news_state import NewsState, canonical_url

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()

ATOM = "{http://www.w3.org/2005/Atom}"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
STOP_WORDS = {"the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "for", "on", "and", "or", "with"}
# A trade deal or acquisition is news. Match shopping context, not the word "deal".
JUNK_RE = re.compile(r"promo code|coupon|% off|black friday|prime day|gift guide|"
                     r"\b(?:shopping|laptop|headphone|phone|amazon|best tech) deals?\b", re.I)
MARKET_KEYWORDS = ["stock", "market", "nvidia", "semiconductor", "chip", "fed", "federal reserve",
                   "interest rate", "inflation", "ipo", "merger", "acquisition", "valuation",
                   "earnings", "trade war", "tariff", "sanction", "export control"]


def load_key():
    key = os.environ.get("NEWSAPI_KEY", "")
    if key:
        return key
    env = Path(__file__).resolve().parents[1] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key_name, sep, value = line.strip().partition("=")
            if sep and key_name.strip() == "NEWSAPI_KEY":
                return value.strip().strip("\"'")
    return ""


def parse_date(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def is_fresh(article, max_hours, now=None):
    now = now or datetime.now(timezone.utc)
    dt = parse_date(article.get("published"))
    # Missing dates remain explicit in the digest, never replaced with today's date.
    return dt is None or -timedelta(minutes=5) <= now - dt <= timedelta(hours=max_hours)


def has_keyword(text, keyword):
    return bool(re.search(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", text, re.I))


def guess_section(article):
    text = (article.get("title", "") + " " + article.get("desc", "")).lower()
    groups = {
        "geopolitics": ["china", "us", "tariff", "sanction", "export control", "military",
                        "ukraine", "russia", "congress", "trade war"],
        "economics": MARKET_KEYWORDS,
        "technology": ["ai", "artificial intelligence", "machine learning", "openai",
                       "anthropic", "llm", "gpt", "claude", "gemini", "agent"],
    }
    scores = {section: sum(has_keyword(text, word) for word in words) for section, words in groups.items()}
    return max(scores, key=scores.get) if any(scores.values()) else "general"


class ResponseTooLarge(ValueError):
    pass


def error_label(exc):
    # Avoid printing request URLs: NewsAPI URLs contain a credential.
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, (TimeoutError, urllib.error.URLError)):
        return "network timeout or connection failure"
    if isinstance(exc, ResponseTooLarge):
        return "response exceeds 8 MiB limit"
    if isinstance(exc, (ET.ParseError, ValueError, UnicodeError)):
        return "invalid response format"
    return type(exc).__name__


def request_bytes(url, deadline):
    """At most two attempts, six seconds each, within the source's total budget."""
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("source deadline exceeded")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "NewsAgent/1.1"})
            with urllib.request.urlopen(req, timeout=min(6, remaining), context=SSL_CONTEXT) as response:
                content = response.read(MAX_RESPONSE_BYTES + 1)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise ResponseTooLarge("response exceeds 8 MiB limit")
                return content
        except (urllib.error.URLError, TimeoutError) as exc:
            retryable = not isinstance(exc, urllib.error.HTTPError) or exc.code == 429 or exc.code >= 500
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            if attempt or not retryable or deadline - time.monotonic() < 0.3:
                raise
            time.sleep(0.2)


class Reader:
    def __init__(self, budget=40):
        self.deadline = time.monotonic() + budget
        self.errors = []

    def read(self, url, parser):
        try:
            return parser(request_bytes(url, self.deadline))
        except Exception as exc:
            self.errors.append(error_label(exc))
            raise

    def json(self, url):
        return self.read(url, json.loads)

    def xml(self, url):
        return self.read(url, ET.fromstring)


@dataclass(frozen=True)
class Source:
    name: str
    publisher: str
    tier: int
    section: str
    url: str
    kind: str = "rss"


# Each feed is its own task: a full first feed cannot truncate later feeds.
SOURCES = [
    Source("TechCrunch", "TechCrunch", 2, "technology", "https://techcrunch.com/feed/"),
    Source("The Verge", "The Verge", 2, "technology", "https://www.theverge.com/rss/index.xml"),
    Source("Ars Technica", "Ars Technica", 2, "technology", "https://feeds.arstechnica.com/arstechnica/index"),
    Source("Wired", "Wired", 2, "technology", "https://www.wired.com/feed/rss"),
    Source("MIT Technology Review", "MIT Technology Review", 2, "technology", "https://www.technologyreview.com/feed/"),
    Source("The Guardian", "The Guardian", 1, "geopolitics", "https://www.theguardian.com/world/rss"),
    Source("Al Jazeera", "Al Jazeera", 2, "geopolitics", "https://www.aljazeera.com/xml/rss/all.xml"),
    Source("New York Times", "New York Times", 1, "geopolitics", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    Source("NPR", "NPR", 2, "general", "https://feeds.npr.org/1001/rss.xml"),
    Source("BBC News", "BBC", 1, "general", "https://feeds.bbci.co.uk/news/rss.xml"),
    Source("BBC Technology", "BBC", 1, "technology", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    Source("Bloomberg Markets", "Bloomberg", 1, "economics", "https://feeds.bloomberg.com/markets/news.rss"),
    Source("Bloomberg Technology", "Bloomberg", 1, "technology", "https://feeds.bloomberg.com/technology/news.rss"),
    Source("CNBC", "CNBC", 2, "economics", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910"),
    Source("The Economist Weekly", "The Economist", 1, "economist_daily", "https://feeds.economist.com/v1/rss/weekly/58f882cb-21c4-4f19-aa4e-fc3b425d2e9d"),
    Source("The Intelligence", "The Economist", 1, "economist_daily", "https://feeds.economist.com/v1/rss/the-intelligence/b41cc30e-db0c-4a90-a773-02a6817ca53a"),
    Source("The World in Brief", "The Economist", 1, "economist_daily", "https://feeds.economist.com/v1/rss/the-world-in-brief/558c580d-7a74-40b4-8c9e-e55a79022c4b"),
    Source("HackerNews", "HackerNews", 3, "community", "https://hacker-news.firebaseio.com/v0/topstories.json", "hn"),
    Source("Reddit r/artificial", "Reddit", 3, "community", "https://www.reddit.com/r/artificial/hot.json?limit=12", "reddit"),
    Source("Reddit r/MachineLearning", "Reddit", 3, "community", "https://www.reddit.com/r/MachineLearning/hot.json?limit=12", "reddit"),
    Source("arXiv", "arXiv", 3, "research", "https://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=10", "arxiv"),
]


def article(source, title, desc, url, published, **extra):
    dt = parse_date(published)
    item = dict(source=source.name, publisher=source.publisher, tier=source.tier, section=source.section,
                title=html.unescape(" ".join((title or "").split())),
                desc=html.unescape(re.sub(r"<[^>]+>", "", desc or ""))[:500],
                url=canonical_url(url), published=dt.isoformat() if dt else None, **extra)
    if source.section == "general":
        item["section"] = guess_section(item)
    return item


def fetch_feed(source, reader):
    root = reader.xml(source.url)
    items = root.findall(".//item") or root.findall(f"{ATOM}entry")
    if not items and root.tag not in ("rss", f"{ATOM}feed", "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF"):
        raise ValueError("not an RSS/Atom feed")
    results = []
    for item in items[:30]:
        title = item.findtext("title") or item.findtext(f"{ATOM}title") or ""
        if JUNK_RE.search(title):
            continue
        url = item.findtext("link") or ""
        if not url:
            links = item.findall(f"{ATOM}link")
            url = next((el.get("href", "") for el in links if el.get("rel", "alternate") == "alternate"), "")
        desc = (item.findtext("description") or item.findtext(f"{ATOM}summary")
                or item.findtext("{http://www.itunes.com/dtds/podcast-1.0.dtd}summary") or "")
        published = (item.findtext("pubDate") or item.findtext(f"{ATOM}published")
                     or item.findtext(f"{ATOM}updated") or item.findtext("{http://purl.org/dc/elements/1.1/}date"))
        results.append(article(source, title, desc, url, published))
    return results


def fetch_hn(source, reader):
    ids = reader.json(source.url)
    if not isinstance(ids, list):
        raise ValueError("expected story IDs")
    results = []
    for sid in ids[:25]:
        if time.monotonic() >= reader.deadline:
            reader.errors.append("source deadline exceeded")
            break
        try:
            item = reader.json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
            if not isinstance(item, dict) or item.get("type") != "story" or not item.get("title"):
                continue
            published = datetime.fromtimestamp(item.get("time", 0), timezone.utc).isoformat()
            results.append(article(source, item["title"],
                f"Score:{item.get('score', 0)}|Comments:{item.get('descendants', 0)}",
                item.get("url") or f"https://news.ycombinator.com/item?id={sid}", published,
                community_score=item.get("score", 0)))
        except Exception as exc:
            # Network/parse errors are recorded by Reader; malformed items are recorded here.
            if not reader.errors or reader.errors[-1] != error_label(exc):
                reader.errors.append(error_label(exc))
    return results


def fetch_reddit(source, reader):
    payload = reader.json(source.url)
    children = payload.get("data", {}).get("children")
    if not isinstance(children, list):
        raise ValueError("expected Reddit listing")
    results = []
    for post in children:
        item = post.get("data", {})
        if item.get("stickied"):
            continue
        results.append(article(source, item.get("title"), f"Score:{item.get('score', 0)}|Comments:{item.get('num_comments', 0)}",
            f"https://www.reddit.com{item.get('permalink', '')}",
            datetime.fromtimestamp(item.get("created_utc", 0), timezone.utc).isoformat(),
            community_score=item.get("score", 0)))
    return results


def fetch_arxiv(source, reader):
    root = reader.xml(source.url)
    if root.tag != f"{ATOM}feed":
        raise ValueError("expected arXiv Atom feed")
    return [article(source, item.findtext(f"{ATOM}title"), item.findtext(f"{ATOM}summary"),
                    item.findtext(f"{ATOM}id"), item.findtext(f"{ATOM}published"),
                    authors=", ".join(a.findtext(f"{ATOM}name", "") for a in item.findall(f"{ATOM}author")[:3]))
            for item in root.findall(f"{ATOM}entry")]


def fetch_newsapi(source, reader):
    # Supplemental only; preserve the underlying publisher for corroboration.
    results = []
    requests = [("top-headlines", dict(category=category, pageSize=20))
                for category in ("technology", "business", "general")]
    queries = ["AI", "semiconductor", "OpenAI", "NVIDIA", "AI regulation", "China tech",
               "machine learning", "sanctions", "defense", "election", "foreign policy",
               "Iran", "Ukraine", "China", "Middle East", "tariff", "trade war", "IPO", "Federal Reserve"]
    requests += [("everything", dict(q=query, pageSize=3, sortBy="publishedAt")) for query in queries]
    for endpoint, params in requests:
        if time.monotonic() >= reader.deadline:
            reader.errors.append("source deadline exceeded")
            break
        try:
            params = urllib.parse.urlencode(dict(params, language="en", apiKey=source.url))
            payload = reader.json(f"https://newsapi.org/v2/{endpoint}?" + params)
            if payload.get("status") != "ok":
                raise ValueError("NewsAPI rejected request")
            for item in payload.get("articles", []):
                name = (item.get("source") or {}).get("name") or "Unknown"
                publisher = next((s for s in SOURCES if s.name == name or s.publisher == name), None)
                if publisher is None and name in ("Reuters", "AP News", "Financial Times", "Nature"):
                    publisher = Source(name, name, 2 if name == "Nature" else 1, "general", "")
                if publisher is None:
                    continue
                results.append(article(publisher, item.get("title"), item.get("description"),
                                       item.get("url"), item.get("publishedAt")))
        except Exception as exc:
            if not reader.errors or reader.errors[-1] != error_label(exc):
                reader.errors.append(error_label(exc))
    return results


FETCHERS = {"rss": fetch_feed, "hn": fetch_hn, "reddit": fetch_reddit, "arxiv": fetch_arxiv, "newsapi": fetch_newsapi}


def run_source(source):
    started = time.monotonic()
    reader = Reader()
    try:
        items = FETCHERS[source.kind](source, reader)
        items = [a for a in items if a["url"] and a["title"]]
    except Exception as exc:
        if not reader.errors or reader.errors[-1] != error_label(exc):
            reader.errors.append(error_label(exc))
        items = []
    status = ("partial" if items else "error") if reader.errors else ("ok" if items else "empty")
    return {
        "name": source.name, "status": status, "article_count": len(items),
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "errors": reader.errors, "articles": items,
    }


def title_words(article):
    return set(re.findall(r"\b\w+\b", article["title"].lower())) - STOP_WORDS


def compute_score(item, articles):
    words = title_words(item)
    publishers = set()
    for other in articles:
        if other["publisher"] == item["publisher"] or other["url"] == item["url"]:
            continue
        other_words = title_words(other)
        overlap = words & other_words
        if len(overlap) >= 3 and len(overlap) / max(1, len(words | other_words)) >= 0.5:
            publishers.add(other["publisher"])
    credibility = {1: 40, 2: 25, 3: 10}.get(item.get("tier"), 0)
    impact = min(20, 10 * sum(has_keyword(item["title"] + " " + item["desc"], kw) for kw in MARKET_KEYWORDS))
    # Community popularity is retained as a separate signal, not factual credibility.
    return min(100, credibility + min(30, 15 * len(publishers)) + impact)


def prepare_articles(results, now):
    unique = {}
    for result in results:
        for item in result["articles"]:
            hours = 72 if item["section"] in ("research", "economist_daily") else 48
            if not is_fresh(item, hours, now):
                continue
            # Prefer the original publisher over a community repost of the same URL.
            previous = unique.get(item["url"])
            if previous is None or item["tier"] < previous["tier"]:
                unique[item["url"]] = item
    articles = list(unique.values())
    for item in articles:
        item["signal_score"] = compute_score(item, articles)
    return sorted(articles, key=lambda a: (a["signal_score"], a["published"] or "", a["url"]), reverse=True)


def collect(sources=None, workers=6, directory=None):
    sources = SOURCES if sources is None else sources
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as executor:
        results = list(executor.map(run_source, sources))
    now = datetime.now(timezone.utc)
    articles = prepare_articles(results, now)
    successful = sum(r["status"] in ("ok", "empty", "partial") for r in results)
    health = [{k: v for k, v in r.items() if k != "articles"} for r in results]
    report = {
        "schema_version": 1, "generated_at": now.isoformat(),
        "status": "error" if not successful else "degraded" if any(r["status"] in ("error", "partial") for r in results) else "ok",
        "sources": health, "fetched_count": len(articles), "articles": [],
    }
    if not successful:
        return report
    with NewsState(directory) as state:
        state.prune()
        rendered = state.rendered_urls()
        candidates = [a for a in articles if a["url"] not in rendered]
        selected, counts = [], {}
        for item in candidates:
            section = item["section"]
            if counts.get(section, 0) < 6:
                selected.append(item)
                counts[section] = counts.get(section, 0) + 1
        report["run_id"] = state.record_fetch(articles, selected, report["generated_at"])
    report.update(articles=selected, selected_count=len(selected), unreported_count=len(candidates))
    return report


def format_digest(report):
    lines = [
        "=== Daily Briefing Data ===", f"Generated: {report['generated_at']}",
        f"Status: {report['status']}", f"Run ID: {report.get('run_id', 'none')}",
        f"Fetched: {report['fetched_count']} | Selected: {len(report['articles'])}",
        "Copy run_id into the brief JSON; article_urls must list ONLY cached articles actually used.",
        "", "== SOURCE HEALTH ==",
    ]
    for source in report["sources"]:
        lines.append(f"{source['name']}: {source['status']} | {source['article_count']} articles | {source['elapsed_ms']} ms"
                     + (" | " + "; ".join(source["errors"]) if source["errors"] else ""))
    if not report["articles"]:
        lines += ["", "No new eligible articles. Do not invent stories to fill sections."]
    for section in dict.fromkeys(a["section"] for a in report["articles"]):
        lines += ["", f"==SECTION:{section}=="]
        for item in (a for a in report["articles"] if a["section"] == section):
            lines += [f"[{item['signal_score']}] {item['title']}",
                      f"  Source:{item['source']}|{item['published'] or 'publication time unknown'}",
                      f"  URL:{item['url']}", f"  >{item['desc']}", ""]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable fetch report")
    args = parser.parse_args()
    sources = list(SOURCES)
    key = load_key()
    if key:
        sources.append(Source("NewsAPI", "NewsAPI", 0, "general", key, "newsapi"))
    report = collect(sources)
    print(json.dumps(report, ensure_ascii=False) if args.json else format_digest(report))
    return 2 if report["status"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())

