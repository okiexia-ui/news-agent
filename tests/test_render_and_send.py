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
                for note in ("今日无突出信号", "今日无突出跨板块信号", "今日无突出要闻",
                             "今日无突出地缘事件", "今日无突出市场新闻", "今日无概率评估",
                             "今日无情景规划", "今日无突出社区讨论", "今日无重点观察"):
                    self.assertIn(note, html)

    def test_fallback_notes_disappear_when_sections_have_items(self):
        html = renderer.render_html({
            "geopolitical": [{"title": "g"}],
            "probabilities": [{"event": "e", "pct": 40}],
            "watch_list": [{"text": "w"}],
        }, "morning")
        self.assertNotIn("今日无突出地缘事件", html)
        self.assertNotIn("今日无概率评估", html)
        self.assertNotIn("今日无重点观察", html)
        self.assertIn("今日无情景规划", html)

    def test_probability_values_are_coerced_and_clamped(self):
        cases = [(65, 65), (65.4, 65), ("65", 65), (" 72% ", 72), (150, 100), (-5, 0)]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                html = renderer.render_html({"probabilities": [{"event": "e", "pct": raw}]}, "morning")
                self.assertIn(f'style="width:{expected}%"', html)
                self.assertIn(f'<span class="pr-pct">{expected}%</span>', html)

    def test_invalid_probability_rows_are_skipped(self):
        for raw in (None, "high", True, [], float("nan"), float("inf")):
            with self.subTest(raw=raw):
                with patch("builtins.print"):
                    html = renderer.render_html({"probabilities": [{"event": "bad", "pct": raw}]}, "morning")
                self.assertNotIn('class="prob-row"', html)
                self.assertIn("今日无概率评估", html)

    def test_template_keeps_cards_whole_across_pages(self):
        css = re.sub(r"/\*.*?\*/", "", renderer.TEMPLATE_PATH.read_text(), flags=re.S)
        rule = re.search(r"([^{}]+)\{[^}]*break-inside:avoid", css)
        self.assertIsNotNone(rule)
        selectors = {s.strip() for s in rule.group(1).split(",")}
        for cls in (".nc", ".geo", ".bp-card", ".cross-item", ".prob-box", ".scen-box", ".et"):
            self.assertIn(cls, selectors)

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
                    item = {field: text}
                    if section == "probabilities":
                        item["pct"] = 50  # rows without a usable pct are skipped
                    html = renderer.render_html({section: [item]}, "evening")
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
        self.assertIn('style="width:65%"', html)
        self.assertIn('class="nc-tag nct2"', html)

    def test_malformed_list_items_are_skipped(self):
        with patch("builtins.print"):
            html = renderer.render_html({"news": ["invalid", {"title": "valid"}], "cross_signal": None}, "morning")
        self.assertIn('class="nc-title">valid</div>', html)
        self.assertNotIn('class="nc-title">invalid</div>', html)


if __name__ == "__main__":
    unittest.main()
