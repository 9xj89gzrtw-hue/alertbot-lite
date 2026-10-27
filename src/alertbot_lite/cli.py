"""CLI: run, test-notify, sources, explain."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import __version__
from .fetch import FetchError
from .notify import NotifyError, format_alert, send
from .rules import RuleError, evaluate, load_rules
from .sources import fetch_profiles, fetch_search
from .store import Store

DEFAULT_CONFIG = "config.json"


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        raise SystemExit("no config at %s — copy config.example.json to config.json" % path)
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    if not isinstance(cfg, dict):
        raise SystemExit("config must be a JSON object")
    return cfg


def collect(cfg: dict):
    """Return (items, errors) for the configured source."""
    src = (cfg.get("source") or {})
    kind = src.get("type", "dexscreener_profiles")
    errors = []
    items = []
    try:
        if kind == "dexscreener_profiles":
            items = fetch_profiles()
        elif kind == "dexscreener_search":
            query = src.get("query")
            if not query:
                raise SystemExit("source.query is required for dexscreener_search")
            items = fetch_search(query)
        else:
            raise SystemExit("unknown source.type %r (dexscreener_profiles | dexscreener_search)" % kind)
    except FetchError as exc:
        errors.append(str(exc))
    return items, errors


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    rules = load_rules(cfg)
    store = Store((cfg.get("store") or {}).get("path", "alertbot.sqlite"),
                  ttl_days=float((cfg.get("store") or {}).get("ttl_days", 30)))

    items, errors = collect(cfg)
    sent = matched = suppressed = failed = 0
    for item in items:
        if store.seen(item.id):
            suppressed += 1
            continue
        match = evaluate(item, rules)
        if not match:
            continue
        matched += 1
        text = format_alert(item, match)
        try:
            status = send(text, cfg, dry_run=args.dry_run)
            store.mark(item.id, sent=True)
            if status != "dry-run":
                sent += 1
        except NotifyError as exc:
            failed += 1
            sys.stderr.write("send failed for %s: %s\n" % (item.id, exc))
            store.mark(item.id, sent=False)
    pruned = store.prune()
    store.close()

    print("cycle: items=%d matched=%d sent=%d suppressed=%d failed=%d errors=%d pruned=%d"
          % (len(items), matched, sent, suppressed, failed, len(errors), pruned))
    for err in errors:
        sys.stderr.write("source error: %s\n" % err)
    return 1 if (failed or errors) else 0


def cmd_test_notify(args) -> int:
    cfg = load_config(args.config)
    from .sources import Item
    item = Item(id="test", source="test", title="Test alert — <b>not escaped</b>",
                url="https://example.com", chain="base", symbol="TEST",
                liquidity_usd=123456.0, volume_24h=98765.0)
    text = format_alert(item, {"score": 99.0, "rule": "test", "reasons": ["this is a drill"]})
    try:
        status = send(text, cfg, dry_run=args.dry_run)
    except NotifyError as exc:
        sys.stderr.write("%s\n" % exc)
        return 1
    print("test-notify: %s" % status)
    return 0


def cmd_sources(args) -> int:
    cfg = load_config(args.config)
    started = time.time()
    items, errors = collect(cfg)
    ms = (time.time() - started) * 1000
    kind = (cfg.get("source") or {}).get("type", "dexscreener_profiles")
    if errors:
        print("FAIL %-24s %s" % (kind, errors[0]))
        return 1
    print("OK   %-24s items=%-4d latency=%7.1fms" % (kind, len(items), ms))
    for item in items[:3]:
        print("     · %s" % item.title[:90])
    return 0


def cmd_explain(args) -> int:
    cfg = load_config(args.config)
    rules = load_rules(cfg)
    items, errors = collect(cfg)
    if errors:
        sys.stderr.write("source error: %s\n" % errors[0])
        return 1
    for item in items[: args.limit]:
        match = evaluate(item, rules)
        if match:
            print("%5.1f  %-18s %s" % (match["score"], match["rule"], item.title[:80]))
        else:
            print("    -  %-18s %s" % ("no match", item.title[:80]))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="alertbot",
        description="Self-hosted alert bot: DexScreener → rules → Telegram. Stdlib only.",
        epilog="examples:\n"
               "  alertbot sources --check\n"
               "  alertbot run --once --dry-run\n"
               "  alertbot test-notify\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version="alertbot-lite %s" % __version__)
    p.add_argument("-c", "--config", default=DEFAULT_CONFIG, help="config path (default: config.json)")
    sub = p.add_subparsers(dest="command")

    run = sub.add_parser("run", help="poll the source and send alerts")
    run.add_argument("--once", action="store_true", help="single cycle (default)")
    run.add_argument("--loop", action="store_true", help="keep running")
    run.add_argument("--interval", type=int, default=300, help="seconds between cycles")
    run.add_argument("--dry-run", action="store_true", help="print instead of sending")
    run.set_defaults(func=cmd_run)

    t = sub.add_parser("test-notify", help="send a sample alert to the configured sink")
    t.add_argument("--dry-run", action="store_true")
    t.set_defaults(func=cmd_test_notify)

    s = sub.add_parser("sources", help="probe the configured source")
    s.add_argument("--check", action="store_true", help="probe and report (default)")
    s.set_defaults(func=cmd_sources)

    e = sub.add_parser("explain", help="show how each item scores against the rules")
    e.add_argument("--limit", type=int, default=10)
    e.set_defaults(func=cmd_explain)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "command", None):
        build_parser().print_help()
        return 2
    if getattr(args, "loop", False):
        while True:
            args.func(args)
            time.sleep(args.interval)
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
