"""Tiny stdlib HTTP helpers with retries (no third-party dependencies)."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "trmnl-fantasy-scout/1.0 (+https://github.com/catchymangos/trmnl-fantasy-scout)"


def get(url, params=None, headers=None, retries=3, timeout=30):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    hdrs.update(headers or {})
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            if isinstance(e, urllib.error.HTTPError) and 400 <= e.code < 500 and e.code != 429:
                break
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET failed: {url[:120]} ({last})")


def get_json(url, params=None, headers=None, **kw):
    return json.loads(get(url, params=params, headers=headers, **kw))


def post_json(url, payload, timeout=30):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8")
