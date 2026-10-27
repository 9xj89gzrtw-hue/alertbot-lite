"""DexScreener → normalised items. One source, two shapes.

`token-profiles` gives brand-new listings (no price, no timestamp — the API does
not publish them), and `search` gives live pairs with liquidity and volume.
Both are flattened into the same `Item` so the rules engine does not care.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .fetch import get_json

PROFILES_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
SEARCH_URL = "https://api.dexscreener.com/latest/dex/search?q=%s"


@dataclass
class Item:
    id: str
    source: str
    title: str
    url: str
    chain: str = ""
    symbol: str = ""
    liquidity_usd: Optional[float] = None
    volume_24h: Optional[float] = None
    created_at: Optional[datetime] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def age_hours(self, now: Optional[datetime] = None) -> Optional[float]:
        if not self.created_at:
            return None
        now = now or datetime.now(timezone.utc)
        delta = now - self.created_at
        return max(0.0, delta.total_seconds() / 3600.0)


def from_profiles(payload: Any, source: str = "dexscreener_profiles") -> List[Item]:
    if not isinstance(payload, list):
        raise ValueError("token-profiles: expected a JSON array")
    items = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        address = (row.get("tokenAddress") or "").strip()
        if not address:
            continue
        chain = (row.get("chainId") or "").strip()
        items.append(Item(
            id="profile:%s:%s" % (chain, address),
            source=source,
            title="New profile: %s on %s" % (address, chain or "?"),
            url=row.get("url") or "https://dexscreener.com/%s/%s" % (chain, address),
            chain=chain,
            symbol="",
            raw=row,
        ))
    return items


def from_search(payload: Any, source: str = "dexscreener_search") -> List[Item]:
    if not isinstance(payload, dict) or "pairs" not in payload:
        raise ValueError("search: expected an object with a 'pairs' array")
    pairs = payload.get("pairs") or []
    items = []
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        base = pair.get("baseToken") or {}
        address = (base.get("address") or "").strip()
        chain = (pair.get("chainId") or "").strip()
        if not address:
            continue
        symbol = (base.get("symbol") or "").strip()
        created = pair.get("pairCreatedAt")
        created_at = None
        if isinstance(created, (int, float)) and created > 0:
            created_at = datetime.fromtimestamp(created / 1000.0, tz=timezone.utc)
        liquidity = ((pair.get("liquidity") or {}).get("usd"))
        volume = ((pair.get("volume") or {}).get("h24"))
        items.append(Item(
            id="pair:%s:%s" % (chain, pair.get("pairAddress") or address),
            source=source,
            title="%s/%s on %s" % (symbol or "?", (pair.get("quoteToken") or {}).get("symbol") or "?", pair.get("dexId") or "?"),
            url=pair.get("url") or "https://dexscreener.com/%s/%s" % (chain, pair.get("pairAddress")),
            chain=chain,
            symbol=symbol,
            liquidity_usd=_num(liquidity),
            volume_24h=_num(volume),
            created_at=created_at,
            raw=pair,
        ))
    return items


def fetch_profiles() -> List[Item]:
    return from_profiles(get_json(PROFILES_URL))


def fetch_search(query: str) -> List[Item]:
    from urllib.parse import quote
    return from_search(get_json(SEARCH_URL % quote(query)))


def _num(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
