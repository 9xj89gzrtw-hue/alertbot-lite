"""Offline tests for alertbot-lite. No network, no tokens.

    python3 -m unittest discover -s tests
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from alertbot_lite.notify import SAFE_LIMIT, format_alert, truncate  # noqa: E402
from alertbot_lite.rules import RuleError, evaluate, load_rules, score  # noqa: E402
from alertbot_lite.sources import Item, from_profiles, from_search  # noqa: E402
from alertbot_lite.store import Store  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")


def fixture(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


def item(**kw):
    base = dict(id="x", source="test", title="SOL/USDC on raydium", url="https://example.com",
                chain="solana", symbol="SOL", liquidity_usd=200000.0, volume_24h=50000.0)
    base.update(kw)
    return Item(**base)


class TestSources(unittest.TestCase):
    def test_profiles_normalised(self):
        items = from_profiles(fixture("profiles.json"))
        self.assertEqual(len(items), 2)
        self.assertTrue(all(i.id.startswith("profile:") for i in items))
        self.assertEqual(items[0].chain, "solana")

    def test_profiles_rejects_wrong_shape(self):
        with self.assertRaises(ValueError):
            from_profiles({"not": "a list"})

    def test_profiles_skips_rows_without_address(self):
        self.assertEqual(from_profiles([{"chainId": "solana"}]), [])

    def test_search_normalised(self):
        items = from_search(fixture("search.json"))
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.symbol, "SOL")
        # chain and figures are read from the fixture, not hard-coded
        self.assertEqual(first.chain, first.raw["chainId"])
        self.assertAlmostEqual(first.liquidity_usd, first.raw["liquidity"]["usd"], places=2)
        self.assertAlmostEqual(first.volume_24h, first.raw["volume"]["h24"], places=2)

    def test_search_created_at_parsed(self):
        pair = {"pairs": [{"chainId": "base", "pairAddress": "0x1",
                           "baseToken": {"address": "0x2", "symbol": "T"},
                           "pairCreatedAt": 1700000000000}]}
        items = from_search(pair)
        self.assertIsNotNone(items[0].created_at)
        self.assertGreater(items[0].age_hours(), 0)

    def test_search_missing_pairs_key(self):
        with self.assertRaises(ValueError):
            from_search({"nope": []})

    def test_age_unknown_is_none(self):
        self.assertIsNone(item(created_at=None).age_hours())


class TestRules(unittest.TestCase):
    def rules(self, **kw):
        cfg = {"rules": [dict({"name": "r", "min_score": 0}, **kw)]}
        return load_rules(cfg)

    def test_deny_keyword_blocks(self):
        rules = self.rules(deny_keywords=["scam"])
        self.assertIsNone(evaluate(item(title="SCAM coin"), rules))

    def test_required_keyword_blocks(self):
        rules = self.rules(required_keywords=["bonk"])
        self.assertIsNone(evaluate(item(), rules))

    def test_chain_filter(self):
        rules = self.rules(chains=["base"])
        self.assertIsNone(evaluate(item(chain="solana"), rules))

    def test_min_liquidity_blocks_and_passes(self):
        rules = self.rules(min_liquidity_usd=500000)
        self.assertIsNone(evaluate(item(liquidity_usd=1000), rules))
        self.assertIsNotNone(evaluate(item(liquidity_usd=900000), rules))

    def test_missing_liquidity_is_rejected_when_threshold_set(self):
        rules = self.rules(min_liquidity_usd=10)
        self.assertIsNone(evaluate(item(liquidity_usd=None), rules))

    def test_max_age(self):
        old = item(created_at=datetime.now(timezone.utc) - timedelta(hours=100))
        rules = self.rules(max_age_hours=24)
        self.assertIsNone(evaluate(old, rules))

    def test_unknown_age_passes_but_says_so(self):
        rules = self.rules(max_age_hours=24)
        match = evaluate(item(created_at=None), rules)
        self.assertIsNotNone(match)
        self.assertIn("age unknown", match["reasons"])

    def test_min_score_threshold(self):
        rules = self.rules(min_score=99.5)
        self.assertIsNone(evaluate(item(), rules))

    def test_score_is_bounded(self):
        rules = self.rules(min_liquidity_usd=1, min_volume_24h_usd=1,
                           allow_keywords=["sol"], weights={"liquidity": 80, "volume": 80})
        value, _ = score(item(), rules[0])
        self.assertLessEqual(value, 100.0)

    def test_deterministic(self):
        rules = self.rules(min_liquidity_usd=1)
        self.assertEqual(score(item(), rules[0]), score(item(), rules[0]))

    def test_bad_config_raises(self):
        with self.assertRaises(RuleError):
            load_rules({"rules": []})
        with self.assertRaises(RuleError):
            load_rules({"rules": [{"min_liquidity_usd": "lots"}]})


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "db.sqlite"), ttl_days=1)

    def tearDown(self):
        self.store.close()

    def test_mark_and_seen(self):
        self.assertFalse(self.store.seen("a"))
        self.store.mark("a", sent=True)
        self.assertTrue(self.store.seen("a"))

    def test_duplicate_is_idempotent(self):
        self.store.mark("a")
        self.store.mark("a")
        self.assertEqual(self.store.count(), 1)

    def test_prune_removes_old_rows(self):
        self.store.mark("old")
        removed = self.store.prune(now=__import__("time").time() + 3 * 86400)
        self.assertEqual(removed, 1)
        self.assertFalse(self.store.seen("old"))

    def test_prune_keeps_fresh_rows(self):
        self.store.mark("new")
        self.assertEqual(self.store.prune(), 0)
        self.assertTrue(self.store.seen("new"))


class TestNotify(unittest.TestCase):
    def test_titles_are_html_escaped(self):
        text = format_alert(item(title="<script>alert(1)</script>"), {"score": 1, "rule": "r"})
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)

    def test_url_quotes_escaped(self):
        text = format_alert(item(url='https://x.test/?a="b"'), {"score": 1, "rule": "r"})
        self.assertIn("&quot;", text)

    def test_truncate_under_limit(self):
        long = "\n".join("line %d %s" % (i, "x" * 100) for i in range(200))
        out = truncate(long)
        self.assertLessEqual(len(out), SAFE_LIMIT)
        self.assertIn("truncated", out)

    def test_short_message_untouched(self):
        self.assertEqual(truncate("hello"), "hello")

    def test_reasons_rendered(self):
        text = format_alert(item(), {"score": 42.5, "rule": "r", "reasons": ["liquidity 1"]})
        self.assertIn("42.5", text)
        self.assertIn("liquidity 1", text)


if __name__ == "__main__":
    unittest.main()
