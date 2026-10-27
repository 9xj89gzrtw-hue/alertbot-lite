# alertbot-lite — DexScreener → rules → Telegram, in one file and no dependencies

A self-hosted alert bot for one job: watch a source you already refresh by hand, and tell you only
when something matches a rule you wrote down. No account, no SaaS, no API keys except a Telegram
bot token you create yourself in two minutes.

Python 3.9+, standard library only, 27 offline tests.

```
$ ./alertbot -c config.example.json sources --check
OK   dexscreener_search       items=30   latency=  551.0ms
     · SOL/USDC on aerodrome
     · SOL/USDC on aero
     · SOL/cbBTC on aero

$ ./alertbot -c config.example.json run --once --dry-run
<b>SOL/USDC on raydium</b>
score <code>82.4</code> · rule <code>liquid-solana-pairs</code> · dexscreener_search
chain <code>solana</code>
liquidity $1627.15M
24h volume $82.6K
why: liquidity 1627150143, volume24h 82568
<a href="https://dexscreener.com/solana/fqqkcjycqgmpk67yonsvhfwqkeb3bguugkxe3fbr7pzk">open</a>
cycle: items=30 matched=3 sent=0 suppressed=0 failed=0 errors=0 pruned=0
```

Both blocks are real runs, captured 27 Oct 2026. The second cycle prints `suppressed=3` because the
same three pairs are already in sqlite.

## Install

```bash
git clone https://github.com/9xj89gzrtw-hue/alertbot-lite
cd alertbot-lite
cp config.example.json config.json
./alertbot sources --check          # no install step, no PYTHONPATH
python3 -m unittest discover -s tests
```

## Configure

`config.json` has four blocks:

```json
{
  "source":  { "type": "dexscreener_search", "query": "SOL" },
  "store":   { "path": "alertbot.sqlite", "ttl_days": 30 },
  "notify":  { "telegram": { "token_env": "TELEGRAM_BOT_TOKEN", "chat_id_env": "TELEGRAM_CHAT_ID" } },
  "rules":   [ { "name": "liquid-solana-pairs", "chains": ["solana"], "min_liquidity_usd": 50000 } ]
}
```

| Field | Meaning |
|---|---|
| `source.type` | `dexscreener_search` (live pairs for a query) or `dexscreener_profiles` (newest token profiles) |
| `source.query` | what to search: a symbol (`SOL`), a name, or a token address |
| `store.ttl_days` | how long a seen id is remembered before it can alert again |
| `rules[].chains` | restrict to chain ids (`solana`, `base`, `ethereum`, …) |
| `rules[].deny_keywords` | any hit → the item is dropped, no score |
| `rules[].required_keywords` | all must appear in title/symbol |
| `rules[].min_liquidity_usd` / `min_volume_24h_usd` | hard floors; a missing figure fails the rule |
| `rules[].max_age_hours` | pair age ceiling; an unknown age passes and says `age unknown` |
| `rules[].min_score` | threshold a match must clear |
| `rules[].weights` | points added for `liquidity`, `volume`, `keyword`, `freshness` |

Scoring is deterministic: base 50, plus weighted ratios, capped at 100. Same item and same rules
always produce the same score, so `explain` is a real debugging tool, not a guess:

```bash
./alertbot -c config.json explain --limit 10
```

## Telegram setup (accurate steps)

1. In Telegram, open **@BotFather** → `/newbot` → pick a name and a username ending in `bot`.
2. BotFather replies with a token like `8123456789:AAH…`. That is `TELEGRAM_BOT_TOKEN`.
3. Send any message to your new bot (a bot cannot message you first).
4. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and read `result[0].message.chat.id`.
   That number is `TELEGRAM_CHAT_ID`. For a group, add the bot to the group first and use the
   negative id that appears there.

```bash
export TELEGRAM_BOT_TOKEN='…'
export TELEGRAM_CHAT_ID='…'
./alertbot test-notify          # one real message
./alertbot run --loop --interval 300
```

Without those variables, `run` refuses to send and tells you to use `--dry-run` — it does not fail
silently.

## What this is not

- **Not a trading bot.** No keys, no swaps, no signatures. It reads a public API and sends text.
- **Not a signal service.** A high score means "matches your written rule", nothing about price.
- **Not immune to rate limits.** DexScreener's public API is rate-limited per IP; a 300-second
  interval is polite, a 5-second interval will get you throttled.
- **Not a complete news feed.** One source, one query. Multi-source fan-in, JSON scoring across
  adapters, Discord delivery and loop health checks are in the Pro pack.

## Lite vs Pro

| | Lite (this repo) | Pro |
|---|---|---|
| DexScreener source (profiles + search) | ✓ | ✓ |
| JSON rules + deterministic scoring | ✓ | ✓ |
| sqlite dedupe with TTL | ✓ | ✓ |
| Telegram HTML delivery | ✓ | ✓ |
| `sources --check`, `explain`, dry-run | ✓ | ✓ |
| Superteam Earn, GitHub bounty issues, RSS adapters | — | ✓ |
| Per-source scoring, watchlist persistence | — | ✓ |
| Discord embeds | — | ✓ |
| 156-test suite, fixtures for every adapter | 27 | ✓ |

## Licence

MIT.
