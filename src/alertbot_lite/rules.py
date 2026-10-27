"""Deterministic JSON rules. No model, no randomness: same item + same rules = same score."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .sources import Item


class RuleError(ValueError):
    pass


@dataclass
class Rule:
    name: str
    enabled: bool = True
    chains: Optional[List[str]] = None
    required_keywords: Optional[List[str]] = None
    allow_keywords: Optional[List[str]] = None
    deny_keywords: Optional[List[str]] = None
    min_liquidity_usd: Optional[float] = None
    min_volume_24h_usd: Optional[float] = None
    max_age_hours: Optional[float] = None
    min_score: float = 0.0
    weights: Optional[Dict[str, float]] = None

    def applies_to(self, item: Item) -> bool:
        return not self.chains or item.chain in self.chains


def load_rules(config: Dict[str, Any]) -> List[Rule]:
    raw = config.get("rules")
    if not isinstance(raw, list) or not raw:
        raise RuleError("config.rules must be a non-empty list")
    rules = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise RuleError("rules[%d] must be an object" % i)
        name = entry.get("name")
        if not name:
            raise RuleError("rules[%d] has no name" % i)
        rules.append(Rule(
            name=str(name),
            enabled=bool(entry.get("enabled", True)),
            chains=_strlist(entry.get("chains")),
            required_keywords=_strlist(entry.get("required_keywords")),
            allow_keywords=_strlist(entry.get("allow_keywords")),
            deny_keywords=_strlist(entry.get("deny_keywords")),
            min_liquidity_usd=_f(entry.get("min_liquidity_usd")),
            min_volume_24h_usd=_f(entry.get("min_volume_24h_usd")),
            max_age_hours=_f(entry.get("max_age_hours")),
            min_score=_f(entry.get("min_score")) or 0.0,
            weights=entry.get("weights") or {},
        ))
    return rules


def score(item: Item, rule: Rule) -> Tuple[float, List[str]]:
    """Return (score, reasons). A denial returns (0.0, ["denied: ..."])."""
    if not rule.enabled:
        return 0.0, ["rule disabled"]
    if not rule.applies_to(item):
        return 0.0, ["chain %s not in rule" % (item.chain or "?")]

    haystack = ("%s %s" % (item.title, item.symbol or "")).lower()
    reasons: List[str] = []

    for word in rule.deny_keywords or []:
        if word.lower() in haystack:
            return 0.0, ["denied: contains %r" % word]

    for word in rule.required_keywords or []:
        if word.lower() not in haystack:
            return 0.0, ["missing required %r" % word]

    if rule.min_liquidity_usd is not None:
        if item.liquidity_usd is None:
            return 0.0, ["no liquidity figure"]
        if item.liquidity_usd < rule.min_liquidity_usd:
            return 0.0, ["liquidity %.0f < %.0f" % (item.liquidity_usd, rule.min_liquidity_usd)]

    if rule.min_volume_24h_usd is not None:
        if item.volume_24h is None:
            return 0.0, ["no 24h volume figure"]
        if item.volume_24h < rule.min_volume_24h_usd:
            return 0.0, ["volume %.0f < %.0f" % (item.volume_24h, rule.min_volume_24h_usd)]

    if rule.max_age_hours is not None:
        age = item.age_hours()
        if age is not None and age > rule.max_age_hours:
            return 0.0, ["age %.1fh > %.1fh" % (age, rule.max_age_hours)]
        if age is None:
            reasons.append("age unknown")

    total = 50.0
    weights = rule.weights or {}

    if rule.min_liquidity_usd and item.liquidity_usd:
        ratio = min(1.0, item.liquidity_usd / (rule.min_liquidity_usd * 10))
        total += weights.get("liquidity", 20.0) * ratio
        reasons.append("liquidity %.0f" % item.liquidity_usd)

    if rule.min_volume_24h_usd and item.volume_24h:
        ratio = min(1.0, item.volume_24h / (rule.min_volume_24h_usd * 10))
        total += weights.get("volume", 15.0) * ratio
        reasons.append("volume24h %.0f" % item.volume_24h)

    for word in rule.allow_keywords or []:
        if word.lower() in haystack:
            total += weights.get("keyword", 10.0)
            reasons.append("keyword %r" % word)
            break

    age = item.age_hours()
    if age is not None:
        total += weights.get("freshness", 10.0) * max(0.0, 1.0 - min(age, 72.0) / 72.0)

    return round(min(total, 100.0), 1), reasons


def evaluate(item: Item, rules: List[Rule]) -> Optional[Dict[str, Any]]:
    """Best matching rule wins. Returns None when nothing clears its threshold."""
    best = None
    for rule in rules:
        value, reasons = score(item, rule)
        if value <= 0:
            continue
        if value < rule.min_score:
            continue
        if best is None or value > best["score"]:
            best = {"rule": rule.name, "score": value, "reasons": reasons}
    return best


def _strlist(value) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    raise RuleError("expected a string or a list of strings, got %r" % type(value).__name__)


def _f(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise RuleError("expected a number, got %r" % (value,))
