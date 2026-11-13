import json
import tempfile
import time
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import fetch_news as fetch
from scripts.news_state import NewsState, canonical_url


def fixture_articles(count=9):
    now = datetime.now(timezone.utc).isoformat()
    return [fetch.article(fetch.SOURCES[0], f"Example story {i}", "A factual summary",
                          f"https://example.com/{i}", now) for i in range(count)]


def result(items, status="ok"):
    return dict(name="Fixture", status=status, article_count=len(items), elapsed_ms=1,
                errors=[] if status == "ok" else ["HTTP 503"], articles=items)


class FetchTests(unittest.TestCase):
    def test_iso_offset_and_future_dates(self):
        dt = fetch.parse_date("2026-11-13T12:00:00+08:00")
        self.assertEqual(dt.isoformat(), "2026-11-13T04:00:00+00:00")
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        self.assertFalse(fetch.is_fresh({"published": "2099-01-01T00:00:00Z"}, 48, now))
        self.assertFalse(fetch.is_fresh({"published": (now - timedelta(hours=49)).isoformat()}, 48, now))

    def test_market_deals_are_not_shopping(self):
        for title in ("US and China reach trade deal", "NVIDIA signs chip deal", "Merger deal approved"):
            self.assertIsNone(fetch.JUNK_RE.search(title))
        for title in ("Wired coupon codes", "Best tech deals this week", "Black Friday discounts"):
            self.assertIsNotNone(fetch.JUNK_RE.search(title))

    def test_keyword_matches_have_word_boundaries(self):
        self.assertEqual(fetch.guess_section({"title": "Business confidence rises", "desc": ""}), "general")
        self.assertEqual(fetch.guess_section({"title": "AI regulation", "desc": ""}), "technology")

    def test_corroboration_requires_distinct_publishers(self):
        a = fixture_articles(1)[0]
        a["title"] = "Government climate policy announcement today"
        others = [dict(a, url=f"https://example.com/other-{i}", source=f"Another desk {i}") for i in range(3)]
        baseline = fetch.compute_score(a, [a])
        self.assertEqual(fetch.compute_score(a, [a] + others), baseline)
        others[0]["publisher"] = "Independent Publisher"
        self.assertEqual(fetch.compute_score(a, [a] + others), baseline + 15)
        others[1]["publisher"] = "Independent Publisher"
        self.assertEqual(fetch.compute_score(a, [a] + others), baseline + 15)

    def test_every_feed_survives_a_full_first_feed(self):
        def response(url, deadline):
            items = "".join(f"<item><title>Story {i}</title><link>{url}/{i}</link></item>" for i in range(20))
            return ("<rss><channel>" + items + "</channel></rss>").encode()
        feeds = [s for s in fetch.SOURCES if s.publisher in ("BBC", "Bloomberg", "The Economist")]
        with patch.object(fetch, "request_bytes", side_effect=response):
            results = [fetch.run_source(s) for s in feeds]
        self.assertEqual(len(results), 7)
        self.assertTrue(all(r["article_count"] == 20 for r in results))

    def test_atom_uses_alternate_link_and_preserves_time(self):
        data = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Example</title><link rel="self" href="https://example.com/feed"/><link rel="alternate" href="https://example.com/article"/><published>2026-11-13T12:00:00+08:00</published></entry></feed>'
        with patch.object(fetch, "request_bytes", return_value=data):
            r = fetch.run_source(fetch.SOURCES[1])
        self.assertEqual(r["articles"][0]["url"], "https://example.com/article")
        self.assertEqual(r["articles"][0]["published"], "2026-11-13T04:00:00+00:00")

    def test_newsapi_keeps_topic_queries_publishers_and_full_timestamps(self):
        source = fetch.Source("NewsAPI", "NewsAPI", 0, "general", "fixture-key", "newsapi")
        payload = dict(status="ok", articles=[dict(source={"name": "Reuters"}, title="Trade agreement",
                       description="Evidence", url="https://example.com/reuters",
                       publishedAt="2026-11-13T12:00:00+08:00")])
        with patch.object(fetch, "request_bytes", return_value=json.dumps(payload).encode()) as request:
            r = fetch.run_source(source)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(request.call_count, 22)
        self.assertTrue(any("everything?" in call.args[0] for call in request.call_args_list))
        self.assertEqual(r["articles"][0]["publisher"], "Reuters")
        self.assertEqual(r["articles"][0]["published"], "2026-11-13T04:00:00+00:00")

    def test_duplicate_urls_with_tracking_are_one_article(self):
        source = fetch.SOURCES[0]
        now = datetime.now(timezone.utc)
        items = [fetch.article(source, "Same story", "Summary", "https://example.com/story" + query, now.isoformat())
                 for query in ("?utm_source=a", "?utm_source=b")]
        self.assertEqual(len(fetch.prepare_articles([result(items)], now)), 1)

    def test_source_failures_are_explicit_and_do_not_leak_credentials(self):
        source = fetch.Source("Secret source", "Fixture", 1, "general", "https://example.com/?apiKey=secret")
        error = urllib.error.HTTPError(source.url, 403, "denied", {}, None)
        self.addCleanup(error.close)
        with patch.object(fetch, "request_bytes", side_effect=error):
            r = fetch.run_source(source)
        self.assertEqual(r["status"], "error")
        self.assertEqual(r["errors"], ["HTTP 403"])
        self.assertNotIn("secret", json.dumps(r).lower().replace("secret source", ""))

    def test_retry_is_bounded_and_does_not_retry_forbidden_requests(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"ok"
        transient = urllib.error.HTTPError("https://example.com", 503, "unavailable", {}, None)
        with patch.object(fetch.urllib.request, "urlopen", side_effect=[transient, response]) as request, \
                patch.object(fetch.time, "sleep"):
            self.assertEqual(fetch.request_bytes("https://example.com", time.monotonic() + 40), b"ok")
            self.assertEqual(request.call_count, 2)
        forbidden = urllib.error.HTTPError("https://example.com", 403, "forbidden", {}, None)
        with patch.object(fetch.urllib.request, "urlopen", side_effect=forbidden) as request:
            with self.assertRaises(urllib.error.HTTPError):
                fetch.request_bytes("https://example.com", time.monotonic() + 40)
            self.assertEqual(request.call_count, 1)

    def test_large_podcast_feeds_are_supported_with_a_clear_size_limit(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b" " * 3_000_000
        with patch.object(fetch.urllib.request, "urlopen", return_value=response):
            self.assertEqual(len(fetch.request_bytes("https://example.com", time.monotonic() + 40)), 3_000_000)
            response.__enter__.return_value.read.return_value = b" " * (fetch.MAX_RESPONSE_BYTES + 1)
            with self.assertRaises(fetch.ResponseTooLarge):
                fetch.request_bytes("https://example.com", time.monotonic() + 40)

    def test_all_source_failures_do_not_create_a_run(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(fetch, "run_source", return_value=result([], "error")):
            report = fetch.collect(fetch.SOURCES[:2], directory=tmp)
            self.assertEqual(report["status"], "error")
            self.assertNotIn("run_id", report)
            self.assertFalse((Path(tmp) / "state.sqlite3").exists())

    def test_fetch_and_retry_do_not_consume_any_articles(self):
        items = fixture_articles()
        with tempfile.TemporaryDirectory() as tmp, patch.object(fetch, "run_source", return_value=result(items)):
            first = fetch.collect(fetch.SOURCES[:1], directory=tmp)
            retry = fetch.collect(fetch.SOURCES[:1], directory=tmp)
            self.assertEqual(first["selected_count"], 6)
            self.assertEqual([a["url"] for a in first["articles"]], [a["url"] for a in retry["articles"]])
            with NewsState(tmp) as state:
                self.assertEqual(state.rendered_urls(), set())
                pdf = Path(tmp) / "brief.pdf"
                pdf.write_bytes(b"%PDF-fixture")
                used = [a["url"] for a in first["articles"]]
                state.mark_rendered(first["run_id"], used, pdf)
                self.assertEqual(state.rendered_urls(), set(used))
            after = fetch.collect(fetch.SOURCES[:1], directory=tmp)
            self.assertEqual(after["selected_count"], 3)
            self.assertFalse(set(a["url"] for a in after["articles"]) & set(used))

    def test_only_used_subset_is_consumed_and_delivery_is_separate(self):
        with tempfile.TemporaryDirectory() as tmp, NewsState(tmp) as state:
            items = fixture_articles(3)
            run_id = state.record_fetch(items, items, datetime.now(timezone.utc).isoformat())
            pdf = Path(tmp) / "brief.pdf"
            pdf.write_bytes(b"%PDF-fixture")
            state.mark_rendered(run_id, [items[0]["url"]], pdf)
            self.assertEqual(state.rendered_urls(), {items[0]["url"]})
            self.assertIsNone(state.db.execute("SELECT sent_at FROM runs WHERE id=?", (run_id,)).fetchone()[0])
            state.mark_sent(run_id)
            self.assertEqual(state.db.execute("SELECT count(*) FROM articles WHERE sent_at IS NOT NULL").fetchone()[0], 1)

    def test_selection_rejects_unknown_run_and_unselected_urls(self):
        with tempfile.TemporaryDirectory() as tmp, NewsState(tmp) as state:
            items = fixture_articles(2)
            run_id = state.record_fetch(items, items[:1], datetime.now(timezone.utc).isoformat())
            for rid, urls in (("missing", []), (run_id, [items[1]["url"]]), (run_id, None)):
                with self.subTest(rid=rid, urls=urls), self.assertRaises(ValueError):
                    state.validate_selection(rid, urls)

    def test_state_expires_after_retention_window(self):
        with tempfile.TemporaryDirectory() as tmp, NewsState(tmp) as state:
            items = fixture_articles(1)
            old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
            state.record_fetch(items, items, old)
            state.prune()
            self.assertEqual(state.db.execute("SELECT count(*) FROM articles").fetchone()[0], 0)
            self.assertEqual(state.db.execute("SELECT count(*) FROM runs").fetchone()[0], 0)

    def test_url_dedup_drops_tracking_but_preserves_semantic_query(self):
        self.assertEqual(canonical_url("https://EXAMPLE.com/a?id=7&utm_source=feed#fragment"), "https://example.com/a?id=7")
        for url in ("javascript:alert(1)", "https://user:password@example.com/a", "https://example.com:bad/a"):
            self.assertEqual(canonical_url(url), "")


if __name__ == "__main__":
    unittest.main()
