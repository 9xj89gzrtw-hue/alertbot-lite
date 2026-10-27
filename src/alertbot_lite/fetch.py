"""HTTP with a timeout, a user agent, and bounded retries. Nothing clever."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

UA = "alertbot-lite/0.1 (+https://github.com/9xj89gzrtw-hue/alertbot-lite)"
DEFAULT_TIMEOUT = 15.0
RETRIES = 2


class FetchError(RuntimeError):
    """A source could not be read. The message is safe to print."""


def get_json(url: str, timeout: float = DEFAULT_TIMEOUT, retries: int = RETRIES):
    """GET a URL and parse JSON, retrying on 429/5xx and network errors."""
    last = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(0.7 * (2 ** (attempt - 1)))
        req = urllib.request.Request(
            url,
            headers={"User-Agent": UA, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return json.loads(raw.decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            last = "HTTP %s from %s" % (exc.code, _host(url))
            if exc.code in (429, 500, 502, 503, 504):
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = "%s: %s" % (_host(url), getattr(exc, "reason", exc))
        except json.JSONDecodeError as exc:
            last = "%s returned invalid JSON (%s)" % (_host(url), exc)
            break
    raise FetchError(last or "request failed")


def _host(url: str) -> str:
    try:
        return url.split("//", 1)[1].split("/", 1)[0]
    except IndexError:
        return url
