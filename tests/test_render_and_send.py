import re
import unittest
from datetime import datetime, timezone
from html import escape
from unittest.mock import patch

from scripts import render_and_send as renderer


class RenderTests(unittest.TestCase):
    def test_utc_source_timestamp_keeps_local_issue_date(self):
        local = datetime(2026, 1, 2, 1, 30)
        utc = datetime(2026, 1, 1, 17, 30, tzinfo=timezone.utc)
        with patch.object(renderer, "datetime") as clock:
            clock.now.side_effect = lambda tz=None: local if tz is None else utc.astimezone(tz)
            html = renderer.render_html({}, "morning")
        self.assertIn("2026年01月02日 星期五", html)
        self.assertIn("VOL.0102", html)
        self.assertIn("数据采集 · 2026-01-01 17:30 UTC", html)
        self.assertEqual(clock.now.call_args_list[1].args, (timezone.utc,))

    def test_empty_payload_has_no_placeholders(self):
        for label in ("morning", "evening"):
            with self.subTest(label=label):
                html = renderer.render_html({}, label)
                self.assertFalse(re.search(r"__[A-Z_]+__", html))
                self.assertIn("今日无突出市场新闻", html)
                self.assertIn("今日无突出社区讨论", html)

    def test_all_plain_text_fields_are_escaped(self):
        text = '中文 <AI> & "quotes" \'single\''
        sections = {
            "big_picture": ["tag", "title", "desc"],
            "cross_signal": ["title", "body"],
            "news": ["category", "impact", "credibility", "title", "source", "signal", "fact", "impact_text", "url"],
            "geopolitical": ["title", "source", "signal", "what", "why", "market", "watch"],
            "probabilities": ["event"],
            "scenarios": ["type", "text"],
            "watch_list": ["text"],
            "market_data": ["name", "value"],
            "arxiv": ["title", "authors", "summary"],
        }
        for section, fields in sections.items():
            for field in fields:
                with self.subTest(section=section, field=field):
                    html = renderer.render_html({section: [{field: text}]}, "evening")
                    self.assertIn(escape(text), html)
                    self.assertNotIn(text, html)
        for field in ("text", "author"):
            html = renderer.render_html({"quote": {field: text}}, "morning")
            self.assertIn(escape(text), html)
        for data in ({"hashtags": [text]}, {"editor_take": text}, {"quote": {"text": text}}):
            html = renderer.render_html(data, "evening")
            self.assertIn(escape(text), html)
            self.assertNotIn(escape(escape(text)), html)

    def test_filtered_cards_escape_text_and_keep_generated_markup(self):
        text = "<strong>Research & tools</strong>"
        news = {"title": text, "category": "市场", "credibility": "低可信"}
        html = renderer.render_html({"news": [news], "probabilities": [{"event": text, "pct": 65}]}, "morning")
        self.assertEqual(html.count(escape(text)), 4)
        self.assertNotIn(text, html)
        self.assertIn('<strong>&lt;strong&gt;Research &amp; tools&lt;/strong&gt;</strong>', html)
        self.assertIn('style="width:65px"', html)
        self.assertIn('class="nc-tag nct2"', html)

    def test_malformed_list_items_are_skipped(self):
        with patch("builtins.print"):
            html = renderer.render_html({"news": ["invalid", {"title": "valid"}], "cross_signal": None}, "morning")
        self.assertIn('class="nc-title">valid</div>', html)
        self.assertNotIn('class="nc-title">invalid</div>', html)


if __name__ == "__main__":
    unittest.main()
