"""Polite HTTP client: rate limited, retrying, and caching raw responses on disk.

Every response we fetch is written to the raw landing zone (gzipped JSON) before
parsing, so parsers can be re-run without hitting the network again.
"""

import gzip
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from deepsports import config

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    pass


class PoliteClient:
    def __init__(
        self,
        raw_dir: Path = config.RAW_DIR,
        min_interval: float = config.MIN_REQUEST_INTERVAL,
        max_retries: int = 4,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.raw_dir = raw_dir
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.client = client or httpx.Client(
            headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"},
            timeout=20.0,
            follow_redirects=True,
        )
        self._sleep = sleep
        self._last_request = 0.0
        self.network_requests = 0

    def cache_path(self, key: str) -> Path:
        return self.raw_dir / f"{key}.json.gz"

    def read_cache(self, key: str) -> Any | None:
        path = self.cache_path(key)
        if not path.exists():
            return None
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)

    def write_cache(self, key: str, data: Any) -> None:
        path = self.cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(data, f)
        tmp.replace(path)

    def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        cache_key: str,
        cache_ok: Callable[[Any], bool] | None = None,
    ) -> Any:
        """Fetch JSON, reusing the cached copy when `cache_ok(cached)` is true.

        `cache_ok=None` means always refetch (the response is still saved).
        """
        if cache_ok is not None:
            cached = self.read_cache(cache_key)
            if cached is not None and cache_ok(cached):
                return cached
        data = self._fetch(url, params)
        self.write_cache(cache_key, data)
        return data

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            self._sleep(wait)
        self._last_request = time.monotonic()

    def _fetch(self, url: str, params: dict[str, Any] | None) -> Any:
        for attempt in range(self.max_retries + 1):
            self._throttle()
            self.network_requests += 1
            try:
                resp = self.client.get(url, params=params)
            except httpx.TransportError as e:
                if attempt == self.max_retries:
                    raise FetchError(f"{url}: {type(e).__name__}") from e
                self._backoff(attempt, None)
                continue
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in RETRY_STATUS and attempt < self.max_retries:
                self._backoff(attempt, resp.headers.get("Retry-After"))
                continue
            raise FetchError(f"{url} params={params}: HTTP {resp.status_code}")
        raise FetchError(f"{url}: retries exhausted")  # pragma: no cover

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        delay = 2.0 ** (attempt + 1)
        if retry_after and retry_after.isdigit():
            delay = max(delay, float(retry_after))
        log.warning("retrying in %.0fs (attempt %d)", delay, attempt + 1)
        self._sleep(delay)
