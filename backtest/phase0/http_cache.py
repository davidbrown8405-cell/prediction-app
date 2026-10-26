"""Disk cache for GET requests: never re-pull a response that is already cached."""
import hashlib
import json
import time
from pathlib import Path

import requests

CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "raw_cache"
_SECRET_PARAMS = {"apiKey", "apikey", "api_key"}
_last_call = {}


def _key(url, params):
    public = {k: v for k, v in sorted((params or {}).items()) if k not in _SECRET_PARAMS}
    return hashlib.sha256(f"{url}|{json.dumps(public)}".encode()).hexdigest()


def cached_get(url, params=None, headers=None, timeout=30, min_interval=0.0, allow_404=False):
    """Return (json_body, response_headers, from_cache). A cached 404 returns body None."""
    path = CACHE_DIR / f"{_key(url, params)}.json"
    if path.exists():
        blob = json.loads(path.read_text())
        return blob["body"], blob["headers"], True
    host = url.split("/")[2]
    wait = min_interval - (time.monotonic() - _last_call.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    _last_call[host] = time.monotonic()
    if allow_404 and resp.status_code == 404:
        body = None
    else:
        resp.raise_for_status()
        body = resp.json()
    blob = {"url": url, "status": resp.status_code, "body": body, "headers": dict(resp.headers)}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob))
    return body, blob["headers"], False
