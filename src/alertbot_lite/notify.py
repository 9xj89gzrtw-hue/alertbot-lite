"""Delivery: Telegram HTML, or stdout for dry runs.

Two rules that matter more than formatting:
  * every string that came from a remote source is HTML-escaped before it is
    placed in a Telegram message, so a token named `<b>rug</b>` cannot inject;
  * every message is truncated on a line boundary under the platform limit.
"""

from __future__ import annotations

import html
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict

from .fetch import UA
from .sources import Item

TELEGRAM_LIMIT = 4096
SAFE_LIMIT = 3900  # headroom for the footer we append


class NotifyError(RuntimeError):
    pass


def format_alert(item: Item, match: Dict[str, Any]) -> str:
    lines = [
        "<b>%s</b>" % html.escape(item.title),
        "score <code>%s</code> · rule <code>%s</code> · %s" % (
            match.get("score"), html.escape(str(match.get("rule"))), html.escape(item.source)),
    ]
    if item.chain:
        lines.append("chain <code>%s</code>" % html.escape(item.chain))
    if item.liquidity_usd is not None:
        lines.append("liquidity $%s" % _money(item.liquidity_usd))
    if item.volume_24h is not None:
        lines.append("24h volume $%s" % _money(item.volume_24h))
    if match.get("reasons"):
        lines.append("why: %s" % html.escape(", ".join(match["reasons"])))
    lines.append('<a href="%s">open</a>' % html.escape(item.url, quote=True))
    return truncate("\n".join(lines))


def truncate(text: str, limit: int = SAFE_LIMIT) -> str:
    if len(text) <= limit:
        return text
    out = []
    used = 0
    for line in text.split("\n"):
        if used + len(line) + 1 > limit - 20:
            break
        out.append(line)
        used += len(line) + 1
    out.append("… truncated")
    return "\n".join(out)


def send_telegram(text: str, token: str, chat_id: str, timeout: float = 15.0) -> Dict[str, Any]:
    if not token or not chat_id:
        raise NotifyError("telegram token/chat_id missing")
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/sendMessage" % token,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise NotifyError("telegram HTTP %s: %s" % (exc.code, detail))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise NotifyError("telegram unreachable: %s" % getattr(exc, "reason", exc))
    if not body.get("ok"):
        raise NotifyError("telegram refused: %s" % body.get("description"))
    return body


def send(text: str, config: Dict[str, Any], dry_run: bool = False) -> str:
    """Return a short status string: 'sent', 'dry-run', or raise NotifyError."""
    if dry_run:
        sys.stdout.write("[dry-run] would send:\n%s\n%s\n" % ("-" * 60, text))
        return "dry-run"
    tg = (config.get("notify") or {}).get("telegram") or {}
    token = os.environ.get(tg.get("token_env", "TELEGRAM_BOT_TOKEN"), "")
    chat_id = os.environ.get(tg.get("chat_id_env", "TELEGRAM_CHAT_ID"), "")
    if not token or not chat_id:
        raise NotifyError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set (use --dry-run to preview)")
    send_telegram(text, token, chat_id)
    return "sent"


def _money(value: float) -> str:
    if value >= 1_000_000:
        return "%.2fM" % (value / 1_000_000)
    if value >= 1_000:
        return "%.1fK" % (value / 1_000)
    return "%.0f" % value
