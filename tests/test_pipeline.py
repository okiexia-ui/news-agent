import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import render_and_send as renderer
from scripts.news_state import NewsState
from tests.test_fetch_news import fixture_articles


class ProvenanceTests(unittest.TestCase):
    def market(self, **overrides):
        item = dict(name="Demo index", value="123.45", unit="points", change="up",
                    source_url="https://example.com/quote?a=1&b=2", as_of="2026-11-13T12:00:00+08:00")
        item.update(overrides)
        return item

    def test_verified_metadata_is_visible_and_link_is_escaped(self):
        html = renderer.render_html({"market_data": [self.market()]}, "morning")
        self.assertIn("123.45 points", html)
        self.assertIn("2026-11-13 04:00 UTC", html)
        self.assertIn('href="https://example.com/quote?a=1&amp;b=2"', html)

    def test_incomplete_or_unsafe_provenance_suppresses_the_value(self):
        cases = [{"source_url": ""}, {"source_url": "javascript:alert(1)"}, {"as_of": "not a date"},
                 {"as_of": "2026-11-13T12:00:00"}, {"as_of": None}, {"unit": ""}]
        for case in cases:
            with self.subTest(case=case), contextlib.redirect_stderr(io.StringIO()):
                html = renderer.render_html({"market_data": [self.market(**case)]}, "morning")
            self.assertIn("暂无数据", html)
            self.assertNotIn("123.45", html)
            self.assertNotIn('href="javascript:', html)

    def test_null_and_nonfinite_values_are_missing_but_zero_is_valid(self):
        for value in (None, True, float("nan"), float("inf"), ""):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                html = renderer.render_html({"market_data": [self.market(value=value)]}, "morning")
            self.assertIn("暂无数据", html)
        self.assertIn("0 points", renderer.render_html({"market_data": [self.market(value=0)]}, "morning"))

    def test_null_quote_and_hashtags_are_valid_empty_fields(self):
        html = renderer.render_html({"quote": None, "hashtags": None}, "morning")
        self.assertNotIn("__QUOTE__", html)
        for data in ([], {"quote": "wrong"}, {"hashtags": "wrong"}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                renderer.render_html(data, "morning")

    def test_forecasts_are_optional_and_explicitly_subjective(self):
        html = renderer.render_html({"probabilities": [{"event": "Demo event", "pct": 65,
                                                       "basis": "Demo evidence", "horizon": "30 days"}]}, "morning")
        self.assertIn("主观估计 · 30 days · Demo evidence", html)
        self.assertIn("今日无概率评估", renderer.render_html({}, "morning"))

    def test_collection_timestamp_is_not_replaced_with_render_time(self):
        html = renderer.render_html({"collected_at": "2026-11-12T23:30:00+08:00"}, "morning")
        self.assertIn("数据采集 · 2026-11-12 15:30 UTC", html)


class PipelineStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"NEWS_AGENT_STATE_DIR": str(self.directory)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.items = fixture_articles(3)
        with NewsState() as state:
            self.run_id = state.record_fetch(self.items, self.items, datetime.now(timezone.utc).isoformat())
        self.payload = self.directory / "brief.json"
        self.pdf = self.directory / "brief.pdf"
        self.data = dict(run_id=self.run_id, article_urls=[self.items[0]["url"]], news=[self.items[0]])
        self.payload.write_text(json.dumps(self.data))

    def invoke(self, pdf_action, email_action=None, no_email=True):
        argv = [str(self.payload), "morning", "--output", str(self.pdf)]
        if no_email:
            argv.append("--no-email")
        with patch.object(renderer, "html_to_pdf", side_effect=pdf_action), \
                patch.object(renderer, "send_email", side_effect=email_action) as send, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = renderer.main(argv)
        return code, send

    def write_pdf(self, html, path):
        Path(path).write_bytes(b"%PDF-fixture")

    def test_failed_pdf_does_not_consume_news_or_send_email(self):
        code, send = self.invoke(RuntimeError("render failed"))
        self.assertEqual(code, 1)
        send.assert_not_called()
        with NewsState() as state:
            self.assertEqual(state.rendered_urls(), set())

    def test_missing_pdf_is_not_a_successful_render(self):
        code, send = self.invoke(lambda *args: None)
        self.assertEqual(code, 1)
        send.assert_not_called()
        with NewsState() as state:
            self.assertEqual(state.rendered_urls(), set())

    def test_no_email_records_only_used_articles(self):
        code, send = self.invoke(self.write_pdf)
        self.assertEqual(code, 0)
        send.assert_not_called()
        with NewsState() as state:
            self.assertEqual(state.rendered_urls(), {self.items[0]["url"]})
            self.assertIsNone(state.db.execute("SELECT sent_at FROM runs WHERE id=?", (self.run_id,)).fetchone()[0])

    def test_email_failure_preserves_render_but_does_not_mark_sent(self):
        code, send = self.invoke(self.write_pdf, RuntimeError("SMTP failed"), no_email=False)
        self.assertEqual(code, 1)
        send.assert_called_once()
        with NewsState() as state:
            self.assertEqual(state.rendered_urls(), {self.items[0]["url"]})
            self.assertIsNone(state.db.execute("SELECT sent_at FROM runs WHERE id=?", (self.run_id,)).fetchone()[0])

    def test_successful_delivery_marks_only_rendered_subset_sent(self):
        code, send = self.invoke(self.write_pdf, no_email=False)
        self.assertEqual(code, 0)
        send.assert_called_once()
        with NewsState() as state:
            rows = state.db.execute("SELECT url FROM articles WHERE sent_at IS NOT NULL").fetchall()
            self.assertEqual(rows, [(self.items[0]["url"],)])


if __name__ == "__main__":
    unittest.main()
