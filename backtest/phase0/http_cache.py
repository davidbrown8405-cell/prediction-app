"""Disk cache for GET requests: never re-pull a response that is already cached."""
import hashlib
import json
from pathlib import Path

import requests

CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "raw_cache"
_SECRET_PARAMS = {"apiKey", "apikey", "api_key"}


def _key(url, params):
    public = {k: v for k, v in sorted((params or {}).items()) if k not in _SECRET_PARAMS}
    return hashlib.sha256(f"{url}|{json.dumps(public)}".encode()).hexdigest()


def cached_get(url, params=None, headers=None, timeout=30):
    """Return (json_body, response_headers, from_cache)."""
    path = CACHE_DIR / f"{_key(url, params)}.json"
    if path.exists():
        blob = json.loads(path.read_text())
        return blob["body"], blob["headers"], True
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    blob = {"url": url, "body": resp.json(), "headers": dict(resp.headers)}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob))
    return blob["body"], blob["headers"], False
