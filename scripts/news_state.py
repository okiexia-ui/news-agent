"""Durable pipeline state; fetching alone never consumes a news item."""
import json
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def load_env():
    path = Path(__file__).resolve().parents[1] / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if sep:
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def state_dir():
    load_env()
    return Path(os.environ.get("NEWS_AGENT_STATE_DIR", "~/.cache/news-agent")).expanduser()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def canonical_url(url):
    if not isinstance(url, str):
        return ""
    try:
        p = urlsplit(url.strip())
        if p.scheme.lower() not in ("http", "https") or not p.hostname or p.username or p.password:
            return ""
        host = p.hostname.lower()
        port = p.port
        if ":" in host:
            host = f"[{host}]"
        if port and (p.scheme.lower(), port) not in (("http", 80), ("https", 443)):
            host += f":{port}"
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")]
        return urlunsplit((p.scheme.lower(), host, p.path or "/", urlencode(sorted(query)), ""))
    except ValueError:
        return ""


def atomic_write(path, text):
    """Replace one complete file on the same filesystem; never expose a partial write."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class NewsState:
    def __init__(self, directory=None):
        directory = Path(directory) if directory is not None else state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(directory / "state.sqlite3", timeout=30)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                url TEXT PRIMARY KEY, fetched_at TEXT NOT NULL,
                rendered_at TEXT, sent_at TEXT
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, fetched_at TEXT NOT NULL,
                rendered_at TEXT, sent_at TEXT, pdf_path TEXT, used_urls TEXT
            );
            CREATE TABLE IF NOT EXISTS selected (
                run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
                url TEXT REFERENCES articles(url) ON DELETE CASCADE,
                PRIMARY KEY (run_id, url)
            );
        """)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def prune(self, days=30):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self.db:
            self.db.execute("DELETE FROM runs WHERE fetched_at < ?", (cutoff,))
            self.db.execute("DELETE FROM articles WHERE fetched_at < ?", (cutoff,))

    def rendered_urls(self):
        return {row[0] for row in self.db.execute("SELECT url FROM articles WHERE rendered_at IS NOT NULL")}

    def record_fetch(self, articles, selected, fetched_at):
        run_id = uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO runs(id, fetched_at) VALUES (?, ?)", (run_id, fetched_at))
            for item in articles:
                url = canonical_url(item.get("url"))
                if url:
                    self.db.execute("""INSERT INTO articles(url, fetched_at) VALUES (?, ?)
                        ON CONFLICT(url) DO UPDATE SET fetched_at=excluded.fetched_at""", (url, fetched_at))
            self.db.executemany("INSERT OR IGNORE INTO selected(run_id, url) VALUES (?, ?)",
                                [(run_id, canonical_url(a["url"])) for a in selected])
        return run_id

    def validate_selection(self, run_id, urls):
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a nonempty string copied from the news cache")
        if not isinstance(urls, list) or any(not canonical_url(u) for u in urls):
            raise ValueError("article_urls must be a list of HTTP(S) URLs used in this brief")
        run = self.db.execute("SELECT fetched_at FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError("run_id is unknown or expired; use the same NEWS_AGENT_STATE_DIR as prefetch")
        selected = {row[0] for row in self.db.execute("SELECT url FROM selected WHERE run_id=?", (run_id,))}
        used = {canonical_url(u) for u in urls}
        if not used <= selected:
            raise ValueError("article_urls contains URLs outside this run's selected cache; list only cached articles")
        return used, run[0]

    def mark_rendered(self, run_id, urls, pdf_path):
        used, _ = self.validate_selection(run_id, urls)
        if not Path(pdf_path).is_file() or not Path(pdf_path).stat().st_size:
            raise ValueError("Cannot mark articles rendered without a nonempty PDF")
        now = utc_now()
        with self.db:
            self.db.execute("UPDATE runs SET rendered_at=?, pdf_path=?, used_urls=?, sent_at=NULL WHERE id=?",
                            (now, str(pdf_path), json.dumps(sorted(used)), run_id))
            self.db.executemany("UPDATE articles SET rendered_at=? WHERE url=?", [(now, u) for u in used])

    def mark_sent(self, run_id):
        row = self.db.execute("SELECT used_urls FROM runs WHERE id=? AND rendered_at IS NOT NULL", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Cannot mark an unrendered run sent")
        now = utc_now()
        with self.db:
            self.db.execute("UPDATE runs SET sent_at=? WHERE id=?", (now, run_id))
            self.db.executemany("UPDATE articles SET sent_at=? WHERE url=?", [(now, u) for u in json.loads(row[0])])
